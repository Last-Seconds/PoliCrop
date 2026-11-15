"""Part A of brief 3: how well the year index tracks what actually happened. Writes data/validation.json.

Run from backend/:  python tools/validate.py            (first run reads MODIS for every area: several minutes)
The app reads the file; it never runs this live.

For several areas from the dry west to the wet east of the county:
1. MODIS 250 m pixels where one crop covers at least 75% of the pixel in that year's crop map (CDL).
2. For each crop and year, the average over those pixels of the highest greenness (NDVI, Terra 16-day
   composites starting 23 April to 28 July).
3. Each crop's yearly series against the year index at the area's centre, taken for every pixel in the
   position it actually held (after fallow, or after a harvested crop, from the previous year's map).

Reported per area and crop: correlation; the leave-one-year-out error reduction against "the crop's own
average"; years and pixels; what a May–June temperature term would add; whether El Niño / La Niña / neutral
grouping explains anything the index does not. Then sensitivities (slope of each crop's relative deviation
on winter wheat's). If data/us/county_yields.csv exists (year, crop, yield, unit; from USDA QuickStats by
hand), the same comparison with yields, preferred everywhere, and a search of e_winter within 0.60–0.75.
Greenness is never used to tune water constants.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
import rasterio  # noqa: E402
from rasterio.warp import transform  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from fieldshift.app import DATA_DIR, get_cache, get_service  # noqa: E402
from fieldshift.core import units  # noqa: E402
from fieldshift.core.geometry import field_from_spec  # noqa: E402
from fieldshift.core.weather import DailySeries  # noqa: E402
from fieldshift.core.yearindex import build_index  # noqa: E402
from fieldshift.providers.us.cdl import CropScapeCountyCdl  # noqa: E402

log = logging.getLogger("validate")
AREAS = [  # west to east; 51 x 51 MODIS pixels (about 12 km) around each centre
    {"id": "west", "name": "Near LaCrosse (dry west)", "lon": -117.880, "lat": 46.812},
    {"id": "west_central", "name": "Near Endicott", "lon": -117.640, "lat": 46.960},
    {"id": "central", "name": "West of Colfax", "lon": -117.420, "lat": 46.930},
    {"id": "east", "name": "Near Pullman (wet east)", "lon": -117.238, "lat": 46.847},
]
HALF = 25
YEARS = list(range(2008, 2026))
DOY = (113, 209)  # composites starting 23 April to 28 July: "late April to late July"
MIN_SHARE, MIN_PIXELS = 0.75, 10
CROPS = {"winter_wheat": [24], "spring_wheat": [23], "spring_barley": [21], "spring_peas": [53], "lentils": [52],
         "chickpeas": [51], "spring_canola": [31]}
FALLOW = 61
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
OUT = DATA_DIR / "validation.json"
YIELDS = DATA_DIR / "us" / "county_yields.csv"
QUICK = {"east": {"correlation": 0.64}, "west": {"correlation": 0.42}}  # docs/EXPERIMENTS.md, test 2


# ------------------------------------------------------------------------------------------- data

def modis_peaks(area: dict, cache_dir: Path) -> dict[int, np.ndarray]:
    """Per year: the peak greenness of each pixel in the window (NaN where never good)."""
    path = cache_dir / f"modis_{area['id']}_{HALF}.npz"
    if path.exists():
        z = np.load(path)
        return {"years": list(z["years"]), "peaks": z["peaks"], "crs": str(z["crs"]), "tr": tuple(z["tr"])}
    import planetary_computer as pc
    from pystac_client import Client
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    items = []
    for it in cat.search(collections=["modis-13Q1-061"], intersects={"type": "Point", "coordinates": [area["lon"], area["lat"]]},
                         datetime=f"{YEARS[0]}-04-01/{YEARS[-1]}-08-15", query={"platform": {"eq": "terra"}}).items():
        tag = it.id.split(".")[1]
        y, doy = int(tag[1:5]), int(tag[5:8])
        if DOY[0] <= doy <= DOY[1] and y in YEARS:
            items.append((y, it))
    geo: dict = {}

    def read(arg):
        y, it = arg
        for attempt in range(3):
            try:
                it = pc.sign(it)
                with rasterio.open(it.assets["250m_16_days_NDVI"].href) as ds:
                    xs, ys = transform("EPSG:4326", ds.crs, [area["lon"]], [area["lat"]])
                    r, c = ds.index(xs[0], ys[0])
                    if r - HALF < 0 or c - HALF < 0 or r + HALF >= ds.height or c + HALF >= ds.width:
                        return None  # the other tile holds the window
                    w = Window(c - HALF, r - HALF, 2 * HALF + 1, 2 * HALF + 1)
                    nd = ds.read(1, window=w).astype("float32")
                    if not geo:
                        geo.update(crs=ds.crs.to_wkt(), tr=tuple(ds.window_transform(w))[:6])
                with rasterio.open(it.assets["250m_16_days_pixel_reliability"].href) as ds:
                    rel = ds.read(1, window=w)
                nd[(rel > 1) | (nd < -2000)] = np.nan  # good (0) and marginal (1) kept, as the quick tests did
                return y, nd * 0.0001
            except Exception as exc:  # noqa: BLE001
                log.warning("MODIS read failed (%s), attempt %d: %s", it.id, attempt + 1, exc)
        return None

    stacks: dict[int, list] = {}
    with ThreadPoolExecutor(12) as ex:
        for r in ex.map(read, items):
            if r:
                stacks.setdefault(r[0], []).append(r[1])
    years = sorted(stacks)
    peaks = np.stack([np.nanmax(np.stack(stacks[y]), axis=0) for y in years])
    np.savez(path, years=np.array(years), peaks=peaks, crs=np.array(geo["crs"]), tr=np.array(geo["tr"]))
    return {"years": years, "peaks": peaks, "crs": geo["crs"], "tr": geo["tr"]}


def cdl_classes(area: dict, modis: dict, cdl: CropScapeCountyCdl, cache_dir: Path) -> dict:
    """Per year: dominant crop-map class and its share inside each MODIS pixel (9 x 9 CDL cells)."""
    path = cache_dir / f"cdl_{area['id']}_{HALF}.npz"
    if path.exists():
        z = np.load(path)
        return {"years": list(z["years"]), "dom": z["dom"], "share": z["share"]}
    n = 2 * HALF + 1
    a, b, c, d, e, f = modis["tr"]
    cols, rows = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
    X, Y = c + cols * a + rows * b, f + cols * d + rows * e
    doms, shares, years = [], [], []
    for y in YEARS:
        try:
            p = cdl.county_file(y)
        except Exception as exc:  # noqa: BLE001
            log.warning("CDL %s unavailable: %s", y, exc)
            continue
        with rasterio.open(p) as ds:
            cx, cy = transform(modis["crs"], ds.crs, X.ravel().tolist(), Y.ravel().tolist())
            arr = ds.read(1)
            dom = np.zeros(n * n, int)
            share = np.zeros(n * n)
            for i, (x, yy) in enumerate(zip(cx, cy)):
                r, cc = ds.index(x, yy)
                if r - 4 < 0 or cc - 4 < 0 or r + 5 > arr.shape[0] or cc + 5 > arr.shape[1]:
                    continue
                win = arr[r - 4:r + 5, cc - 4:cc + 5].ravel()
                vals, cnt = np.unique(win, return_counts=True)
                k = cnt.argmax()
                dom[i], share[i] = vals[k], cnt[k] / win.size
        years.append(y)
        doms.append(dom)
        shares.append(share)
    np.savez(path, years=np.array(years), dom=np.array(doms), share=np.array(shares))
    return {"years": years, "dom": np.array(doms), "share": np.array(shares)}


def oni_phases(cache_dir: Path) -> dict[int, str]:
    """Crop year -> el_nino | la_nina | neutral, from the December–February ONI anomaly of that winter."""
    path = cache_dir / "oni.ascii.txt"
    if not path.exists():
        path.write_bytes(urllib.request.urlopen(ONI_URL, timeout=60).read())
    out = {}
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) == 4 and parts[0] == "DJF":
            anom = float(parts[3])
            out[int(parts[1])] = "el_nino" if anom >= 0.5 else "la_nina" if anom <= -0.5 else "neutral"
    return out


# ------------------------------------------------------------------------------------------- statistics

def loo_reduction(y: np.ndarray, X: np.ndarray | None) -> float | None:
    """1 − RMSE(leave-one-out linear fit) / RMSE(leave-one-out mean); None if too few years."""
    n = len(y)
    if n < 6:
        return None
    e_fit, e_base = [], []
    for i in range(n):
        m = np.arange(n) != i
        e_base.append(y[i] - y[m].mean())
        if X is None:
            continue
        A = np.column_stack([np.ones(m.sum()), X[m]])
        coef, *_ = np.linalg.lstsq(A, y[m], rcond=None)
        e_fit.append(y[i] - np.r_[1.0, X[i]] @ coef)
    rb = float(np.sqrt(np.mean(np.square(e_base))))
    if X is None or rb == 0:
        return None
    return 1 - float(np.sqrt(np.mean(np.square(e_fit)))) / rb


def corr(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 4 or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def r3(v):
    return None if v is None else round(float(v), 3)


def sensitivity(pairs: list[tuple[float, float]], years: set[int], basis: str) -> dict:
    """Slope of a crop's relative deviation on winter wheat's, through the origin, with its LOO check."""
    if not pairs:
        return {"value": 1.0, "basis": "assumed", "n_years": 0, "n_pairs": 0, "reason": "no data"}
    x = np.array([p[0] for p in pairs])
    y = np.array([p[1] for p in pairs])
    slope = float((x @ y) / (x @ x)) if (x @ x) > 0 else 0.0
    e_fit, e_base = [], []
    for i in range(len(x)):
        m = np.arange(len(x)) != i
        b = float((x[m] @ y[m]) / (x[m] @ x[m])) if (x[m] @ x[m]) > 0 else 0.0
        e_fit.append(y[i] - b * x[i])
        e_base.append(y[i])
    red = 1 - float(np.sqrt(np.mean(np.square(e_fit)))) / max(1e-12, float(np.sqrt(np.mean(np.square(e_base)))))
    out = {"estimate": round(slope, 3), "loo_reduction": round(red, 3), "n_years": len(years), "n_pairs": len(pairs)}
    if len(years) < 8 or red <= 0:
        return {**out, "value": 1.0, "basis": "assumed",
                "reason": "fewer than 8 years" if len(years) < 8 else "no better than the crop's own average"}
    if basis == "measured":
        return {**out, "value": round(slope, 3), "basis": "measured"}
    return {**out, "value": round(min(2.0, max(0.5, slope)), 3), "basis": "measured (greenness)",
            "note": "Clipped to 0.5–2.0. Greenness saturates over dense wheat, which inflates other crops' ratios."}


# ------------------------------------------------------------------------------------------- main

def area_analysis(area, svc, cdl, cache_dir, phases):
    modis = modis_peaks(area, cache_dir)
    classes = cdl_classes(area, modis, cdl, cache_dir)
    lon, lat = area["lon"], area["lat"]
    series = DailySeries.from_raw(svc.providers.weather.daily(lon, lat))
    d = 0.006
    sq = {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                                              [lon - d, lat + d], [lon - d, lat - d]]]}
    try:
        soil = svc.field_soil(field_from_spec({"type": "polygon", "geometry": sq}))
    except Exception as exc:  # noqa: BLE001
        log.warning("soil for %s failed: %s", area["id"], exc)
        soil = None
    s = svc.content.settings
    cap = soil.capacity_mm if soil else {"0_100cm": units.in_to_mm(s["water.default_capacity_0_100cm_in"]),
                                          "0_150cm": units.in_to_mm(s["water.default_capacity_0_150cm_in"])}
    yi = build_index(series, cap, s)
    # May–June mean daily high per year
    tmax = {}
    for y in yi.years:
        w = series.window(series.tmax, dt.date(int(y), 5, 1), dt.date(int(y), 6, 30))
        w = w[~np.isnan(w)]
        tmax[int(y)] = float(w.mean()) if w.size else None
    myears = {int(y): k for k, y in enumerate(modis["years"])}
    cyears = {int(y): k for k, y in enumerate(classes["years"])}
    years = [y for y in YEARS if y in myears and y in cyears]
    crops: dict = {}
    allg = []  # area-average greenness of cropped pixels, for the test-2 comparison
    within, between = [], []
    for y in years:
        peak = modis["peaks"][myears[y]].ravel()
        dom, share = classes["dom"][cyears[y]], classes["share"][cyears[y]]
        prev = classes["dom"][cyears[y - 1]] if (y - 1) in cyears else None
        cropped = np.isin(dom, sum(CROPS.values(), [])) & (share >= MIN_SHARE) & ~np.isnan(peak)
        if cropped.sum() >= MIN_PIXELS:
            allg.append((y, float(peak[cropped].mean()), yi.at(y, "autumn", "harvested")))
            within.append(float(peak[cropped].std()))
        for cid, codes in CROPS.items():
            m = np.isin(dom, codes) & (share >= MIN_SHARE) & ~np.isnan(peak)
            if m.sum() < MIN_PIXELS:
                continue
            season = "autumn" if cid == "winter_wheat" else "spring"
            kinds = np.where(prev[m] == FALLOW, "fallow", "harvested") if prev is not None else np.full(m.sum(), "harvested")
            idx = np.mean([yi.at(y, season, k) for k in kinds]) if y in set(yi.years.tolist()) else None
            if idx is None:
                continue
            crops.setdefault(cid, []).append({"year": y, "greenness": round(float(peak[m].mean()), 4), "index": round(float(idx), 4),
                                              "pixels": int(m.sum()), "after_fallow_share": round(float((kinds == "fallow").mean()), 3)})
    if allg:
        between = [float(np.std([g for _, g, _ in allg]))]
    out_crops = {}
    for cid, rows in crops.items():
        g = np.array([r["greenness"] for r in rows])
        x = np.array([r["index"] for r in rows])
        t = np.array([tmax.get(r["year"]) or np.nan for r in rows])
        ph = [phases.get(r["year"], "neutral") for r in rows]
        dummies = np.column_stack([[p == "el_nino" for p in ph], [p == "la_nina" for p in ph]]).astype(float)
        ok_t = ~np.isnan(t)
        out_crops[cid] = {
            "years": len(rows), "pixels_median": int(np.median([r["pixels"] for r in rows])),
            "correlation": r3(corr(x, g)),
            "loo_reduction": r3(loo_reduction(g, x)),
            "loo_reduction_with_temperature": r3(loo_reduction(g[ok_t], np.column_stack([x[ok_t], t[ok_t]]))) if ok_t.sum() >= 6 else None,
            "loo_reduction_with_enso": r3(loo_reduction(g, np.column_stack([x, dummies]))),
            "series": rows,
        }
    ag = np.array([g for _, g, _ in allg])
    ax = np.array([x for _, _, x in allg])
    at = np.array([tmax.get(y) or np.nan for y, _, _ in allg])
    aph = [phases.get(y, "neutral") for y, _, _ in allg]
    adum = np.column_stack([[p == "el_nino" for p in aph], [p == "la_nina" for p in aph]]).astype(float)
    return {
        "id": area["id"], "name": area["name"], "lon": lon, "lat": lat,
        "mean_crop_year_precip_in": round(units.mm_to_in(float(np.mean(yi_replay_precip(series, cap, s)))), 1),
        "capacity_0_150cm_in": round(units.mm_to_in(cap["0_150cm"]), 1), "capacity_from_soil_survey": soil is not None,
        "index_notes": yi.notes,
        "all_crops": {"years": len(allg), "correlation": r3(corr(ax, ag)), "loo_reduction": r3(loo_reduction(ag, ax)),
                      "loo_reduction_with_temperature": r3(loo_reduction(ag, np.column_stack([ax, at]))) if len(allg) >= 6 else None,
                      "loo_reduction_with_enso": r3(loo_reduction(ag, np.column_stack([ax, adum]))),
                      "correlation_with_may_june_high": r3(corr(at, ag)),
                      "spread_between_neighbouring_pixels": r3(np.mean(within)) if within else None,
                      "spread_of_area_average_between_years": r3(between[0]) if between else None},
        "crops": out_crops,
    }


def yi_replay_precip(series, cap, s):
    from fieldshift.core.replay import build_replay
    return build_replay(series, cap, s).crop_year_precip_mm


def county_yields() -> dict[str, dict[int, float]] | None:
    if not YIELDS.exists():
        return None
    out: dict[str, dict[int, float]] = {}
    with YIELDS.open() as fh:
        for row in csv.DictReader(fh):
            try:
                out.setdefault(row["crop"].strip(), {})[int(row["year"])] = float(row["yield"])
            except (KeyError, ValueError):
                continue
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    svc = get_service()
    cache = get_cache()
    cache_dir = Path(cache.file_path("validation", "x")).parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    cdl = CropScapeCountyCdl(str(svc.content.region.get("fips")), cache)
    phases = oni_phases(cache_dir)
    areas = []
    for a in AREAS:
        log.info("area %s", a["id"])
        areas.append(area_analysis(a, svc, cdl, cache_dir, phases))

    # Sensitivities, pooled over areas: each crop's relative deviation from its own mean on winter wheat's.
    sens: dict = {"winter_wheat": {"value": 1.0, "basis": "definition", "n_years": None}}
    for cid in CROPS:
        if cid == "winter_wheat":
            continue
        pairs, yrs = [], set()
        for ar in areas:
            ww = {r["year"]: r["greenness"] for r in ar["crops"].get("winter_wheat", {}).get("series", [])}
            cc = {r["year"]: r["greenness"] for r in ar["crops"].get(cid, {}).get("series", [])}
            common = sorted(set(ww) & set(cc))
            if len(common) < 4:
                continue
            mw, mc = np.mean([ww[y] for y in common]), np.mean([cc[y] for y in common])
            pairs += [(ww[y] / mw - 1, cc[y] / mc - 1) for y in common]
            yrs |= set(common)
        sens[cid] = sensitivity(pairs, yrs, "greenness")

    cy = county_yields()
    county = {"available": cy is not None}
    if cy:
        # County yields against the mean index of the areas (winter cereal after a harvested crop for winter
        # wheat, spring cereal otherwise); preferred everywhere when present.
        county["crops"] = {}
        idx_by_year = {}
        for ar in areas:
            for cid, c in ar["crops"].items():
                for r in c["series"]:
                    idx_by_year.setdefault((cid, r["year"]), []).append(r["index"])
        for crop, ys in cy.items():
            yrs = sorted(y for y in ys if (crop, y) in idx_by_year)
            if len(yrs) < 6:
                continue
            g = np.array([ys[y] for y in yrs])
            x = np.array([np.mean(idx_by_year[(crop, y)]) for y in yrs])
            county["crops"][crop] = {"years": len(yrs), "correlation": r3(corr(x, g)), "loo_reduction": r3(loo_reduction(g, x))}
        ww = cy.get("winter_wheat", {})
        for crop, ys in cy.items():
            if crop == "winter_wheat":
                continue
            common = sorted(set(ww) & set(ys))
            if len(common) >= 10:
                mw, mc = np.mean([ww[y] for y in common]), np.mean([ys[y] for y in common])
                sens[crop] = sensitivity([(ww[y] / mw - 1, ys[y] / mc - 1) for y in common], set(common), "measured")
        county["e_winter_search"] = "not run: needs per-area replays with each e_winter; report only, never applied"

    east = next(a for a in areas if a["id"] == "east")
    west = next(a for a in areas if a["id"] == "west")
    out = {
        "generated": dt.date.today().isoformat(),
        "method": {"areas": "51 x 51 MODIS pixels (about 12 km) around each centre", "years": f"{YEARS[0]}–{YEARS[-1]}",
                   "pixels": f"one crop covers at least {MIN_SHARE:.0%} of the pixel in that year's crop map; at least {MIN_PIXELS} pixels",
                   "greenness": "highest MODIS NDVI in Terra composites starting 23 April to 28 July",
                   "index": "brief 3 section 4, at the area's centre, in each pixel's position (after fallow or a harvested crop)",
                   "loo": "leave one year out; reduction in error against the crop's own average"},
        "areas": areas,
        "sensitivities": sens,
        "county_yields": county,
        "quick_tests": {"east_correlation": QUICK["east"]["correlation"], "west_correlation": QUICK["west"]["correlation"],
                        "source": "docs/EXPERIMENTS.md, test 2 (2000–2025, all cropped pixels, water supply not this index)"},
        "summary": {"east_correlation": east["all_crops"]["correlation"], "west_correlation": west["all_crops"]["correlation"],
                    "east_years": east["all_crops"]["years"], "west_years": west["all_crops"]["years"]},
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT}")
    for a in areas:
        ac = a["all_crops"]
        print(f"{a['id']:13s} {a['mean_crop_year_precip_in']:5.1f} in  all crops: r={ac['correlation']} loo={ac['loo_reduction']} "
              f"(+temp {ac['loo_reduction_with_temperature']}, +enso {ac['loo_reduction_with_enso']}) n={ac['years']} "
              f"spread pixels {ac['spread_between_neighbouring_pixels']} years {ac['spread_of_area_average_between_years']}")
        for cid, c in a["crops"].items():
            print(f"    {cid:14s} r={c['correlation']} loo={c['loo_reduction']} +temp={c['loo_reduction_with_temperature']} "
                  f"+enso={c['loo_reduction_with_enso']} years={c['years']} px={c['pixels_median']}")
    print("sensitivities:", json.dumps({k: (v["value"], v["basis"], v.get("estimate"), v.get("n_years")) for k, v in sens.items()}))


if __name__ == "__main__":
    sys.exit(main())
