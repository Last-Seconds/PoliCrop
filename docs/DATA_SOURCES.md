# Data sources for Field Shift: survey and tests

Researched 2026-11-15. "Tested" means I called the service that day and got usable data for Whitman County. "Listed" means I confirmed it exists in a catalogue or on its provider's page but did not pull data. "Search result only" means I saw it described in search results and did not open it.

## 1. Rainfall comparison against weather stations

Crop-year totals (September to August), years where station, Daymet and NASA POWER all have complete data.

| Place | Years compared | Station | Daymet | NASA POWER |
|---|---|---|---|---|
| Pullman (wet east) | 38, between 1982 and 2025 | 19.9 in | 21.0 in (+6%) | 25.8 in (+30%) |
| LaCrosse (dry west) | 30, between 1982 and 2021 | 14.2 in | 14.7 in (+3%) | 16.2 in (+14%) |

| | Daymet vs station | NASA POWER vs station |
|---|---|---|
| Year-to-year agreement (correlation), Pullman | 0.92 | 0.85 |
| Year-to-year agreement (correlation), LaCrosse | 0.95 | 0.87 |
| Typical error per year, Pullman | 1.5 in | 5.9 in |
| Typical error per year, LaCrosse | 0.8 in | 2.2 in |

Stations: NOAA cooperative stations Pullman 2 NW (USC00456789) and LaCrosse (USC00454338), through the ACIS service.

Caveat: Daymet is built by interpolating weather stations, very likely including these two, so its agreement with them is partly by construction. It still shows Daymet reproduces local conditions where NASA POWER does not.

## 2. Trends, re-checked with station and Daymet data

Three periods: 1982–1996, 1997–2011, 2012–2025.

| Measure | Pullman station | Pullman Daymet | LaCrosse station | LaCrosse Daymet |
|---|---|---|---|---|
| April–July rain (in) | 5.9 → 5.1 → 4.6 | 6.8 → 5.5 → 4.9 | 4.2 → 3.5 → 3.2 | 4.2 → 3.8 → 3.3 |
| June–July days at or above 90 °F | 7 → 9 → 13 | 8 → 10 → 15 | 20 → 20 → 25 | 16 → 17 → 21 |
| Crop-year rain (in) | 20.1 → 19.4 → 20.2 | 22.8 → 21.3 → 20.9 | 14.1 → 14.9 → 13.9 | 15.0 → 15.7 → 14.7 |

2021: Pullman station 15.5 in and 30 hot days; LaCrosse station 7.9 in and 43 hot days. The US Drought Monitor shows 100% of Whitman County in its most severe class (D4) in late July 2021.

Reading: yearly rainfall is flat; growing-season rain is down about a fifth; summer hot days have roughly doubled at Pullman. Station records have missing days, so station totals use only near-complete years.

## 3. Sources by need

### Weather history

| Source | Provider | Detail | Access | Status | Notes |
|---|---|---|---|---|---|
| Daymet V4 R1 | NASA (Oak Ridge data centre) | 1 km grid, daily, 1980 to end of 2025 | Free point service, no key: `https://daymet.ornl.gov/single-pixel/api/data?lat=..&lon=..&vars=prcp,tmax,tmin&start=..&end=..` | Tested | Best match to stations. Released yearly, so the current year is missing. The Planetary Computer copy stops in 2020. |
| NOAA cooperative stations | NOAA, through ACIS | Daily measurements. Pullman 2 NW since 1940; Rosalia since 1893; LaCrosse 1908–2021; Colfax to 2017; St. John to 2020. 25 stations in the county, including volunteer rain gauges. | Free, no key: `https://data.rcc-acis.org/StnData` and `StnMeta` | Tested | Real ground measurements, at points only, with gaps. |
| gridMET | University of California Merced Climatology Lab | 4 km grid, daily, 1979 to yesterday. Also gives reference evapotranspiration and a drought index. Blends PRISM with NASA's NLDAS-2. | Provider's own data server | Listed | Covers the current year. The Planetary Computer copy stops in 2020. |
| NASA POWER | NASA | About 50 km grid, daily, 1981 to yesterday | Free, no key | Tested (in the app now) | Overstates rainfall here by 14–30%. |
| AgWeatherNet | Washington State University | Station network, 15-minute data | Paid or by request; commercial use restricted | Listed | Not practical for the hackathon. |

### Soil

| Source | Provider | Detail | Access | Status |
|---|---|---|---|---|
| SSURGO through Soil Data Access | USDA NRCS | Soil type, drainage class, slope, hydrologic group and available water storage for any point | Free, no key: SQL posted to `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` | Tested |

Test at Pullman returned "Caldwell silt loam, 0 to 3 percent slopes", somewhat poorly drained, storing 19.6 cm of plant-available water in the top metre.

### Field outlines and crop history

| Source | Provider | Detail | Status |
|---|---|---|---|
| Cropland Data Layer | USDA NASS | 30 m, yearly, 2008–2025 | Tested (in the app now) |
| Crop Sequence Boundaries | USDA NASS | Field polygons with eight-year crop sequences, derived from the Cropland Data Layer; a 2024 edition exists | Search result only |

Crop Sequence Boundaries would let a farmer pick a field instead of drawing it, and would give nearby fields' rotations directly.

### Vegetation

| Source | Provider | Detail | Status | Notes |
|---|---|---|---|---|
| Sentinel-2 | European Space Agency | 10 m, every few days, from 2015 | Tested (in the app now) | |
| MODIS vegetation index (13Q1) | NASA | 250 m, every 16 days, from 2000 | Listed (Planetary Computer, current) | A 26-year record for spotting stress years; pixels are coarse for small fields. |
| Landsat Collection 2 | NASA and USGS | 30 m, every 8–16 days, from 1982 | Listed (Planetary Computer, current) | The longest field-scale record. |
| Harmonized Landsat Sentinel-2 | NASA | 30 m, every 2–3 days | Listed; on Planetary Computer only from 2020 | Too short there for history. |

### Soil moisture and drought

| Source | Provider | Detail | Status |
|---|---|---|---|
| US Drought Monitor | University of Nebraska, NOAA, USDA | Weekly share of the county in each drought class, from 2000 | Tested; free, no key |
| Crop-CASMA | USDA NASS, NASA, George Mason University | Soil moisture for US cropland from NASA's SMAP satellite, 2015 to present; vegetation from 2000 | Listed |
| GRACE drought indicators (GRACE-DA-DM) | NASA Goddard | Weekly groundwater and root-zone soil moisture wetness, about 25 km grid, from 2003; on Amazon's open data registry | Listed |

### Evapotranspiration

| Source | Provider | Detail | Status |
|---|---|---|---|
| OpenET | OpenET consortium (NASA-supported) | Field-scale, monthly from 2000, daily from 2016; needs a free key | Listed |
| gridMET reference evapotranspiration | As above | 4 km, daily | Listed |

### Terrain

| Source | Provider | Detail | Status |
|---|---|---|---|
| NASADEM | NASA | 30 m elevation, a reprocessing of SRTM | Listed (Planetary Computer) |
| 3DEP | USGS | Finer US elevation | Listed (Planetary Computer) |

### Future climate

| Source | Provider | Detail | Status |
|---|---|---|---|
| NEX-GDDP-CMIP6 | NASA | Daily rain and temperature, 1950–2100, 35 models, two emissions scenarios | Listed (Planetary Computer) |

### Risk and economics

| Source | Provider | Detail | Status |
|---|---|---|---|
| Cause of Loss files | USDA Risk Management Agency | County crop insurance losses by cause (drought, heat, freeze and so on) and crop | Search result only: https://legacy.rma.usda.gov/data/cause.html |
| QuickStats | USDA NASS | County yields by crop and year | Not tested; free key for automated use |

## 4. What I would change in the app

1. Use Daymet as the main weather history, in place of NASA POWER. It is a NASA product at 1 km and matches local stations.
2. Use gridMET or NASA POWER only to fill the current year, which Daymet lacks.
3. Show the nearest station's record beside the gridded data as a ground check.
4. Add soil properties from Soil Data Access, for water fit and the poorly-drained warning.
5. Add MODIS or Landsat vegetation history, to find stress years before 2015.
6. Add NASADEM slope when the erosion work starts.
7. Consider Crop Sequence Boundaries for picking fields and for nearby rotations.
8. Consider the Drought Monitor and GRACE indicators as a regional context panel.

NASA datasets in the app would then be Daymet, MODIS or Landsat, and NASADEM, with SMAP (through Crop-CASMA), GRACE and the climate projections as options.
