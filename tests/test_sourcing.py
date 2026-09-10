"""Deterministic sourcing and browser checks; retailer/API responses are fixtures."""
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from playwright.sync_api import sync_playwright, Error as BrowserError

from main import app, DesignLayout, DesignRequest, SourcedLayout, source, validate_layout
from sourcing import EXTRACT_PRODUCTS, feature_kind, select_product, source_layout


def element(kind="Boxwood shrub", category="plant", quantity=2, **kwargs):
    return dict(id=kind, type=kind, category=category, quantity=quantity,
                position_x_ft=0, position_y_ft=0, width_ft=4, length_ft=5, **kwargs)


def layout(*elements):
    return dict(elements=list(elements), estimated_cost_usd=100, notes=[])


class SourcingTests(unittest.TestCase):
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
            with self.assertRaisesRegex(ValueError, "existing feature"):
                validate_layout(DesignLayout.model_validate(layout(element(name, "hardscape"))), request)
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
        with patch("sourcing.sync_playwright"), patch("sourcing.search_product", side_effect=[
            (product, None), (None, "No price")]) as search:
            result = source_layout(layout(element(), second, element("Chair", "furniture")))
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["sourced_materials_total_usd"], 79.96)
        self.assertFalse(result["sourcing_complete"])
        self.assertIsNone(result["elements"][-1]["sourced_total_usd"])
        SourcedLayout.model_validate(result)

    def test_missing_browser_retains_feature_estimates(self):
        with patch("sourcing.sync_playwright", side_effect=BrowserError("missing browser")):
            result = source_layout(layout(element(), element("Patio", "hardscape")))
        self.assertFalse(result["sourcing_complete"])
        self.assertEqual(result["estimated_features_range_usd"], {"min": 160, "max": 500})
        self.assertIn("browser unavailable", result["elements"][0]["sourcing_note"])

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
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_card_price_and_structured_offer_extraction(self):
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


if __name__ == "__main__":
    unittest.main()
