"""Local validation checks; no simulated API responses or network calls."""
from io import BytesIO
import os
import unittest

from fastapi import HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from main import EstimateRange, MAX_IMAGE_BYTES, YardAnalysis, analyze


class ValidationTests(unittest.TestCase):
    def assert_upload_error(self, data, status):
        file = UploadFile(filename="yard.png", file=BytesIO(data))
        with self.assertRaises(HTTPException) as error:
            analyze(file)
        self.assertEqual(error.exception.status_code, status)
        self.assertTrue(file.file.closed)

    def test_invalid_uploads(self):
        self.assert_upload_error(b"", 400)
        self.assert_upload_error(b"not an image", 400)
        self.assert_upload_error(b"x" * (MAX_IMAGE_BYTES + 1), 413)

    def test_missing_key_returns_error_for_valid_image(self):
        buffer = BytesIO()
        Image.new("RGB", (16, 16)).save(buffer, format="PNG")
        previous = os.environ.pop("OPENAI_API_KEY", None)
        try:
            self.assert_upload_error(buffer.getvalue(), 503)
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous

    def test_rejects_invalid_ranges(self):
        for low, high in [(30, 20), (0, 10), (-1, 10), (1, float("inf"))]:
            with self.subTest(low=low, high=high), self.assertRaises(ValidationError):
                EstimateRange(min=low, max=high)

    def test_measurements_are_required_but_nullable(self):
        schema = YardAnalysis.model_json_schema()
        for field in ("width_ft", "length_ft", "area_sq_ft", "reference_object"):
            self.assertIn(field, schema["required"])
            self.assertIn({"type": "null"}, schema["properties"][field]["anyOf"])


if __name__ == "__main__":
    unittest.main()
