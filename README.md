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
  "width_ft": { "min": 30, "max": 40 },
  "length_ft": { "min": 45, "max": 60 },
  "area_sq_ft": { "min": 1350, "max": 2400 },
  "reference_object": {
    "object": "Fence panel",
    "assumed_dimension": "width",
    "size_ft": { "min": 6, "max": 8 },
    "reasoning": "No usable standard door is visible; a fence panel provides an approximate scale."
  },
  "confidence": "low",
  "visible_boundaries": ["left", "right", "far"],
  "boundary_assumptions": ["Near boundary taken as the photographer's position."],
  "slope": "Appears mostly level in the visible portion.",
  "existing_features": ["Wood fence", "Grass"],
  "limitations": "Panel sizes and the obscured far boundary are uncertain."
}
```

Every valid, configured analysis calls the real OpenAI Responses API with the
uploaded image and a structured output schema at `temperature=0`. The model
estimates width, length and area ranges directly by comparing the yard holistically
with familiar reference objects. There are no pixel-count calculations, pixel
ratios or depth multipliers. Area is estimated directly to allow for irregular yards.
Reference preference is standard door, fence panel, then shed, with fence pickets
(typically 5.5 inches wide), raised beds, deck boards, furniture, grills and other
familiar objects also allowed. Reference size assumptions and visual reasoning
are included in the response.

Every successful analysis returns numeric width, length and area ranges. The
photographer's position supplies the near boundary. Missing left, right or far
boundaries are named in `boundary_assumptions` and force low confidence.
`visible_boundaries` lists observed edges; `confidence` remains visible on the page.
If no reference is identifiable, the model gives broad hypothetical planning ranges
and a null reference, with low confidence and an explicit scale assumption.
The server preserves the returned dimension and area ranges without arithmetic.
Upload and API failures retain their normal HTTP errors.

Width and length use feet; area uses square feet. The page shows reference
assumptions, confidence, boundary assumptions, slope, features and limitations.
The editable area input starts at the range midpoint; edits do not modify the
original analysis JSON and disappear on reload.
After analysis, enter a budget in USD and select **Generate design**. The page
posts the original analysis, budget, and any area value to `/design`, then shows
the layout elements in a table with quantities, positions, and dimensions,
alongside the estimated cost, design notes, and warnings.

`/design` returns a `warnings` array instead of rejecting a structurally valid
proposal for budget or site constraints. Budget warnings include the dollar
overrun. Elements are ordered from highest to lowest priority by the model;
when footprint area is over the available area, the server drops additions from
the end of that order until they fit. It reports the excess area and every drop.
Misplaced footprints are moved inside the boundary when possible; oversized
footprints are dropped rather than shrinking physical retail products. Existing
features listed as purchases or overlapped by additions are removed with warnings.
Duplicate IDs are renamed. Missing yard dimensions use an explicit planning
assumption from the available area/dimension (a 20 × 20 ft boundary when none are
available). Existing bounds outside the yard produce warnings rather than rejection.

After elements are dropped, the original estimated cost is retained with a warning
because no per-element cost breakdown exists; sourcing recalculates the remaining
materials total. Warnings carry through `/source` and `/render` inputs. The prompt
always requests a proposal, favoring fewer or cheaper additions for small yards or
tight budgets. If all proposed additions must be removed, the response still
returns a layout with an empty list and explanatory warnings. Malformed API data,
invalid request types, and service failures retain their normal HTTP errors.

After sourcing, select **Render redesigned yard**. The page displays the generated
image beside the original analyzed photo (stacked on small screens). A new analysis,
design, or sourcing attempt clears the previous rendering. Rendering requires at
least one layout element and uses the server's `OPENAI_API_KEY`.

`POST /render` accepts JSON with `analysis` (the `/analyze` response), `layout`
(the enriched `/source` response), and required `original_photo` (the original
uploaded image as a base64 image data URL). The browser retains the file used for
the current analysis and sends that exact file for editing. It returns `image_url`, a PNG data URL, and
`prompt`, the exact image-generation prompt. Analysis now includes
`photo_description`: visible scene, viewpoint, background, surfaces, colors, and
lighting. Older analysis JSON without that field falls back to its existing-feature
and slope descriptions. The prompt uses each sourced product's actual name,
quantity, X/Y position, and group footprint, preserving existing site features.
Estimated features and unavailable products use their generic layout descriptions.

The server calls `client.images.edit` in the
[OpenAI Images API](https://developers.openai.com/api/docs/guides/image-generation)
with the original photo as an image input and `OPENAI_IMAGE_MODEL` (default
`gpt-image-2`), one PNG at medium quality with automatic output size,
a 180-second timeout, and no automatic retries. Image generation incurs API charges
and requires access to the configured image model. Missing configuration or quota
limits return 503, upstream failures or invalid image data return 502, and timeouts
return 504. Invalid layouts return 422 before generation.

Rendering edits the **original uploaded photo**; the description supplements it.
The server validates the upload (10 MiB maximum), corrects EXIF orientation, and
normalizes it to JPEG up to 2048 pixels per side in memory before sending it to
the editing API. Missing photos return 422, invalid images return 400, and oversized
decoded images return 413. The prompt preserves the original camera view and keeps
the deck, fence, shed, garden beds and other structures in their original positions,
adding only new layout elements. Existing structures take precedence over conflicting
additions. This is a generative edit, not a guarantee of pixel-exact preservation;
review the result for unintended changes. The original stays in browser memory
for comparison; generated images are returned directly and not saved on the server.
Both disappear on page reload.

Existing features are retained site constraints, not purchases. The design prompt
excludes them from new elements and costs, and validation removes named duplicates
such as an existing shed with warnings. Descriptive locations still require measured bounds to
verify clearances; free-text feature matching is conservative, not a complete
semantic inventory.

Select **Source products** after generating a design. `POST /source` accepts the
original `/design` JSON directly (up to 50 elements, with unique IDs). Retailer
searches use the browser; product-match confirmation requires `OPENAI_API_KEY`
and uses `OPENAI_MODEL`. It returns these additional fields on each element:

- `sourced_product`: the lowest-priced successful match's `name`, `price` in USD
  per retail unit, `retailer`, and `url`, or `null` when not sourced.
- `alternative_products`: all other valid matches from the rendered search
  results, sorted by price, each with the same product fields. The page shows
the selected retailer and expandable alternatives with their retailers/prices.

Before price selection, obvious sprays, chemicals, treatments, seeds, accessories
and replacement parts are rejected for plant/tree and furniture elements. The
remaining candidates are reviewed by the model in batches of 20 using their
scraped names, retailer and URL against the requested type and category. The model
must confirm the actual plant/tree or complete furniture piece, not a related
accessory. Uncertain matches are rejected. The cheapest confirmed match becomes
`sourced_product`; only other confirmed matches become alternatives. Verification
is cached per element type/category within the request. Missing credentials,
failed reviews or malformed candidate IDs leave those candidates unverified and
excluded, never silently accepted. Model reviews incur API usage and can add up
to 60 seconds per batch on timeout. This is title-based model confirmation, not
inspection of the physical product; check details before purchasing.
- `estimated_feature`: an explicitly `estimated` cost range, region, pricing
  basis, reference URL, and review date for installed pools, patios, and bars.
- `sourcing_status`, `sourcing_note`, and `sourced_total_usd`: sourcing outcome,
  failure explanation if applicable, and product price multiplied by quantity.

The response and page show `sourced_materials_total_usd` and
`estimated_features_range_usd` separately. `sourcing_complete: false` means the
materials subtotal excludes unpriced items; missing prices are not free products.
The original `estimated_cost_usd` remains the design's planning estimate. Sourcing
does not force actual prices under that estimate or the original budget.

Playwright navigates Home Depot, Lowe's, Wayfair, and Amazon in real Chromium
browser pages, with one independent worker per retailer running in parallel.
Each worker reads hydrated, rendered product cards; sourcing uses neither `httpx`
nor `requests`, response JSON, or private retailer APIs. It keeps relevant matches
with positive prices and retailer product links, skipping unavailable items,
obvious accessories, and duplicate links. Results cover the loaded search page,
not all pages of a retailer's catalog. Identical element types reuse results within
the request. The lowest listed retail-unit price is selected; totals and rendering
use that selected product. Alternatives may differ in size, material, or pack count.

Browser sessions use a normal desktop user agent matching the installed Chromium
version and platform. Persistent profiles under `.sourcing-browser/` retain cookies
and local storage across requests. Separate profiles and per-retailer locks prevent
concurrent requests within one server process from colliding. Run one Uvicorn worker
per checkout; multiple server processes must not share these profile directories.
The implementation uses Playwright's
[persistent browser contexts](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).

A 403, timeout, browser error, or unreadable result is silently skipped for that
retailer. Other matches still appear normally. Only when every retailer fails to
produce a match does the item show as unpriced and the materials total as partial.
For diagnosis, `sourcing-diagnostics/` contains timestamped JSON metadata (retailer,
query, URL, HTTP status, reason) and the failed page's HTML when a page is available.
Browser startup failures have metadata only. Diagnostic write failures are logged
to the server console without discarding successful results. Profiles and diagnostic
files are ignored by Git and are not exposed by the web app. They remain locally
until removed and may contain retailer session/page data.

Retailer markup, location requirements, and access blocks can still prevent sourcing.
Each distinct query can take about 37 seconds per retailer on timeout, plus browser
startup; retailers run concurrently. Prices reflect each site's default/persisted
location, not a national retail average. Check sizes, pack counts and material
coverage before buying; totals assume one retail unit per layout item and exclude
tax, delivery and installation of retail items.

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
they do not call OpenAI or retailers. Verify live yard estimates by uploading a
yard photo with a configured API key. Run the optional live retailer probe with
`python tests/probe_retailers.py "Adirondack chair"`.

File uploads follow the [FastAPI documentation](https://fastapi.tiangolo.com/tutorial/request-files/).
The integration follows OpenAI's [image input](https://developers.openai.com/api/docs/guides/images-vision)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs) guides.
