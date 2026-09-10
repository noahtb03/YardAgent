"""Selection totals, feature routing and render item identity."""
import json
import unittest
from unittest.mock import patch
from sourcing import source_layout, feature_kind
from main import RenderRequest, build_render_prompt, DesignLayout
from test_render import payload


def element(name, category="hardscape"):
    return dict(id=name, type=name, category=category, quantity=1,
                position_x_ft=0, position_y_ft=0, width_ft=10, length_ft=10)


class SelectionBudgetTests(unittest.TestCase):
    def test_large_hardscape_never_searches_retailers(self):
        names = ["Pool", "Concrete paver patio", "Outdoor bar", "Deck", "Stone retaining wall", "Pergola", "Gazebo", "Built-in fire pit"]
        with patch("sourcing.search_all_retailers") as search:
            result = source_layout(dict(elements=[element(name) for name in names], notes=[]), 1000)
        search.assert_not_called()
        self.assertTrue(all(item["estimated_feature"] for item in result["elements"]))
        self.assertIn("Over budget", result["budget_note"])
        self.assertIsNone(feature_kind(element("Patio pavers")))

    def test_budget_range_and_partial_totals(self):
        product = dict(name="Solar stake light", price=20, retailer="Amazon", url="https://www.amazon.com/dp/A")
        light = element("Solar stake light", "lighting")
        light["quantity"] = 4
        layout = dict(elements=[element("Patio"), light], notes=[])
        with patch("sourcing.search_all_retailers", return_value={"Solar stake light": [product]}), \
                patch("sourcing.confirm_products", return_value=[product]):
            result = source_layout(layout, 1000)
        self.assertEqual(result["sourced_materials_total_usd"], 80)
        self.assertEqual(result["project_total_range_usd"], dict(min=880, max=2580))
        self.assertIn("May exceed budget by up to $1,580.00", result["budget_note"])
        with patch("sourcing.search_all_retailers", return_value={"Solar stake light": []}):
            result = source_layout(layout, 3000)
        self.assertIn("partial", result["budget_note"])

    def test_render_keeps_type_and_quantity_and_excludes_unpriced_items(self):
        data = payload()
        light = data["layout"]["elements"][0]
        light.update(type="Solar stake light", quantity=4, category="lighting")
        light["sourced_product"]["name"] = "Hampton Bay Solar Stake Light"
        unpriced = {**light, "id": "unpriced", "type": "String lights", "sourced_product": None, "sourcing_status": "unavailable"}
        data["layout"]["elements"].append(unpriced)
        prompt = build_render_prompt(RenderRequest.model_validate(data))
        additions = json.loads(prompt.split("SCENE DATA:\n")[1])["new_additions"]
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0]["quantity"], 4)
        self.assertEqual(additions[0]["requested_type"], "Solar stake light")
        self.assertIn("NEVER string lights", prompt)
        self.assertNotIn("estimated_cost_usd", DesignLayout.model_json_schema()["properties"])
