# Crop table additions (version 4, 2026-11-15)

This file adds to `docs/CROP_TABLE_DRAFT.md`, which is unchanged. Source tags below S27 refer to that file's list.

These values come from documents that could not be reached when the crop table was first researched. They were searched by keyword for the open gaps, not read in full. Tables quoted below were read from extracted text, not checked against page images. The files themselves are outside this repository, in the team's `research/sources_raw/` folder.

The most useful is Chapter 5 of the regional handbook [S27]. It divides the region into three zones by how much land is fallowed: Annual Crop (the wet east), Transition, and Grain-Fallow (the dry west). Whitman County spans all three.

### Gaps now closed

| Gap | Value | Source |
|---|---|---|
| Chickpea nitrogen credit | 15 lb N/ac to the next wheat crop, at chickpea yields above 2,000 lb/ac | [S27] Table 5-9 |
| Winter pea and winter lentil nitrogen credit | Winter pea 30 lb N/ac above 3,750 lb/ac; winter lentil 20 above 2,500 | [S27] Table 5-9 |
| Canola residue | Spring canola: 5,142 lb/ac at a 2,000 lb yield; 3,850 at 1,500; 1,285 at 500. Winter canola: 7,700 at 3,000. | [S27] Table 5-A2 (computed there from seed as 20–35% of biomass, the same method this draft used) |
| Winter canola water use | 12 in at Okanogan (795 lb/ac yield) and 22 in at Pomeroy (2,185 lb/ac); 15–20% of it in autumn. 65 and 105 lb of seed per acre per inch of water, "similar to spring canola in the area". | [S28] |
| Typical yields outside the wet zone | Table below | [S27] Tables 5-12 to 5-14, 5-A2 |
| Relative water use of crops | Highest: winter wheat, winter triticale, winter canola. Then chickpea. Then spring cereals and spring canola. Then lentil. Lowest: pea. | [S27] Table 5-A3 |

Typical yields by zone [S27]:

| Crop | Annual Crop | Transition | Grain-Fallow |
|---|---|---|---|
| Soft white winter wheat | 80 bu/ac (range 80–120) | 78–86 after fallow | 45–50 |
| Soft white spring wheat | 58 | 50 | – |
| Spring barley | 1.5 tons/ac | 1.5 | – |
| Spring canola | 1,500 lb/ac | 1,500 | 500 (Table 5-A2) |
| Winter canola | 3,000 lb/ac (Table 5-A2) | – | 1,500 |
| Peas | 1,700 | 1,600 (Table 5-A2) | – |
| Lentils | 1,100 | 1,200 (Table 5-A2) | – |
| Chickpeas | 1,200 (2,000 in Table 5-A2) | – | – |

The two tables in the chapter do not always agree, as the chickpea row shows.

### Values in this draft that should change

| Item | Was | Should be | Source |
|---|---|---|---|
| Spring canola water use | Assumed equal to chickpeas (9.8 in) | Grouped with spring cereals, below chickpeas | [S27] Table 5-A3 |
| Winter canola water use | Assumed equal to winter wheat | Confirmed: same group as winter wheat | [S27] Table 5-A3 |
| Winter canola yield | Assumed 3,000 lb/ac everywhere | 3,000 in the wet zone, 1,500 in the dry zone | [S27] |
| Chickpea nitrogen credit | General pulse figure, 10–20 lb | 15 lb at high yield | [S27] |
| Winter pea cold limit | −6 °F, from one trial | Depends on variety: 'Lynx' −5 °F, 'Windham' 0 °F, 'Whistler' and 'Specter' +5 °F, Austrian +10 °F | [S27] Table 5-4 |
| Water left by legumes | Ignored | Peas, lentils and chickpeas "generally use 15–35% less water than cereals or oilseeds, leaving more water in the profile for subsequent crops" | [S27] |

### New facts useful to the design

- **Rotations in real use, by zone** [S27, Table 5-2]:

  | Zone | Traditional | Alternatives named |
  |---|---|---|
  | Annual Crop | Winter wheat – spring wheat or barley – pea, lentil or chickpea | Winter wheat – spring wheat – winter wheat – legume; winter wheat – spring wheat – spring canola; winter wheat – spring wheat – winter pea or winter lentil; winter wheat – spring canola – legume |
  | Transition | Winter wheat – spring wheat – fallow; winter wheat – fallow | Winter wheat – spring wheat – winter pea or lentil; winter wheat – fallow – winter canola; winter wheat – fallow – spring canola; winter wheat – spring wheat – spring canola; winter wheat – spring barley – fallow |
  | Grain-Fallow | Winter wheat – fallow | Winter wheat – fallow – winter pea; winter wheat – fallow – winter canola |

  None has two legumes in a row. One has two broadleaf crops in a row (canola then a legume), which some growers are trying for weed control.

- **Minimum stored water before planting** [S27, Table 5-11, from Lutcher et al. 2013], in inches of plant-available water:

  | Average annual precipitation | Autumn planting | Spring planting |
  |---|---|---|
  | Under 10 in | 3.5 | 4.5 |
  | 10 to 12 | 3.0 | 4.0 |
  | 12 to 14 | 2.5 | 3.5 |
  | 14 to 16 | 2.0 | 3.0 |
  | 16 to 18 | 1.5 | 2.5 |
  | Over 18 | 1.0 | 2.0 |

  The chapter also recommends using the wheat–water equations of [S7] with real-time moisture to choose between fallow and a spring crop.

- **Soil water holding capacity by zone:** 2.0–2.4 in per foot (Annual Crop), 1.8–2.2 (Transition), 1.6–2.0 (Grain-Fallow) [S27, Table 5-A2]. Over five feet that is 8 to 12 in, in line with the soil database values used so far.
- **Winter canola "is less suited to the Annual Crop" zone,** because the soil is too dry after harvest to sow it in mid-August [S27]. This confirms the "only after fallow" rule.
- **Wheat after canola:** gains of 30% and 39% reported by growers and on-farm trials; no gain in a five-year trial near Reardan; and "not yet documented from long-term research sites" [S27]. Mixed, like the legume effect.
- **Nitrogen fixed by pulses** (Swift Current, Saskatchewan): field pea 48.5 lb/ac, chickpea 46, lentil 44 [S30]. This is nitrogen taken from the air by the crop, not the credit to the next crop. The three are close, which supports treating chickpeas like the other two.
- **Whitman County growers' own figures** [S29]: a farm near Colfax (18–19 in of rain) runs winter wheat – spring barley – spring canola and averaged 1,900 lb/ac of canola over ten years.
- **Water before any grain:** "at least 4 inches and often closer to 5" for wheat, barley and canola [S31, Alberta]. Indicative only; the regional figure for wheat is 2.3 in [S7].

### Still open

1. Barley water use without irrigation, as a figure. Its rank is now sourced: with the spring cereals.
2. Chickpea residue.
3. Winter canola harvest month.
4. Whitman County yields from USDA statistics.
5. The claim that USDA stopped weekly crop progress for Washington in 2026: I searched the saved report and did not find it.

### Sources added

- [S27] Kirby, Pan, Huggins, Painter and Bista, "Rotational Diversification and Intensification", Chapter 5 of *Advances in Dryland Farming in the Inland Pacific Northwest*, WSU Extension EM108, 2017. `research/sources_raw/em108_advances_dryland_farming/em108-ch5.pdf`
- [S28] Reese, Pan, Young and Schillinger, "Winter Canola Water and Nitrogen Use in Low Rainfall Areas of Eastern Washington", WSU 2016 Field Day Abstracts, and the related poster. `research/sources_raw/wsu_winter_canola_water_nitrogen_use_low_rainfall.pdf`, `research/sources_raw/wsu_Reese_poster11_winter_canola_water_use.pdf`
- [S29] Sowers et al., *Oilseed Production Case Studies in the Eastern Washington High Rainfall Zone*, WSU Extension EM037E. `research/sources_raw/wsu_EM037E_oilseed_case_studies_high_rainfall.pdf`
- [S30] "Nitrogen fixation varies between and within pulse crops", Canadian Agronomist, 2018, reporting Gan et al. 2017. `research/sources_raw/canadianagronomist_nitrogen-fixation-varies.pdf`
- [S31] Alberta Agriculture, *Crop Water Use and Requirements*, Agdex 100/561-1, 2011. `research/sources_raw/alberta_agrifacts_crop_water_use_2011.pdf`
