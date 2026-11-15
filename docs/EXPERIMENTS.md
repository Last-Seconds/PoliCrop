# Quick experiments behind the design

Run on 2026-11-15 to check ideas before building them. Each is a short script in `experiments/`. Nobody has reviewed them. Treat the numbers as indications of direction, not as results to quote without re-running.

The scripts read and write under `/tmp` and use the Python environment of the app (`potato-tomato/backend/.venv`). Paths need adjusting to run them again.

Shared limits:

- "Greenness" is the highest MODIS vegetation index (NDVI) between late April and late July. It is not yield, and it saturates over dense wheat, which hides differences between good years.
- Tests use one or two areas of 5 to 15 km near Pullman (east) and in the wheat–fallow country to the west.
- The water budget used one assumed soil capacity (10.6 in) everywhere.
- Series are short: 7 to 26 years.

## 1. Water budget prototype (`sim.py`)

The budget of `BUILD_BRIEF_2.md` section 6.2, on Daymet data, crop years 1982–2025.

| | Pullman (east) | LaCrosse (west) |
|---|---|---|
| Mean crop-year precipitation | 21.7 in | 15.2 in |
| Median supply, wheat after a harvested crop | 14.6 in | 10.5 in |
| Median supply, wheat after fallow | 15.8 in | 13.5 in |
| Gain from fallow | 1.2 in | 3.0 in |
| Wheat after a crop, short of its after-fallow normal | 41% of years | 68% |
| Wheat after fallow, short of the same | 18% | 5% |
| Wheat shortfall in 2021, after a crop, against its own normal | 3.8 in | 4.9 in |

Reading: fallow pays in the west and barely in the east, which is what farmers there do.

Weakness: spring legumes near Pullman show almost no shortfall in 2021. The budget has no heat term.

## 2. Does the model track what happened? (`modis_test.py`, `resid.py`)

Area-average greenness of cropped pixels, 2000–2025, against the model's water supply. Fitted on 2000–2015, tested on 2016–2025.

| | East | West |
|---|---|---|
| Correlation with modelled water supply | 0.64 | 0.42 |
| Correlation with crop-year rain alone | 0.45 | 0.41 |
| Correlation with May–June mean daily high | −0.68 | −0.42 |
| Test error against "predict the average", water only | 12% lower | 15% lower |
| Same, with temperature added | 17% lower | 17% lower |
| Same, leaving out one year at a time, water only | 18% lower | 6% lower |
| Spread between neighbouring pixels in one year | 0.075 | 0.138 |
| Spread of the area average between years | 0.040 | 0.037 |

Reading:

- The budget does better than yearly rain alone in the east. In the west the gain is not reliable.
- Temperature matters about as much as water in the east.
- Neighbouring fields differ two to four times more in one year than the area average differs between years. Field-level outcomes are dominated by crop, soil, slope position and management. Tune at area level; use field-level differences for a constant correction and for asking the farmer what happened.

## 3. El Niño and what is known by the end of March (`enso.py`)

NOAA's Oceanic Niño Index against the same water budget, 1982–2025.

| | Pullman | LaCrosse |
|---|---|---|
| September–March precipitation, El Niño winters | 14.2 in | 10.3 in |
| Same, La Niña winters | 16.2 in | 11.6 in |
| Probability that difference is chance | 0.07 | 0.13 |
| April–June rain, difference between phases | None | None |
| Correlation of the year's supply with the index known in autumn | −0.17 | −0.17 |
| Share of supply variance fixed by stored water on 31 March | 24% | 59% |
| Shortfall years caught by a 31 March check | 4 of 8 | 7 of 8 |
| False alarms from that check | 4 | 5 |

Reading: El Niño winters lean dry but explain about 3% of the variation. What has already fallen by the end of March is a far stronger signal, in the dry west.

The index for August–October 2026 was +2.46, a strong El Niño.

## 4. Does one crop tell you about another? (`crosscrop2.py`)

Greenness per crop in a 15 km area near Pullman, 2014–2025, using the Cropland Data Layer to keep only MODIS pixels at least 75% one crop. Figures are the reduction in error against using the crop's own average, leaving out one year at a time.

| Predicted crop | From winter wheat | From spring wheat | From canola | From all four references |
|---|---|---|---|---|
| Barley | 39% | 61% | 37% | 68% |
| Canola | 39% | 66% | – | 52% |
| Chickpeas | 15% | 36% | 38% | 35% |
| Peas | 75% | 82% | – | – |
| Spring wheat | 54% | – | 63% | 60% |
| Lentils | Worse | Worse | Worse | – |

Reading:

- Good and bad years are shared across crops.
- The nearest reference crop does much better than winter wheat alone. Sowing season matters more than plant family.
- Lentils did not work: 7 years and about 34 pixels a year, so this may be noise.
- Chickpeas, lentils and peas have only 7 usable years.

Spring wheat greenness in that area, by year: 0.79, 0.84, 0.84, 0.77, 0.83 (2014–2018); 0.71, 0.88, 0.65, 0.86, 0.67, 0.83, 0.72 (2019–2025). It fell below 0.72 in four of the last seven years and in none of the five before. Winter wheat moved much less in the same years.

## 5. Ideas these tests support

None of these is in `BUILD_BRIEF_2.md` yet.

1. A validation step that repeats test 2 properly and shows the result in the app.
2. Farmer yield records by year, blended with regional values by a weight that grows with the number of records: `w = n / (n + k)`.
3. A question to the farmer about years where the estimate and the field disagree, so that hail or disease is not mistaken for drought.
4. An in-season update at the end of March from that winter's actual precipitation. It needs a current-year weather source, which Daymet is not.
5. Reference crops (winter wheat, spring wheat, chickpeas, canola) that carry a shared year effect to crops with little data, weighted by similarity, sowing season first.

The test that would settle most open questions: repeat tests 2 and 4 with real yields, for example county yields per crop from USDA QuickStats.
