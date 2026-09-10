# YardAgent

A FastAPI image upload project. Requires Python 3.10+.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 for the upload page or http://127.0.0.1:8000/docs
for interactive API documentation. On macOS/Linux, activate with
`source .venv/bin/activate`.

## API

`POST /analyze` accepts a multipart image field named `file`:

```powershell
curl.exe -F "file=@photo.jpg" http://127.0.0.1:8000/analyze
```

Example JSON:

```json
{
  "filename": "photo.jpg",
  "content_type": "image/jpeg",
  "format": "JPEG",
  "width": 1920,
  "height": 1080,
  "mode": "RGB",
  "size_bytes": 245678
}
```

Analysis returns image metadata, with no external AI service required.
The app does not save uploaded images. Pillow supports common formats such as
JPEG, PNG, GIF, and WebP; animated images are decoded for the first frame only.

Empty or invalid images return HTTP 400, files over 10 MiB or excessive image
dimensions return HTTP 413, and a missing file field returns HTTP 422.

File uploads follow the [FastAPI documentation](https://fastapi.tiangolo.com/tutorial/request-files/).
