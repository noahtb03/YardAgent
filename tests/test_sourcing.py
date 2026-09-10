"""Deterministic sourcing and browser checks; retailer/API responses are fixtures."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from playwright.sync_api import sync_playwright, Error as BrowserError

from main import app, DesignLayout, DesignRequest, SourcedLayout, source, validate_layout
from sourcing import (EXTRACT_PRODUCTS, RETAILERS, feature_kind, select_product,
                      select_products, source_layout, search_all_retailers, search_retailer)


def element(kind="Boxwood shrub", category="plant", quantity=2, **kwargs):
    return dict(id=kind, type=kind, category=category, quantity=quantity,
                position_x_ft=0, position_y_ft=0, width_ft=4, length_ft=5, **kwargs)


def layout(*elements):
    return dict(elements=list(elements), estimated_cost_usd=100, notes=[])


class SourcingTests(unittest.TestCase):
    def setUp(self):
        verifier = patch("sourcing.confirm_products", side_effect=lambda element, candidates: candidates)
        verifier.start()
        self.addCleanup(verifier.stop)

    def test_source_endpoint_returns_enriched_layout_and_validates_input(self):
        with TestClient(app) as client:
            response = client.post("/source", json=layout(element("Patio", "hardscape")))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["elements"][0]["estimated_feature"]["status"], "estimated")
            self.assertEqual(client.post("/source", json=layout(element(), element())).status_code, 422)
            invalid = element(); invalid["quantity"] = 0
            self.assertEqual(client.post("/source", json=layout(invalid)).status_code, 422)

    def test_existing_shed_rejected_but_accessory_allowed(self):
        request = DesignRequest.model_validate(dict(budget=1000, analysis=dict(
            width_ft=dict(min=30, max=40), length_ft=dict(min=30, max=40),
            area_sq_ft=None, reference_object=None, slope="Flat",
            existing_features=["Wooden shed at the far right", "Patio at the left"], limitations="")))
        for name in ("Shed", "Storage shed", "Existing wooden shed"):
            result = validate_layout(DesignLayout.model_validate(layout(element(name, "hardscape"))), request)
            self.assertEqual(result.elements, [])
            self.assertTrue(any("existing feature" in warning for warning in result.warnings))
        validate_layout(DesignLayout.model_validate(layout(element("Patio chair", "furniture"))), request)

    def test_features_and_materials_are_distinct(self):
        for kind in ("Patio", "Concrete paver patio"):
            self.assertEqual(feature_kind(element(kind, "hardscape")), "patio")
        for kind, category in (("Patio pavers", "hardscape"), ("Pool pump", "hardscape"),
                               ("Bar stool", "furniture"), ("Patio table", "furniture")):
            self.assertIsNone(feature_kind(element(kind, category)))

    def test_feature_totals_do_not_launch_browser_or_multiply_group_area(self):
        with patch("sourcing.sync_playwright") as browser:
            result = source(DesignLayout.model_validate(layout(
                element("Patio", "hardscape", 2), element("Pool", "hardscape", 1),
                element("Outdoor bar", "hardscape", 2))))
        browser.assert_not_called()
        self.assertEqual(result["estimated_features_range_usd"], {"min": 55160, "max": 128500})
        self.assertEqual(result["sourced_materials_total_usd"], 0)
        self.assertTrue(result["sourcing_complete"])
        SourcedLayout.model_validate(result)

    def test_partial_results_quantity_rounding_and_deduplication(self):
        product = dict(name="Boxwood shrub", price=19.99, url="https://www.homedepot.com/p/Boxwood/123")
        second = element(); second["id"] = "second"
        with patch("sourcing.search_all_retailers", return_value={"Boxwood shrub": [product], "Chair": []}) as search:
            result = source_layout(layout(element(), second, element("Chair", "furniture")))
        search.assert_called_once_with(["Boxwood shrub", "Chair"])
        self.assertEqual(result["sourced_materials_total_usd"], 79.96)
        self.assertFalse(result["sourcing_complete"])
        self.assertIsNone(result["elements"][-1]["sourced_total_usd"])
        SourcedLayout.model_validate(result)

    def test_missing_browser_retains_feature_estimates(self):
        with TemporaryDirectory() as diagnostics, patch("sourcing.DIAGNOSTICS_ROOT", Path(diagnostics)), \
                patch("sourcing.sync_playwright", side_effect=BrowserError("missing browser")):
            result = source_layout(layout(element(), element("Patio", "hardscape")))
            self.assertEqual(len(list(Path(diagnostics).glob("*.json"))), 4)
        self.assertFalse(result["sourcing_complete"])
        self.assertEqual(result["estimated_features_range_usd"], {"min": 160, "max": 500})
        self.assertEqual(result["elements"][0]["sourcing_note"], "No confirmed matching products found.")

    def test_parallel_retailers_failure_isolation_and_lowest_price(self):
        barrier = Barrier(4)
        def worker(retailer, queries):
            barrier.wait(timeout=5)  # Fails if workers were run serially.
            if retailer == "Home Depot":
                raise BrowserError("403")
            price = {"Lowe's": 19.99, "Wayfair": 29.99, "Amazon": 15.50}[retailer]
            return {query: [dict(name=query, price=price, retailer=retailer,
                                url="https://www." + RETAILERS[retailer]["domain"] + "/p/test")]
                    for query in queries}
        with patch("sourcing.search_retailer_queries", side_effect=worker), patch("sourcing.log_failure") as log:
            result = source_layout(layout(element()))
        item = result["elements"][0]
        self.assertEqual(item["sourced_product"]["retailer"], "Amazon")
        self.assertEqual([p["retailer"] for p in item["alternative_products"]], ["Lowe's", "Wayfair"])
        self.assertEqual(result["sourced_materials_total_usd"], 31)
        self.assertTrue(result["sourcing_complete"])
        self.assertIsNone(item["sourcing_note"])
        log.assert_called_once()
        SourcedLayout.model_validate(result)

    def test_select_first_reasonable_priced_safe_product(self):
        candidates = [dict(name="Boxwood fertilizer", price="5", url="/p/Food/1"),
                      dict(name="Boxwood shrub", price="NaN", url="/p/Plant/2"),
                      dict(name="Boxwood shrub", price="1", url="https://evil.example/p/3"),
                      dict(name="Boxwood shrub", price="19.99", url="/p/Plant/4"),
                      dict(name="Boxwood shrub", price="10", url="/p/Plant/5")]
        product = select_product(candidates, "Boxwood")
        self.assertEqual(product["price"], 19.99)
        self.assertEqual(product["url"], "https://www.homedepot.com/p/Plant/4")


class BrowserTests(unittest.TestCase):
    def setUp(self):
        verifier = patch("sourcing.confirm_products", side_effect=lambda element, candidates: candidates)
        verifier.start()
        self.addCleanup(verifier.stop)

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_card_price_ignores_unrendered_structured_offer(self):
        page = self.browser.new_page()
        try:
            page.set_content('''<div data-testid="product-pod">
                <a data-testid="product-header" href="https://www.homedepot.com/p/Boxwood/123">Boxwood shrub</a>
                <div class="price-format__main-price">$<span>19</span>\n<span>99</span></div>
                <s>$29.99</s></div>
                <script type="application/ld+json">{"@type":"Product","name":"Boxwood food",
                "url":"/p/Food/1","offers":{"price":4,"priceCurrency":"USD"}}</script>''')
            product = select_product(page.evaluate(EXTRACT_PRODUCTS), "Boxwood shrub")
            self.assertEqual(product["price"], 19.99)
        finally:
            page.close()

    def test_retailer_dom_adapters_and_403_diagnostics(self):
        fixtures = {
            "Lowe's": '<div data-selector="splp-prd-lst"><a href="https://www.lowes.com/pd/chair/123"><h3>Adirondack chair</h3></a><div data-selector="splp-prc">$39.99</div></div>',
            "Wayfair": '<div data-test-id="ListingCard"><a href="https://www.wayfair.com/outdoor/pdp/chair.html"><h2 data-name-id="ListingCardName">Adirondack chair</h2></a><span data-test-id="PricingStandard-leadPrice">$49.99</span><s>$79.99</s></div>',
            "Amazon": '<div data-component-type="s-search-result" data-asin="ABC"><a href="https://www.amazon.com/chair/dp/ABC"><h2>Adirondack chair</h2></a><span class="a-price"><span class="a-price-symbol">$</span><span class="a-price-whole">29.</span><span class="a-price-fraction">99</span></span><span class="a-price a-text-price">$79.99</span></div>',
        }
        page = self.browser.new_page()
        try:
            for retailer, html in fixtures.items():
                with self.subTest(retailer=retailer):
                    page.set_content(html)
                    products = select_products(page.evaluate(EXTRACT_PRODUCTS, RETAILERS[retailer]), "Adirondack chair", retailer)
                    self.assertEqual(len(products), 1)
                    self.assertEqual(products[0]["retailer"], retailer)
                    self.assertEqual(products[0]["price"], {"Lowe's":39.99,"Wayfair":49.99,"Amazon":29.99}[retailer])
            page.route("**/s/**", lambda route: route.fulfill(status=403, content_type="text/html", body="<h1>Access denied diagnostic fixture</h1>"))
            with TemporaryDirectory() as diagnostics, patch("sourcing.DIAGNOSTICS_ROOT", Path(diagnostics)):
                self.assertEqual(search_retailer(page, "chair", "Home Depot"), [])
                self.assertIn("diagnostic fixture", next(Path(diagnostics).glob("*.html")).read_text())
                self.assertIn('"status": 403', next(Path(diagnostics).glob("*.json")).read_text())
        finally:
            page.close()

    def test_ui_sourcing_and_retry(self):
        page = self.browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        original = layout(element("Patio", "hardscape"))
        enriched = source_layout(original)
        try:
            page.route("http://yard.test/", lambda route: route.fulfill(
                content_type="text/html", body=(Path(__file__).parents[1] / "static/index.html").read_text(encoding="utf-8")))
            page.route("**/source", lambda route: route.fulfill(json=enriched))
            page.goto("http://yard.test/")
            page.evaluate("value => { layout = value; designResults.hidden = false; }", original)
            page.get_by_role("button", name="Source products").click()
            page.wait_for_function("document.querySelector('#source-totals').hidden === false")
            self.assertIn("$160.00–$500.00", page.locator("#features-total").inner_text())
            self.assertIn("$0.00", page.locator("#materials-total").inner_text())
            page.get_by_role("button", name="Source products").click()
            page.wait_for_function("document.querySelector('#source-products').disabled === false")
            self.assertEqual(page.locator("#sourced-items li").count(), 1)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_ui_shows_selected_retailer_and_alternatives(self):
        page = self.browser.new_page()
        product = dict(name="Adirondack chair", price=50, retailer="Amazon", url="https://www.amazon.com/dp/ABC")
        alternative = dict(name="Wood Adirondack chair", price=70, retailer="Wayfair", url="https://www.wayfair.com/outdoor/pdp/chair.html")
        original = layout(element("Adirondack chair", "furniture"))
        with patch("sourcing.search_all_retailers", return_value={"Adirondack chair": [product, alternative]}):
            enriched = source_layout(original)
        try:
            page.route("http://yard.test/", lambda route: route.fulfill(content_type="text/html",
                body=(Path(__file__).parents[1] / "static/index.html").read_text(encoding="utf-8")))
            page.route("**/source", lambda route: route.fulfill(json=enriched))
            page.goto("http://yard.test/")
            page.evaluate("value => { layout = value; designResults.hidden = false; }", original)
            page.get_by_role("button", name="Source products").click()
            page.wait_for_function("document.querySelector('#source-totals').hidden === false")
            self.assertIn("Amazon: $50.00", page.locator("#sourced-items").inner_text())
            page.get_by_text("See 1 alternatives").click()
            self.assertIn("Wayfair: $70.00", page.locator("#sourced-items details").inner_text())
            self.assertIn("$100.00", page.locator("#materials-total").inner_text())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
