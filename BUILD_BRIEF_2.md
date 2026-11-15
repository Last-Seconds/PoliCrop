# Build brief 2: Field Shift, from skeleton to a tool a farmer can use

This brief is for the coding agent building the second version of the app in this repository. It replaces `BUILD_BRIEF.md` wherever the two disagree. Read it fully before starting.

Two companion files hold the evidence behind it:

- `docs/CROP_TABLE_DRAFT.md`: the researched crop values, with sources `[S1]` to `[S26]`. Source tags in this brief refer to that list.
- `docs/DATA_SOURCES.md`: the data-source survey, with what was tested live.

## 1. Where things stand

Version 0 exists and works (checked 2026-11-15: one demo field loads end to end, 22 offline tests pass). A farmer draws a field in Whitman County, Washington and sees crop history, weather, vegetation and three unranked alternative rotations.

What it lacks is judgment. It has two filter rules, no scoring, an empty crop table and no farmer input beyond corrections to the crop history. One alternative it offered was "cover crop, then fallow, then canola", which no farmer would take seriously. It is also hard to use: the answer sits below four screens of charts, under about fifteen caution boxes, in technical words and metric units.

This build gives the tool its judgment and makes it simple to use.

**Who it is for.** A farmer in Whitman County, possibly on a phone, with no training in remote sensing or statistics. They want to know whether a different rotation would serve their field better, and why. The tool supports their judgment; it never claims to replace it.

**What "done" looks like.** The farmer picks a field and, on the first screen after that, sees their current rotation beside three alternatives. Each alternative says in one sentence what changes, and for each of four measures whether it is better, about the same, or worse than what they do now. Everything else is one tap away.

## 2. How to treat this brief

Three kinds of content, treated differently:

| Kind | Where | How to treat it |
|---|---|---|
| Team decisions | Sections 3, 4, 7 | Settled. Do not reopen. |
| Provisional model | Sections 5, 6 and Appendix A | Designed for this brief from sourced figures. Nobody with farming expertise has reviewed it. Implement it as written so it can be reviewed, keep every constant in a settings file with its basis, and do not "improve" it with agronomy of your own. If something looks wrong, build it anyway and say so in your report. |
| Engineering | Everything else | Your judgment. The existing structure is sound; build on it. |

**Do not invent agronomic values.** Every crop figure and model constant you need is in this brief or in `docs/CROP_TABLE_DRAFT.md`. If you find you need one that is not there, leave it empty, show the result as "not assessed", and report it.

**Basis labels.** Every value in the crop table and settings carries a `basis`:

- `sourced`: stated in a cited document.
- `derived`: calculated from a sourced figure.
- `assumed`: a stand-in chosen for this brief. These must stay visible to the user wherever they affect a result (section 6.6).

## 3. Decisions already made

### Scope

- **Area:** Whitman County, Washington (FIPS 53075). Rain-fed farming only. Keep the separation between core logic and the US provider set, so another region stays a new provider set.
- **A strategy** is a sequence of crop roles, each filled by a crop. One slot per crop year (September to August), with real sowing and harvest dates inside it, so periods with nothing growing are visible.
- **Candidates** come from generate-and-filter, using crops grown near the field. Each carries its distance from the existing rotation.
- **No trained model** in this build. Explanations come from templates filled with computed values.
- **US units on screen:** inches, °F, acres, pounds per acre, bushels per acre.

### Crops

| Offered in generated strategies | Recognised in history only |
|---|---|
| Winter wheat, spring wheat, spring barley, spring peas, winter peas, lentils, chickpeas, spring canola, winter canola, fallow, cover crop | Alfalfa, dry beans, anything else the crop map shows |

- Remove dry beans from generation. In old crop-map years "dry beans" may really be chickpeas; keep the existing hint that the farmer can correct it.
- The crop map cannot tell winter from spring peas or canola. Assume spring unless the farmer corrects it. Offer the winter variants when the map's class for that crop is in the local pool.

### Four measures

Each strategy is judged on four measures. Farmer-facing names are in the second column.

| Measure | On screen | Question it answers |
|---|---|---|
| Water fit | Water | Does the field's water cover what the crops need, including in dry years? |
| Nitrogen | Nitrogen | How much nitrogen do legumes in the rotation supply to the following crops? |
| Soil protection | Soil protection | How well is the soil covered in its least-protected winter, and how much does that matter on this field's slopes? |
| Diversity | Crop variety | Does the rotation mix crop types and seasons enough to break weed and disease cycles? |

Erosion is part of soil protection, not a fifth measure. On one field, slope and soil are the same for every strategy, so an erosion rating would always rank strategies exactly as winter cover does. Slope and soil instead decide how much the measure matters on this field, and drive the map (section 6.3).

Shown as notes, never scored: income, number of harvests, how much changes from the current rotation, and how common the pattern is nearby.

### How results are expressed

- Each measure is a **physical quantity, shown as a range**, plus a **comparison with the current rotation**: better, about the same, or worse.
- "About the same" has a margin per measure, because the inputs are rough.
- **No total score** and no "best" label.
- Selection pipeline: filter by rules, score, drop dominated strategies, order by the farmer's priorities, show three at different distances from the current rotation, plus the current rotation.
- Uncertainty is shown through ranges, the margin, "assumed" tags and cautions attached to specific claims. There is no separate confidence score.

### The future

- **Replay:** every strategy is run through each past year of weather. The main view is the last 15 crop years; the full record is shown for comparison; 2021, the driest and hottest year on record there, is called out.
- **Scenario sliders** rerun the replay with changed weather.
- **A 2050 outlook** from climate projections is a separate display panel. It never feeds the scoring.

### Data

- **Daymet replaces NASA POWER** for all weather. Against local weather stations, NASA POWER overstated yearly rainfall by 30% at Pullman and 14% at LaCrosse; Daymet was within 6% and 3%. Remove NASA POWER from calculations and charts.
- The current, unfinished year is left out. Daymet is released yearly and covers 1980 to the end of 2025.
- All sources in section 8 are to be included, in the staged order of section 10.

## 4. Simplicity rules

These are requirements, not preferences. The build adds a great deal; these rules keep the first screen small.

1. **One required step:** choose the field. Everything else is optional.
2. **The answer comes first.** Once a field is chosen, the strategies are at the top. Evidence sits below, closed by default.
3. **Three alternatives by default,** each with one plain sentence saying what changes and why. A "show more" control may reveal further ones.
4. **Each measure is one line:** better, about the same, or worse than now. Numbers open on a tap.
5. **All optional inputs live in one "Adjust" panel,** each with a visible default.
6. **At most two cautions show per strategy;** the rest are behind "more". No caution appears twice on a screen.
7. **Plain words and US units** (word list in section 9).
8. **A second tab, "About this area",** holds regional context, the 2050 outlook, data sources, and how the tool works.
9. **It works on a phone,** at 360 px wide, without sideways scrolling.
10. **Internal markers stay out of the farmer's view.** "Provisional" tags belong on the "how it works" page. "Assumed" appears only where it affects a result.

Also: never signal better or worse by colour alone; pair it with a word or symbol. Fix the version 0 rainfall and vegetation charts, which rendered as a narrow strip in a 1280 px capture.

## 5. The crop table

Fill `data/crops.yaml` from Appendix A. Extend its schema as needed; name fields with their units. Each value carries `basis` and `source`.

Roles: cereal (winter wheat, spring wheat, spring barley); legume (spring peas, winter peas, lentils, chickpeas); oilseed (spring canola, winter canola); fallow; cover crop. Forage stays a history-only role.

**Cover crop, as modelled here.** It replaces a fallow year. That is the only use with a local water figure [S14]. A cover crop grown over one winter between two cash crops is not modelled; where a field shows a bare period, the tool may mention the idea as something to check locally, with no score.

## 6. The model

### 6.1 Rules

A generated candidate that fails a hard rule is discarded. The farmer's existing rotation is never discarded; its rule results are shown gently, since the crop map may be wrong.

Hard rules:

| Id | Rule | Basis |
|---|---|---|
| H1 | No identical crop in consecutive years (exists) | General |
| H2 | No overlapping dates: a crop's latest usual sowing date must not fall before the previous crop's usual harvest end (exists; now uses real windows) | Physical |
| H3 | The same legume crop appears at most once in any 3 consecutive crop years, counted cyclically | Chickpeas once in 3 to 5 years [S3]; 3 or more years between pulse crops [S16] |
| H4 | Winter canola only directly after fallow | Soil too dry after a harvested crop for it to establish before winter [S25] |
| H5 | No two consecutive years without a harvest (fallow or cover crop) | Structural sanity rule added in this brief; `assumed` |

Warnings, shown beside a strategy and never removing it:

| Id | Warning | Trigger | Basis |
|---|---|---|---|
| W1 | Chickpeas every third year | Chickpeas exactly 3 years apart | Guides say 3 to 5 years, 4 to 5 where Fusarium wilt is present [S3] |
| W2 | Two different legumes close together | Any two legume crops less than 3 years apart | [S16] |
| W3 | Spring canola in a dry location | Field's mean yearly precipitation under 12 in | [S25] |
| W4 | Soil may be too acid | Farmer's soil pH below the crop's critical pH (Appendix A) | [S13] |
| W5 | Heat during chickpea flowering | Share of replay years with a day at or above 98 °F in June or July | Limit [S16]; the June–July window is `assumed` |
| W6 | Winter-kill risk for winter peas | Share of replay winters with a night at or below −6 °F, November to March | [S4]; snow cover, which protects the crop, is not known |
| W7 | Peas on poorly drained soil | Peas on a field whose main soil is "poorly" or "somewhat poorly" drained | [S2]; soil class from the soil database |
| W8 | Herbicide carryover | Standing "check locally" note on any strategy that puts a legume or canola after a cereal, or canola after a legume | [S5], [S23]; the tool cannot know what was sprayed |
| W9 | Spring peas in a dry location | Field's mean yearly precipitation under 17.7 in (450 mm) | Very little spring pea is grown below 450 mm; water and heat stress at flowering limit it [S4] |

W5 and W6 are frequencies, worded like "in 4 of the last 15 years".

### 6.2 Replay and the water budget

**Weather.** Daily precipitation and temperature from Daymet at the field's centre.

- A crop year `y` runs from 1 September of `y−1` to 31 August of `y`.
- Replay years: crop years 1982 to 2025. "Recent" means the last 15 (2011 to 2025).
- Every slot of the rotation is evaluated in every replay year, as if the farm had one field in each phase.

**Supply.** The winter-rain climate stores water in the soil for the crop to use in spring and summer. The budget follows the definitions of the regional wheat study [S7].

For the crop in a slot, in crop year `y`:

```
winter_gain  = e_winter × P(1 Sep y−1 … 31 Mar y)

previous slot was a harvested crop:
    stored = min(capacity, winter_gain)

previous slot was fallow:
    fallow_store = e_fallow × P(1 Aug y−2 … 31 Aug y−1)
    stored = min(capacity, fallow_store + winter_gain)

previous slot was a cover crop:
    as fallow, with fallow_store reduced by cover_cost, never below zero

supply = stored + P(growing season)
```

`P(a … b)` is total precipitation between two dates.

| Constant | Value | Basis |
|---|---|---|
| `e_winter` | 0.60 to 0.75, central 0.675 | `sourced` [S6]: 60–75% of winter precipitation is stored until April |
| `e_fallow` | 0.30 | `sourced` [S6]: 30% of precipitation over a 13-month fallow is stored |
| `cover_cost` | 2 to 4 in, central 3 | `sourced` [S14]: a forage cover crop left 2–4 in less soil water than fallow |
| `capacity`, cereals and canola | Plant-available water storage, 0–150 cm, averaged over the field | Soil database; wheat draws from 6 ft [S7], canola roots reach 46–65 in [S19] |
| `capacity`, all four legumes | The same, 0–100 cm | Soil database; legume roots are shallower [S2], [S3], [S16] |
| Growing season, cereals and winter crops | 1 April to 30 June | `sourced` [S7] |
| Growing season, spring legumes and spring canola | 1 April to 31 July | `assumed`, from their harvest dates |

After a harvested crop the soil starts with no stored available water. That matches [S7], which defines water left at harvest as unavailable. It ignores the small amount shallow-rooted crops leave behind.

**Known gaps, to list under "what we don't know":**

- Heat and evaporation are not in the budget. A hot, dry spring hurts crops more than the missing rain alone suggests.
- The legume and spring canola needs are fixed figures from one trial, not a response to conditions.
- Water left behind by shallow-rooted crops is ignored.
- Weather is a 1 km grid estimate, and soil storage comes from the soil survey, not from the field.

**Need.**

- Spring peas, lentils, chickpeas, spring canola: the figure in Appendix A.
- Cereals: the median supply that crop receives across the full replay record in its reference position. The reference position is where the crop sits in the farmer's current rotation (after fallow, or after a harvested crop). If the crop is not in the current rotation, the reference is "after a harvested crop". If it sits in several positions, take the median across all of them.
- Winter peas: the winter wheat need minus 1.2 in [S4]. Winter canola: the winter wheat need (`assumed`).

So for cereals the question is "how does this year's water compare with what this crop normally gets on this field under the farmer's present system?". This avoids needing a yield target, which no source gives for the drier parts of the county.

**Shortfall.** `shortfall = max(0, need − supply)`. A crop is "short" in a year when the shortfall exceeds 1.5 in (`assumed`). For wheat, each inch is worth about 5.8 bushels per acre [S7]; use that only to illustrate a shortfall, never to predict a yield.

**Worked example,** for your tests. Take September–March precipitation 10.0 in, April–June 3.0 in, fallow-period precipitation 15.0 in, capacity 10.6 in, central constants:

| Case | Stored | Supply |
|---|---|---|
| Wheat after a harvested crop | min(10.6, 6.75) = 6.75 | 9.75 in |
| Wheat after fallow | min(10.6, 4.5 + 6.75) = 10.6 | 13.6 in |
| Wheat after a cover crop | min(10.6, 1.5 + 6.75) = 8.25 | 11.25 in |

**The measure.** The share of crops grown that were short of water, over the recent 15 years, with the same share over the full record beside it.

- On screen, say it as people do: "about 1 crop in 5 was short of water". Give the typical depth of a shortfall in inches, and a line for 2021.
- "About the same" margin: 7 percentage points (`assumed`).
- Supply depends only on the crop's root-zone class, its growing-season class, the kind of previous slot, and the year. Compute that small table once per field and score candidates by lookup.

### 6.3 Soil protection

**Quantity:** estimated crop residue on the soil surface entering the rotation's least-protected winter, in pounds per acre, as a range. Erosion in this region happens in winter, from rain and snowmelt on frozen ground [S8], so the weakest winter is what counts.

For the winter after slot `k`:

```
surface_residue = tillage × ( residue(k) × persist(k) + carry(k−1) × residue(k−1) )
```

| Term | Value | Basis |
|---|---|---|
| `residue`, cereals | From the grain-yield relationships in [S9] (Appendix A) at the expected yield | `sourced` |
| `residue`, spring peas, lentils | 1,500 to 2,000 lb/ac | `sourced` [S8] |
| `residue`, chickpeas | Same as peas and lentils | `assumed` |
| `residue`, winter peas | The Austrian winter pea relationship in [S9] | `sourced` |
| `residue`, canola | yield × (1 − h) / h, with h from 0.20 to 0.35 | `derived` [S19]: seed is 20–35% of above-ground dry matter |
| `residue`, fallow | 0 | |
| `persist`, legumes | 0.33 to 0.75 | `derived` [S8]: 500–1,500 lb/ac remain of 1,500–2,000 |
| `persist`, cereals and canola | 1.0 | `assumed` |
| `carry`, cereals and canola | 0.5 into a second winter | `assumed`; [S6] says only that cereal residue is long-lived |
| `carry`, legumes | 0 | `assumed` |
| `tillage`, no-till | 1.0 | `assumed` |
| `tillage`, reduced | 0.6 | `sourced` [S6]: chisel or disk leaves 60% or more of stubble on the surface |
| `tillage`, conventional | 0.15 | `assumed` |
| The winter after a cover-crop year | Counts as 3,000 lb/ac | `assumed` |

- Default tillage when the farmer has not said: reduced (`assumed`, shown as the default).
- "About the same" margin: 500 lb/ac (`assumed`).
- Seedlings of an autumn-sown crop are ignored; the sources name winter wheat sown after a legume as the high-risk case despite them [S6].

**Expected yield,** used here and for the pea nitrogen tier, never for water:

1. The farmer's own typical yield, if entered.
2. Otherwise, where the field's mean yearly precipitation is 18 in or more, the regional typical yield in Appendix A [S18].
3. Otherwise, for cereals, the yield implied by the field's median supply using the [S7] relationship: (supply − 2.3 in) × 348 lb per acre per inch (5.8 bushels of 60 lb). For other crops, the regional figure, tagged as coming from a wetter area.

**How much it matters on this field.** From the soil database: the main soil's slope class and its erodibility factor. From elevation data (stage 4): slope across the field.

- Sensitivity classes by representative slope: under 5% low, 5 to 15% moderate, above 15% high (`assumed` thresholds).
- On a high-sensitivity field, say so on the soil protection line: the difference between strategies matters more there. On a low one, say it matters less.
- No tons-per-acre estimate. The standard erosion formula handles frozen-ground runoff poorly, so an absolute figure would mislead.

### 6.4 Nitrogen

**Quantity:** nitrogen credit supplied by legumes, in pounds per acre per year averaged over the rotation, as a range.

- Credits per legume crop are in Appendix A [S11], [S23].
- Beside it, as a plain fact: how many years of the rotation grow a nitrogen-demanding crop (any cereal or canola).
- "About the same" margin: 2 lb/ac per year (`assumed`).
- In the details, give context: winter wheat needs 2.4 to 3.1 lb of nitrogen per bushel [S10]; canola needs more per pound of seed than wheat [S22]; less fertiliser also slows soil acidification [S12].
- Do not score the yield boost wheat gets after a legume. Sources disagree: 19% after peas in regional research [S18], no difference in a 2023–2024 Pullman trial [S15]. Mention it in the details as "0 to 19%".

### 6.5 Crop variety

**Quantities:**

- How many of four groups the rotation grows: winter grass, spring grass, winter broadleaf, spring broadleaf.
- The longest run of grass crops in a row, counted cyclically.

More groups is better; with equal groups, a shorter grass run is better. Fallow and cover crops belong to no group.

Why these: the main local grass weeds share winter wheat's life cycle [S4], and broadleaf crops allow selective control of grass weeds [S3]. Counting distinct crop names would miss this.

### 6.6 Comparing, filtering, ordering

**Comparison on one measure.** Use central values and the measure's margin to decide better, about the same or worse.

**Assumed values never decide alone.** If either strategy's quantity rests on an `assumed` value, and the verdict would flip when the ranges are taken at their unfavourable ends, report "about the same" and say it depends on an assumed figure.

**Dominance.** Strategy A dominates B when A is no worse on all four measures, better on at least one, and has at least as many harvest years. Drop dominated candidates. The harvest condition matters: fallow lowers water need, so without it the tool would favour growing less.

**Ordering.** By the farmer's priority order. Compare first the verdict against the current rotation on the top priority (better before about the same before worse), then the verdict on the second priority, and so on through all four. Break remaining ties by the quantity on the top priority, then by the pattern more common nearby.

**Selection.** Split surviving candidates into three bands by distance from the current rotation (small, moderate, large change). Show the top-ordered candidate of each band. If a band is empty, take the next best overall.

**Honest outcomes.** State these plainly when they occur:

- No alternative improves the farmer's top priority: "your current rotation holds up; these options trade one thing for another".
- An alternative is at least as good on all four measures: say so, and name the harvest count beside it.
- The current rotation breaks a rule: say what the crop map shows and that it may be wrong.

### 6.7 Notes on each strategy

| Note | Content |
|---|---|
| Harvests | "3 harvests in 3 years", against the current rotation |
| Change | What differs from the current rotation, in words (exists; reword in plain language) |
| Income | Regional return per acre for each crop where known (Appendix A), averaged over the rotation only if every crop has a figure. Always labelled "2011–2015 regional averages", with the fact that winter wheat lost money in 2016 while peas, chickpeas and lentils did not [S18]. |
| Nearby use | Share of cropland within 10 km whose recent crop-map sequence matches the strategy's role pattern, cyclically. Worded as evidence that the pattern is workable locally, never as proof it is good. |

### 6.8 Scenarios

Two sliders rerun the replay:

- **Growing-season rain:** −30% to +10%, applied to daily precipitation from April to July.
- **Summer temperature:** 0 to +5 °F, applied to daily highs and lows.

Needs stay as calibrated on the unchanged record, so a drier scenario shows more shortfalls.

Say on screen what the temperature slider does and does not do: it changes the heat and cold frequencies (W5, W6). It does not raise crop water demand, because the model has no evaporation term. That understates the effect of warming, and must be stated as a gap.

For reference in the evidence section: at the Pullman weather station, April–July rain fell from 5.9 in (1982–1996) to 4.6 in (2012–2025), and June–July days at or above 90 °F rose from 7 to 13 per year, while yearly rain stayed flat. See `docs/DATA_SOURCES.md`.

### 6.9 What each strategy must explain

The challenge asks for five things per strategy. The details view of each card has exactly these headings:

1. **Why this option:** which measures improve, in one or two sentences.
2. **The evidence:** the quantities with ranges, the replay frequencies, and the sources.
3. **What it may gain you:** the benefits in plain terms.
4. **What we don't know:** anything not assessed, every assumed value that mattered, and the model gaps.
5. **Check locally:** the warnings, the herbicide note, and a reminder to talk to an agronomist or extension office.

## 7. Farmer inputs

The field alone must give a complete result. Every other input is optional, has a visible default, and says what it changes. Results mark which values came from the farmer and which are defaults. Remember inputs in the browser; no accounts.

| Input | Changes | Default |
|---|---|---|
| The field | Everything | Required |
| Corrections to crop history, including winter or spring for peas and canola | The current rotation | The crop map, spring assumed |
| Priority order of the four measures | Ordering | Water, soil protection, nitrogen, crop variety |
| "Dry region mode" | Judges every option on dry years only (below) | Off |
| Crops to rule out; crops to keep | Filtering | None |
| Plan length | Generation | Length of the current rotation |
| Soil pH from a soil test | Warning W4 | Unknown, and W4 says so |
| Tillage: conventional, reduced, no-till | Soil protection | Reduced |
| Own typical yields | Residue and the pea nitrogen tier | Section 6.3 |
| The two scenario sliders | The replay | No change |

**Dry region mode.** The team asked for a mode aimed at "least water, most food". As defined for this brief (`assumed`): the water measure is computed over the five driest of the recent 15 crop years, by the field's crop-year precipitation, instead of all 15; water is placed first in the priority order; and ties are broken in favour of more harvests. The screen says the mode is on and what it does.

The soil database also reports a pH, but it describes the soil as surveyed, typically 6.5 to 7 here, while measured field values in the region have fallen below 5 [S12]. Never use the database pH for W4.

## 8. Data sources

"Tested" means called on 2026-11-14 or 2026-11-15 with usable data returned for Whitman County. Verify anything else before relying on it. Cache every external call, as now.

### Stage 1 sources

**Daymet V4 R1** (NASA). Tested.

- `https://daymet.ornl.gov/single-pixel/api/data?lat=<lat>&lon=<lon>&vars=prcp,tmax,tmin&start=1980-01-01&end=2025-12-31`
- Returns CSV: several header lines, then a row starting `year,yday`, then `prcp (mm/day)`, `tmax (deg c)`, `tmin (deg c)`. No key.
- 1 km grid. Every year has exactly 365 rows; in leap years 31 December is dropped.
- Other variables exist, including snow water equivalent (`swe`), which could later refine W6.

**Soil.** Two routes to the same USDA data; use whichever gives area-weighted values over a field more simply.

- *Soil Data Access.* Tested, no key. POST JSON `{"format": "JSON+COLUMNNAME", "query": "<SQL>"}` to `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest`. This query returned 13 rows for a test polygon near Pullman, with slope classes, drainage, storage and erodibility:

```sql
SELECT mu.mukey, mu.muname, c.compname, c.comppct_r, c.drainagecl,
       c.slope_l, c.slope_r, c.slope_h, c.hydgrp,
       ma.aws0100wta, ma.aws0150wta,
       (SELECT TOP 1 ch.kwfact FROM chorizon ch
         WHERE ch.cokey = c.cokey ORDER BY ch.hzdept_r) AS kw_top
FROM mapunit mu
JOIN component c ON c.mukey = mu.mukey
JOIN muaggatt ma ON ma.mukey = mu.mukey
WHERE c.majcompflag = 'Yes'
  AND mu.mukey IN (SELECT * FROM
      SDA_Get_Mukey_from_intersection_with_WktWgs84('polygon((lon lat, ...))'))
```

  Storage (`aws0100wta`, `aws0150wta`) is in centimetres. It lists the soil map units a polygon touches without their area shares. A server-side query that intersected the polygon with the soil polygons and returned areas did work, but took more than a minute; too slow for a live request unless cached.

- *gNATSGO rasters* on Planetary Computer, collection `gnatsgo-rasters`. Listed, not read. Assets include `aws0_100`, `aws0_150` and `mukey`, which make area-weighting a raster window read. Check its units against Soil Data Access at the same spot before trusting them.

**Cropland Data Layer** and **Sentinel-2**: as in version 0.

### Stage 4 sources

**NOAA weather stations through ACIS.** Tested, no key.

- Find stations: POST `{"county": "53075", "meta": "name,sids,ll,elev,valid_daterange", "elems": "pcpn"}` to `https://data.rcc-acis.org/StnMeta`. It returned 25 stations.
- Get data: POST `{"sid": "USC00456789", "sdate": "1980-09-01", "edate": "2025-08-31", "elems": [{"name": "pcpn"}, {"name": "maxt"}, {"name": "mint"}]}` to `https://data.rcc-acis.org/StnData`.
- Values are strings in inches and °F. `M` is missing, `T` is a trace, `S` and a trailing `A` mark multi-day accumulations. Records have gaps; use only near-complete years.
- Long records: Pullman 2 NW (`USC00456789`, from 1940), Rosalia (`USC00457180`, from 1893), LaCrosse (`USC00454338`, 1908–2021).

**MODIS vegetation index** (NASA), Planetary Computer collection `modis-13Q1-061`. Item search tested. 250 m, every 16 days, from 2000. Assets `250m_16_days_NDVI` and `250m_16_days_pixel_reliability` are cloud-optimised GeoTIFFs. The county spans tiles h09v04 and h10v04, from both the Terra and Aqua satellites.

**NASADEM** (NASA), collection `nasadem`. Item search tested. Asset `elevation`, 30 m, in 1° tiles such as `NASADEM_HGT_n46w118`. The Palouse's hills are short, so a 30 m grid understates their steepness; show the soil database's slope class beside it.

**US Drought Monitor.** Tested, no key.

- `https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=53075&startdate=7/1/2021&enddate=7/31/2021&statisticsType=1` with header `Accept: application/json`.
- Weekly rows with `none`, `d0` to `d4` as cumulative percent of the county. Late July 2021 returned 100% in every class through D4.

### Stage 5 source

**USDA Crop Sequence Boundaries.** Not verified. They are field polygons with eight-year crop sequences, derived from the Cropland Data Layer; a 2024 edition exists. The only catalogue entry found had no queryable service, so it may be a large download. See section 10 for the fallback.

### Stage 6 sources

**NEX-GDDP-CMIP6** (NASA), collection `nasa-nex-gddp-cmip6`. Item search and one file header tested.

- Daily values 1950–2100, 35 climate models, scenarios `historical`, `ssp245`, `ssp585`. Variables include `pr`, `tasmax`, `tasmin`.
- One NetCDF file per model, scenario, variable and year, about 190 MB each. Byte-range requests work, so a small window can be read without downloading the file. Sign URLs through `https://planetarycomputer.microsoft.com/api/sas/v1/sign?href=<url>`.

**Crop-CASMA** (USDA and NASA; soil moisture from the SMAP satellite, 2015 on) and **GRACE drought indicators** (NASA; weekly groundwater and root-zone wetness, about 25 km, 2003 on, on Amazon's open-data registry). Listed only; access not tested.

## 9. Interface

### Layout

**Screen 1: choose a field.** The map, a draw tool, the demo fields. In stage 5, also tap to pick.

**Screen 2: this field.**

1. *Header.* Field size in acres, and the current rotation in words, with "from the USDA crop map; fix it if wrong".
2. *A one- or two-sentence headline* built from the results (section 6.6, "honest outcomes").
3. *Options.* The current rotation and three alternatives as cards. On a phone they stack. Each card has:
   - a timeline of the years, coloured by role, crops named;
   - one sentence: what changes and the main reason;
   - four lines, one per measure: better, about the same, or worse than now;
   - a line of facts: harvests, and how many years change;
   - up to two cautions;
   - "Why and details", opening the five headings of section 6.9.
4. *An "Adjust" control* opening one panel with three groups: "What matters most to you", "Your field and how you farm it", "What if the weather changes".
5. *"What we know about your field",* closed by default: crop history (editable), rain and heat, greenness and bare periods, soil and slope.

**Tab "About this area":** regional context, the 2050 outlook, data sources and attributions, and "how this works" with the methods, every parameter and its basis.

### Words

| Do not show | Show |
|---|---|
| NDVI | Greenness |
| Candidate, generated strategy | Option |
| Distance 1.5 of 3 | "Changes 2 of 3 years" |
| Dominated | (never shown) |
| Replay | "Looking back over the last 15 years" |
| Precipitation | Rain and snow |
| Residue | Crop residue (straw and stubble left on the field) |
| Provisional | (only on the "how this works" page) |
| mm, °C, ha, kg/ha | in, °F, acres, lb/acre |

Explain any farming or science term the first time it appears, in a few words.

### Evidence sections

- **Rain and heat.** Rain by month; rain per crop year with 2021 marked; April–July rain and hot days for three periods of the record, which is where the change shows. A line comparing the grid estimate with the nearest weather station (stage 4).
- **Greenness and bare periods.** The Sentinel-2 chart, simplified; bare periods summarised in a sentence. From stage 4, peak greenness per year since 2000 from MODIS, each year labelled with its crop, dry years marked. Skip MODIS for fields too small to hold whole 250 m pixels, and say so.
- **Soil and slope.** Main soil types, drainage, water storage in inches, slope class; from stage 4 a slope map of the field with steep ground highlighted.

## 10. Build stages

Finish each stage, with its tests and checks passing and the app working, before starting the next. If time runs out, stop at a stage boundary. Stages 1 to 3 are the product; 4 to 6 add evidence and reach.

| Stage | Contents |
|---|---|
| **1. Foundations** | Crop table from Appendix A. Daymet weather provider; remove NASA POWER. Soil provider. Rules H3 to H5 and real season windows. Internal units settled, US units at the display edge, conversions tested. Add one demo field in the dry west of the county, near LaCrosse. |
| **2. Judgment** | Replay engine and water budget. The four measures. Comparison, margins, the assumed-value rule, dominance, ordering, selection. Warnings W1 to W9. Notes except nearby use. The sanity checks of section 12. |
| **3. The simple interface** | Screen 2 rebuilt to section 9. The Adjust panel with all inputs of section 7, including the scenario sliders. Plain words, US units, phone layout, chart fix. |
| **4. Evidence** | Nearest weather station check. MODIS greenness history. Drought Monitor. Slope from NASADEM with the map. Nearby use, computed from the cached county crop-map rasters. |
| **5. Field picking** | Tap a field to select it. First spend at most an hour finding out whether Crop Sequence Boundaries can be queried for one county without a multi-gigabyte download. If not, build it from what exists: `backend/tools/trace_demo_fields.py` already traces an outline from crop-map pixels that share one crop sequence. Drawing stays available either way. |
| **6. About this area** | Regional context from the Drought Monitor; add Crop-CASMA or GRACE only if an hour's investigation finds simple access. The 2050 outlook, below. |

**The 2050 outlook.** Build it as an offline tool that writes a small data file into `data/`, not as a live request.

- For the few grid cells covering the county, compare a historical window with a mid-century window under both scenarios.
- Report the change in April–July precipitation, in June–July days at or above 90 °F, and in mean temperature.
- Give the middle value and the spread across models, and say how many models were used. A subset of at least five is acceptable; name them.
- On screen it is a separate panel. It says the models disagree, and that two published studies of this region drew opposite conclusions: one projected that more fallow would be needed, the other that yields would rise and fallow would decrease. Both are summarised at https://csanr.wsu.edu/climate-change-and-fallow/ (Washington State University, 2018). Link to it; do not turn it into a number.

## 11. Engineering constraints

- **Keep the structure:** core logic with no network and no web framework; providers behind small interfaces; content in data files; a cache between providers and core.
- **New provider interfaces** as needed: soil, terrain, weather stations, drought, field boundaries, long vegetation history. Daymet implements the existing weather interface.
- **Scorers** plug into the existing scorer registry. Each returns the quantity as low, central and high, its unit, whether an assumed value fed it, and the pieces of the explanation.
- **Everything tunable is a named parameter** in a settings file, with its unit, basis and source.
- **External data is untrusted.** Validate shapes and ranges; a failing source degrades one section, never the page. If soil data fails, water uses a stated default capacity and says so.
- **Tests run offline.** Cover the water budget (use the worked example), each rule, the comparison and dominance logic, the assumed-value rule, and unit conversions.
- **Do not commit or push** unless the team asks.

## 12. Done means

Stages 1 to 3:

- A farmer can pick a field and read the first screen without scrolling past evidence to reach the options.
- No option shown has two years running without a harvest.
- Winter wheat, then spring wheat, then chickpeas passes every hard rule, with warning W1. Winter wheat alternating with peas fails H3. Winter canola straight after a harvested crop fails H4.
- **The west–east check.** A fallow year should add clearly more water for the following wheat in the dry west (near LaCrosse) than in the wet east (near Pullman), and winter wheat after fallow in the west should be short of water far less often than winter wheat after a harvested crop. That is the pattern farmers there actually follow, so it is the main evidence the water budget is sensible. If it fails, report it and do not tune constants to force it.
- A quick prototype of the budget on Daymet data, using one assumed capacity of 10.6 in at both places, gave these figures. Yours will differ with real soil values, but the pattern should match:

  | | Pullman (east) | LaCrosse (west) |
  |---|---|---|
  | Mean crop-year precipitation, 1982–2025 | 21.7 in | 15.2 in |
  | Median supply, wheat after a harvested crop | 14.6 in | 10.5 in |
  | Median supply, wheat after fallow | 15.8 in | 13.5 in |
  | Gain from fallow | 1.2 in | 3.0 in |
  | Wheat after a crop, short of its after-fallow normal (full record) | 41% of years | 68% of years |
  | Wheat after fallow, short of the same (full record) | 18% | 5% |
  | Wheat shortfall in 2021, after a harvested crop, against its own normal | 3.8 in | 4.9 in |

- 2021 appears as a shortfall year for cereals at both places. Expect the prototype's weakness too: spring legumes near Pullman showed almost no shortfall in 2021, even though the US Drought Monitor put the whole county in its most severe class that July. The budget has no heat term, and stored winter water hid the dry spring. Do not hide that; it belongs under "what we don't know", and warning W5 partly covers it for chickpeas.
- Every quantity shows a range; every comparison uses a margin; every assumed value that affected a verdict is visible in that strategy's details.
- Changing a crop value, a rule threshold or a model constant needs no code change.
- The page is usable at 360 px wide, in US units, with no term from the left column of the word list.
- At most two cautions per card; none repeated.

Stage 4 and later:

- Daymet's crop-year totals sit within about 10% of the nearest long-record station.
- The slope map and the soil database's slope class tell a consistent story, or the difference is explained on screen.
- The 2050 panel states the number of models and their spread.

## 13. Out of scope

Trained models; user accounts; irrigated farming; other regions; a tons-per-acre erosion figure; reasoning about herbicide history; double cropping and intercropping; cover crops between two cash crops as a scored option; profit calculations beyond the regional notes.

## 14. Report back

When you stop, say:

- which stages are complete and what works end to end;
- the result of the west–east check, with the numbers;
- every place a data source behaved differently from this brief;
- every value you needed and did not find;
- anything in the provisional model that produced a result you think is wrong, with an example;
- what you verified yourself, and what you built but could not check.

---

## Appendix A: crop values

Sources `[S..]` are listed in `docs/CROP_TABLE_DRAFT.md`. Keep the Cropland Data Layer codes already in `data/crops.yaml`, which version 0 checked against the official legend.

### Seasons, type and class

Windows are the "most active" ranges. H2 uses the latest usual sowing date and the usual harvest end.

| Crop | Type | Sown | Usual sowing window | Usual harvest window | Basis |
|---|---|---|---|---|---|
| Winter wheat | Grass | Autumn | 1 Sep – 10 Oct | 25 Jul – 20 Aug | `sourced` [S24] |
| Spring wheat | Grass | Spring | 25 Mar – 30 Apr | 1 Aug – 30 Aug | `sourced` [S24] |
| Spring barley | Grass | Spring | 30 Mar – 5 May | 1 Aug – 30 Aug | `sourced` [S24] |
| Spring peas | Broadleaf, legume | Spring | 10 Apr – 15 May | 20 Jul – 20 Aug | `sourced` [S24] |
| Lentils | Broadleaf, legume | Spring | 10 Apr – 30 Apr | 1 Aug – 31 Aug | Harvest month `sourced` [S2]; sowing window `assumed` from "early spring; after April lowers yield" [S2] |
| Chickpeas | Broadleaf, legume | Spring | 1 Apr – 30 Apr | 25 Jul – 31 Aug | Month `sourced` [S15]; window bounds `assumed` around two observed harvests (28 Jul, 18 Aug) |
| Winter peas | Broadleaf, legume | Autumn | 25 Aug – 7 Sep | 1 Jul – 15 Jul | `sourced` [S4], from a drier site |
| Spring canola | Broadleaf | Spring | 1 Apr – 10 May | 1 Aug – 31 Aug | `sourced` [S15], [S17], [S26] |
| Winter canola | Broadleaf | Autumn | 1 Aug – 15 Sep | 15 Jul – 15 Aug | Sowing `sourced` [S5]; harvest `assumed`, as winter wheat |
| Fallow | – | – | From the previous harvest to the next sowing, about 13 months | | `sourced` [S6] |
| Cover crop | – | – | Occupies a fallow year | | Modelling choice, section 5 |

### Water

| Crop | Need | Root-zone storage | Basis |
|---|---|---|---|
| Winter wheat, spring wheat | Self-calibrated (section 6.2) | 0–150 cm | [S7] |
| Spring barley | As wheat | 0–150 cm | `assumed`: [S7] studied wheat only |
| Spring peas | 9.3 in | 0–100 cm | `sourced` [S3]: Pendleton, Oregon, wetter-than-average years |
| Lentils | 9.7 in | 0–100 cm | `sourced` [S3], same trial |
| Chickpeas | 9.8 in | 0–100 cm | `sourced` [S3], same trial |
| Winter peas | Winter wheat need − 1.2 in | 0–100 cm | `derived` [S4] |
| Spring canola | 9.8 in | 0–150 cm | `assumed`, as chickpeas; a Pullman trial ranks its soil-water use between peas and chickpeas [S15] |
| Winter canola | Winter wheat need | 0–150 cm | `assumed` |

### Expected yield, residue, nitrogen

Regional typical yields are 2011–2015 averages for the part of the region with 18 in of precipitation or more [S18].

| Crop | Regional typical yield | Residue at harvest | Nitrogen credit to the next crop |
|---|---|---|---|
| Winter wheat | 80 bu/ac (4,800 lb) | 1.1274 × yield + 1,175 | – |
| Spring wheat | 58 bu/ac (3,480 lb) | 0.8613 × yield + 2,068 | – |
| Spring barley | 1.5 tons/ac (3,000 lb) | 0.7013 × yield + 1,303 | – |
| Spring peas | 1,700 lb/ac | 1,500–2,000 lb/ac | 10 lb/ac under 1,500 lb yield; 15 at 1,500–2,500; 20 above [S11] |
| Lentils | 1,100 lb/ac | 1,500–2,000 lb/ac | 10 lb/ac [S11] |
| Chickpeas | 1,200 lb/ac | 1,500–2,000 lb/ac (`assumed`) | 10–20 lb/ac, the general figure for pulse crops [S23]; no chickpea-specific figure exists |
| Winter peas | 2,000 lb/ac | 1.3427 × yield + 1,327 | The spring pea tiers (`assumed`) |
| Spring canola | 1,500 lb/ac | yield × (1 − h) / h, h = 0.20–0.35 | – |
| Winter canola | 3,000 lb/ac (`assumed`: twice spring canola, after [S5]) | As spring canola | – |

The residue relationships are from [S9] and work in kilograms per hectare for both yield and residue. Convert at the edges.

### Limits

| Crop | Critical soil pH [S13] | Other limits |
|---|---|---|
| Winter and spring wheat | 5.2–5.4 | |
| Spring barley | 5.2 | |
| Spring peas | 5.5 | Dies after 24–48 hours of waterlogging [S2] |
| Winter peas | 5.5 (`assumed`: the source lists spring peas) | Killed at −6 °F without snow cover in one trial year [S4] |
| Lentils | 5.7 | |
| Chickpeas | None: the source lists it as unknown. No W4 for chickpeas. | Stressed at or above 98 °F in early flowering and pod fill [S16]; once in 3 to 5 years [S3] |
| Spring canola | 5.5 | Uncommon under 12 in of yearly precipitation [S25] |
| Winter canola | 5.5 | Only after fallow [S25] |

### Income notes

Return over total cost per acre, 2011–2015 regional averages [S18]. Use only these rows; other crops have no complete figure.

| Crop | Return per acre |
|---|---|
| Soft white winter wheat | +$64 |
| Soft white spring wheat | +$27 |
| Chickpeas | +$63 |
| Lentils | +$18 (the source's table; its text says $29) |
| Spring peas | −$7 |
| Spring barley | −$24 |
| Spring canola | −$35 |

The source stresses that crops losing money in their own year can still raise the rotation's return. Say so wherever these figures appear.
