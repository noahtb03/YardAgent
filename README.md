# YardAgent

A FastAPI image upload project. Requires Python 3.10+.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
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
# Optional: a GPT Image model supporting PNG output.
$env:OPENAI_IMAGE_MODEL = "gpt-image-2"
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

After analysis, enter a budget in USD and select **Generate design**. The page
posts the original analysis, budget, and any area value to `/design`, then shows
the layout elements in a table with quantities, positions, and dimensions,
alongside the estimated cost and design notes. Width and length estimates are
required to generate a design.

After sourcing, select **Render redesigned yard**. The page displays the generated
image beside the original analyzed photo (stacked on small screens). A new analysis,
design, or sourcing attempt clears the previous rendering. Rendering requires at
least one layout element and uses the server's `OPENAI_API_KEY`.

`POST /render` accepts JSON with `analysis` (the `/analyze` response) and `layout`
(the enriched `/source` response). It returns `image_url`, a PNG data URL, and
`prompt`, the exact image-generation prompt. Analysis now includes
`photo_description`: visible scene, viewpoint, background, surfaces, colors, and
lighting. Older analysis JSON without that field falls back to its existing-feature
and slope descriptions. The prompt uses each sourced product's actual name,
quantity, X/Y position, and group footprint, preserving existing site features.
Estimated features and unavailable products use their generic layout descriptions.

The server calls the [OpenAI Images API](https://developers.openai.com/api/docs/guides/image-generation)
with `OPENAI_IMAGE_MODEL` (default `gpt-image-2`), one 1536×1024 PNG at medium quality,
a 180-second timeout, and no automatic retries. Image generation incurs API charges
and requires access to the configured image model. Missing configuration or quota
limits return 503, upstream failures or invalid image data return 502, and timeouts
return 504. Invalid layouts return 422 before generation.

Rendering uses the photo's **text description**, not a direct image edit. It is a
photorealistic concept, with approximate product appearance and positioning. The
original photo stays in browser memory for comparison; generated images are
returned directly and are not saved on the server. Both disappear on page reload.

Existing features are retained site constraints, not purchases. The design prompt
excludes them from new elements and costs, and validation rejects named duplicates
such as an existing shed. Descriptive locations still require measured bounds to
verify clearances; free-text feature matching is conservative, not a complete
semantic inventory.

Select **Source products** after generating a design. `POST /source` accepts the
original `/design` JSON directly (up to 50 elements, with unique IDs), without an
API key. It returns the layout with these additional fields on each element:

- `sourced_product`: Home Depot `name`, `price` in USD per retail unit, and `url`,
  or `null` when not sourced.
- `estimated_feature`: an explicitly `estimated` cost range, region, pricing
  basis, reference URL, and review date for installed pools, patios, and bars.
- `sourcing_status`, `sourcing_note`, and `sourced_total_usd`: sourcing outcome,
  failure explanation if applicable, and product price multiplied by quantity.

The response and page show `sourced_materials_total_usd` and
`estimated_features_range_usd` separately. `sourcing_complete: false` means the
materials subtotal excludes unpriced items; missing prices are not free products.
The original `estimated_cost_usd` remains the design's planning estimate. Sourcing
does not force actual prices under that estimate or the original budget.

Playwright opens public Home Depot search pages in headless Chromium and selects
the first relevant result with a readable product name, positive price, and Home
Depot product link. It checks structured product offers and rendered product
cards, skips unavailable offers and obvious accessories, and reuses searches for
identical types within a request. Retailer markup, location requirements, and
access blocks can prevent sourcing; the app reports unavailable results without
inventing products or prices. Requests may take roughly 35 seconds per distinct
product when searches time out. Prices reflect the site's default location, not
a national retail price average. Check product sizes, pack quantities, and material
coverage before buying; totals assume one retail unit per layout item and exclude
tax, delivery, and installation of retail items.

Feature allowances are hardcoded in `sourcing.FEATURE_COSTS`, using the
`US-national` table for now. Regional questions and verified regional tables are
deferred. The defaults, reviewed September 10, 2026, are:

| Installed feature | National planning range | Basis |
| --- | --- | --- |
| Pool | $45,000–$88,000 | Per in-ground pool |
| Patio | $8–$25/sq ft | Brick-paver patio, entire group footprint |
| Outdoor bar | $5,000–$20,000 | Per installed bar |

Pool and bar allowances reference [Angi's outdoor living cost guide](https://www.angi.com/articles/cost-outdoor-living-space.htm).
Patio allowances reference [Angi's patio installation guide](https://www.angi.com/articles/how-much-does-it-cost-install-patio.htm).
These are broad planning ranges, not quotes. Patio area already covers the entire
group, so quantity does not multiply it again. Standalone patio pavers, pool
pumps, and bar stools are retail items; installed features are not also sourced
as material purchases. Chromium installation follows the
[Playwright browser documentation](https://playwright.dev/python/docs/browsers).

The app does not save uploaded images locally. It normalizes the first frame to
an orientation-corrected JPEG up to 2048 pixels per side and sends it to OpenAI
with response storage disabled. Pillow supports common formats such as JPEG,
PNG, GIF, and WebP. API usage incurs charges on the configured OpenAI account.

Empty or invalid images return HTTP 400, files over 10 MiB or excessive image
dimensions return HTTP 413, and a missing file field returns HTTP 422.
Missing API configuration or rate/quota limits return HTTP 503; upstream errors,
refusals, or invalid results return HTTP 502; API timeouts return HTTP 504.

Run local validation checks with `python -m unittest discover -s tests`.
These checks include Chromium tests against controlled HTML and response fixtures;
they do not call OpenAI or Home Depot. Verify live yard estimates by uploading a
yard photo with a configured API key. Run the optional live retailer probe with
`python tests/probe_home_depot.py`.

File uploads follow the [FastAPI documentation](https://fastapi.tiangolo.com/tutorial/request-files/).
The integration follows OpenAI's [image input](https://developers.openai.com/api/docs/guides/images-vision)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs) guides.
