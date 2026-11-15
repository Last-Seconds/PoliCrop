# Build brief: Field Shift, preliminary app (v0)

This brief is for the coding agent building the first version of the app. It says what to build now, what is deliberately left open, and how to leave room for it. Where it gives a default "until decided", build the default and keep it easy to change.

## 1. What this is

A web app for the NASA Space Apps 2026 challenge "Field Shift: Adapting Farms with NASA Data".
Challenge page: https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/

The finished tool helps a farmer explore crop-rotation strategies for one field. A crop rotation is the sequence of crops grown on the same field over several years. The farmer picks a field; the app reads the field's conditions and crop history from public data, proposes alternative rotations, and compares them with the existing one, showing the evidence and the gaps behind each. It supports the farmer's judgment and must never present itself as replacing it.

This brief covers v0: a running app with the complete path from "pick a field" to "see compared rotations", with the agronomy content still provisional.

## 2. Decisions already made (do not reopen)

- **Area:** Whitman County, Washington, USA (FIPS 53075). Rain-fed wheat country, known as the Palouse. Typical crops: winter wheat, spring wheat, barley, peas, lentils, chickpeas, canola, and fallow. Steep rolling hills.
- **US first, other regions later.** Core logic must not call any data source directly. It asks a provider interface for things like "crop history for this field" or "daily weather for this point", and a US implementation answers. Another country later is a new provider, not a rewrite.
- **A strategy is a sequence of crop roles** (for example cereal, nitrogen-fixing legume, oilseed, fallow, cover crop), each role having alternative crops that can fill it. Steps are seasonal, with start and end dates, not one-per-year, so that a period with nothing growing is representable. Plan length is a parameter that defaults to the length of the field's existing rotation.
- **Candidates come from generate-and-filter:** generate role sequences, fill roles with crops, discard those that break hard rules. The crop pool is the crops actually grown in the surrounding area (from the crop-type map) plus cover crops. Each candidate carries a "distance from the existing rotation" value.
- **Warnings are specific:** a data caveat is attached to the claim it affects (for example "this value is a 50 km regional average, not your field"), never a blanket disclaimer.

## 3. Not decided yet: build the mechanism, not the content

These are open on purpose. For each, build the plumbing and ship clearly-labelled provisional content in data files, so the team can replace content without touching code.

| Open item | What to build now |
|---|---|
| Crop table (crops, roles, attributes) | A data file (JSON or YAML) with a schema: name, CDL code, role, season window, water need, temperature limits, nitrogen effect, ground cover. Fill in only name, CDL code and role for the crops listed in section 2. Leave every other attribute null. **Do not invent agronomic numbers.** |
| Filter rules | A rule interface (input: candidate; output: pass/fail plus a human-readable reason) and a registry. Ship two provisional rules only: no identical crop in consecutive steps, and no overlapping step dates. |
| Scoring and ranking | A scorer interface that returns named criteria per strategy. Ship no scoring. The comparison view shows strategies unranked. |
| How the future enters (trends, scenarios, projections) | Nothing. All charts show historical data and say so. |
| How a field is defined | Default: the user draws a polygon on the map. Keep "field geometry" abstract so a click-a-point or pick-a-parcel option can be added. |
| What the farmer is asked | Only the field. Allow the farmer to correct the detected crop history. |
| Live fetch or precomputed data | A cache layer between providers and the core, so both work. Pre-warm the cache for a few demo fields in Whitman County. |
| Thresholds (what counts as "bare") | Named parameters in one config file, each marked provisional. |

Anything provisional must be visibly marked as such in the UI (a small "provisional" tag is enough).

## 4. Scope of v0

### Build

1. **Field selection.** A map centred on Whitman County with satellite imagery. The user draws a field outline. Reject fields outside the county with a clear message.
2. **Existing rotation.** For each available year, the dominant crop class inside the field outline, from the Cropland Data Layer. Keep the share of the field that class covers, as a confidence signal.
3. **Climate indicators** for the field's centre point, from NASA POWER: rainfall, daily maximum and minimum temperature.
4. **Vegetation and bare periods.** A vegetation index (NDVI) time series for the field from Sentinel-2, and from it the periods when nothing was growing.
5. **Candidate generation.** The generate-and-filter engine from section 2, running on the provisional crop table and rules.
6. **Comparison view.** At least three strategies side by side: the existing rotation plus generated ones at different distances from it.

### Do not build

Erosion maps, heat zones, "dry region mode", what-if input of a custom rotation, nearby-rotation similarity, time-lapse, file upload, soil-colour visuals, user accounts, any trained machine-learning model. Several of these are planned for later, so do not design them out, but do not start them.

## 5. Data sources

Facts marked (checked) were verified against the live service on 2026-11-14. Verify anything else before relying on it.

### Crop history: USDA Cropland Data Layer (CDL)

A yearly 30 m raster of the US where each pixel is a crop-type code.

- **Microsoft Planetary Computer**, STAC collection `usda-cdl`, asset `cropland`. Covers **2008 to 2021 only** (checked). STAC API: `https://planetarycomputer.microsoft.com/api/stac/v1`. Files are cloud-optimised GeoTIFFs; URLs need signing with the `planetary-computer` Python package.
- **USDA CropScape web service** for later years. A point query works for 2024 (checked):
  `https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue?year=2024&x=<x>&y=<y>`
  Coordinates are in USA Contiguous Albers (EPSG:5070), not latitude/longitude. The response gives the code, the category name and an official display colour. Probe for the newest available year. The service also offers area statistics and file extraction; check its documentation.
- The CDL labels a pixel by the crop harvested that year. Winter wheat is sown in autumn and harvested the next summer, so its label year is the harvest year.
- Expected codes for the local crops (from memory, **verify against the official CDL legend**): 21 barley, 23 spring wheat, 24 winter wheat, 31 canola, 36 alfalfa, 51 chickpeas, 52 lentils, 53 peas, 61 fallow/idle cropland.

### Weather: NASA POWER

Daily weather for any point, free, no account. Grid cells are roughly 50 km, so values are regional.

- Endpoint (checked):
  `https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M_MAX,T2M_MIN&community=AG&longitude=<lon>&latitude=<lat>&start=YYYYMMDD&end=YYYYMMDD&format=JSON`
- `PRECTOTCORR` is precipitation in mm/day; `T2M_MAX` and `T2M_MIN` are air temperature at 2 m in °C. Missing values are `-999`.
- Fetch the longest record available (it starts in the early 1980s) once per location and cache it.

### Vegetation index: Sentinel-2

10 m imagery, a new image every few days.

- Planetary Computer collection `sentinel-2-l2a` (checked: scenes exist over Whitman County; tile `11TMN` covers the test point 46.88, -117.36).
- NDVI = (B08 − B04) / (B08 + B04), where B08 is near-infrared and B04 is red. Use the `SCL` asset to mask clouds, cloud shadow and snow before averaging over the field.
- Read only the field's window from each file; do not download scenes. Years of imagery per field is slow, so cache the resulting series.
- The Palouse has snow cover and persistent cloud in winter. Expect gaps and show them as gaps; do not interpolate silently.

### County boundary

US Census TIGER/Line county boundaries, FIPS 53075. Fetch the real geometry; do not hard-code approximate coordinates.

### Licences

Each source has its own terms. Record the source and attribution for every dataset in one place, and show attributions in the app.

## 6. Screens and visualisations

One page with two states is enough: before a field is chosen (the map), and after (the field report).

### Map

- Satellite basemap, county outline, drawing tool for the field.
- Optional overlay: the most recent crop-type layer, with a legend.

### Field report

Each chart needs a one-sentence plain-language caption saying what it shows and what its limits are. The audience is a farmer, not a remote-sensing specialist.

| Section | What to show | Notes |
|---|---|---|
| Crop history | A horizontal strip, one block per year, coloured and labelled by crop | Use the official CDL colours. Show the share of the field each label covers; flag years below a provisional share threshold as uncertain. Editable by the farmer. |
| Rainfall through the year | Average rainfall per month, with the range across years | Shows when the wet and dry seasons fall. |
| Rainfall over the years | Total per year (or per growing season), one bar per year | No trend line and no forecast in v0. |
| Temperature | Monthly average highs and lows; number of frost days per year | Frost day = minimum below 0 °C. |
| Vegetation | NDVI over time for the field, with bare periods shaded | Gaps left as gaps. The "bare" threshold is provisional. |
| Strategies | Three or more cards or columns: the existing rotation and generated alternatives | See below. |

For every value from NASA POWER, state that it is a regional value. For crop history, state that it is a classification with errors, which is why it is editable.

### Strategy comparison

For each strategy show:

- the sequence as a timeline of steps, coloured by role, with the crop named;
- how it differs from the existing rotation, in words ("adds a legume in year 2"), plus the distance value;
- which rules it passed;
- a "not yet assessed" list naming the criteria that have no data yet (water use, nitrogen, erosion, income), so the gaps are explicit;
- a "check locally" note.

No ranking, no "best" label, no scores.

## 7. Architecture constraints

- **Core logic is independent of data sources and of the web framework.** It should be testable with canned inputs and no network.
- **Providers** implement a small interface per kind of data (crop history, weather, vegetation series, boundaries).
- **Content lives in data files:** crop table, roles, rules configuration, thresholds, attributions.
- **Cache every external call.** A demo must work when a remote service is slow.
- **Stack:** the repository is empty and the team has not chosen. A sensible default is a Python backend (the geospatial libraries are there: `rasterio`, `pystac-client`, `planetary-computer`, `shapely`, `pyproj`) with a JavaScript map front end (MapLibre or Leaflet). Use something else if the team says so.
- **External data is untrusted input.** Validate shapes and ranges; handle missing values and failed requests without crashing the page.

## 8. Done means

- A user can draw a field in Whitman County and get the full report without errors.
- The crop history for a known wheat field shows a plausible sequence of the local crops, and the years after 2021 are present.
- The rainfall-by-month chart shows wet winters and dry summers, which is the known pattern there; if it does not, something is wrong.
- The vegetation chart shows a yearly green-up and harvest cycle, with bare periods shaded.
- At least three strategies appear, including the existing one, each with the fields listed in section 6.
- Every provisional item is marked in the UI, and every chart has its caption and caveat.
- Changing the crop table or a threshold needs no code change.
- The core logic has tests that run offline.

## 9. Report back

When finished, say what works end to end, what was stubbed, any place a data source behaved differently from this brief, and anything you had to assume.
