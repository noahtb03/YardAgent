"""Match verification must precede price selection."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from sourcing import MatchReview, confirm_products, source_layout


def product(name, price):
    return dict(name=name, price=price, retailer="Amazon", url=f"https://www.amazon.com/dp/{price}")


class ProductMatchingTests(unittest.TestCase):
    def test_rejects_treatments_then_selects_cheapest_confirmed_match(self):
        candidates = [product("Oak tree spray", 2), product("Oak tree fertilizer", 3),
                      product("Oak tree decorative ornament", 5), product("Live oak tree", 40),
                      product("Live oak tree 3 gallon", 30)]
        with patch.dict("os.environ", OPENAI_API_KEY="test"), patch("sourcing.OpenAI") as api:
            parse = api.return_value.__enter__.return_value.responses.parse
            parse.return_value = SimpleNamespace(status="completed", output_parsed=MatchReview.model_validate(dict(decisions=[
                dict(candidate_id=0, matches=False, reason="Decoration"),
                dict(candidate_id=1, matches=True, reason="Living tree"),
                dict(candidate_id=2, matches=True, reason="Living tree") ])))
            result = confirm_products(dict(type="Oak tree", category="plant"), candidates)
        self.assertEqual([item["price"] for item in result], [30, 40])
        self.assertNotIn("spray", parse.call_args.kwargs["input"])
        self.assertNotIn("fertilizer", parse.call_args.kwargs["input"])

    def test_no_key_or_invalid_review_never_accepts_unverified_product(self):
        candidates = [product("Patio chair", 20)]
        with patch.dict("os.environ", OPENAI_API_KEY=""), patch("sourcing.OpenAI") as api:
            self.assertEqual(confirm_products(dict(type="Patio chair", category="furniture"), candidates), [])
            api.assert_not_called()
        with patch.dict("os.environ", OPENAI_API_KEY="test"), patch("sourcing.OpenAI") as api:
            api.return_value.__enter__.return_value.responses.parse.return_value = SimpleNamespace(
                status="completed", output_parsed=MatchReview.model_validate(dict(decisions=[dict(candidate_id=99, matches=True, reason="Wrong ID")])) )
            self.assertEqual(confirm_products(dict(type="Patio chair", category="furniture"), candidates), [])

    def test_furniture_parts_filtered_before_model(self):
        with patch("sourcing.OpenAI") as api:
            self.assertEqual(confirm_products(dict(type="Patio chair", category="furniture"),
                [product("Patio chair replacement legs", 5), product("Patio furniture cleaner spray", 4)]), [])
            api.assert_not_called()

    def test_selected_total_and_alternatives_use_only_approved_matches(self):
        item = dict(id="oak", type="Oak tree", category="plant", quantity=2,
                    position_x_ft=0, position_y_ft=0, width_ft=4, length_ft=4)
        candidates = [product("Oak ornament", 5), product("Live oak", 30), product("Live oak 3 gallon", 40)]
        with patch("sourcing.search_all_retailers", return_value={"Oak tree": candidates}), \
                patch("sourcing.confirm_products", return_value=candidates[1:]):
            result = source_layout(dict(elements=[item], notes=[]))
        self.assertEqual(result["sourced_materials_total_usd"], 60)
        self.assertEqual(result["elements"][0]["alternative_products"], [candidates[2]])
