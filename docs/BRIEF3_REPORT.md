# Brief 3 report (with addenda 1 and 2)

Written 2026-11-15. Tests: 220 offline tests pass (`backend/.venv/bin/python -m pytest`), up from 160. Browser checks:
`tools/screen_check.py` (part S screen targets) and `tools/fields_check.py` (part F), both against the running app.

## What is complete

| Part | State |
|---|---|
| S1 options | Done. H3 is "legumes at least 3 years apart, cyclic"; W2 removed; every crop's need self-calibrated; "may be too dry here" (W10) and "not seen nearby" (W11) added; options seen nearby ordered first among equal verdicts. |
| S2 screen | Done. All targets measured in Chromium at 360 × 780 (table below). |
| F my fields | Done. Saved fields above the map, rename / remove with confirmation, auto-save with "✓ saved", last field remembered, download / load with validation and a version number, kept options with notes (scored even after settings change). |
| A validation | Done. `tools/validate.py` writes `data/validation.json`; summary on About → How this works. No county yields file was available. |
| B records | Done: typed table prefilled from the crop history, blank `.xlsx` sheet, `.xlsx`/`.csv` upload with preview, units and totals, sanity checks, expected-against-actual chart, the odd-year question, "download my records". **Not built:** the optional "without records" greenness question. |
| C fitting | Done: blend by `n_eff/(n_eff+k)`, e_winter and storage-factor fit, shrinkage by spread, leave-one-out self-check, coverage line, "Fit to my field", undo, marks on fitted values. |
| D this year so far | Done: station season scaled to the field, rank at this date, look-alike years, [S27] guideline table, records from look-alike years, alternatives, refill message, El Niño on About. The line is hidden today (15 November is outside 1 January–31 May); append `&asof=2025-03-31` to a field's address to replay a past date. |
| E borrowing | Done: `data/similarity.yaml`, sensitivities and levels borrowed from the four reference crops, always naming the crops. |

## Part S: options before and after

Before (brief 2, `tools/demo_options.py`), two of three options were three legumes in a row on four of five fields:

| Field | Before: options A, B, C |
|---|---|
| A Colfax N | winter peas–spring wheat–chickpeas; **spring peas–lentils–chickpeas**; **lentils–spring peas–chickpeas** |
| B Steptoe | winter peas–chickpeas–winter wheat; spring peas–winter peas–winter wheat; spring peas–winter peas–spring wheat |
| C Colfax W | winter wheat–spring peas–winter peas; **spring peas–lentils–chickpeas**; **spring peas–chickpeas–lentils** |
| D Pullman | chickpeas–winter wheat–winter peas; **chickpeas–spring peas–lentils**; **chickpeas–lentils–spring peas** |
| E LaCrosse | fallow–spring canola; spring canola–spring wheat |

After S1, the addendum and addendum 2 (now; no option has two legumes within three years on any field):

| Field | Now: options A, B, C | Headline |
|---|---|---|
| A | winter wheat–spring wheat–spring canola; spring wheat–winter wheat–spring canola; winter wheat–spring wheat–barley | holds up on water; options trade |
| B | winter wheat–spring peas–spring wheat; spring canola–winter peas–winter wheat ⚠; spring wheat–winter peas–spring canola ⚠ | A at least as good on all four |
| C | winter wheat–spring wheat–spring canola; winter peas–spring wheat–spring canola ⚠; winter peas–winter wheat–spring canola ⚠ | A at least as good on all four |
| D | spring canola–winter wheat–spring wheat; spring wheat–winter wheat–spring canola; barley–winter wheat–fallow | A better on water, gives something up |
| E | fallow–winter canola ⚠; cover crop–spring canola ⚠; fallow–spring canola ⚠ | A at least as good, "but note winter canola may be too dry" |

⚠ = serious caution (addendum 2). Swapping one spring crop for another no longer changes the water verdict: tested on all pairs of six spring crops on all five real fields, and offline. Water differences now come only from fallow, cover crops and rooting depth, as the brief expected. Right after S1 (before addendum 2), all options on fields A–D were spring canola plus winter peas, because crop variety was the only measure still separating options; addendum 2's A1 and A4 changed that.

## Part S: screen against the targets (360 × 780, Chromium)

| Target | A | B | C | D | E |
|---|---|---|---|---|---|
| Headline words (≤ 25) | 13 | 17 | 17 | 15 | 25 |
| Bottom of the 4th row, px (≤ 780) | 578 | 557 | 616 | 557 | 537 |
| Closed card words, current and A–C (≤ 45) | 27 32 31 26 | 26 39 45 45 | 26 34 38 39 | 26 28 27 30 | 19 34 35 33 |
| First details layer words (≤ 150) | 85–114 | 85–129 | 77–133 | 86–108 | 73–100 |
| Adjust panel top-level controls (5) | 5 | 5 | 5 | 5 | 5 |

Before: first rotation card 564 px down, first alternative 1,275 px; closed card 100–140 words; Adjust 39 controls, 1,930 px tall. No text is under 16 px, no tappable under 44 px, no horizontal scroll, no "Default:" lines, light theme by default (dark via ◐). Nothing was removed: every figure is one layer down ("show the numbers", "see all", sources as numbered links to the data-sources page). Kept here, the field map adds one collapsible line above the headline on a phone (addendum 2, B).

## Part A: validation

Four areas, 51 × 51 MODIS pixels each, 2008–2025 (18 years), pixels at least 75% one crop:

| Area | Rain | r all crops | LOO gain | + May–June heat | + El Niño groups | Pixel spread in a year | Spread of area mean between years |
|---|---|---|---|---|---|---|---|
| West (LaCrosse) | 15.2 in | 0.58 | 16% | 18% | 5% | 0.078 | 0.045 |
| West-central | 17.7 in | 0.77 | 33% | 26% | 39% | 0.083 | 0.052 |
| Central | 18.4 in | 0.77 | 30% | 24% | 40% | 0.074 | 0.050 |
| East (Pullman) | 22.4 in | 0.73 | 22% | 12% | 35% | 0.066 | 0.051 |

Compared with `docs/EXPERIMENTS.md`: the match is better than the quick tests (east 0.73 against 0.64, west 0.58 against 0.42), still weaker in the west. Two findings differ and need the team's judgment:

- **Temperature**: May–June heat correlates with greenness (−0.60 to −0.72) but adding it to the index *lowers* leave-one-out skill in three of four areas. Not added, as the brief says.
- **El Niño**: in the three wetter areas, grouping years by El Niño phase adds a lot (e.g. east 22% → 35%, spring wheat 29% → 42%). With 18 years and two extra terms this may be overfitting, but it contradicts the quick test's "small". Reported only; it changes nothing.

By crop (east): winter wheat r 0.63, spring wheat 0.75, barley 0.55, canola 0.84, chickpeas 0.86 (7 years); **lentils −0.44 and spring peas 0.18 did not fit**, as in the quick tests. Sensitivities (pooled, greenness, clipped 0.5–2.0): spring wheat 1.74, barley 1.40, spring canola 1.26, lentils 1.18, spring peas 0.75; chickpeas 1.0 assumed (7 years). Spring wheat at 1.74 is high; greenness saturation over dense winter wheat inflates it, as the brief warned. County yields: not available (`data/us/county_yields.csv` absent); the code path exists, and the e_winter search is reported as not run.

The year index (section 4) stays positive everywhere. In the east the month-by-month relationship gives about 101–109 bu/ac in a median year, above the regional 80: it was fitted in drier country. Only the relative index is used, so this does not reach any figure on screen.

## Fitting (parts B, C, E): cases that looked wrong or strange

- With up to about 10 records the fit almost never changes anything: `w_fit` was 0.03–0.32 on example records, so e_winter shrinks back to within 0.01 of 0.675 and the farmer reads "we keep the regional figure". Honest, but "Fit to my field" will look inert in demonstrations.
- With 12% noise on example records, "within 8 bu/ac" held in only 2 of 9 years on field D: 8 bu/ac is 10% of an 80 bu crop, so the sentence is harsh for normal year-to-year noise.
- Borrowing from winter wheat alone (field E records) moves lentil and pea levels by a few percent. Small, and named, as designed.

## Part D on the example fields (replayed over 1982–2025)

| Field | Spring cereal (5 ft): short years, caught, false alarms, refill share | Spring legume (3 ft): refill share |
|---|---|---|
| E LaCrosse (dry west) | 8, **5**, 1, 0.05 | 0.55 |
| D Pullman (east) | 11, 1, 3, 0.46 | **0.91 → "spring rain decides"** |
| A, B, C | 11–13, 3–4, 3–6, 0.30–0.43 | 0.86–0.93 |

The dry west catches most short years (5 of 8; quick test 7 of 8). Stored water on 31 March explains 56% of the supply variance at E (quick test 59%) and 25–43% in the east (24%). The east gives "spring rain decides" for its legume slot, not for a 5 ft cereal, because the soil survey's deeper storage rarely fills.

## Constants (`assumed`) found too loose or too tight

- **Look-alike band ±1 in** (D): too loose in wet fields: 23–29 of 44 years count as "started like this one", so the odds are close to the base rate.
- **Refill share ⅔** (D): the answer depends almost entirely on rooting depth (legumes 86–93%, cereals 30–46% on the same field). It should probably be judged per slot, as it now is, and said so.
- **Within 8 bu/ac** (B): too tight for normal noise (above).
- **Three times the typical yield** (B): loose; a bushel/pound mix-up is 60×, so it is caught, but a 2.5× typing error is not.
- **k = 5 and the ±0.3 normal-year scale** (C): together with recency they make 5 recent records worth `w` about 0.25–0.35 in practice, not the brief's 0.45, because few years have an index near 0.
- **Not seen nearby, under 1%** (S1): fires on most options in the dry west, where nearly all cropland is wheat–fallow.

## Addendum 1 (corrected crop values)

| Item | Applied | Note |
|---|---|---|
| 1 Yields by zone | Yes | Zone boundary 18 in sourced, 15 in assumed; winter wheat after a harvested crop in Transition 35 bu/ac, assumed. |
| 2 Nitrogen credits | Yes | Chickpeas 15 lb above 2,000 lb/ac, 10 below (assumed); winter peas 30 above 3,750. |
| 3 W6 threshold 0 °F | Yes | Detail names the variety range. |
| 4 Canola water use from yield | Yes, **result looks wrong for winter canola** | 3,000 lb ÷ 105 = 28.6 in, more than any field's yearly precipitation, so winter canola is "may be too dry" on every field, including the wet east; field E's headline now carries it. Spring canola (14.3 in) is plausible: flagged on B narrowly and on E. Suggest comparing only the spring share of use, or a per-zone yield. |
| 5 Stored-water table | Yes | Shown in the season panel as a guideline. |
| 6 Rotations in real use | Yes | All 22 sequences pass every hard rule; each zone's traditional sequence is a candidate on every example field. None failed. |
| 7 Legume water | Not applied (optional; S1 water work was finished and tested) | The handbook's sentence was added to the known gaps. |

## Addendum 2

| Item | Done | Note |
|---|---|---|
| A1 serious cautions | Yes | W6 when it fires, W10, W5 at 5+ of 15 years. Ordered last; shown options sorted; never hidden on a card (red, all listed); ⚠ on the row; headline names it ("but note winter-kill risk"). |
| A2 one-way assumed rule | Yes | "probably worse", counted as worse for ordering and dominance. |
| A3 snow | Yes | Daymet `swe` added (cache namespace `daymet_swe`, so records were re-fetched). Wording: "Cold enough to kill, with little snow, in N of 15 winters", modelled estimate stated. |
| A4 options that differ | Yes | If no unbeaten option avoids the shared crop, the best one not beaten by the current rotation is used (field B needed this). |
| B field layers | Yes, without drainage | Map beside the results on wide screens (sticky as cards open), collapsible above on phones, closed by default to keep the four rows on the first screen. Layers: satellite photo, crop map, slope, each with a one-line legend. **Drainage skipped**: the soil data has no per-map-unit geometry. |
| C1–C5 | Not done | No time. The cache is already warm locally (`python -m fieldshift.prewarm` exists). |

A3 winter-kill counts, last 15 winters, any cold night at or below 0 °F → with little snow: A 7 → 4, B 8 → 4, C 7 → 5, D 8 → 6, E 7 → 6. (The addendum's own field: 7 → 5.)

## Engineering notes

- `.xlsx` is read and written with the standard library (zip + XML): values only, formulas never evaluated, macro workbooks and old formats refused, size and unpacked size limited.
- Results are never stored in the browser; storage version 1 (`fieldshift.fields`), older per-field keys from brief 2 are read once.
- New API: `/records_template.xlsx`, `/records/read`, `/records/check`, `/example_records`, `/season` (with `date=` for replays), `/season_replay`, `/enso`, `/api/validation`. Inputs gain `kept`, `records`, `answers`, `fit`, `example_records`.
