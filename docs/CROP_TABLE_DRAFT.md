# Crop table draft: Whitman County, Washington

Version 3, researched 2026-11-15 for the Field Shift crop table. This is a draft for the team to check, not vetted agronomy. Every value has a source; values not found are listed as gaps, not guessed.

Confidence labels:

- **Sourced**: the figure is stated in the cited document.
- **Verified**: sourced, and I checked the original page image, not only extracted text.
- **Derived**: calculated from a sourced figure; the calculation is shown.
- **General**: standard botany, not specific to the region.
- **Gap**: not found.

Location labels matter, because conditions differ across the region:

- **Whitman County**: measured in the county (Pullman).
- **Annual-cropping region**: the wetter part of eastern Washington, northern Idaho and north-eastern Oregon (about 18 inches of rain or more), which includes eastern Whitman County.
- **Elsewhere**: named in the row.

## 1. Which crops (USDA Cropland Data Layer, Whitman County, 2025)

| Crop | Acres | Share of these crops |
|---|---|---|
| Winter wheat | 370,700 | 41% |
| Spring wheat | 160,100 | 18% |
| Fallow / idle | 138,900 | 16% |
| Chickpeas | 104,500 | 12% |
| Lentils | 37,200 | 4% |
| Canola | 32,300 | 4% |
| Barley | 24,900 | 3% |
| Alfalfa | 13,600 | 1.5% |
| Peas | 13,000 | 1.5% |

Source: CropScape `GetCDLStat`, FIPS 53075, year 2025 (queried 2026-11-15).

## 2. Seasons

| Crop | Sown | Harvested | Confidence and location | Source |
|---|---|---|---|---|
| Winter wheat | Aug 30 – Oct 20 (mostly Sep 1 – Oct 10) | Jul 15 – Aug 30 (mostly Jul 25 – Aug 20) | Verified; statewide, 2010 edition | [S24] |
| Winter wheat | First week of October | Jul 25–26 | Sourced; Whitman County, 2023–2024 trial | [S15] |
| Spring wheat | Mar 15 – May 10 (mostly Mar 25 – Apr 30) | Jul 25 – Sep 5 (mostly Aug 1 – Aug 30) | Verified; statewide, 2010 edition | [S24] |
| Spring barley | Mar 20 – May 10 (mostly Mar 30 – May 5) | Jul 25 – Sep 5 (mostly Aug 1 – Aug 30) | Verified; statewide, 2010 edition | [S24] |
| Spring peas | Mar 10 – May 20 (mostly Apr 10 – May 15) | Jul 10 – Aug 30 (mostly Jul 20 – Aug 20) | Verified; statewide, 2010 edition | [S24] |
| Spring peas | April | Aug 18 (2022, wet year); Jul 28 (2023, drought year) | Sourced; Whitman County trial | [S15] |
| Lentils | Early spring; planting after April lowers yield and quality | August; maturity about 100 days after emergence | Sourced; Idaho and Washington | [S2] |
| Chickpeas | April | Aug 18 (2022); Jul 28 (2023) | Sourced; Whitman County trial | [S15] |
| Chickpeas | Within a week or two of the best spring wheat date; large-seeded types mature in 110–120 days | | Sourced; Montana | [S16] |
| Winter peas | Late August or early September | Early to mid July | Sourced; Ritzville (drier than Whitman County) | [S4] |
| Spring canola | April | August | Sourced; eastern Washington, over-20-inch rainfall zone | [S17] |
| Spring canola | April | Aug 18 (2022); Jul 28 (2023) | Sourced; Whitman County trial | [S15] |
| Spring canola | Apr 20 (2016) and May 9 (2017) at Pullman; a comparable trial at Walla Walla was harvested Aug 14 | | Sourced; Whitman County trials | [S26] |
| Spring canola | March or April, depending on soil moisture | | Sourced; inland Pacific Northwest | [S25] |
| Winter canola | Early August to mid September, into fallow; best yields from Aug 14–24 | Harvest month **gap** (crop season is given as Sep 1 – Aug 31) | Sourced; Pacific Northwest | [S5] |
| Winter canola | August in the fallow region of eastern Washington; plants must reach 8–12 inches across before winter to survive | | Sourced | [S25] |
| Fallow | Runs about 13 months between crops | | Sourced | [S6] |

Spring sowing dates in practice depend on when the soil is dry enough to drive on [S15].

The statewide dates above are from the 2010 edition of the USDA handbook [S24], the newest one published. The 1997 edition [S1] differs by one to three weeks in places. The 2010 Washington table has no rows for lentils, chickpeas or canola.

## 3. Plant type and season class (for the diversity criterion)

| Crop | Type | Season |
|---|---|---|
| Winter wheat | Grass | Winter |
| Spring wheat, spring barley | Grass | Spring |
| Spring peas, lentils, chickpeas | Broadleaf, legume | Spring |
| Winter peas | Broadleaf, legume | Winter |
| Winter canola | Broadleaf | Winter |
| Spring canola | Broadleaf | Spring |

Confidence: General.

Local relevance:

- The main grass weeds (downy brome, jointed goatgrass) are winter annuals with the same life cycle as winter wheat [S4].
- Broadleaf crops allow selective herbicides against grass weeds [S3].
- The standard rotation in the annual-cropping region is winter wheat, then a spring grain, then a "break" crop that is not wheat or barley, such as peas or canola. Winter wheat "cannot be profitably produced without some type of crop rotation" [S18].

## 4. Water

| Crop | Figure | Confidence and location | Source |
|---|---|---|---|
| Wheat (winter and spring) | 2.3 inches of available water before any grain, then about 5.8 bushels per acre per further inch. "Available water" = soil water stored over winter + spring rain. | Sourced; 175 plots across eastern Washington, 1993–2005, mostly low and intermediate rainfall sites | [S7] |
| Wheat, as a need | 58 bu/ac needs about 12 in; 80 bu/ac needs about 16 in | Derived: 2.3 + yield ÷ 5.8, using the regional yields in section 7 | [S7], [S18] |
| Spring peas | 9.3 inches from planting to maturity | Sourced; Pendleton, Oregon, 1983–84, wetter-than-average years | [S3] |
| Lentils | 9.7 inches | Same | [S3] |
| Chickpeas | 9.8 inches | Same | [S3] |
| Peas vs chickpeas vs canola | Peas used the least water and stopped earliest; chickpeas used the most in the top 70 cm; canola drew water from deeper in the soil. | Sourced; Whitman County, 2022–2023 | [S15] |
| Same trial, soil water drawn down in the top 70 cm during the dry part of the season | Peas about 3.1–3.2 in; canola about 3.4–3.9 in; chickpeas about 3.8–4.6 in | Derived: the paper's daily rate × the days until uptake levelled off (for example chickpeas 2022: 3.1 mm/day × 37.6 days = 117 mm). This is soil water only, not total water use: it leaves out rain and the first 45–65 days after sowing. | [S15] |
| Palouse soil water | Annual precipitation above 400 mm (16 in); soils hold about 167 mm of water per metre of depth (2 in per foot). The authors say conserving soil moisture "is not a prominent concern" there because winter rain refills the soil each year, unlike areas under 250 mm (10 in). | Sourced; Whitman County | [S15] |
| Winter peas | About 1.2 inches (30 mm) less soil water than winter wheat | Sourced; Ritzville | [S4] |
| Chickpeas, climate fit | Does well with 6–10 inches of growing-season precipitation; does not yield well above 30 inches a year | Sourced; Montana and Oregon | [S16], [S3] |
| Canola, rooting depth | 65 inches (winter), 46 inches (spring) | Sourced; literature value quoted by WSU | [S19] |
| Canola, water use in inches | **Gap**. In a low-rainfall trial, water use and yield of oilseeds after fallow were lower than those of winter cereals. | Sourced (qualitative, abstract only); inland Pacific Northwest sites with under 350 mm (about 14 inches) of rain | [S20] |
| Barley, dryland water use | **Gap**. Irrigated spring barley in southern Idaho uses 15–19 inches a season, which is not comparable. | | [S21] |
| Fallow | Stores about 30% of the precipitation over the 13-month fallow. 60–75% of winter precipitation after harvest is stored until April. | Sourced | [S6] |
| Spring cereal rule of thumb | Growers consider a spring cereal when winter recharge reaches 3 feet deep and at least 5 inches of plant-available water is stored | Sourced | [S6] |

Chickpea rooting depth is disputed: "up to 4 feet" [S3] against "no more than 30 inches" [S16].

## 5. Residue (for winter ground cover)

| Crop | Residue left | Confidence | Source |
|---|---|---|---|
| Winter wheat | 3,000–5,000 lb/ac on ridgetops and upper slopes; 6,000–11,000 lb/ac on lower slopes and bottomland | Verified; high-precipitation zone | [S8] |
| Spring wheat, spring barley | 50–70% of the winter crops | Verified | [S8] |
| Peas, lentils | 1,500–2,000 lb/ac at harvest; only 500–1,500 lb/ac left by seeding time, because it shatters and decays quickly | Verified | [S8] |
| Canola | Residue is a large share of the plant: seed is only 20–35% of above-ground dry matter. No lb/ac figure. | Sourced | [S19] |
| Chickpeas | **Gap** | | |

Residue can also be estimated from grain yield (both in kg/ha): residue = slope × yield + intercept [S9].

| Crop | Slope | Intercept | Fit (r²) |
|---|---|---|---|
| Winter wheat | 1.1274 | 1,175 | 0.69 |
| Spring wheat | 0.8613 | 2,068 | 0.31 |
| Spring barley | 0.7013 | 1,303 | 0.55 |
| Peas | 0.7181 | 941 | 0.29 |
| Lentils | 0.4684 | 1,844 | 0.09 (very weak) |
| Austrian winter peas | 1.3427 | 1,327 | 0.63 |

Related findings:

- Cereal residue lasts long enough to protect the soil through a following legume crop and into the next winter wheat [S6].
- Erosion is worst in a two-year wheat–legume rotation, after the legume. Three-year rotations erode less, but still above acceptable levels [S6].

## 6. Nitrogen

| Item | Figure | Confidence and location | Source |
|---|---|---|---|
| Winter wheat need | 2.4 to 3.1 lb N per bushel of expected yield, rising with rainfall (2.5 at 18–21 in; 2.7 at 21–24 in) | Sourced; northern Idaho | [S10] |
| Wheat uptake | Soft white winter wheat takes up 2.2 lb N per 100 lb of grain | Sourced | [S22] |
| Canola uptake | 5.8 lb N per 100 lb of seed, of which 2.4 lb returns to the soil in residue | Sourced | [S22] |
| Canola need | 6–12 lb N supply per 100 lb of seed in Washington (lower at higher yields); 100 lb N/ac applied in the over-20-inch budget | Sourced | [S22], [S17] |
| Credit after peas | 10 lb N/ac (pea yield under 1,500 lb/ac), 15 (1,500–2,500), 20 (over 2,500) | Sourced; eastern Washington | [S11] |
| Credit after lentils | 10 lb N/ac (lentil yield over 1,000 lb/ac) | Sourced; eastern Washington | [S11] |
| Credit after any pulse crop | About 10–20 lb N/ac depending on yield | Sourced; Montana | [S23] |
| Credit after chickpeas | No chickpea-specific figure. Chickpeas are listed with the legumes that give a credit; use the general pulse range. | **Gap** for a specific number | [S10], [S23] |
| Credit after alfalfa | 50 lb N/ac | Sourced | [S11] |
| Penalty after a cereal | Add 15 lb N/ac per ton of straw left, up to 50 lb | Sourced; northern Idaho | [S10] |
| Wheat after a legume | Winter wheat yields 19% more after peas, and 15% more after spring canola | Sourced; Palouse research cited in the regional baseline | [S18] |
| Wheat after peas, chickpeas or canola | No difference in winter wheat yield between the three | Sourced; Whitman County, 2023–2024 | [S15] |
| Winter pea trial | Soil nitrate 25–41% higher after winter peas than after winter wheat | Sourced; Ritzville | [S4] |

## 7. Yields, prices and returns (for the income notes)

Typical figures for the annual-cropping region, 2011–2015 averages [S18]:

| Crop | Yield per acre | Price | Return over total cost per acre |
|---|---|---|---|
| Soft white winter wheat | 80 bu | $6.44/bu | +$64 |
| Soft white spring wheat | 58 bu | $6.44/bu | +$27 |
| Hard red spring wheat | 58 bu | $8.41/bu | +$60 |
| Chickpeas | 1,200 lb | $0.34/lb | +$63 |
| Lentils | 1,100 lb | $0.30/lb | +$18 |
| Peas | 1,700 lb | $0.19/lb | −$7 |
| Spring barley | 1.5 tons | $182/ton | −$24 |
| Spring canola | 1,500 lb | $0.21/lb | −$35 |

Notes:

- The most profitable rotation was soft white winter wheat, hard red spring wheat, chickpeas: $62 per acre per year [S18].
- Returns swing with prices. In 2016 the only profitable crops were peas ($50/ac), chickpeas ($40/ac) and lentils ($11/ac); winter wheat lost money [S18].
- Crops that lose money in their own year can still raise the rotation's return, through weed control and higher wheat yields afterwards [S18].
- The lentil figure is inconsistent inside the source: the table gives $18, the text says $29.
- Older spring canola yields by rainfall zone (2006): 1,000 lb/ac at 12–15 in, 1,300 at 15–20 in, 1,600 above 20 in [S17].
- These are 2011–2015 prices and costs. They show relative standing, not current income.

## 8. Acid soil

Critical pH below which a crop loses significant productivity [S13, Table 1, verified]:

| Crop | Critical pH |
|---|---|
| Alfalfa | 6.0 |
| Lentils | 5.7 |
| Spring peas | 5.5 |
| Canola | 5.5 |
| Wheat | 5.2–5.4 |
| Spring barley | 5.2 |
| Chickpeas | Unknown (the source says so); reported to do better than other legumes |

Related findings:

- Soil pH below 5.0 has been measured throughout the Palouse [S12].
- Chickpeas tolerate acid soil better than the other legumes, because their nitrogen-fixing bacteria cope with low pH [S13].
- Canola is sensitive to manganese toxicity on some acid soils [S13].
- An older source gives different "critically low" levels: 5.3 for peas and 5.6 for wheat [S8]. The two disagree for wheat.
- The source warns that no absolute cutoff exists; response depends on other soil properties and on the variety [S13].

## 9. Rotation limits (candidates for filter rules)

| Limit | Source |
|---|---|
| Chickpeas only once in 3 to 5 years on the same field (Ascochyta blight); 4 to 5 years between chickpea crops against Fusarium wilt | [S3] |
| A break of three or more years between pulse crops lets diseased residue disappear | [S16] |
| It may be hard to follow chickpeas with winter wheat, because chickpeas mature late; a spring crop may fit better | [S16], Montana |
| Winter canola rarely fits after a harvested crop without irrigation: the soil stays too dry until October, too late for the plants to grow large enough to survive winter. It is sown into fallow. | [S25] |
| Spring canola is not commonly grown where rainfall is under 12 inches; it yields half to two thirds of winter canola there | [S25] |
| In Whitman County, winter wheat was sown in early October after chickpeas harvested in late July to mid August, with no yield penalty | [S15] |
| Herbicide carryover: imazethapyr ("Pursuit"), used on legumes, has damaged canola up to six years later | [S5] |
| Herbicide carryover: after chlorsulfuron ("Glean"), used on cereals, the label restricts lentils for 36 months and peas for 24 | [S23] |
| Repeated winter wheat favours winter-annual grass weeds | [S4] |
| Peas are not planted on poorly drained soils; they die after 24–48 hours of waterlogging | [S2] |
| Winter peas were killed at −21 °C with no snow cover in one trial year | [S4] |
| Chickpeas are stressed above 98 °F (37 °C) during early flowering and pod development | [S16] |

Rotations farmers actually used in the high-precipitation zone (1990s) [S8, verified]:

- Three-year: winter wheat – spring cereal – pea or lentil; winter wheat – spring cereal – spring canola; winter wheat – fallow – winter rapeseed.
- Two-year: winter wheat – pea or lentil.
- Continuous cereal: winter wheat – winter wheat; winter wheat – spring cereal.

## 10. Cover crops: an important caution

- Across 38 studies in temperate drylands, yields of the following crop fell by 11% on average after cover crops. The authors estimate about 27 inches of annual precipitation is needed to avoid a yield loss [S14].
- In a University of Idaho study in the Palouse, a forage cover crop left 2–4 inches less soil water than fallow; modelling suggested lower wheat yields in about half of years [S14].
- The effect is worst where most rain falls in winter, which describes this region [S14].

Implication: filling a bare period with a cover crop is not free here. It spends water the next crop needs. The water criterion has to judge it.

This caution is strongest in the drier west of the county. In the wetter east, the Pullman trial's authors describe soil water as refilled every winter [S15], so the cost of a cover crop there is likely smaller. The sources do not give a figure for where the line falls inside the county.

## 11. Remaining gaps

1. Canola water use in inches (the WSU studies exist, by Reese, Pan and Schillinger, but their files could not be downloaded).
2. Barley dryland water use.
3. Chickpea residue amount, and a chickpea-specific nitrogen credit.
4. Winter canola harvest month.
5. Whitman County yields from USDA statistics (the QuickStats service needs an access key). Regional baseline yields are in section 7.
6. Official sowing and harvest dates for lentils, chickpeas and canola in Washington: the USDA handbook [S24] does not list them.

## 12. What changed from version 1

- Checked three tables against the original page images: the dates table [S1], the residue figures [S8] and the critical pH table [S13].
- Added measurements from a 2022–2024 trial at Pullman, inside Whitman County [S15].
- Filled in spring canola dates, canola nitrogen, critical pH per crop, and regional yields, prices and returns.
- Added herbicide carryover limits and the rotations in actual use.

## 13. What changed from version 2 to version 3

- Replaced the 1997 statewide dates with the 2010 edition [S24].
- Added Pullman spring canola sowing dates [S26] and the limits on where winter and spring canola fit [S25].
- Derived soil-water drawdown for peas, chickpeas and canola from the Pullman trial's regression table [S15].
- Added the trial authors' statement that soil water refills each winter in the Palouse, which qualifies the cover crop caution.

## Sources

- [S1] USDA NASS, *Usual Planting and Harvesting Dates for U.S. Field Crops*, Agricultural Handbook 628, December 1997, Washington table. https://swat.tamu.edu/media/90113/crops-typicalplanting-harvestingdates-by-states.pdf
- [S2] USA Dry Pea & Lentil Council, *USA Dry Pea, Lentil & Chickpea Production*. https://agresearch.montana.edu/wtarc/producerinfo/agronomy-nutrient-management/Pulses/USADryPeaCouncil%20FactSheet.pdf
- [S3] Corp et al., *Chickpea Production Guide*, Oregon State University EM 8791-E, 2004. https://agsci.oregonstate.edu/sites/agsci.oregonstate.edu/files/cbarc/attachments/EM8791_-_Chickpea_Production_Guide_0.pdf
- [S4] Schillinger, *Winter Pea: Promising New Crop for Washington's Dryland Wheat-Fallow Region*, Frontiers in Ecology and Evolution, 2017. https://www.frontiersin.org/journals/ecology-and-evolution/articles/10.3389/fevo.2017.00043/full
- [S5] US Canola Association, *Canola Growers' Manual*. https://agresearch.montana.edu/wtarc/producerinfo/agronomy-nutrient-management/Canola/USCanolaProdGuide.pdf
- [S6] Schillinger et al., *Dryland Cropping in the Western United States*, PNW Conservation Tillage Handbook No. 28, 2003. https://s3.wp.wsu.edu/uploads/sites/3233/2023/03/Number-28.pdf
- [S7] Schillinger et al., *Predicting Wheat Grain Yields Based on Available Water*, WSU Extension EM049E. https://s3.wp.wsu.edu/uploads/sites/2200/2012/04/Available-water-and-wheat-yield-EM049E.pdf
- [S8] Veseth et al., "Achieving Conservation Compliance with Residue Farming in the High-Precipitation Zone", in *Crop residue management to reduce erosion and improve soil quality: Northwest*, USDA ARS Conservation Research Report 40, p. 17. https://upload.wikimedia.org/wikipedia/commons/f/f0/Crop_residue_management_to_reduce_erosion_and_improve_soil_quality_-_northwest_%28IA_cropresiduemanag40pape%29.pdf
- [S9] McClellan et al., *Grain yield and biomass relationship for crops in the Inland Pacific Northwest United States*, 2012. https://www.ars.usda.gov/ARSUserFiles/20902500/TemporaryPublicationFilepubswithnohandle/Grain%20yield%20and%20biomass%20relationship.pdf
- [S10] University of Idaho, *Northern Idaho Fertilizer Guide: Winter Wheat*, CIS 453. https://content-hub.uidaho.edu/api/public/content/7819b47a72f84162a6949d607c69e8b1?v=69134fb9
- [S11] WSU Extension, *Eastern Washington Nutrient Management Guide: Dryland Winter Wheat*, EB1987E. https://wpcdn.web.wsu.edu/cahnrs/uploads/sites/16/EB1987E-3.pdf
- [S12] WSU Small Grains, *Soil Acidification in the Inland Pacific Northwest*. https://smallgrains.wsu.edu/soil-and-water-resources/soil-acidification-in-the-inland-northwest/
- [S13] Froese et al., *Recommended Crop Species and Wheat Varieties for Acidic Soil*, WSU Extension FS169E, 2015. https://wpcdn.web.wsu.edu/wp-ecommerce/uploads/sites/2/product-4095-sku-FS169E.pdf
- [S14] McGuire, *Water Use Limitations of Cover Crops in Dryland Cropping*, WSU CSANR, 2023. https://csanr.wsu.edu/wateruselimitationscovercrops/
- [S15] Heineck et al., *Yield and water use of grain legumes intercropped with spring canola in Eastern Washington*, Agrosystems, Geosciences & Environment, 2025. Trial at the Palouse Conservation Field Station near Pullman. https://acsess.onlinelibrary.wiley.com/doi/10.1002/agg2.70167
- [S16] McVay et al., *Chickpea Production*, Montana State University Extension, 2016. https://aes.colostate.edu/swrcr/wp-content/uploads/sites/92/2019/03/MSU-Extension-Chickpea-Production.pdf
- [S17] Painter et al., *Economics of Spring Canola Production in Dryland Eastern Washington*, WSU Extension EB2009E, 2006. https://wpcdn.web.wsu.edu/cahnrs/uploads/sites/5/2015/02/eb2009e.pdf
- [S18] Painter, *Cost and Returns Baseline for the Dryland Grain Annual Cropping Region of the Pacific Northwest for 2011–2015*, Pacific Northwest Extension. https://content-hub.uidaho.edu/api/public/content/50a05df64991421e840f6ab5a7690031?v=c2f61a6d
- [S19] Koenig et al., *Canola Growth, Development, and Fertility*, WSU Extension FS045E. https://pnwcanola.org/wp-content/uploads/2026/05/Canola-Growth-Development-Fertility.pdf
- [S20] Williams et al., *Productivity and water use efficiency of intensified dryland cropping systems under low precipitation in Pacific Northwest, USA*, Field Crops Research, 2020 (abstract only). https://agris.fao.org/search/en/providers/122535/records/65de9d0ab766d82b18fdd4d2
- [S21] University of Idaho, *Idaho Spring Barley Production Guide*. https://agresearch.montana.edu/wtarc/producerinfo/agronomy-nutrient-management/Barley/IdahoSpringBarleyProdGuide.pdf
- [S22] Pan et al., *4R Nitrogen Management When Integrating Canola into Semi-arid Wheat*, Crops & Soils, 2017. https://pnwcanola.org/wp-content/uploads/2026/05/4R-Nitrogen-Management-When-Integrating-Canola-into-Semi-arid-Wheat.pdf
- [S23] McVay et al., *Montana Cool-Season Pulse Production Guide*, Montana State University Extension EB0210. https://www.montana.edu/extension/Full_HTML_Pubs/EB0210-MontanaCoolSeasonPulseProductionGuide/EB0210-MontanaCoolSeasonPulseProductionGuide.html
- [S24] USDA NASS, *Field Crops: Usual Planting and Harvesting Dates*, Agricultural Handbook 628, October 2010, Washington table. https://esmis.nal.usda.gov/sites/default/release-files/vm40xr56k/dv13zw65p/z603r1055/planting-10-29-2010.txt
- [S25] Sowers et al., *Physiology Matters: Adjusting Wheat-Based Management Strategies for Oilseed Production*, WSU Extension FS244E. https://pnwcanola.org/wp-content/uploads/2026/05/Physiology-Matters-Adjusting-Wheat-Based-Management-Strategies-for-Oilseed-Production.pdf
- [S26] Zuger and Burke, *Spring Canola Seeding Rates*, WSU 2018 Field Day Abstracts. https://pnwcanola.org/wp-content/uploads/2026/05/Spring-Canola-Seeding-Rates.pdf
