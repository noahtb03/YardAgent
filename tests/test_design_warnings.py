"""Constraint violations should adjust/warn, not reject a valid proposal."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app, DesignRequest, DesignLayout, validate_layout


def request():
    return DesignRequest.model_validate(dict(budget=100, area_sq_ft=25, analysis=dict(
        width_ft=dict(min=10, max=12), length_ft=dict(min=10, max=12),
        area_sq_ft=dict(min=100, max=144), reference_object=None, slope="Flat",
        existing_features=[], limitations="")))


def item(name, width=4, length=4, x=0, y=0):
    return dict(id=name, type=name, category="plant", quantity=1,
                position_x_ft=x, position_y_ft=y, width_ft=width, length_ft=length)


def layout(*items):
    return DesignLayout.model_validate(dict(elements=list(items), notes=[]))


class DesignWarningTests(unittest.TestCase):
    def test_design_has_no_cost_or_budget_evaluation(self):
        with patch.dict("os.environ", OPENAI_API_KEY="test"), patch("main.OpenAI") as api, TestClient(app) as client:
            api.return_value.__enter__.return_value.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed=layout(item("Rose")))
            response = client.post("/design", json=request().model_dump())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["elements"]), 1)
        self.assertNotIn("estimated_cost_usd", response.json())
        self.assertFalse(any("budget" in warning for warning in response.json()["warnings"]))

    def test_area_reduces_footprints_and_preserves_all_elements(self):
        original = layout(item("Rose"), item("Fern", x=5))
        result = validate_layout(original, request())
        self.assertEqual([item.id for item in result.elements], ["Rose", "Fern"])
        self.assertEqual(len(original.elements), 2)
        self.assertLess(result.elements[1].width_ft,original.elements[1].width_ft)
        self.assertTrue(any("by 7 sq ft" in warning for warning in result.warnings))

    def test_out_of_bounds_moves_or_shrinks_and_never_drops(self):
        result = validate_layout(layout(item("Rose", x=9), item("Tree", width=12)), request())
        self.assertEqual(len(result.elements), 2)
        self.assertLessEqual(result.elements[0].position_x_ft + result.elements[0].width_ft, 10)
        self.assertEqual(result.elements[0].width_ft, 4)
        self.assertTrue(any("resize" in warning for warning in result.warnings))

    def test_existing_bounds_outside_yard_and_overlap_are_warnings(self):
        data = request().model_dump()
        data["existing_feature_bounds"] = [dict(name="Shed", position_x_ft=0, position_y_ft=0, width_ft=12, length_ft=4)]
        result = validate_layout(layout(item("Rose")), DesignRequest.model_validate(data))
        self.assertEqual(len(result.elements), 1)
        self.assertTrue(any("bounds remain reserved" in warning for warning in result.warnings))

    def test_missing_dimensions_and_duplicate_ids_do_not_block(self):
        data = request().model_dump()
        data["analysis"]["width_ft"] = None
        data["area_sq_ft"] = 100
        result = validate_layout(layout(item("Rose", width=3, length=3), item("Rose", width=3, length=3, x=6)), DesignRequest.model_validate(data))
        self.assertEqual([item.id for item in result.elements], ["Rose", "Rose-2"])
        self.assertTrue(any("Missing yard dimensions" in warning for warning in result.warnings))
