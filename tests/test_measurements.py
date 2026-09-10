"""Holistic analysis contract and boundary assumptions."""
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import UploadFile
from PIL import Image
from pydantic import ValidationError
from main import NumericYardAnalysis, finalize_analysis, analyze


def estimate():
    return NumericYardAnalysis.model_validate(dict(
        width_ft=dict(min=23, max=37), length_ft=dict(min=31, max=49),
        area_sq_ft=dict(min=650, max=1600), reference_object=dict(
            object="Fence picket", assumed_dimension="width", size_ft=dict(min=5.5/12, max=5.5/12),
            reasoning="Compare the yard extent holistically with the fence."),
        slope="Flat", existing_features=["Fence"], limitations="Approximate scale",
        visible_boundaries=["left", "right", "far"], confidence="medium", boundary_assumptions=[]))


class MeasurementTests(unittest.TestCase):
    def test_direct_ranges_are_preserved_including_irregular_area(self):
        original = estimate()
        result = finalize_analysis(original)
        self.assertEqual(result.width_ft, original.width_ft)
        self.assertEqual(result.length_ft, original.length_ft)
        self.assertEqual(result.area_sq_ft, original.area_sq_ft)
        self.assertNotEqual(result.area_sq_ft.min, result.width_ft.min * result.length_ft.min)
        self.assertEqual(result.confidence, "medium")
        self.assertIn("photographer", result.boundary_assumptions[-1])
        self.assertEqual(original.boundary_assumptions, [])

    def test_missing_boundaries_and_reference_force_low_confidence(self):
        data = estimate()
        data.visible_boundaries = ["far"]
        data.reference_object = None
        data.confidence = "high"
        result = finalize_analysis(data)
        self.assertEqual(result.confidence, "low")
        self.assertTrue(any("Left boundary" in note for note in result.boundary_assumptions))
        self.assertTrue(any("Right boundary" in note for note in result.boundary_assumptions))
        self.assertTrue(any("Scale assumed" in note for note in result.boundary_assumptions))
        self.assertEqual(result.area_sq_ft, data.area_sq_ft)

    def test_schema_requires_numbers_and_has_no_pixel_fields(self):
        schema = NumericYardAnalysis.model_json_schema()
        for removed in ("pixel_measurements", "measurement_calculation", "depth_scale_multiplier"):
            self.assertNotIn(removed, schema["properties"])
        for field in ("width_ft", "length_ft", "area_sq_ft"):
            data = estimate().model_dump()
            data[field] = None
            with self.assertRaises(ValidationError):
                NumericYardAnalysis.model_validate(data)

    def test_analyze_zero_temperature_and_direct_schema(self):
        buffer = BytesIO()
        Image.new("RGB", (100, 80)).save(buffer, format="PNG")
        upload = UploadFile(filename="yard.png", file=BytesIO(buffer.getvalue()))
        with patch.dict("os.environ", OPENAI_API_KEY="test"), patch("main.OpenAI") as api:
            parse = api.return_value.__enter__.return_value.responses.parse
            parse.return_value = SimpleNamespace(status="completed", output_parsed=estimate())
            result = analyze(upload)
        self.assertEqual(parse.call_args.kwargs["temperature"], 0)
        self.assertIs(parse.call_args.kwargs["text_format"], NumericYardAnalysis)
        self.assertEqual(result.area_sq_ft.min, 650)
        self.assertTrue(upload.file.closed)