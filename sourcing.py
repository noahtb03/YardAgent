"""Public Home Depot search pages and explicit national feature allowances."""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urljoin, urlsplit

from playwright.sync_api import Error as BrowserError, sync_playwright
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class CostRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float = Field(ge=0, allow_inf_nan=False)
    max: float = Field(ge=0, allow_inf_nan=False)


class SourcedProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    price: float = Field(gt=0, allow_inf_nan=False)
    url: str
    currency: Literal["USD"] = "USD"
    retailer: Literal["Home Depot"] = "Home Depot"


class FeatureEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["estimated"] = "estimated"
    region: Literal["US-national"] = "US-national"
    cost_range_usd: CostRange
    basis: str
    source_url: str
    reviewed_on: str = "2026-09-10"


# National defaults; add verified regional tables here when location questions ship.
# These are planning allowances, not live retailer prices or contractor quotes.
FEATURE_COSTS = {
    "US-national": {
        "pool": (45000, 88000, "per pool; assumes an in-ground installation",
                 "https://www.angi.com/articles/cost-outdoor-living-space.htm"),
        "patio": (8, 25, "per sq ft of the entire footprint; assumes brick pavers",
                  "https://www.angi.com/articles/how-much-does-it-cost-install-patio.htm"),
        "bar": (5000, 20000, "per installed outdoor bar",
                "https://www.angi.com/articles/cost-outdoor-living-space.htm"),
    }
}


def feature_kind(element):
    if element["category"] != "hardscape":
        return None
    words = set(re.findall(r"[a-z]+", element["type"].lower()))
    if re.search(r"\bpatio\s*$", element["type"], re.I):
        return "patio"
    # Materials and accessories containing 'patio', 'pool', or 'bar' are retail items.
    if words & {"paver", "pavers", "tile", "tiles", "stone", "stones", "sand",
                "gravel", "material", "materials", "pump", "liner", "cover",
                "stool", "stools", "chair", "chairs", "light", "lights"}:
        return None
    return next((kind for kind in ("pool", "patio", "bar") if kind in words), None)


def estimate_feature(element, kind):
    low, high, basis, url = FEATURE_COSTS["US-national"][kind]
    # Footprints already encompass all items: do not multiply patio area by quantity.
    units = (Decimal(str(element["width_ft"])) * Decimal(str(element["length_ft"]))
             if kind == "patio" else Decimal(element["quantity"]))
    return FeatureEstimate(cost_range_usd=CostRange(
        min=float((units * low).quantize(Decimal("0.01"))),
        max=float((units * high).quantize(Decimal("0.01")))),
        basis=basis, source_url=url).model_dump()


# Prefer structured Product offers, then visible cards. Never parse a page-wide
# dollar amount, which could be financing, a crossed-out price, or another item.
EXTRACT_PRODUCTS = r"""() => {
  const products = [];
  function walk(value) {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) { value.forEach(walk); return; }
    const types = [].concat(value['@type'] || []);
    if (types.includes('Product')) {
      for (const offer of [].concat(value.offers || [])) {
        if (offer.price != null && (!offer.priceCurrency || offer.priceCurrency === 'USD') &&
            !/OutOfStock|Discontinued|PreOrder/i.test(offer.availability || '')) {
          products.push({name: value.name, price: String(offer.price),
            url: offer.url || value.url});
        }
      }
    }
    Object.values(value).forEach(walk);
  }
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { walk(JSON.parse(script.textContent)); } catch (_) {}
  }
  const cards = document.querySelectorAll(
    '[data-testid="product-pod"], [data-testid="product-pod-group"], .product-pod');
  for (const card of cards) {
    if (!card.getClientRects().length || /out of stock|unavailable|sold out/i.test(card.innerText)) continue;
    const anchor = card.querySelector('a[data-testid="product-header"], a[href*="/p/"]');
    const title = card.querySelector('[data-testid="product-header"], .product-header__title');
    const price = card.querySelector('[data-testid="price-format"], .price-format__main-price');
    if (!anchor || !price) continue;
    // Split dollar/cents spans are common in the rendered Home Depot cards.
    const match = price.innerText.match(/\$\s*([\d,]+)(?:\s*[.\n]\s*(\d{2})|\s+(\d{2}))?/);
    if (match) products.push({name: (title || anchor).innerText.trim() || anchor.title,
      price: match[1].replaceAll(',', '') + '.' + (match[2] || match[3] || '00'),
      url: anchor.href});
  }
  return products;
}"""


def select_product(candidates, query):
    def tokens(text):
        return {word.rstrip("s") for word in re.findall(r"[a-z]+", text.lower())
                if len(word) > 2 and word not in {"with", "and", "the", "for"}}
    wanted = tokens(query)
    for candidate in candidates:
        name = candidate.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        url = urljoin("https://www.homedepot.com", str(candidate.get("url") or ""))
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"homedepot.com", "www.homedepot.com"}
                or not parsed.path.startswith("/p/") or parsed.username or parsed.password):
            continue
        matched = wanted & tokens(name)
        if not matched or len(matched) / max(len(wanted), 1) < 0.5:
            continue
        accessory_words = {"fertilizer", "food", "seed", "cover", "cushion", "replacement"}
        if (tokens(name) & accessory_words) - wanted:
            continue
        try:
            price = Decimal(str(candidate.get("price", "")).replace(",", ""))
            if not price.is_finite() or price <= 0:
                continue
        except InvalidOperation:
            continue
        return SourcedProduct(name=name.strip(), price=float(price.quantize(Decimal("0.01"))),
                              url=url).model_dump()
    return None


def search_product(page, query):
    response = page.goto("https://www.homedepot.com/s/" + quote(query, safe=""),
                         wait_until="domcontentloaded", timeout=25000)
    if response and response.status >= 400:
        return None, f"Home Depot search returned HTTP {response.status}."
    try:
        page.wait_for_function("""() => document.querySelector(
          '[data-testid="product-pod"], .product-pod, script[type="application/ld+json"]') ||
          /access denied|verify you are human|no results/i.test(document.body.innerText)""",
          timeout=10000)
    except BrowserError:
        return None, "Home Depot did not return readable product results in time."
    product = select_product(page.evaluate(EXTRACT_PRODUCTS), query)
    return product, None if product else "No relevant, available product with a readable price was found."


def source_layout(layout):
    enriched = {**layout, "elements": []}
    retail = []
    for element in layout["elements"]:
        item = {**element, "sourced_product": None, "estimated_feature": None,
                "sourcing_status": "unavailable", "sourcing_note": None,
                "sourced_total_usd": None}
        kind = feature_kind(element)
        if kind:
            item.update(estimated_feature=estimate_feature(element, kind), sourcing_status="estimated")
        else:
            retail.append(item)
        enriched["elements"].append(item)
    if retail:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(locale="en-US")
                    cache = {}
                    for item in retail:
                        query = item["type"].strip()
                        if query not in cache:
                            try:
                                cache[query] = search_product(page, query)
                            except BrowserError:
                                cache[query] = (None, "Home Depot search failed or timed out; retry sourcing later.")
                        product, note = cache[query]
                        item.update(sourced_product=product, sourcing_note=note)
                        if product:
                            item["sourcing_status"] = "sourced"
                            item["sourced_total_usd"] = float(
                                Decimal(str(product["price"])) * item["quantity"])
                finally:
                    browser.close()
        except (BrowserError, OSError):
            for item in retail:
                if item["sourcing_status"] != "sourced":
                    item["sourcing_note"] = "Product browser unavailable. Install Playwright Chromium on the server, then retry."
    enriched["sourced_materials_total_usd"] = float(sum(
        (Decimal(str(item["sourced_total_usd"])) for item in retail
         if item["sourced_total_usd"] is not None), Decimal(0)))
    enriched["estimated_features_range_usd"] = {
        bound: float(sum((Decimal(str(item["estimated_feature"]["cost_range_usd"][bound]))
                         for item in enriched["elements"] if item["estimated_feature"]), Decimal(0)))
        for bound in ("min", "max")}
    enriched["sourcing_complete"] = all(item["sourcing_status"] == "sourced" for item in retail)
    return enriched
