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

Before starting the server, set your API key in the same shell:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
# Optional: choose another model supporting vision and structured outputs.
$env:OPENAI_MODEL = "gpt-4o"
```

On macOS/Linux, use `export OPENAI_API_KEY="your-api-key"`.
Keep the key on the server; never put it in browser code or commit it.

The JSON response has this structure (numbers depend on the uploaded photo):

```json
{
  "width_ft": { "min": 20, "max": 30 },
  "length_ft": { "min": 30, "max": 45 },
  "area_sq_ft": { "min": 600, "max": 1350 },
  "reference_object": {
    "object": "Fence panel",
    "assumed_dimension": "width",
    "size_ft": { "min": 6, "max": 8 },
    "reasoning": "The visible panels provide an approximate scale."
  },
  "slope": "Appears mostly level in the visible portion.",
  "existing_features": ["Wood fence", "Grass"],
  "limitations": "Panel sizes and the obscured far boundary are uncertain."
}
```

Every valid, configured analysis calls the real OpenAI Responses API with the
uploaded image and a Pydantic structured output schema. There are no canned
results or fallback estimates. Measurements and the reference object can be
`null` when the photo does not provide enough evidence. Width and length use
feet; area uses square feet. The page displays the ranges, reference assumptions,
slope, features, and limitations. Its editable area input starts at the area
range midpoint, or stays empty when area cannot be estimated. Edits remain in
the page and do not change the original JSON response or persist after reload.

The app does not save uploaded images locally. It normalizes the first frame to
an orientation-corrected JPEG up to 2048 pixels per side and sends it to OpenAI
with response storage disabled. Pillow supports common formats such as JPEG,
PNG, GIF, and WebP. API usage incurs charges on the configured OpenAI account.

Empty or invalid images return HTTP 400, files over 10 MiB or excessive image
dimensions return HTTP 413, and a missing file field returns HTTP 422.
Missing API configuration or rate/quota limits return HTTP 503; upstream errors,
refusals, or invalid results return HTTP 502; API timeouts return HTTP 504.

Run local validation checks with `python -m unittest discover -s tests`.
These checks do not call OpenAI; verify live estimates by uploading a yard photo
with a configured API key.

File uploads follow the [FastAPI documentation](https://fastapi.tiangolo.com/tutorial/request-files/).
The integration follows OpenAI's [image input](https://developers.openai.com/api/docs/guides/images-vision)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs) guides.
