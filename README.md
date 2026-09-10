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

Width and length use feet; area uses square feet. On page 1, enter the photo,
budget, intent/style and optional known-area override before clicking **Design my
yard**. The override constrains available area without replacing the analysis.
`/design` honors `user_intent` and returns no model-generated cost estimate.
Every existing feature has an `existing_feature_decisions` entry with its exact
`feature` description, `action` (`keep` or `remove`), and one-line `reason`.
Missing model decisions default to keep with a warning. Existing assets are never
new purchases. Removal is conceptual; demolition costs are not included.
The design prompt aims for a 3 ft walking route, without requiring an aisle around
every object. Placement uses small buffers: 0.25 ft for trees, 0.15 ft for seating,
bars, grills and tables, 0.05 ft for lights, and 0.1 ft for other additions. Optional
buffers relax to zero when the physical footprints fit.

`/design` returns warnings instead of rejecting site constraints. Every new element
and its quantity remain selected: placement first moves the footprint, then reduces
it toward a type-specific minimum viable size, then uses the nearest yard edge as
a last resort. Edge fallbacks explicitly warn about overlaps or boundary overruns.
Area limits reduce lower-priority footprints; excess area still remaining at minimum
sizes is reported without deleting items. Existing assets accidentally listed as
new purchases are still excluded from purchasing; this is separate from placement.
Footprint reductions are conceptual and do not change verified product dimensions
or prices. Verify that a compact product is suitable before purchasing.
Duplicate IDs are renamed. Missing yard dimensions use an explicit planning
assumption from the available area/dimension (a 20 × 20 ft boundary when none are
available). Existing bounds outside the yard produce warnings rather than rejection.

The viewer checklist starts with all proposed elements checked. Unchecking an item
hides its geometry and removes its costs and collision bounds immediately, without
another sourcing or Blender request. Rechecking restores it. Click **Update preview**
to regenerate all three preview stages for the changed selection. Warnings carry through
`/source` and `/render` inputs. The prompt
always requests a proposal, favoring fewer or cheaper additions for small yards or
tight budgets. Placement retains additions even when minimum footprints cannot fit,
with explicit edge-placement warnings. Malformed API data,
invalid request types, and service failures retain their normal HTTP errors.

On `/`, **Design my yard** runs `/analyze` ? `/design` ? `/source`, with stage
progress and disabled inputs while processing. Failures allow retry. The enriched
layout, original photo and selections are saved in per-tab IndexedDB, then the
browser navigates to `/view`. **Edit inputs** restores all inputs and the photo.
Submitting creates a fresh design. Browser site storage must be enabled.

Page 2 runs three stages in order:

1. **Before / after:** `/render` edits the original upload with selected sourced
   products and explicit keep/remove decisions. Both photos stay above the 3D view.
2. **Reconciliation:** `/reconcile` receives `{analysis, layout, original_photo,
   redesigned_photo}` (both images are data URLs). The Responses API reads both
   actual images at temperature 0 with structured output. It reports each selected
   item's actual type, quantity and individual footprints, and each existing
   feature's kept/removed/changed/uncertain status and observed bounds. The page
   shows corrections, observations, confidence, limitations and corrected JSON.
   Prices and product URLs are joined from the original sourcing records. Missing
   items leave the layout/totals; mismatched or unexpected items become unpriced.
   Totals adjust for depicted quantities and installed-feature areas. No new
   retailer search runs during reconciliation.
3. **3D:** `/model` receives the corrected layout, `existing_feature_bounds`, and
   `depicted_instances` (one footprint plus `element_id` per depicted unit).
   This mode preserves observed footprints and does not invent boundary fences or
   infer new positions for existing structures. Conflicting image-derived bounds
   use the same move/shrink/edge pass, logging any difference from the photo. Image-derived
   positions, sizes and product appearance remain approximate, not a measured scan.

Stages persist after completion. Reconciliation never blocks 3D: transport errors,
refusals, malformed JSON, or invalid observations return `skipped: true` and the
unchanged sourced layout. The browser also handles HTTP/network/invalid-response
failures and proceeds to `/model` without image-derived instances. The page says
reconciliation was skipped; it does not claim the scene was visually verified.
Missing/null observation fields inherit the existing layout, including quantities,
positions and keep/remove decisions. Explicit empty instance lists still mean an
item was absent. Responses use a strict JSON schema before local validation.

Raw model responses, validation errors (including field paths), and field repairs
are logged in `.yard-models/reconciliation/<diagnostic_id>.json`. The response
includes `diagnostic_id`; logs are private, Git-ignored, and contain no uploaded
image data or API keys. If the model call failed before returning, `raw_response`
is null and the error is recorded. Diagnostic write failures do not block 3D.

A failed 3D build retains the already-generated photos and reconciliation. Unchecking items
updates geometry and totals immediately, invalidates the photo/check, and offers
**Update preview** to rerun render ? reconcile ? model. Selection is disabled while
these stages run so results cannot be attached to a different item list.

`/view` starts in orbit mode. Walk mode uses a 5.5 ft eye height on supported
desktop browsers. Click **Walk mode** or the yard to capture the mouse; WASD moves and the mouse looks around.
**Esc**, **Orbit mode**, or **Reset view** returns to orbit. In orbit, drag to rotate,
right-drag to pan and scroll/pinch to zoom. Touch devices, unavailable mouse capture,
invalid movement, or no clear walking space fall back to orbit. Walking uses a
0.23 m body radius, object/yard collision bounds and substeps to prevent tunneling
through thin objects. Patios are walkable; pools block movement. There is no jumping
or swimming. Existing features remain static. The sidebar keeps product links,
alternatives, unpriced items, national feature ranges and the selected budget total.

Three.js 0.180.0 is vendored under `static/vendor/three` with its MIT license; no
external CDN is needed. Controls use
[PointerLockControls](https://threejs.org/docs/pages/PointerLockControls.html) and
[OrbitControls](https://threejs.org/docs/pages/OrbitControls.html).

`POST /model` takes `{ "analysis": <analysis>, "layout": <sourced layout>,
"existing_feature_bounds": [] }`. Optional bounds use the same name, X/Y, width
and length fields as `/design`. It returns `model_url`, `fallback`, and `warnings`.
The server writes a deterministic Blender script and separate scene JSON, runs
Blender headless with a 120-second timeout, and exports binary glTF (`yard.glb`).
Only the generated GLB is served at `/models/<job-id>/yard.glb`; scripts and logs
remain private under ignored `.yard-models/`. These local artifacts persist until
removed by the operator. Blender jobs run one at a time.

Both ordinary and reconciled `/model` calls use `placement.py`. Existing structures
stay fixed (conflicting static bounds warn). Every addition is retained, including
all quantity instances. Compact minimum envelopes are defined in
`placement.MINIMUM_FOOTPRINTS`: for example, chairs 1.8 x 2 ft, bars 4 x 3 ft,
trees 3 x 3 ft, and lights 0.2 x 0.2 ft. Already smaller footprints are not enlarged
by the minimum-size rule. Unavoidable edge overlaps remain visible with warnings;
walk mode can fall back to orbit when no clear walking position exists.

Each adjustment records its action, element ID/instance, old/new position, old/new
size, and reason. Design logs live in `.yard-models/design-placement/*.json`;
Blender logs are in each job's `placement.json` and returned as `placement_changes`.
Warnings are displayed in the viewer. `omitted_element_ids` remains an empty array
for API compatibility. Prices and selection are never removed by placement.
`adjusted_layout` contains the final group footprints. Blender audits each composite
against its envelope, but an explicitly warned edge fallback may overlap another.

Install Blender and put `blender` on PATH, or set `BLENDER_PATH` to its executable.
Windows installations under `Program Files/Blender Foundation` are also detected:

```powershell
$env:BLENDER_PATH = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
```

Ground dimensions use the same minimum width/length estimates as design validation.
Coordinates are near-left group footprints in feet, converted to meters for glTF.
Quantities are distributed within each footprint. `blender_scene.py` builds fence
pickets/posts/rails along all four boundaries, tapered tree trunks with branches,
irregular foliage clusters and individual leaves, hollow tapered planter walls,
soil and emerging plants, paver tiles with grout, recessed pools with refractive
water and coping, and path lights with emissive heads. Bars have overhanging tops,
cabinet doors, foot rails and 2–3 stools; chairs have slatted backs/arms/cushions;
tables have aprons and legs. Grills include carts, wheels, rounded lids, shelves
and controls; decks include boards, steps and railings; sheds have pitched roofs,
doors and windows. Composite envelopes include all these parts.

Retail feeds do not yet provide verified product dimensions: human-scale objects
use explicit typical dimensions (for example, 2.6 × 3 ft chairs and an 8 × 5.5 ft
bar with a 3.5 ft top), instead of stretching to fill arbitrary allocations. Larger
site features retain their planned footprints. These dimensions are not manufacturer
specifications. Reconciled scenes instead use the image-derived individual
footprints, with approximate heights. Old saved previews run the new three-stage flow.

PBR materials include weathered wood grain, textured bark, rough concrete, painted
metal and bare steel, plus water transmission/refraction at IOR 1.333. The ground
has gentle relief, grass texture/bump and broad color variation. Pool openings have
grass patches that become visible when unchecked. Contextual neighboring lawn and
instanced distant trees extend beyond the enclosure. A procedural clouded sky,
distance haze, warm afternoon sun, soft shadows and sky reflection map provide the
environment. Screen-space ambient occlusion adds contact depth; restrained bloom
affects bright emissive lights. Optional postprocessing failures retain the lit 3D
scene. Contextual landscaping is not included in the purchase list.

Repeated parts share Blender meshes and are batched per selectable group into
[InstancedMesh](https://threejs.org/docs/pages/InstancedMesh.html) objects to reduce
draw calls. Geometry limits and the Blender timeout fall back to the photo preview.
These are detailed procedural approximations, not exact manufacturer product meshes;
heights and gentle terrain relief are illustrative. Existing features carry no
purchase price. Explicit bounds preserve their placement; otherwise description-based
positions/sizes are approximate and listed in warnings. Unpriced additions remain
in the sidebar but are omitted from photo editing. Unexpected or mismatched
objects observed by reconciliation are represented in 3D without assigning a price.

If Blender fails, times out, or the browser cannot display 3D, the before/after
and item list remain available. Photo editing requires the original upload and
server `OPENAI_API_KEY`. Empty selections can still render explicit removals or
an unchanged yard. Image editing failures have a retry button. Reconciliation
failures skip the visual check and continue building from the original layout.

`POST /render` accepts JSON with `analysis` (the `/analyze` response), `layout`
(the enriched `/source` response), and required `original_photo` (the original
uploaded image as a base64 image data URL). The browser retains the file used for
the current analysis and sends that exact file for editing. It returns `image_url`, a PNG data URL, and
`prompt`, the exact image-generation prompt. Analysis now includes
`photo_description`: visible scene, viewpoint, background, surfaces, colors, and
lighting. Older analysis JSON without that field falls back to its existing-feature
and slope descriptions. The prompt uses each sourced product's actual name,
quantity, X/Y position, and group footprint, preserving features marked keep.
Selected estimated installed features use their layout descriptions. Unpriced
retail items are excluded from rendering. The editing prompt requires exact
product type and quantity with no extra additions: four stake lights cannot be
replaced by string lights. Image models can still make mistakes; inspect the result.

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
the deck, fence, shed, garden beds and other structures in their original positions
unless explicitly marked remove. It adds only selected layout elements.
Retained structures take precedence over conflicting
additions. This is a generative edit, not a guarantee of pixel-exact preservation;
review the result for unintended changes. The original stays in browser memory
for comparison; generated images are returned directly and not saved on the server.
Both persist in the tab's IndexedDB design across reloads.

Existing features are site constraints with explicit keep/remove decisions, not purchases. The design prompt
excludes them from new elements and costs, and validation removes named duplicates
such as an existing shed with warnings. Descriptive locations still require measured bounds to
verify clearances; free-text feature matching is conservative, not a complete
semantic inventory.

The **Design my yard** pipeline sources proposed items automatically. `POST /source` accepts
`{"layout": <design with only checked elements>, "budget": <USD number>}`
(up to 50 elements, with unique IDs). Retailer
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
`project_total_range_usd` adds the sourced materials total to each end of the
estimated-feature range. `budget_note` reports whether that range is over budget,
may exceed it, or fits. Unpriced selected items make the comparison partial.
There is no model-generated design price. The comparison excludes retail tax,
delivery and installation; installed-feature costs remain estimates.

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
| Deck | $20–$45/sq ft | Entire installed footprint |
| Installed fire pit | $200–$3,000 | Per feature |
| Other installed hardscape | $1,000–$20,000 | Provisional allowance; not a researched average; contractor quote required |

Pools, patios, bars, decks and other large construction features (including
pergolas, gazebos and retaining walls) go to this table, never retailer search.
The provisional catch-all is deliberately labeled in the output and has no source
claim. Standalone materials such as patio pavers and boards may still be sourced.
Deck rates use the outdoor living guide below; fire-pit rates use
[Angi's fire-pit installation guide](https://www.angi.com/articles/how-much-does-it-cost-install-fire-pit.htm).

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
