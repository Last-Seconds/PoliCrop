# Addendum to build brief 3: corrected crop values

Written 2026-11-15, after work on brief 3 had started. Newly obtained sources close several gaps in the crop table and show that a few values assumed in briefs 2 and 3 were off. The evidence is in `docs/CROP_TABLE_ADDITIONS.md`; source tags `[S27]` to `[S31]` are listed there.

**How to use this.** Finish the step you are on, then apply the items below at the next natural stopping point. Nothing here changes the structure of brief 3. If an item conflicts with work already finished and tested, do not rework it: leave it and say so in your report.

Items are in order of value. 1 to 4 are data corrections. 5 and 6 feed parts D and S. 7 is a model change and is optional.

## 1. Expected yields by rainfall zone

Brief 2 gave regional yields only for fields with 18 in of yearly precipitation or more, and fell back on a water-implied figure below that. Sourced yields now exist for three zones [S27].

| Zone | Field's mean yearly precipitation | Basis of the boundary |
|---|---|---|
| Annual Crop | 18 in or more | `sourced` [S18] |
| Transition | 15 to 18 in | `assumed`, from published descriptions of the zones |
| Grain-Fallow | under 15 in | `assumed`, same |

| Crop | Annual Crop | Transition | Grain-Fallow |
|---|---|---|---|
| Winter wheat | 80 bu/ac | 78 bu/ac after fallow | 45 bu/ac after fallow |
| Spring wheat | 58 bu/ac | 50 bu/ac | 40 bu/ac |
| Spring barley | 3,000 lb/ac | 3,000 lb/ac | 1,900 lb/ac |
| Spring peas | 1,700 lb/ac | 1,600 lb/ac | – |
| Lentils | 1,100 lb/ac | 1,200 lb/ac | – |
| Chickpeas | 1,200 lb/ac | – | – |
| Spring canola | 1,500 lb/ac | 1,500 lb/ac | 500 lb/ac |
| Winter canola | 3,000 lb/ac | – | 1,500 lb/ac |
| Winter peas | 2,000 lb/ac | – | 1,500 lb/ac |

- From Tables 5-12, 5-13, 5-14 and 5-A2 of [S27]. Basis `sourced`.
- Where a cell is empty, keep brief 2's fallback: for cereals the yield implied by the field's median water; for other crops the nearest wetter zone's figure, tagged as such.
- Winter wheat sown after a harvested crop in the Transition zone: the source table gives a second, lower figure of 30 to 40 bu/ac, which appears to be for that case. Use 35 bu/ac and mark it `assumed`, since the table does not label it.
- The farmer's own yields still override all of this.
- These yields feed residue and the nitrogen tiers only. The water measure does not use them.

## 2. Nitrogen credits

| Crop | Credit to the next crop | Basis |
|---|---|---|
| Chickpeas | 15 lb N/ac when the chickpea yield is above 2,000 lb/ac; 10 lb N/ac below that | First figure `sourced` [S27, Table 5-9]; second `assumed` |
| Winter peas | 30 lb N/ac when the yield is above 3,750 lb/ac; otherwise the spring pea tiers | First `sourced` [S27, Table 5-9]; second `assumed`, as before |

This replaces the general "10 to 20" range for chickpeas.

## 3. Winter pea cold limit (warning W6)

Brief 2 used −6 °F, from one trial. Winter hardiness depends on the variety [S27, Table 5-4]: 'Lynx' −5 °F, 'Windham' 0 °F, 'Whistler' and 'Specter' +5 °F, Austrian winter pea +10 °F.

- Set the W6 threshold to 0 °F. 'Windham' is the variety in the regional trials.
- Keep it a named parameter. In the warning's detail, say that varieties range from −5 °F to +10 °F.
- The warning will fire more often than before. That is the correction.

## 4. Canola water, for the "may be too dry here" caution

Brief 2 assumed spring canola uses as much water as chickpeas (9.8 in). The handbook groups it with spring cereals, and winter canola with winter wheat [S27, Table 5-A3].

For the caution that part S1 introduces, replace the fixed 9.8 in for canola with a figure tied to yield:

```
canola water use = expected yield ÷ 105 lb of seed per acre per inch
```

- 105 is the higher of two measured efficiencies, 65 and 105 lb per acre per inch, from winter canola trials said to be "similar to spring canola in the area" [S28]. Basis `derived`.
- Show the range by also dividing by 65.
- Use it for both spring and winter canola.

## 5. Stored water needed before planting (part D)

Part D quotes one rule of thumb. A fuller, sourced table exists [S27, Table 5-11, from Lutcher et al. 2013]: the minimum plant-available soil water, in inches.

| Field's mean yearly precipitation | Autumn planting | Spring planting |
|---|---|---|
| Under 10 in | 3.5 | 4.5 |
| 10 to 12 | 3.0 | 4.0 |
| 12 to 14 | 2.5 | 3.5 |
| 14 to 16 | 2.0 | 3.0 |
| 16 to 18 | 1.5 | 2.5 |
| Over 18 | 1.0 | 2.0 |

- In the "this year so far" panel, show the row for the field's precipitation beside the stored-water estimate, in place of the single rule of thumb.
- Word it as the source does: a guideline only.

## 6. Rotations in real use, as a check on part S1

The handbook lists the rotations farmers use and the alternatives being tried, by zone [S27, Table 5-2]. Add a test that every one of these passes the hard rules, using the crops this tool knows:

| Zone | Sequences |
|---|---|
| Annual Crop | Winter wheat, spring wheat, pea. The same with barley for spring wheat, and with lentil or chickpea for pea. Winter wheat, spring wheat, winter wheat, legume. Winter wheat, spring wheat, spring canola. Winter wheat, spring wheat, winter pea. Winter wheat, spring canola, legume. |
| Transition | Winter wheat, spring wheat, fallow. Winter wheat, fallow. Winter wheat, fallow, winter canola. Winter wheat, fallow, spring canola. Winter wheat, spring barley, fallow. |
| Grain-Fallow | Winter wheat, fallow. Winter wheat, fallow, winter pea. Winter wheat, fallow, winter canola. |

- If any fails a hard rule, do not relax the rule to make it pass. Report which one and why.
- None has two legumes in a row, which supports the new H3.
- After the part S1 fixes, check that the traditional sequence for each example field's zone is among the candidates the generator considers, when its crops are grown nearby.

## 7. Optional: water left behind by legumes

Brief 2 starts every crop after a harvested crop with no stored water, and listed the water legumes leave behind as a known gap. The handbook gives a figure: peas, lentils and chickpeas "generally use 15–35% less water than cereals or oilseeds, leaving more water in the profile for subsequent crops" [S27].

Only if part S1's water changes are still open, and it can be done without disturbing finished work:

```
previous slot was a legume:
    carry  = c × ( supply a cereal would have had in that slot, that year )
    stored = min( capacity, carry + winter_gain )
```

- `c` from 0.15 to 0.35, central 0.25. Basis `derived` [S27].
- Remove the matching line from the known gaps.
- Otherwise leave the model as it is, keep the gap listed, and add the handbook's sentence to it.

## Not changed

Canola residue needs no change: the handbook computes it the same way brief 2 does. Winter canola's water use being grouped with winter wheat confirms brief 2's assumption; mark it `sourced` [S27].

## Report

Add to your brief 3 report: which of items 1 to 7 you applied, which you left and why, and whether any sequence in item 6 failed a rule.
