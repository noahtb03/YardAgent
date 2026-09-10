from io import BytesIO
from pathlib import Path
import warnings

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

app = FastAPI(title="YardAgent")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
INDEX_PATH = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX_PATH)


@app.post("/analyze")
def analyze(file: UploadFile):
    """Validate an uploaded image and return its metadata."""
    try:
        data = file.file.read(MAX_IMAGE_BYTES + 1)
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image must be 10 MiB or smaller.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    result = {
                        "filename": file.filename,
                        "content_type": Image.MIME.get(image.format, "application/octet-stream"),
                        "format": image.format,
                        "width": image.width,
                        "height": image.height,
                        "mode": image.mode,
                        "size_bytes": len(data),
                    }
                    image.verify()
                with Image.open(BytesIO(data)) as image:
                    image.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(413, "Image dimensions are too large.")
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise HTTPException(400, "Upload a valid, supported image.")
        return result
    finally:
        file.file.close()
