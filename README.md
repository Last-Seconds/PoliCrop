# Field Shift

A web app for the NASA Space Apps 2026 challenge *Field Shift: Adapting Farms with NASA Data*.
A farmer picks one field in Whitman County, Washington (the Palouse). The app reads the field's crop
history, weather, soil and slope from public data, and puts the current rotation beside three alternatives,
each judged on four measures (water, soil protection, nitrogen, crop variety) as better, about the same or
worse than now, with the evidence one tap away. See `BUILD_BRIEF_2.md` for the design; the model is
provisional (designed from sourced figures, not yet reviewed by anyone with farming expertise).

## Run

```bash
cd backend
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"   # or python -m venv + pip
.venv/bin/uvicorn fieldshift.api:app --port 8765
# open http://localhost:8765
```

Pre-warm the cache for the example fields (the first time takes a while, mostly satellite images and the
soil database, which answers in about a minute per query):

```bash
.venv/bin/python -m fieldshift.prewarm
```

Tests (offline, canned providers): `.venv/bin/python -m pytest`

Checks against real data:

```bash
.venv/bin/python tools/west_east_check.py      # the brief's west–east water check (section 12)
.venv/bin/python tools/validate.py             # brief 3 part A: writes data/validation.json (reads MODIS; minutes)
.venv/bin/python tools/demo_options.py         # options on each example field
.venv/bin/python tools/screen_check.py --chrome PATH   # brief 3 part S screen targets (Playwright; app on :8777)
.venv/bin/python tools/fields_check.py --chrome PATH   # brief 3 part F (save, reload, download, load, damaged file)
```

Brief 3 results and open questions: `docs/BRIEF3_REPORT.md`.

## Layout

```
data/                      content: edit these, no code change needed
  crops.yaml               crop table (Appendix A of the brief); every value has a basis and source
  roles.yaml               crop roles
  rules.yaml               hard rules H1–H5 and warnings W1–W9, with parameters, basis and source
  settings.yaml            every model constant and threshold, with unit, basis and source
  sources.yaml             the cited sources [S1]..[S26]
  attributions.yaml        data sources and licences (shown in the app)
  region.yaml              the region served and its provider set
  demo_fields.geojson      example fields, including one near LaCrosse in the dry west
backend/fieldshift/
  core/                    pure logic: no network, no web framework (enforced by a test)
    units.py               internal units (mm, °C, kg/ha, ha); US units only at the display edge
    content.py             loads and validates the data files
    weather.py climate.py  daily series, window sums, rain-and-heat summaries
    replay.py              the water budget, replayed over every past crop year (1982 on)
    soil.py terrain.py     soil facts; slope from the elevation map, compared with the soil survey
    station.py drought.py  weather-station check; county drought history
    nearby.py              how common a pattern of crop types is around the field
    strategies/            model, rules (H1–H5), warnings (W1–W9), generate, measures (scorer registry),
                           compare (verdicts, assumed-value rule, dominance, ordering, selection), plan
    present.py             plain-words, US-unit screen content (the display edge)
    service.py             assembles each section; a failing source degrades one section only
  providers/us/            TIGERweb, CDL, Daymet, gNATSGO + Soil Data Access, Sentinel-2, MODIS,
                           NASADEM, ACIS stations, US Drought Monitor
  cache.py                 file cache between providers and core (stale-if-error)
  api.py                   FastAPI routes (thin)
backend/tools/             scripts that produced data files or run checks
frontend/                  one page: choose a field -> the answer first; Leaflet + Chart.js, no build
cache/                     runtime cache (git-ignored)
```

Another region is a new provider set implementing `core/ports.py`, a `class_codes` key in `crops.yaml`,
and an entry in `PROVIDER_SETS` (`app.py`).

## API

| Method | Path | |
|---|---|---|
| GET | `/api/config` | region, roles, crops, rules, warnings, settings (with basis), sources, measures |
| POST | `/api/field` | `{"field": {"type": "polygon", "geometry": GeoJSON}}`; validates; starts warming slow sources |
| GET | `/api/field/{id}/strategies?inputs={...}` | the screen: headline, current rotation and options with verdicts, details |
| GET | `/api/field/{id}/history?corrections={...}` | crop per year, detected rotation |
| GET | `/api/field/{id}/climate` | rain and heat evidence (US units) |
| GET | `/api/field/{id}/station` | grid weather against the nearest long-record station |
| GET | `/api/field/{id}/soil` · `/slope` · `/slope.png` · `/slope_map.json` | soil, slope, slope map |
| GET | `/api/field/{id}/vegetation` (`/years`, `/year/{y}`) | Sentinel-2 greenness, bare periods |
| GET | `/api/region/context` | county drought history |

`inputs` is one JSON object, every key optional: `corrections`, `priorities`, `dry_mode`, `exclude`,
`keep`, `plan_length`, `ph`, `tillage`, `yields`, `rain_pct`, `temp_f` (brief 2 section 7), and from brief 3
`kept`, `records`, `answers`, `fit`, `example_records`.

Brief 3 adds: `GET /api/field/{id}/records_template.xlsx`, `POST /api/field/{id}/records/read` (raw file body,
read and discarded), `POST /api/field/{id}/records/check`, `GET /api/field/{id}/example_records`,
`GET /api/field/{id}/season` (`date=` replays a past date), `GET /api/field/{id}/season_replay`,
`GET /api/field/{id}/enso`, `GET /api/validation`.
