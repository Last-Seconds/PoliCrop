# Build brief 3: fitting the tool to the field, and checking it against reality

This brief is for the coding agent, and it comes after `BUILD_BRIEF_2.md`, which is built. A review on 2026-11-15 found all 160 offline tests passing and the screens following brief 2's layout. It also found two problems that come first here: the options the tool offers are often not ones a farmer would consider, and the screens still carry too much.

This brief changes three things brief 2 specified: rule H3, warning W2, and how the water measure sets a crop's need. They are in part S. Where this brief is silent, brief 2 rules.

Evidence for the ideas here is in `docs/EXPERIMENTS.md`: quick tests run on 2026-11-15. They were short scripts that nobody reviewed, and they measured satellite greenness, not yield. Treat their numbers as direction, and re-measure everything you show to a user.

## 1. What this adds, and why

After brief 2, the tool judges rotations with regional figures and a water budget nobody has checked against outcomes. This brief does four things about that:

| Part | What it does | Why |
|---|---|---|
| S. Fix and simplify | Stops the tool offering rotations no farmer would grow, and cuts what is on screen | Found in review; farmers are the audience |
| F. My fields | Lets the farmer save several fields and everything they did with each | Work is lost on leaving the page today |
| A. Validation | Measures how well the water budget tracks what actually happened, and says so in the app | The model has never been compared with an outcome |
| B. The farmer's records | Lets the farmer enter past yields, shows them against the tool's expectation, and asks about years that disagree | The farmer knows things no satellite sees |
| C. Fitting to the field | Blends the farmer's records with regional values, by a weight that grows with the number of records | A few records should nudge the result, many should lead it |
| D. This year so far | Uses the winter's actual precipitation to say what kind of year is starting | By late March much of the year's water is already known, especially in the dry west |
| E. Borrowing across crops | Carries what is known about a field from crops with records to crops without | A field that does well for wheat tends to do well for other crops in the same year |

**What this is not.** None of it predicts next year. It sharpens the odds the tool gives for each rotation on this field. Word every output as "in past years like this", never as a forecast of a coming harvest.

**Order.** Build S first, then F: every later part adds to the screens and stores things per field. Then A, B, C, D, E. From the tests, C and D help most; A matters for trust; E rests on the thinnest evidence. If time runs short, stop at a part boundary.

## 2. How to treat this brief

The same three kinds of content as brief 2:

- **Team direction:** the five parts above were discussed and wanted. The details below were designed for this brief and the team has not reviewed them one by one.
- **Provisional model:** sections 4 to 8. Implement as written, keep every constant in the settings file with its basis, and report anything that produces a result you think is wrong.
- **Engineering:** your judgment.

The basis labels `sourced`, `derived` and `assumed` mean what they do in brief 2. Add one: `measured`, for a value the validation tool computed from data. Show its sample size wherever it is shown.

**Simplicity still rules.** Part S sets the layout. After it, parts A to E add nothing to the first view of the field screen except one line in season (part D). Everything else lives in the "Adjust" panel, in a strategy's details, or on the "About this area" tab. The farmer never sees a coefficient.

## Part S: fix and simplify what exists

Do this first. It has two halves: what the tool offers, and how it shows it.

### S1. The options themselves

**What the review found.** On four of the five example fields, two of the three options were three legumes in a row, such as spring peas, lentils, chickpeas, presented as "better on water". Nobody farms that way: pulse crops share diseases and need a break of years between them [S16]. The nearby-use line on those very options read "0% of nearby cropland". And satellite greenness for 2021 showed spring legumes hit harder than winter wheat, the opposite of the verdict (`docs/EXPERIMENTS.md`, test 4).

Two causes, two fixes, and one safeguard:

| Cause | Fix |
|---|---|
| Rule H3 only stops the same legume returning. Different legumes can follow each other. | **H3 becomes:** any two legume crops are at least 3 crop years apart, counted cyclically. A three-year plan then holds one legume at most. Warning W2 is removed; H3 now covers it. Basis: a break of three or more years between pulse crops [S16]; the standard local rotation has one legume in three years [S8], [S18]. |
| The water measure compared cereals with their own normal, but legumes and spring canola with a fixed need that is below what an eastern field usually supplies. So swapping a cereal for a legume always "improved water". | **Every crop's need is set the way brief 2 set it for cereals:** the median supply that crop gets on this field in its reference position. The fixed figures (9.3, 9.7, 9.8 in) stop being needs and become a caution, below. |

- **New caution, "may be too dry here":** shown when a crop's median supply on this field is under its sourced water use plus the shortfall margin. This is where the fixed figures now do their work, mostly in the dry west.
- **New caution, "not seen nearby":** shown when under 1% (`assumed`) of nearby cropland follows the option's pattern of crop types. Among options with equal verdicts, order those seen nearby first.

What to expect after the fix: most swaps of one crop for another will read "about the same" on water. Differences will come from fallow, cover crops and rooting depth. That is honest for now. Part A measures how strongly each crop swings with the year; whether to bring that into the water measure is a decision for the team after seeing those figures. Do not do it in this brief.

The existing rotation is still never removed. Where the crop map shows it breaking the new H3, say so as gently as brief 2 requires.

### S2. What is on screen

Brief 2's structure is right and stays: the answer first, evidence closed, one Adjust panel. The problem is quantity. Measured on example field D:

| Where | Now |
|---|---|
| Phone (360 × 780), where the first rotation card starts | 564 px down |
| Phone, where the first alternative starts | 1,275 px down, on the second screen |
| A closed option card | 100 to 140 words, 600 to 700 px tall |
| The same card with "Why and details" open | About 1,340 words |
| The Adjust panel | 39 controls, 387 words, 1,930 px tall |
| The headline | Opens with the crop map breaking a rule, before the finding |

**Do not delete information. Move it down a layer.** Targets, each of which a test can check:

1. **The comparison at a glance.** Right under the header, a compact list of the current rotation and the three options: one row each, with the crops in order and the four verdicts as symbol plus word. On a phone all four rows are visible without scrolling. Tapping a row opens its card.
2. **A short top.** One line for the field: acres, the current rotation, and "fix". One headline sentence of 25 words or fewer that states the finding. Notes about the crop map's coverage, and about the current rotation breaking a rule, move into the current rotation's card.
3. **A closed card of 45 words or fewer.** The crops in order as plain chips, with no dates and no month axis; the four verdict lines; at most one caution and a count of the rest; the harvest line only when it differs from now. The current rotation's card uses the same layout as the others.
4. **Details in three layers.**
   - First, the five headings of brief 2 in 150 words or fewer altogether.
   - Second, "show the numbers" under each measure: the figures, ranges and year counts that are on the card today.
   - Third, sources as short numbered links to the data-sources page. No full citations inside a card.
   - "What we don't know" lists at most three items, those that changed a verdict, then "see all".
5. **An Adjust panel that opens with five things:** "what matters most?" as a single choice of the four measures; dry region mode; tillage; crops to rule out, as chips to tap; and one slider, "what if spring is drier?". Everything else sits under "more settings": the full order of importance, crops to keep, plan length, soil pH, yields, the temperature slider.
6. **No "Default:" lines.** A control shows its default by its state. Explanations sit behind an information symbol.
7. **Words.** Brief 2's list, plus: "kinds of crop" for crop groups; "the winter with least cover" for barest winter; "this kind of rotation" for pattern of crop types; "water estimate" for budget.
8. **Readable outdoors.** A light theme by default, dark as an option (`assumed`: a dark screen is hard to read in sunlight). Text at 16 px or larger; anything tappable at least 44 px.
9. **A page to take away.** "Print this option" gives one page: the field, the option, the four verdicts, the cautions, and the questions to check locally. It is what a farmer shows an agronomist.

Parts B, C and D add controls. Each goes under "more settings" or inside a details layer, never on the first view.

## Part F: my fields and saved work

Today a farmer who closes the page starts again. This part lets them keep fields and what they did with each.

**My fields.** On the first screen, above the map: the farmer's saved fields, each with its name, acres and current rotation. Tap one to open it. Each can be renamed or removed, with a confirmation before removing.

**Saving.**

- After choosing a field, a "save this field" control asks for a name and offers one, such as "Field near Pullman, 185 acres".
- Once saved, a field saves itself after every change. A small "saved" mark confirms it.
- The last field looked at is remembered even if it was never saved, so a reload does not lose it.

**What is kept with a field:**

| Kept | From |
|---|---|
| The outline | Brief 2 |
| Corrections to the crop history | Brief 2 |
| Every Adjust setting, including the sliders | Brief 2 |
| Options the farmer marked "keep", each with an optional note | New here |
| Harvest records and the answers about odd years | Part B |
| Whether "fit to my field" is on | Part C |

Results are not stored. They are recomputed from what is kept, so a change to the model or the data shows up the next time a field is opened.

**Where it is kept.** In the browser, as brief 2 decided: no accounts, and nothing about the farmer on the server beyond the outline it needs to compute. Say this on screen in one sentence, with its consequence: the fields live on this device and browser.

**Taking it elsewhere.**

- "Download my fields" writes one file holding every saved field and its contents.
- "Load a file" reads it back. If a field with the same outline exists, ask whether to replace it or keep both.
- Treat a loaded file as untrusted input: validate its shape, refuse what does not fit, and say why.
- Stored data and files carry a version number. Read older versions where possible; ignore what cannot be read without breaking the rest.

Not in this brief: accounts, signing in, syncing between devices, sharing a field by link, and pooling one farmer's fields to fit the model.

## 3. The model in one line

For crop `c` on a field, in crop year `t`:

```
expected(c, t) = level(c) × max(0, 1 + sensitivity(c) × index(t))
```

| Term | Meaning | Comes from |
|---|---|---|
| `index(t)` | How good or bad the year was for water, relative to a normal year | The water budget of brief 2 (section 4 below) |
| `sensitivity(c)` | How strongly the crop swings with the year; winter wheat is 1 | Measured by the validation tool, or assumed (sections 5, 8) |
| `level(c)` | The crop's typical yield on this field | Regional value blended with the farmer's records (section 7) |

With no farmer input, `level` is brief 2's expected yield and nothing in brief 2's results changes.

## 4. The year index

For a cereal in the position it actually held that year (after fallow, or after a harvested crop):

```
index(t) = (supply(t) − 2.3) / (median_supply − 2.3) − 1
```

`supply` is brief 2's, in inches. The 2.3 in threshold is from the regional wheat study [S7]. The index is the relative deviation of water-limited wheat yield from its median: −0.2 means water for a fifth less wheat than normal.

For non-cereals, use the index of a cereal in the same position that year. The crop's own response enters through its sensitivity.

### Month by month, for wheat

When rain falls matters as much as how much. The same study gives separate relationships with April, May and June counted apart [S7]. Yield `Y` is in bushels per acre; everything else is in inches.

```
Winter wheat after fallow:   Y = 6.7 SFW + 7.9 OWG + 4.4 A + 7.6 M + 12.2 J − 16.4
Spring wheat after a crop:   Y = 5.4 OWG + 1.4 A + 6.4 M + 5.7 J − 10.6
```

| Symbol | Meaning | In brief 2's budget |
|---|---|---|
| `SFW` | Water stored during the fallow, present at sowing | `fallow_store` |
| `OWG` | Water gained over winter, to late March | `winter_gain`, after the capacity limit |
| `A`, `M`, `J` | Rain in April, May, June | Daymet monthly totals |

The study reports that the first explained 83% and the second 73% of the variation in its plots, and that April rain is worth much less than May or June rain.

Use them for the wheat index:

```
index(t) = Y(t) / median(Y) − 1
```

| Case | Relationship | Basis |
|---|---|---|
| Winter wheat after fallow | The first | `sourced` |
| Spring wheat after a harvested crop | The second | `sourced` |
| Winter wheat after a harvested crop | The first, with `SFW = 0` | `assumed`: the study gives no separate relationship |
| Spring wheat after fallow | The second, with the fallow water added to `OWG` | `assumed` |
| Barley | As spring wheat | `assumed` |

Keep the simpler index above as the fallback. Brief 2's water measure keeps its own supply calculation; only part S changes it, and only in how a crop's need is set. The study's plots were mostly in drier country than the east of the county, so check that `Y` stays positive and plausible there, and report it if not.

**No heat term yet.** In the quick tests, May–June temperature tracked greenness about as closely as water did in the east. No source gives a coefficient for it. The validation tool reports how much a May–June temperature term would improve the fit; the team decides whether to add one. Do not add it on your own.

### A record is judged by its own year's weather

This is the point of the index. A high yield in a wet year does not mean a strong field, and a poor yield in 2021 does not mean a weak one. Every record the farmer enters is compared with what the weather of that year, month by month, would have led the tool to expect on that field.

Do not judge a record by a label such as "an El Niño year". The actual precipitation on the field that year already contains whatever El Niño did, and says far more. The El Niño state may be shown beside a record as context.

## 5. Part A: validation

An offline tool, run by the team, that writes `data/validation.json`. The app reads that file; it never runs the validation live.

**What it measures.** For several areas spread from the dry west to the wet east of the county:

1. Take MODIS pixels where one crop covers at least 75% of the pixel in the Cropland Data Layer that year. Needs brief 2's stage 4.
2. For each crop and year, average the highest greenness between late April and late July.
3. Compare each crop's yearly series with the year index at that area's centre.

**What it reports,** per area and per crop:

- the correlation between the index and greenness;
- the reduction in error against "use the crop's own average", leaving out one year at a time;
- the number of years and of pixels behind each figure;
- whether grouping years by El Niño, La Niña and neutral winters explains anything the year index does not. This is reported only. In the quick tests the El Niño signal was small, and the weights in part C deliberately use each year's actual water, not its El Niño label.

**If the team supplies yields.** The team may add `data/us/county_yields.csv` (year, crop, yield, unit), downloaded by hand from USDA QuickStats. When it is present, repeat the same comparison with yields, and prefer those results everywhere.

**Sensitivities.** For each crop, estimate `sensitivity(c)` as the slope of the crop's relative deviation on winter wheat's, across years.

| Data behind it | How to use it |
|---|---|
| County yields, 10 or more years | Use the estimate; basis `measured` |
| Greenness only | Use the estimate clipped to 0.5–2.0; basis `measured (greenness)`. Greenness saturates over dense wheat, which inflates other crops' ratios, so say so. |
| Fewer than 8 years, or the leave-one-out error is no better than the average | Use 1.0; basis `assumed` |

**No tuning of the water constants from greenness.** Greenness is too indirect. If county yields are present, the tool may search `e_winter` inside its sourced range of 0.60 to 0.75 and report whether leave-one-out error improves by more than 10%. Report it; do not apply it automatically.

**What the app shows,** on the "how this works" page, in plain words:

- how closely the tool's idea of a good or bad year matched what satellites saw, with the numbers;
- where it did not match. In the quick tests the match was moderate in the east (correlation 0.64) and weak in the west (0.42), and lentils did not fit at all. If your figures show the same, say the same.
- that neighbouring fields differ more in one year than the whole area differs between years, so the tool describes the year, not one field's result.

## 6. Part B: the farmer's records

**Input.** In the "Adjust" panel, under "Your field and how you farm it". Two ways in, giving the same result:

*Typing it in.* A small table of year, crop and harvest, prefilled with the years and crops from the crop history. The farmer fills in the years they know and leaves the rest empty.

*Uploading a file.* An Excel workbook (`.xlsx`) or a CSV file.

- Offer a "download a blank sheet" control that produces a file already filled with this field's years and crops, with one empty column for the harvest. Most farmers will fill that in and send it back.
- Also accept the farmer's own file if it has recognisable year, crop and harvest columns. Match column names loosely, in any order, and ask when unsure.
- Show a preview before anything is used: each row, how it was read, and any row that could not be read with the reason. Nothing is imported silently, and a bad row never blocks the good ones.
- Treat the file as untrusted input. Read values only. Reject macro-enabled workbooks (`.xlsm`) and anything above a small size limit. Never evaluate formulas.

*What a harvest figure may be.* Farmers keep records in different forms, so accept either:

- yield per acre, or
- the total amount harvested from the field. Divide it by the field's area, which the farmer can correct if they harvested only part of it.

Units: bushels or pounds for wheat and barley, pounds or hundredweight for the rest, or tons. Convert bushels by the standard weights, 60 lb for wheat and 48 lb for barley, kept in the settings file. Show the converted figure in the preview so the farmer can catch a wrong unit.

*Sanity checks.* A figure of zero or less is refused. A figure above three times the regional typical yield (`assumed`) is kept only after the farmer confirms it.

*Where the records live.* In the browser, with the field. Uploaded files are read and discarded; say so on screen. Offer a "download my records" control that saves the records and the farmer's answers about odd years, so clearing the browser does not lose them.

One field at a time. Pooling several of a farmer's fields would give more data to fit with, and is the natural next step, but it is not part of this brief.

**Expected against actual.** A simple chart: for each year with a record, the farmer's yield beside the tool's expectation. Under it, one sentence, such as "our estimate was within 8 bu/ac of your yield in 6 of 8 years".

**Years that disagree.** A year disagrees when the gap between actual and expected exceeds 25% of the level, and also exceeds 1.5 times the typical gap across the farmer's records (both `assumed`).

For each such year, ask one question: "Our estimate missed this year. Do you know why?"

| Answer | Effect |
|---|---|
| Drought or heat | Kept for fitting |
| Disease, pests or weeds | Left out of fitting |
| Hail or frost | Left out of fitting |
| Late sowing or another change in how it was farmed | Left out of fitting |
| I don't know | Kept, with half weight (`assumed`) |

Store the answers with the field and show them on the chart. This is how knowledge the data cannot hold gets into the tool.

**Without records.** If the farmer has entered none, the tool may still look for odd years by comparing the field's own greenness with the index, for years the field grew the same kind of crop. Use Sentinel-2 for any field, MODIS only where the field holds whole pixels. Ask the same question for at most three years. This is optional; build it last within part B.

## 7. Part C: fitting to the field

### The level, blended by how much the records can tell us

Not every record tells us the same amount. How many there are matters, and so does which years they come from. Each record `i` gets a weight:

```
weight(i) = reason(i) × recency(i) × normal(i)

recency(i) = 0.5 ^ ( age(i) / 10 )
normal(i)  = 1 / ( 1 + ( index(i) / 0.3 )² )
```

| Factor | Meaning | Basis |
|---|---|---|
| `reason` | 1 for an ordinary year; 0 when the farmer said hail, frost, disease or a change in farming explains it; 0.5 for "I don't know" | Part B; the 0.5 is `assumed` |
| `recency` | A record loses half its weight every 10 years of age | `assumed`. Varieties and methods change, and the county's springs have become drier and hotter over the record. |
| `normal` | Full weight for a year of normal water; half at an index of ±0.3; a fifth at ±0.6 | `assumed`. Removing the year effect from a record leans on the model, and leans hardest in extreme years. |

Then, for a crop:

```
n_eff      = sum of weight(i)
w          = n_eff / (n_eff + k)
farm_level = weighted mean of ( yield(i) / (1 + sensitivity × index(i)) )
level(c)   = w × farm_level + (1 − w) × regional_level(c)
```

- `regional_level` is brief 2's expected yield.
- `k = 5` (`assumed`): five full-weight records count as much as the regional figure.
- For a feel of the effect: five records from the last five ordinary years give `w` of about 0.45. The same five from 20 to 25 years ago give about 0.17.

There is no threshold below which records are ignored. One record moves the level a little; that is the point of the weight.

### One field constant, and a second only with more data

| Constant | Allowed range | Needs | Basis of the range |
|---|---|---|---|
| `e_winter`, the share of winter precipitation the soil keeps | 0.60 to 0.75 | 5 or more usable cereal records | `sourced` [S6] |
| A factor on the soil's water storage | 0.7 to 1.3 | 10 or more | `assumed`: soil survey values are averages for a soil type, not for a field |

Fit by weighted least squares on the farmer's cereal yields. For this fit a record's weight is `reason × recency` only. Unusual years are not discounted here: a field's response to water can only be learned from years that differed.

Then shrink the fitted value toward the default by how much the records' years differed from each other:

```
spread = sum of reason(i) × recency(i) × ( index(i) − weighted mean index )²
w_fit  = spread / ( spread + k × var_index )
value  = default + w_fit × ( fitted − default )
```

`var_index` is the variance of the index over the field's whole replay record. So records spread like a typical run of years get the same weight as in the level formula, and records that all come from similar years get almost none, however many there are.

### The tool checks itself before applying anything

1. Leave out each record in turn, fit on the rest, and estimate the one left out.
2. Compare the error with the simplest alternative: the farmer's own average yield.
3. Apply the fitted constant only if the error is at least 10% lower (`assumed`). Otherwise keep the default and tell the farmer: "your records don't show a pattern the water model can explain better than your average".

### What the farmer sees

- One control: "Fit to my field", with a line saying what changed, for example "we now assume your soil keeps a little more of the winter rain than the regional figure".
- An "undo" that returns to the regional values.
- A line about what the records cover, when it matters. If every usable record comes from the same side of normal, or `spread` is under a quarter of what a typical run of years would give, say so plainly: "your records are all from wetter-than-normal years, so we know little about how this field does when it is dry. A dry year's figure would help most."
- In every result that used a fitted value, a mark that it came from the farmer's records, as brief 2 already requires for farmer inputs.

### What fitting changes, and what it does not

It changes: the size of the benefit from fallow, how often a crop is short of water, residue amounts through the yield level, and the shortfall expressed in the farmer's own yield units.

It does not change: the rules, the comparison logic, the margins, or anything about years to come.

## 8. Part E: borrowing across crops

**Reference crops:** winter wheat, spring wheat, chickpeas and spring canola. They are the four most widely grown crops in the county and stand for four kinds: winter cereal, spring cereal, spring legume, spring oilseed.

**Similarity.** Add `data/similarity.yaml`. Each crop is described on five dimensions already in the crop table:

| Dimension | Weight |
|---|---|
| Sowing season (winter or spring) | 0.4 |
| Plant family (grass, legume, oilseed) | 0.25 |
| Root-zone class | 0.15 |
| Water need | 0.1 |
| Usual harvest month | 0.1 |

The weights are `assumed`. The order is supported by the tests: spring-sown crops were predicted far better from spring wheat than from winter wheat, whatever their family. With four reference crops the weights cannot be learned from data, so they stay editable settings.

From the dimensions, compute each crop's weights over the four references, normalised to sum to one.

**Two uses, and only these two:**

1. **Sensitivity for a crop without a measured one:** the similarity-weighted mean of the references' sensitivities.
2. **Level for a crop the farmer has no records for.** A field that beats the regional figure for one crop probably does so for similar crops:

```
field_factor(ref) = farm_level(ref) / regional_level(ref)     for references with records
factor(c)         = similarity-weighted mean of field_factor over those references
level(c)          = regional_level(c) × ( 1 + w × (factor(c) − 1) )
```

   Here `w` uses the summed record weights (part C) behind the references that contributed, each scaled by its similarity weight.

Mark every value obtained this way as borrowed, naming the crops it came from: "estimated from your spring wheat records".

Do not use similarity to replace brief 2's fallbacks for missing crop values, and do not use it to invent a crop's water need.

## 9. Part D: this year so far

Needs brief 2's weather-station provider from stage 4.

**Why.** In the dry west, stored winter water decided 59% of the year's water in the quick test, and a check at the end of March caught 7 of 8 short years. In the wet east the soil usually refills, the figure was 24%, and the check caught 4 of 8. The feature must say which kind of field it is looking at.

**Current-season precipitation.** Daymet stops at the end of the last calendar year. For the season in progress:

1. Take daily precipitation since 1 September from the nearest long-record station.
2. Scale it by the ratio of the field's Daymet average to the station's average over the same months in their common years.
3. If more than 10% of the season's days are missing at the station, say the check is unavailable.

**What it computes.**

- Stored water so far, by brief 2's budget.
- Where that stands among the same date in past years: "wetter than 11 of the last 15 winters at this date".
- Among past years whose stored water at the end of March was within 1 in of this year's (`assumed`), how often the next crop ran short: "in 9 past years that started like this one, a spring crop ran short in 6".
- The regional rule of thumb, as context: growers consider a spring cereal when recharge reaches 3 ft and at least 5 in of plant-available water is stored [S6].
- If the farmer has records from any of those look-alike years, show them: "you recorded 38 and 44 bu/ac in two of them". Here a record matters because its year resembles this one, whatever its age.

**Where it applies.** If stored water reached the soil's capacity in two thirds or more of past years, do not give odds. Say instead: "your soil usually refills over winter; spring rain decides the year here".

**Where it shows.** One line at the top of the field screen from 1 January to 31 May (`assumed`), opening a short panel. Outside those dates it is hidden. It always carries its date.

**How it connects to the rotation.** If the current rotation's next slot is a spring crop or fallow, the panel names the alternatives in the same role and how each fared in past years that started alike. It does not tell the farmer what to plant.

**El Niño, as information only.** On the "About this area" tab:

- The current state from NOAA's index: `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt`, columns season, year, total, anomaly. An anomaly of +0.5 or more is El Niño; −0.5 or less is La Niña.
- What it has meant here, computed from the field's own record: average September–March precipitation in El Niño winters against the others.
- A plain statement that the effect is small. In the quick test El Niño winters were about 12% drier and the index explained about 3% of the year's water.

It never changes scoring or the odds above.

## 10. Example records for demonstrations

The team has no real farmer's records. Fabricated records must never look real.

- For automated tests, generate records from the model plus noise.
- In the app, a "try with example records" control may load such a set. While it is loaded, the screen says "example data, not a real farm" on the chart and beside every value fitted from it.
- If the team supplies real records or county yields, use those and say what they are.

## 11. Done means

Part S:

- On all five example fields, no option has two legume crops within three years. Report the options before and after.
- Swapping one spring crop for another no longer changes the water verdict by itself.
- On a 360 × 780 screen, after choosing a field, the current rotation and all three options are visible as rows without scrolling.
- A closed card has 45 words or fewer; the first layer of details has 150 or fewer; the Adjust panel opens with five controls or groups.
- Nothing that was on screen before is gone; each item can still be reached.

Part F:

- Save two fields, change settings in each, reload the page: both are there with their settings.
- Download, clear the browser's storage, load the file: the same fields give the same results.
- A damaged file is refused with a reason and changes nothing.

Parts A to E:

- With no records and outside the season window, every result is identical to brief 2's.
- The blend weight follows `n_eff / (n_eff + k)` exactly. One extreme record cannot move a level by more than its share.
- A year answered "hail or frost" is excluded from fitting and still shown on the chart.
- The same records entered by typing and by uploading the downloaded sheet give identical results.
- A file with one unreadable row imports the other rows and shows the bad one with its reason. A macro-enabled workbook is refused.
- A total harvest and the matching per-acre yield give the same record.
- Ageing a set of records by 10 years halves their combined weight.
- Records that all come from similar years move a fitted constant far less than the same number spread over wet and dry years, and the coverage line appears.
- Fitting is refused when the self-check fails, and the farmer is told why.
- Undo restores the regional values.
- Replayed over past years for a dry-west demo field, the end-of-March check flags most short years. For an eastern demo field it gives the "spring rain decides" message.
- The validation page states its numbers with sample sizes, including the weak ones.
- Every borrowed value names the crops it was borrowed from.
- No output is worded as a forecast.
- Beyond part S's layout, the first view of the field screen has gained at most one line.

## 12. Report back

- Which parts are complete.
- For part S: the options on each example field before and after the two fixes, and the screen measurements against the targets.
- The validation figures per area and crop, and how they compare with `docs/EXPERIMENTS.md`.
- Whether county yields were available, and what changed when they were used.
- Any case where fitting made a result worse or stranger, with the records that caused it.
- Every `assumed` constant you found too loose or too tight, with an example.
