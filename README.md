# Field Shift: v0

A web app for the NASA Space Apps 2026 challenge *Field Shift: Adapting Farms with NASA Data*.
A farmer draws one field in Whitman County, Washington (the Palouse). The app reads the field's crop
history, weather and vegetation from public data, and puts generated crop-rotation alternatives next to
the existing rotation, without ranking them. Agronomy content is provisional (see `BUILD_BRIEF.md`).

## Run

```bash
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"   # or python -m venv + pip
.venv/bin/uvicorn fieldshift.api:app --port 8765
# open http://localhost:8765
```

Pre-warm the cache for the demo fields (about 10 minutes the first time, mostly Sentinel-2):

```bash
.venv/bin/python -m fieldshift.prewarm
```

Tests (offline, canned providers):

```bash
.venv/bin/python -m pytest
```

## Layout

```
data/                      content: edit these, no code change needed
  crops.yaml               crop table (name, CDL code, role; agronomic attributes null on purpose)
  roles.yaml               crop roles and colours
  rules.yaml               which filter rules are enabled, with parameters
  settings.yaml            every threshold/parameter, each marked provisional or not
  attributions.yaml        data sources, licences, attribution text (shown in the app)
  region.yaml              the region served and its provider set
  demo_fields.geojson      demo fields (outlines traced from the CDL, see backend/tools)
  us/cdl_legend.json       official CDL class names/colours (generated from CropScape)
backend/fieldshift/
  core/                    pure logic: no network, no web framework (enforced by a test)
    ports.py               provider interfaces (region, crop history, weather, vegetation)
    geometry.py            FieldGeometry (polygon now; point/parcel later = new subclass)
    history.py climate.py vegetation.py
    strategies/            model, rule registry, scorer interface (empty), generate-and-filter
    service.py             assembles report sections, attaches caveats to the claims they affect
  providers/us/            US implementation: TIGERweb, CDL (Planetary Computer + CropScape),
                           NASA POWER, Sentinel-2 L2A (Planetary Computer)
  cache.py                 file cache between providers and core (stale-if-error)
  api.py                   FastAPI routes (thin)
  prewarm.py               cache pre-warming CLI
backend/tools/             scripts that produced data files (CDL legend, demo fields)
frontend/                  one page, two states (map -> field report); Leaflet + Chart.js, no build
cache/                     runtime cache (git-ignored)
```

Adding another country means writing a new provider set implementing `core/ports.py`, a legend
file, a `class_codes` key in `crops.yaml`, and an entry in `PROVIDER_SETS` (`app.py`). The core stays the same.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/config` | region outline, roles, crops, rules, settings, attributions |
| POST | `/api/field` | `{"field": {"type": "polygon", "geometry": GeoJSON}}`; validates (inside county, size) |
| GET | `/api/field/{id}/history?corrections={"2024":"peas"}` | crop per year, share, uncertainty, detected rotation |
| GET | `/api/field/{id}/climate` | monthly rainfall and range, crop-year totals, temperature, frost days |
| GET | `/api/field/{id}/vegetation/year/{y}` | warms one year of NDVI (used for progress) |
| GET | `/api/field/{id}/vegetation` | NDVI series, gaps, bare periods |
| GET | `/api/field/{id}/strategies?plan_length=3&alternatives=3&corrections=…` | existing + alternatives |
| GET | `/api/overlay/{year}.png` / `.json` | county crop-type map overlay and legend |
