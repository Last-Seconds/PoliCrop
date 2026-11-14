# Field Shift · Palouse (NASA Space Apps 2026)

Crop-rotation decision-support prototype for the Palouse region (Washington / Idaho, USA).
Status: **front-end preview with placeholder (demo) numbers.** The map layers and crop scores
are NOT yet computed from NASA data. Everything marked "DEMO" in the UI is a stand-in.

## Run locally
```
python3 -m http.server 8000
# open http://localhost:8000
```
(Opening index.html directly also works, but a local server is safer.)
Needs internet for map tiles and the Leaflet / SheetJS CDN scripts.

## Publish on GitHub Pages
Repo → Settings → Pages → Deploy from branch → `main` / root. The site URL goes into the
"Link to Final Project" field of the Space Apps submission.

## Files
- `index.html`, `css/style.css`: layout and look.
- `js/app.js`: map, controls, strategy cards, what-if, field report, CSV/Excel upload.
- `js/i18n.js`: Turkish and English UI text. Add every new string to both.
- `js/engine.js`: **placeholder** scoring engine. Crop values (0-100) are illustrative.
  Replace them with values derived from real data; keep the function names.
- `data/mock/example_result.json`: the shape the real calculation should produce.

## What is real vs placeholder
| Part | Status |
| --- | --- |
| Map, field picking, sliders, constraints, drought mode, what-if, CSV/Excel upload | working UI |
| Strategy scores, risk indicator, uncertainty band | placeholder rules in `engine.js` |
| Erosion / NDVI / moisture / soil-color layers | synthetic pattern, not satellite data |
| NASA POWER, SRTM, SMAP, MODIS, SSURGO, CDL | planned, not connected |

## Crop table upload
CSV or Excel with columns: `crop, water, income, soil, erosion, risk, food, legume`
(values 0-100, `legume` = 1/0). Use the "Download sample template" link in the app.

This tool supports the farmer's judgment; it does not replace the farmer or local agricultural expertise.
