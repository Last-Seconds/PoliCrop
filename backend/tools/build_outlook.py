"""Build data/outlook_2050.json: the 2050 outlook for Whitman County from NASA NEX-GDDP-CMIP6.

Offline tool, never a live request; the file it writes is a display panel and never feeds the scoring.

Run from backend/:  .venv/bin/python tools/build_outlook.py
Options:            --models A,B,C  --hist 1995 2014  --future 2041 2060  --step 1  --workers 16

Access method. The Planetary Computer copy of NEX-GDDP-CMIP6 (collection nasa-nex-gddp-cmip6) stores each
model/scenario/variable/year as one NetCDF4 file whose variable is chunked one whole global day per chunk
(chunks 1 x 600 x 1440, zlib + shuffle). Reading one grid cell therefore means reading and inflating every
chunk, i.e. the whole ~180-245 MB file; its kerchunk reference files only index those same chunks (and exist
for historical runs only). NASA's own NCCS THREDDS server holds the same dataset (the newer v1.1/v2.0 files)
and offers the NetCDF Subset Service, which cuts the county window on the server and returns ~50 KB of
NetCDF-3 per file-year. This tool uses that service; reads are cached under cache/outlook/ so reruns are cheap.

Method:
- Grid cells are the 0.25-degree cells that overlap the county outline (US Census TIGER), weighted by the
  share of the county's area each covers.
- Per model year: April-July precipitation of the area-weighted daily series; June-July days with daily
  maximum >= 90 F counted in each cell, then area-weighted; annual mean of (tasmax + tasmin) / 2.
- Each model's historical-window mean is compared with its mid-century mean under ssp245 and ssp585;
  the file reports the median, 25-75 % range and min-max of those changes across models.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import yaml
from scipy.io import netcdf_file
from shapely.geometry import box, shape

from fieldshift.app import CACHE_DIR, DATA_DIR, get_cache
from fieldshift.cache import CachedProvider
from fieldshift.core import outlook
from fieldshift.providers.http import download, get_text
from fieldshift.providers.us.tiger import TigerCountyRegion

log = logging.getLogger("build_outlook")

THREDDS = "https://ds.nccs.nasa.gov/thredds"
ROOT_PATH = "AMES/NEX/GDDP-CMIP6"
VARS = ("pr", "tasmax", "tasmin")
SCENARIOS = ("ssp245", "ssp585")
# Ten widely used models with standard or no-leap calendars, r1 runs on NCCS for all three experiments.
DEFAULT_MODELS = ("ACCESS-CM2", "CanESM5", "EC-Earth3", "GFDL-ESM4", "INM-CM5-0", "IPSL-CM6A-LR",
                  "MIROC6", "MPI-ESM1-2-HR", "MRI-ESM2-0", "NorESM2-MM")
FALLBACK_BBOX = (-118.25, 46.4, -117.0, 47.27)  # Whitman County, used only if the outline is unavailable
CELL = 0.25
OUT_DIR = CACHE_DIR / "outlook"


# ---------------------------------------------------------------- region

def county_outline(region_cfg: dict):
    try:
        prov = CachedProvider(TigerCountyRegion(region_cfg["fips"], region_cfg["id"], region_cfg["name"]),
                              get_cache(), "tiger", ["region"], lambda m, a, r: 30 * 86400)
        return shape(prov.region()["geometry"]), "US Census TIGERweb county outline"
    except Exception as exc:  # noqa: BLE001 - degrade to the bounding box, and say so
        log.warning("county outline unavailable (%s); using the bounding box", exc)
        return box(*FALLBACK_BBOX), "bounding box %s (county outline unavailable)" % (FALLBACK_BBOX,)


def cell_weights(lats, lons360, county) -> list[tuple[int, int, float, float, float]]:
    """(lat index, lon index, lat, lon, weight) for cells overlapping the county; weight = share of county area."""
    out = []
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons360):
            lo180 = lo - 360.0 if lo > 180 else lo
            cell = box(lo180 - CELL / 2, la - CELL / 2, lo180 + CELL / 2, la + CELL / 2)
            a = cell.intersection(county).area * math.cos(math.radians(la))
            if a > 0:
                out.append((i, j, float(la), float(lo180), a))
    total = sum(c[4] for c in out)
    return [(i, j, la, lo, a / total) for i, j, la, lo, a in out]


# ---------------------------------------------------------------- catalog

def _cached_json(path: Path, build):
    if path.exists():
        return json.loads(path.read_text())
    value = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return value


def _catalog_titles_and_paths(rel: str) -> tuple[list[str], list[str]]:
    xml = get_text(f"{THREDDS}/catalog/{rel}/catalog.xml", timeout=60)
    root = ET.fromstring(xml)
    titles, paths = [], []
    for el in root.iter():
        t = el.attrib.get("{http://www.w3.org/1999/xlink}title")
        if t:
            titles.append(t)
        if el.attrib.get("urlPath"):
            paths.append(el.attrib["urlPath"])
    return titles, paths


def variant(model: str, scenario: str) -> str:
    def build():
        titles, _ = _catalog_titles_and_paths(f"{ROOT_PATH}/{model}/{scenario}")
        runs = sorted(t for t in titles if re.fullmatch(r"r\d+i\d+p\d+f\d+", t))
        if not runs:
            raise RuntimeError(f"no run listed for {model} {scenario}")
        return runs[0]
    return _cached_json(OUT_DIR / "catalog" / f"{model}_{scenario}_variant.json", build)


def year_files(model: str, scenario: str, run: str, var: str) -> dict[int, str]:
    """year -> THREDDS urlPath of the newest file version for that year."""
    def build():
        _, paths = _catalog_titles_and_paths(f"{ROOT_PATH}/{model}/{scenario}/{run}/{var}")
        pat = re.compile(rf"{var}_day_{re.escape(model)}_{scenario}_{run}_g\w+?_(\d{{4}})(?:_v(\d+)\.(\d+))?\.nc$")
        best: dict[int, tuple[tuple[int, int], str]] = {}
        for p in paths:
            m = pat.search(p)
            if not m:
                continue
            year, ver = int(m.group(1)), (int(m.group(2) or 1), int(m.group(3) or 0))
            if year not in best or ver > best[year][0]:
                best[year] = (ver, p)
        return {str(y): v[1] for y, v in best.items()}
    return {int(y): p for y, p in _cached_json(OUT_DIR / "catalog" / f"{model}_{scenario}_{run}_{var}.json",
                                                 build).items()}


# ---------------------------------------------------------------- data

def subset_url(url_path: str, var: str, bbox) -> str:
    w, s, e, n = bbox
    return (f"{THREDDS}/ncss/grid/{url_path}?var={var}&north={n:.4f}&south={s:.4f}"
            f"&west={w + 360:.4f}&east={e + 360:.4f}&temporal=all&accept=netcdf")


def read_subset(path: Path, var: str, year: int):
    """lat, lon (0-360), data (days, lat, lon) in source units; validates the time axis."""
    with netcdf_file(str(path), "r", mmap=False) as f:
        lat = np.array(f.variables["lat"][:], dtype=float)
        lon = np.array(f.variables["lon"][:], dtype=float)
        v = f.variables[var]
        if tuple(d.decode() if isinstance(d, bytes) else d for d in v.dimensions) != ("time", "lat", "lon"):
            raise ValueError(f"{path.name}: unexpected dimensions {v.dimensions}")
        data = np.array(v[:], dtype=float)
        fill = v._attributes.get("_FillValue", 1e20)
        t = f.variables["time"]
        units = t.units.decode() if isinstance(t.units, bytes) else str(t.units)
        cal = t._attributes.get("calendar", b"standard")
        cal = cal.decode() if isinstance(cal, bytes) else str(cal)
        times = np.array(t[:], dtype=float)
    data[np.abs(data) >= 1e19] = np.nan
    data[data == fill] = np.nan
    n = data.shape[0]
    outlook.months_for_year(n)  # raises unless 360/365/366
    m = re.match(r"days since (\d{4})-(\d{1,2})-(\d{1,2})", units)
    if m and cal in ("standard", "gregorian", "proleptic_gregorian"):
        origin = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        first = origin + dt.timedelta(days=int(times[0]))
        last = origin + dt.timedelta(days=int(times[-1]))
        expect = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365
        if (first, last) != (dt.date(year, 1, 1), dt.date(year, 12, 31)) or n != expect:
            raise ValueError(f"{path.name}: time axis {first}..{last} ({n} days) is not the year {year}")
    elif m and cal in ("noleap", "365_day", "360_day"):
        length = 360 if cal == "360_day" else 365
        if (int(m.group(2)), int(m.group(3))) != (1, 1) or n != length \
                or int(times[0]) != (year - int(m.group(1))) * length:
            raise ValueError(f"{path.name}: {cal} time axis does not start on 1 January {year} ({n} days)")
    else:
        raise ValueError(f"{path.name}: unsupported time axis {units!r} / {cal!r}")
    return lat, lon, data


def subset_path(task, bbox) -> Path:
    model, scenario, _, _, url_path = task
    tag = "_".join(f"{v:.3f}" for v in bbox)  # a different window is a different cache entry
    return OUT_DIR / "nc" / tag / model / scenario / Path(url_path).name


def fetch(task, bbox) -> Path:
    model, scenario, var, year, url_path = task
    dest = subset_path(task, bbox)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    download(subset_url(url_path, var, bbox), dest, timeout=300, attempts=4)
    try:
        read_subset(dest, var, year)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--hist", nargs=2, type=int, default=[1995, 2014])
    ap.add_argument("--future", nargs=2, type=int, default=[2041, 2060])
    ap.add_argument("--step", type=int, default=1, help="use every Nth year of each window")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=str(DATA_DIR / "outlook_2050.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    started = time.time()

    region_cfg = yaml.safe_load((DATA_DIR / "region.yaml").read_text())
    county, outline_source = county_outline(region_cfg)
    w, s, e, n = county.bounds
    bbox = (w, s, e, n)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    hist_years = list(range(args.hist[0], args.hist[1] + 1, args.step))
    fut_years = list(range(args.future[0], args.future[1] + 1, args.step))
    windows = {"historical": hist_years, **{sc: fut_years for sc in SCENARIOS}}

    # Resolve files; a model missing any file is dropped (and named in the notes).
    tasks, dropped = [], {}
    for model in models:
        mt = []
        try:
            for scenario, years in windows.items():
                run = variant(model, scenario)
                for var in VARS:
                    files = year_files(model, scenario, run, var)
                    missing = [y for y in years if y not in files]
                    if missing:
                        raise RuntimeError(f"{scenario} {var} has no file for {missing}")
                    mt += [(model, scenario, var, y, files[y]) for y in years]
        except Exception as exc:  # noqa: BLE001
            dropped[model] = str(exc)
            log.warning("dropping %s: %s", model, exc)
            continue
        tasks += mt
    log.info("%d subset files for %d models (%d already cached)", len(tasks), len(models) - len(dropped),
             sum(subset_path(t, bbox).exists() for t in tasks))

    paths, failed = {}, {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch, t, bbox): t for t in tasks}
        for k, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                paths[t[:4]] = fut.result()
            except Exception as exc:  # noqa: BLE001
                failed.setdefault(t[0], str(exc))
                log.warning("failed %s: %s", t[:4], exc)
            if k % 50 == 0 or k == len(tasks):
                log.info("%d/%d files (%.0f s)", k, len(tasks), time.time() - started)
    for m, why in failed.items():
        dropped[m] = f"download failed: {why}"

    # Compute.
    grid = None
    per_model_windows = {}
    for model in models:
        if model in dropped:
            continue
        try:
            means = {}
            for scenario, years in windows.items():
                rows = []
                for y in years:
                    arrays = {}
                    for var in VARS:
                        lat, lon, data = read_subset(paths[(model, scenario, var, y)], var, y)
                        if grid is None:
                            grid = (lat, lon, cell_weights(lat, lon, county))
                        if not (np.allclose(lat, grid[0]) and np.allclose(lon, grid[1])):
                            raise ValueError(f"{model} {scenario} {var} {y}: grid differs from the first file")
                        ii = [c[0] for c in grid[2]]
                        jj = [c[1] for c in grid[2]]
                        arrays[var] = data[:, ii, jj]
                    rows.append(outlook.year_summary(arrays["pr"], arrays["tasmax"], arrays["tasmin"],
                                                     [c[4] for c in grid[2]]))
                means[scenario] = outlook.window_mean(rows)
            per_model_windows[model] = means
        except Exception as exc:  # noqa: BLE001
            dropped[model] = f"computation failed: {exc}"
            log.warning("dropping %s: %s", model, exc)

    used = sorted(per_model_windows)
    if len(used) < 5:
        raise SystemExit(f"only {len(used)} models usable ({dropped}); need at least five")
    scenarios_out = {}
    for sc in SCENARIOS:
        changes = {m: outlook.model_change(per_model_windows[m]["historical"], per_model_windows[m][sc])
                   for m in used}
        scenarios_out[sc] = outlook.scenario_summary(changes)
    baseline = outlook.baseline_summary({m: per_model_windows[m]["historical"] for m in used})
    runs = {m: variant(m, "historical") for m in used}

    def yr_note(ys):
        return f"{ys[0]}-{ys[-1]}" + ("" if args.step == 1 else f", every {args.step} years: {ys}")

    result = {
        "generated": dt.date.today().isoformat(),
        "source": ("NASA NEX-GDDP-CMIP6 (bias-corrected, downscaled CMIP6 daily projections, 0.25 degree), "
                   "read from the NASA Center for Climate Simulation THREDDS server "
                   f"({THREDDS}/catalog/{ROOT_PATH}/catalog.html) with its NetCDF Subset Service; "
                   "the same dataset is on Microsoft Planetary Computer as nasa-nex-gddp-cmip6."),
        "source_url": "https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6",
        "region": {
            "name": region_cfg["name"], "fips": region_cfg["fips"],
            "bbox": [round(v, 4) for v in bbox], "outline": outline_source,
            "grid": "0.25 degree NEX-GDDP-CMIP6 cells; centres listed; weight = share of county area",
            "cells": [{"lat": la, "lon": lo, "weight": round(wt, 4)} for _, _, la, lo, wt in grid[2]],
        },
        "historical": [hist_years[0], hist_years[-1]],
        "mid_century": [fut_years[0], fut_years[-1]],
        "years_used": {"historical": hist_years, "mid_century": fut_years},
        "models": used,
        "model_runs": runs,
        "n_models": len(used),
        "scenarios": scenarios_out,
        "baseline": baseline,
        "notes": [
            f"Historical window {yr_note(hist_years)} (experiment 'historical'); mid-century window "
            f"{yr_note(fut_years)} under ssp245 (middle-of-the-road emissions) and ssp585 (high emissions).",
            "Each change is one model's mid-century mean minus the same model's historical mean; the summary "
            "gives the median across models, the middle half (p25-p75) and the full range (min-max).",
            "April-July precipitation: daily precipitation (kg m-2 s-1 x 86400 = mm/day) averaged over the grid "
            "cells with area weights, summed over April-July; percent change is relative to the model's own "
            "historical mean. Inches = mm / 25.4.",
            "Hot days: June-July days with daily maximum temperature at or above 90 F (305.37 K), counted in "
            "each grid cell separately and then area-weighted, i.e. the count at a typical spot in the county "
            "(not the count of the county-averaged series, which would smooth extremes).",
            "Mean temperature: annual mean of (daily max + daily min) / 2, area-weighted; changes in F = changes "
            "in C x 9/5.",
            "Grid cells: every 0.25 degree cell overlapping the county outline, weighted by the share of the "
            "county it covers (cos-latitude area).",
            "File versions: the newest version NCCS lists for each file (v1.1 or v2.0 where available); "
            "Planetary Computer hosts the original v1.0 files.",
            "Bias correction makes each model's historical climate close to the observation-based reference, "
            "so the baseline describes the reference climate; trust the changes, not small baseline differences.",
            "The models disagree on rain. This outlook is a separate panel and never feeds the strategy scoring.",
        ],
    }
    if dropped:
        result["models_dropped"] = dropped
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=1) + "\n")
    log.info("wrote %s with %d models in %.0f s", out, len(used), time.time() - started)


if __name__ == "__main__":
    main()
