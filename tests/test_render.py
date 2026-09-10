"""Rendering contract and browser tests with generated-image API fixtures."""
import base64
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException
from openai import APITimeoutError, RateLimitError
from PIL import Image
from playwright.sync_api import sync_playwright

from main import app, RenderRequest, build_render_prompt


def payload():
    return dict(original_photo="data:image/png;base64," + base64.b64encode(png()).decode(), analysis=dict(width_ft=dict(min=30, max=40), length_ft=dict(min=30, max=40),
        area_sq_ft=None, reference_object=None, slope="Flat",
        existing_features=["Wooden shed at far right"], limitations="Approximate scale",
        photo_description="A grassy yard with a brown shed, viewed from the house in afternoon light."),
        layout=dict(elements=[dict(id="chair", type="Patio chair", category="furniture", quantity=2,
            position_x_ft=3, position_y_ft=8, width_ft=4, length_ft=5,
            sourced_product=dict(name="Hampton Bay Cedar Adirondack Chair", price=99,
                url="https://www.homedepot.com/p/chair/123"), estimated_feature=None,
            sourcing_status="sourced", sourcing_note=None, sourced_total_usd=198)],
            notes=[], sourced_materials_total_usd=198,
            estimated_features_range_usd=dict(min=0, max=0), sourcing_complete=True))


def png():
    output = BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format="PNG")
    return output.getvalue()


class RenderTests(unittest.TestCase):
    def test_prompt_uses_product_positions_and_original_description(self):
        prompt = build_render_prompt(RenderRequest.model_validate(payload()))
        scene = json.loads(prompt.split("SCENE DATA:\n")[1])
        self.assertEqual(scene["new_additions"][0]["name"], "Hampton Bay Cedar Adirondack Chair")
        self.assertEqual(scene["new_additions"][0]["position_y_ft"], 8)
        self.assertEqual(scene["new_additions"][0]["quantity"], 2)
        self.assertIn("brown shed", scene["original_photo_description"])
        self.assertEqual(scene["existing_features_to_preserve"], ["Wooden shed at far right"])

    def test_partial_sourcing_and_older_analysis_use_explicit_fallback(self):
        data = payload()
        del data["analysis"]["photo_description"]
        item = data["layout"]["elements"][0]
        item.update(sourced_product=None, sourcing_status="unavailable", sourced_total_usd=None)
        with self.assertRaises(HTTPException) as error:
            build_render_prompt(RenderRequest.model_validate(data))
        self.assertEqual(error.exception.status_code, 422)

    def test_render_endpoint_returns_real_api_image_bytes(self):
        encoded = base64.b64encode(png()).decode()
        with patch.dict("os.environ", OPENAI_API_KEY="test", OPENAI_IMAGE_MODEL="gpt-image-2"), \
                patch("main.OpenAI") as api, TestClient(app) as client:
            generate = api.return_value.__enter__.return_value.images.edit
            generate.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])
            response = client.post("/render", json=payload())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["image_url"], "data:image/png;base64," + encoded)
            self.assertEqual(generate.call_args.kwargs["prompt"], response.json()["prompt"])
            self.assertEqual(generate.call_args.kwargs["output_format"], "png")
            image_name, image_bytes, image_type = generate.call_args.kwargs["image"]
            self.assertEqual((image_name, image_type), ("original-yard.jpg", "image/jpeg"))
            with Image.open(BytesIO(image_bytes)) as original:
                self.assertEqual(original.size, (8, 8))
                self.assertEqual(original.format, "JPEG")
            api.return_value.__enter__.return_value.images.generate.assert_not_called()

    def test_missing_or_invalid_original_photo_is_not_generated(self):
        with patch("main.OpenAI") as api, TestClient(app) as client:
            data = payload()
            del data["original_photo"]
            self.assertEqual(client.post("/render", json=data).status_code, 422)
            data["original_photo"] = "data:image/png;base64,bm90IGFuIGltYWdl"
            self.assertEqual(client.post("/render", json=data).status_code, 400)
            data["original_photo"] = "https://example.com/photo.png"
            self.assertEqual(client.post("/render", json=data).status_code, 400)
            api.assert_not_called()

    def test_configuration_input_and_upstream_errors(self):
        with patch.dict("os.environ", OPENAI_API_KEY=""), TestClient(app) as client:
            self.assertEqual(client.post("/render", json=payload()).status_code, 503)
        request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
        failures = [(SimpleNamespace(data=[]), 502),
                    (SimpleNamespace(data=[SimpleNamespace(b64_json="not an image")]), 502),
                    (APITimeoutError(request=request), 504),
                    (RateLimitError("quota", response=httpx.Response(429, request=request), body=None), 503)]
        with patch.dict("os.environ", OPENAI_API_KEY="test"), patch("main.OpenAI") as api, TestClient(app) as client:
            generate = api.return_value.__enter__.return_value.images.edit
            invalid = payload(); invalid["layout"]["elements"][0]["position_x_ft"] = 100
            self.assertEqual(client.post("/render", json=invalid).status_code, 422)
            generate.assert_not_called()
            for result, code in failures:
                generate.side_effect = result if isinstance(result, Exception) else None
                generate.return_value = result
                self.assertEqual(client.post("/render", json=payload()).status_code, code)


class RenderBrowserTests(unittest.TestCase):
    def test_full_flow_comparison_error_retry_and_new_photo_reset(self):
        data = payload()
        encoded = base64.b64encode(png()).decode()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport=dict(width=1100, height=900))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("http://yard.test/", lambda route: route.fulfill(content_type="text/html",
                    body=(Path(__file__).parents[1] / "static/index.html").read_text(encoding="utf-8")))
                page.route("**/analyze", lambda route: route.fulfill(json=data["analysis"]))
                design = {key: data["layout"][key] for key in ("elements", "notes")}
                design = {**design, "elements": [*design["elements"], {**design["elements"][0], "id": "extra", "type": "Extra chair"}]}
                design_requests = []
                source_requests = []
                def design_route(route):
                    design_requests.append(route.request.post_data_json)
                    route.fulfill(json=design)
                def source_route(route):
                    source_requests.append(route.request.post_data_json)
                    route.fulfill(json=data["layout"])
                page.route("**/design", design_route)
                page.route("**/source", source_route)
                render_requests = []
                def render_route(route):
                    render_requests.append(route.request.post_data_json)
                    if len(render_requests) == 1:
                        route.fulfill(status=504, json=dict(detail="Yard rendering timed out. Please try again."))
                    else:
                        route.fulfill(json=dict(image_url="data:image/png;base64," + encoded, prompt="fixture"))
                page.route("**/render", render_route)
                page.goto("http://yard.test/")
                page.locator("#photo").set_input_files(dict(name="yard.png", mimeType="image/png", buffer=png()))
                page.get_by_role("button", name="Analyze photo").click()
                page.locator("#budget").fill("500")
                page.locator("#user-intent").fill("I want a pool and a fire pit")
                page.get_by_role("button", name="Modern", exact=True).click()
                page.get_by_role("button", name="Generate design").click()
                page.locator('input[data-element-id="extra"]').uncheck()
                page.get_by_role("button", name="Source products").click()
                # A changed file picker must not substitute a different photo
                # for the image that produced the current analysis/layout.
                page.locator("#photo").set_input_files(dict(name="other.png", mimeType="image/png", buffer=b"different file"))
                page.get_by_role("button", name="Render redesigned yard").click()
                page.wait_for_function("document.querySelector('#render-status').textContent.includes('timed out')")
                self.assertTrue(page.locator("#render-results").is_hidden())
                page.get_by_role("button", name="Render redesigned yard").click()
                page.wait_for_function("document.querySelector('#render-results').hidden === false")
                self.assertEqual(render_requests[-1], data)
                self.assertEqual(design_requests[0]["user_intent"], "I want a pool and a fire pit. Modern style")
                self.assertEqual([item["id"] for item in source_requests[0]["layout"]["elements"]], ["chair"])
                self.assertEqual(source_requests[0]["budget"], 500)
                self.assertTrue(page.locator("#original-photo").get_attribute("src").startswith("blob:"))
                original = page.locator("#original-photo").bounding_box()
                rendered = page.locator("#rendered-photo").bounding_box()
                self.assertGreater(rendered["x"], original["x"])
                page.set_viewport_size(dict(width=390, height=844))
                self.assertGreater(page.locator("#rendered-photo").bounding_box()["y"],
                                   page.locator("#original-photo").bounding_box()["y"])
                page.get_by_role("button", name="Analyze photo").click()
                self.assertTrue(page.locator("#render-results").is_hidden())
                self.assertIsNone(page.locator("#rendered-photo").get_attribute("src"))
                self.assertEqual(errors, [])
            finally:
                browser.close()
