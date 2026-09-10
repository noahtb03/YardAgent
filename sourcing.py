"""Concurrent retailer searches using rendered Chromium pages."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from threading import Lock
from uuid import uuid4
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
    retailer: Literal["Home Depot", "Lowe's", "Wayfair", "Amazon"] = "Home Depot"


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


RETAILERS = {
    "Home Depot": dict(slug="home-depot", domain="homedepot.com", search="/s/", path=r"^/p/",
        cards='[data-testid="product-pod"], [data-testid="product-pod-group"], .product-pod',
        link='a[data-testid="product-header"], a[href*="/p/"]',
        title='[data-testid="product-header"], .product-header__title',
        price='[data-testid="price-format"], .price-format__main-price'),
    "Lowe's": dict(slug="lowes", domain="lowes.com", search="/search?searchTerm=", path=r"^/pd/",
        cards='[data-selector="splp-prd-lst"], [data-testid="product-card"], .product-card',
        link='a[href*="/pd/"]', title='[data-selector="splp-prd-nm"], [data-testid="product-title"], h3',
        price='[data-selector="splp-prc"], [data-testid="product-price"], [class*="Price_price"]'),
    "Wayfair": dict(slug="wayfair", domain="wayfair.com", search="/keyword.php?keyword=",
        path=r"/pdp/|/p/[^/]+\.html",
        cards='[data-test-id="ListingCard"], [data-hb-id="ProductCard"], [data-testid="product-card"], .ProductCard',
        link='a[href*="/pdp/"], a[href*="/p/"]',
        title='[data-name-id="ListingCardName"], [data-hb-id="ProductCardTitle"], [data-testid="product-name"], h2, h3',
        price='[data-test-id="PricingStandard-leadPrice"], [data-hb-id="PriceBlock"], [data-testid="product-price"], .ProductCard-price'),
    "Amazon": dict(slug="amazon", domain="amazon.com", search="/s?k=", path=r"/(dp|gp/product)/",
        cards='[data-component-type="s-search-result"][data-asin]',
        link='a[href*="/dp/"], a[href*="/gp/product/"]', title='h2',
        price='.a-price:not(.a-text-price)'),
}
ROOT = Path(__file__).resolve().parent
PROFILE_ROOT = ROOT / ".sourcing-browser"
DIAGNOSTICS_ROOT = ROOT / "sourcing-diagnostics"
PROFILE_LOCKS = {name: Lock() for name in RETAILERS}
LOGGER = logging.getLogger(__name__)


# Read rendered cards only, never response JSON or page-wide dollar amounts.
# Price parts avoid mistaking a financing payment or crossed-out list price for
# the current price. Each adapter restricts extraction to its own product cards.
EXTRACT_PRODUCTS = r"""(config) => {
  config = config || {
    cards: '[data-testid="product-pod"], .product-pod',
    link: 'a[href*="/p/"]', title: '[data-testid="product-header"]',
    price: '[data-testid="price-format"], .price-format__main-price'
  };
  const products = [];
  const visible = node => node && node.getClientRects().length &&
    getComputedStyle(node).visibility !== 'hidden';
  const cards = document.querySelectorAll(config.cards);
  for (const card of cards) {
    if (!visible(card) || /out of stock|currently unavailable|sold out/i.test(card.innerText)) continue;
    const title = card.querySelector(config.title);
    const anchor = title?.closest('a[href]') || card.querySelector(config.link);
    const price = Array.from(card.querySelectorAll(config.price)).find(node =>
      visible(node) && !node.closest('s, del') && getComputedStyle(node).textDecorationLine !== 'line-through');
    if (!anchor || !price) continue;
    const whole = price.querySelector('.a-price-whole');
    const fraction = price.querySelector('.a-price-fraction');
    const priceText = whole && fraction
      ? '$' + whole.innerText.replace(/[^\d]/g, '') + '.' + fraction.innerText.trim()
      : price.innerText;
    if (/\/\s*mo|per month|monthly|starting at|from\s*\$/i.test(priceText)) continue;
    const match = priceText.match(/\$\s*([\d,]+)(?:\s*[.\n]\s*(\d{2})|\s+(\d{2}))?/);
    if (match) products.push({name: (title || anchor).innerText.trim() || anchor.title,
      price: match[1].replaceAll(',', '') + '.' + (match[2] || match[3] || '00'),
      url: anchor.href});
  }
  return products;
}"""


def select_products(candidates, query, retailer="Home Depot"):
    config = RETAILERS[retailer]
    products = []
    seen = set()
    def tokens(text):
        return {word.rstrip("s") for word in re.findall(r"[a-z]+", text.lower())
                if len(word) > 2 and word not in {"with", "and", "the", "for"}}
    wanted = tokens(query)
    for candidate in candidates:
        name = candidate.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        url = urljoin("https://www." + config["domain"], str(candidate.get("url") or ""))
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {config["domain"], "www." + config["domain"]}
                or not re.search(config["path"], parsed.path) or parsed.username or parsed.password):
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
        identity = (parsed.hostname, parsed.path)
        if identity in seen:
            continue
        seen.add(identity)
        products.append(SourcedProduct(name=name.strip(), price=float(price.quantize(Decimal("0.01"))),
                                       url=url, retailer=retailer).model_dump())
    return products


def select_product(candidates, query):
    """Compatibility helper for the single-retailer probe."""
    return next(iter(select_products(candidates, query)), None)


def log_failure(page, retailer, query, reason, status=None):
    """Private local diagnostics, deliberately not served by FastAPI."""
    stem = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + RETAILERS[retailer]["slug"] + "-" + uuid4().hex[:8]
    metadata = dict(retailer=retailer, query=query, reason=reason, status=status,
                    timestamp=datetime.now(timezone.utc).isoformat())
    try:
        DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
        if page is not None:
            metadata["url"] = page.url
            try:
                (DIAGNOSTICS_ROOT / (stem + ".html")).write_text(page.content(), encoding="utf-8")
            except BrowserError as error:
                metadata["capture_error"] = str(error)
        (DIAGNOSTICS_ROOT / (stem + ".json")).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        LOGGER.warning("Sourcing diagnostics: %s", DIAGNOSTICS_ROOT / (stem + ".json"))
    except OSError:
        LOGGER.exception("Could not write sourcing diagnostics for %s", retailer)


def search_retailer(page, query, retailer):
    config = RETAILERS[retailer]
    status = None
    try:
        response = page.goto("https://www." + config["domain"] + config["search"] + quote(query, safe=""),
                             wait_until="domcontentloaded", timeout=25000)
        status = response.status if response else None
        if status and status >= 400:
            log_failure(page, retailer, query, "HTTP error", status)
            return []
        # Wait for hydrated prices, not merely a product-card shell.
        page.wait_for_function("""config => {
          const blocked = /access denied|verify you are human|robot check|captcha|no results|sorry, no/i.test(document.body.innerText);
          return blocked || Array.from(document.querySelectorAll(config.cards)).some(card =>
            Array.from(card.querySelectorAll(config.price)).some(price => price.innerText.includes('$')));
        }""", arg=config, timeout=12000)
        products = select_products(page.evaluate(EXTRACT_PRODUCTS, config), query, retailer)
        if not products:
            log_failure(page, retailer, query, "No relevant rendered products with readable prices", status)
        return products
    except BrowserError as error:
        log_failure(page, retailer, query, str(error), status)
        return []


def search_product(page, query):
    products = search_retailer(page, query, "Home Depot")
    return (products[0], None) if products else (None, "No product found.")


def search_retailer_queries(retailer, queries):
    """Each worker owns its Playwright objects and a separate persistent profile."""
    results = {query: [] for query in queries}
    # Avoid profile collisions between simultaneous requests in this server process.
    with PROFILE_LOCKS[retailer]:
        try:
            with sync_playwright() as playwright:
                # Match the installed Chromium version and platform, removing only
                # the headless product token from the ordinary desktop UA string.
                probe = playwright.chromium.launch(headless=True, channel="chromium")
                try:
                    probe_page = probe.new_page()
                    user_agent = probe_page.evaluate("navigator.userAgent").replace("HeadlessChrome/", "Chrome/")
                finally:
                    probe.close()
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_ROOT / RETAILERS[retailer]["slug"]),
                    headless=True, channel="chromium", user_agent=user_agent,
                    locale="en-US", viewport={"width": 1440, "height": 1000},
                    accept_downloads=False,
                )
                try:
                    for query in queries:
                        page = None
                        try:
                            page = context.new_page()
                            results[query] = search_retailer(page, query, retailer)
                        except BrowserError as error:
                            log_failure(page, retailer, query, str(error))
                        finally:
                            if page is not None:
                                try:
                                    page.close()
                                except BrowserError:
                                    pass
                finally:
                    context.close()
        except (BrowserError, OSError) as error:
            log_failure(None, retailer, " | ".join(queries), str(error))
    return results


def search_all_retailers(queries):
    results = {query: [] for query in queries}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(search_retailer_queries, retailer, queries): retailer for retailer in RETAILERS}
        for future in as_completed(futures):
            try:
                for query, products in future.result().items():
                    results[query].extend(products)
            except Exception as error:
                # A broken adapter must not discard the other retailers' results.
                log_failure(None, futures[future], " | ".join(queries), str(error))
    for products in results.values():
        products.sort(key=lambda product: (Decimal(str(product["price"])), product["retailer"], product["url"]))
    return results


def source_layout(layout):
    enriched = {**layout, "elements": []}
    retail = []
    for element in layout["elements"]:
        item = {**element, "sourced_product": None, "estimated_feature": None,
                "sourcing_status": "unavailable", "sourcing_note": None,
                "sourced_total_usd": None, "alternative_products": []}
        kind = feature_kind(element)
        if kind:
            item.update(estimated_feature=estimate_feature(element, kind), sourcing_status="estimated")
        else:
            retail.append(item)
        enriched["elements"].append(item)
    if retail:
        queries = list(dict.fromkeys(item["type"].strip() for item in retail))
        matches = search_all_retailers(queries)
        for item in retail:
            products = matches[item["type"].strip()]
            if products:
                item.update(sourced_product=products[0], alternative_products=products[1:], sourcing_status="sourced")
                item["sourced_total_usd"] = float(Decimal(str(products[0]["price"])) * item["quantity"])
            else:
                item["sourcing_note"] = "No matching priced products found."
    enriched["sourced_materials_total_usd"] = float(sum(
        (Decimal(str(item["sourced_total_usd"])) for item in retail
         if item["sourced_total_usd"] is not None), Decimal(0)))
    enriched["estimated_features_range_usd"] = {
        bound: float(sum((Decimal(str(item["estimated_feature"]["cost_range_usd"][bound]))
                         for item in enriched["elements"] if item["estimated_feature"]), Decimal(0)))
        for bound in ("min", "max")}
    enriched["sourcing_complete"] = all(item["sourcing_status"] == "sourced" for item in retail)
    return enriched
