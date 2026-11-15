"""Check the field's gridded weather against the nearest long-record weather station.

Pure logic, no network: the station list and the station's daily record come in
as plain payloads (see providers.us.acis), the gridded record as the
WeatherProvider payload (Daymet). The result is a summary dict for the evidence
section; all values are internal units (mm, km, m) with inch and mile copies for
display.

Method
------
1. Candidates: stations whose precipitation record overlaps the gridded record by
   at least `min_years` years and that lie within `max_distance_km` of the field
   centroid, nearest first.
2. For each candidate in turn (at most `max_candidates`), fetch its daily record
   and compare crop-year totals (1 September to 31 August by default, labelled by
   the end year). The first candidate with at least `min_years` comparable crop
   years is chosen. Distance decides, not agreement: the comparison never picks
   the station that happens to agree best.
3. Which station days count towards a total. ACIS writes a multi-day
   accumulation as "S" on its first day, "M" on the days between, and the
   amount with a trailing "A" on its last day: S, M, M, 0.25A. Checked on
   2026-11-15 against NOAA's GHCN-Daily file for LaCrosse (USC00454338): for all
   54 accumulations from 1979 to 2021 the days from S to A inclusive equal the
   GHCN day count (DAPR) and the A amount equals the GHCN total (MDPR).
     ordinary value or trace ("T", counted as 0)          usable
     missing ("M") outside an accumulation                 not usable
     a run S, then S or M days, then A                     usable as a whole; the A
                                                           value is the run's total
     an S run that ends in anything but A                  not usable (the total was
                                                           never reported)
     an A with no S before it (ACIS gives no start; the
     GHCN file has no day count for these either)          not usable
     a run that crosses the crop-year boundary             not usable (its rain cannot
                                                           be split between years)
4. A crop year is comparable when at least `min_complete_fraction` of its days are
   usable at the station and present in the grid. Both totals are then summed
   over the *same* days (station usable and grid present; an S..A run only if the
   grid has every day of it). This keeps a few missing station days from showing
   up as a difference. Daymet leaves out 31 December in leap years by design
   (`calendar: "365_day"`), so that day is left out of both totals.

Defaults (the integrator feeds these from settings; all are engineering choices):
    crop_year_start_month   9     month   crop years run Sep-Aug, as climate.crop_year_start_month
    min_years               20    years   fewest comparable crop years for a station to be used
    max_distance_km         40    km      farthest station considered (about 25 miles)
    min_complete_fraction   0.98  share   share of a crop year's days that must be usable
    max_candidates          4     count   most stations fetched before giving up
    agreement_tolerance_pct 10    %       "within about 10%" (BUILD_BRIEF_2 section 12)
"""
from __future__ import annotations

import datetime as dt
import math
import re
from statistics import mean, median
from typing import Callable

import numpy as np

from . import units
from .climate import crop_year_label, crop_year_of
from .weather import DailySeries

KM_PER_MI = 1.609344
FT_PER_M = 1 / 0.3048
EARTH_RADIUS_KM = 6371.0088

DEFAULTS = {
    "crop_year_start_month": 9,
    "min_years": 20,
    "max_distance_km": 40.0,
    "min_complete_fraction": 0.98,
    "max_candidates": 4,
    "agreement_tolerance_pct": 10.0,
}


# --------------------------------------------------------------------- stations

def distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance (haversine on a sphere of the Earth's mean radius)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _overlap_years(ranges, first: dt.date | None, last: dt.date | None) -> float:
    days = 0
    for r in ranges or []:
        try:
            a, b = dt.date.fromisoformat(r[0]), dt.date.fromisoformat(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if first:
            a = max(a, first)
        if last:
            b = min(b, last)
        if b >= a:
            days += (b - a).days + 1
    return days / 365.25


def candidate_stations(stations: list[dict], lon: float, lat: float, *,
                       period: tuple[dt.date, dt.date] | None = None,
                       min_years: float = DEFAULTS["min_years"],
                       max_distance_km: float = DEFAULTS["max_distance_km"]) -> list[dict]:
    """Stations close enough with a long enough precipitation record, nearest first.

    `stations` are the entries of AcisStations.stations()["stations"]. The record
    length counts only the part inside `period` (the gridded record's span). This
    is the period of record, not its completeness; completeness is checked on the
    data. Each returned entry is a copy with `distance_km` and `record_years` added.
    """
    first, last = period if period else (None, None)
    out = []
    for s in stations or []:
        try:
            d = distance_km(lon, lat, float(s["lon"]), float(s["lat"]))
        except (KeyError, TypeError, ValueError):
            continue
        years = _overlap_years(s.get("valid_daterange"), first, last)
        if d <= max_distance_km and years >= min_years:
            out.append({**s, "distance_km": round(d, 2), "record_years": round(years, 1)})
    out.sort(key=lambda s: (s["distance_km"], s.get("id", "")))
    return out


_DIRECTION = re.compile(r"^[NSEW]{1,3}$")
_KEEP_UPPER = {"AP", "WB", "WSO", "FAA", "USFS", "NWS", "II", "III"}


def display_name(name: str) -> str:
    """"PULLMAN 2 NW" -> "Pullman 2 NW"; "ST. JOHN" -> "St. John"."""
    words = []
    for w in str(name).split():
        words.append(w if (_DIRECTION.match(w) or w in _KEEP_UPPER or any(c.isdigit() for c in w))
                     else w.capitalize())
    return " ".join(words)


# --------------------------------------------------------------- station totals

def _parse_station_days(days: list[dict]) -> tuple[list[dt.date], list[float | None], list[str | None]]:
    by_date: dict[dt.date, tuple[float | None, str | None]] = {}
    for rec in days or []:
        try:
            d = dt.date.fromisoformat(str(rec["date"]))
        except (KeyError, TypeError, ValueError):
            continue
        v = rec.get("precip_mm")
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            v = None
        if v is not None and (v != v or v < 0):
            v = None
        flag = rec.get("precip_flag")
        if flag in ("M",) or (v is None and flag not in ("S",)):
            v, flag = None, "M"
        by_date[d] = (v, flag)
    if not by_date:
        return [], [], []
    first, last = min(by_date), max(by_date)
    dates = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    vals = [by_date.get(d, (None, "M"))[0] for d in dates]
    flags = [by_date.get(d, (None, "M"))[1] for d in dates]
    return dates, vals, flags


def usable_for_totals(dates: list[dt.date], vals: list[float | None], flags: list[str | None],
                      start_month: int = DEFAULTS["crop_year_start_month"]) -> dict:
    """Decide which station days count towards totals (rules in the module docstring).

    Returns {"amount": [mm per day, 0 on S days], "usable": [bool], "run": [run id or -1],
             "runs_used": int, "runs_rejected": int}. `dates` must be consecutive.
    """
    n = len(dates)
    amount = [0.0] * n
    usable = [False] * n
    run = [-1] * n
    used = rejected = 0
    i = 0
    while i < n:
        f = flags[i]
        if f == "S":
            j = i
            while j < n and flags[j] in ("S", "M"):
                j += 1
            ok = (j < n and flags[j] == "A" and vals[j] is not None
                  and crop_year_of(dates[i], start_month) == crop_year_of(dates[j], start_month))
            if ok:
                for k in range(i, j + 1):
                    usable[k] = True
                    run[k] = i
                amount[j] = float(vals[j])
                used += 1
                i = j + 1
            else:
                rejected += 1
                # an A ending a run that crosses crop years is unusable too; anything else is re-read
                i = j + 1 if (j < n and flags[j] == "A") else j
            continue
        if f == "A":  # an accumulation with no S days before it: its period is unknown
            rejected += 1
        elif vals[i] is not None:
            usable[i] = True
            amount[i] = float(vals[i])
        i += 1
    return {"amount": amount, "usable": usable, "run": run, "runs_used": used, "runs_rejected": rejected}


def _crop_year_bounds(cy: int, start_month: int) -> tuple[dt.date, dt.date]:
    if start_month == 1:
        return dt.date(cy, 1, 1), dt.date(cy, 12, 31)
    return dt.date(cy - 1, start_month, 1), dt.date(cy, start_month, 1) - dt.timedelta(days=1)


def whole_crop_years(first: dt.date, last: dt.date, start_month: int) -> tuple[int, int]:
    """(first, last) crop year lying wholly between two dates; first > last when there is none."""
    a, b = crop_year_of(first, start_month), crop_year_of(last, start_month)
    if first != _crop_year_bounds(a, start_month)[0]:
        a += 1
    if last != _crop_year_bounds(b, start_month)[1]:
        b -= 1
    return a, b


def compare_totals(station_days: list[dict], grid_raw: dict, *,
                   crop_year_start_month: int = DEFAULTS["crop_year_start_month"],
                   min_complete_fraction: float = DEFAULTS["min_complete_fraction"]) -> dict:
    """Crop-year precipitation, station against grid, over the same days.

    Returns {"rows": [{"year", "label", "station_mm", "grid_mm", "difference_mm",
                       "days_compared", "days_expected", "accumulated_days"}],
             "excluded": [{"year", "label", "reason", "days_compared", "days_expected"}],
             "runs_used": int, "runs_rejected": int}
    Only crop years wholly inside both records are considered. `days_expected` leaves
    out days the grid omits by design (Daymet's 31 December in leap years).
    """
    start = int(crop_year_start_month)
    dates, vals, flags = _parse_station_days(station_days)
    if not dates:
        return {"rows": [], "excluded": [], "runs_used": 0, "runs_rejected": 0}
    use = usable_for_totals(dates, vals, flags, start)
    grid = DailySeries.from_raw(grid_raw)
    s_first, s_last = dates[0], dates[-1]
    lo, hi = max(s_first, grid.first), min(s_last, grid.last)

    # grid value per station day (NaN where the grid has no value, absent by design or missing)
    gvals = np.full(len(dates), np.nan)
    gabsent = np.zeros(len(dates), dtype=bool)  # left out by the grid's calendar, not missing
    if lo <= hi:
        a, b = (lo - s_first).days, (hi - s_first).days + 1
        gvals[a:b] = grid.precip[grid.idx(lo): grid.idx(hi) + 1]
        gabsent[a:b] = grid.absent[grid.idx(lo): grid.idx(hi) + 1]
    gpresent = ~np.isnan(gvals)
    usable = np.array(use["usable"], dtype=bool)
    amount = np.array(use["amount"])
    runs = np.array(use["run"])
    matched = usable & gpresent
    # an S..A run counts only if the grid has every day of it
    for rid in set(runs[runs >= 0].tolist()):
        members = runs == rid
        if not gpresent[members].all():
            matched[members] = False
    cy_first, cy_last = whole_crop_years(lo, hi, start)

    rows, excluded = [], []
    for cy in range(cy_first, cy_last + 1):
        a_d, b_d = _crop_year_bounds(cy, start)
        a, b = (a_d - s_first).days, (b_d - s_first).days + 1
        n_days = b - a
        n_expected = n_days - int(gabsent[a:b].sum())
        m = matched[a:b]
        n_ok = int(m.sum())
        label = crop_year_label(cy, start)
        if n_ok / n_expected < min_complete_fraction:
            excluded.append({"year": cy, "label": label, "reason": "incomplete",
                             "days_compared": n_ok, "days_expected": n_expected})
            continue
        st = float(amount[a:b][m].sum())
        gr = float(gvals[a:b][m].sum())
        rows.append({
            "year": cy, "label": label,
            "station_mm": round(st, 1), "grid_mm": round(gr, 1), "difference_mm": round(gr - st, 1),
            "days_compared": n_ok, "days_expected": n_expected,
            "accumulated_days": int((runs[a:b] >= 0)[m].sum()),
        })
    return {"rows": rows, "excluded": excluded,
            "runs_used": use["runs_used"], "runs_rejected": use["runs_rejected"]}


# ---------------------------------------------------------------------- summary

def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    x, y = np.array(xs), np.array(ys)
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _distance_words(km: float) -> str:
    mi = km / KM_PER_MI
    if mi < 1:
        return "less than a mile away"
    n = round(mi)
    return f"{n} mile away" if n == 1 else f"{n} miles away"


def summary_text(years: int, pct: float, name: str, km: float, tolerance_pct: float) -> str:
    where = f"the {name} weather station, {_distance_words(km)}"
    if abs(pct) <= tolerance_pct:
        within = max(1, math.ceil(round(abs(pct), 1)))  # the one-decimal figure shown, rounded up
        return f"Over {years} crop years, the grid estimate for your field was within {within}% of {where}."
    more = "wetter" if pct > 0 else "drier"
    return (f"Over {years} crop years, the grid estimate for your field was {round(abs(pct))}% {more} "
            f"than {where}.")


def summarize(station: dict, comparison: dict, *,
              crop_year_start_month: int = DEFAULTS["crop_year_start_month"],
              agreement_tolerance_pct: float = DEFAULTS["agreement_tolerance_pct"],
              grid_source: str | None = None) -> dict:
    """The evidence summary from a station entry (with distance_km) and compare_totals() output."""
    rows = comparison["rows"]
    st = [r["station_mm"] for r in rows]
    gr = [r["grid_mm"] for r in rows]
    st_mean, gr_mean = mean(st), mean(gr)
    pct = (gr_mean - st_mean) / st_mean * 100 if st_mean > 0 else None
    typical = median(abs(g - s) for g, s in zip(gr, st))
    corr = _correlation(st, gr)
    name = display_name(station.get("name", station.get("id", "")))
    km = float(station["distance_km"])
    elev_m = station.get("elevation_m")
    for r in rows:
        r["station_in"] = round(units.mm_to_in(r["station_mm"]), 2)
        r["grid_in"] = round(units.mm_to_in(r["grid_mm"]), 2)
        r["difference_in"] = round(units.mm_to_in(r["difference_mm"]), 2)
    return {
        "status": "ok",
        "station": {
            "id": station.get("id"), "name": name, "acis_name": station.get("name"),
            "lon": station.get("lon"), "lat": station.get("lat"),
            "distance_km": round(km, 1), "distance_mi": round(km / KM_PER_MI, 1),
            "elevation_m": elev_m,
            "elevation_ft": round(elev_m * FT_PER_M) if elev_m is not None else None,
            "valid_daterange": station.get("valid_daterange"),
        },
        "grid_source": grid_source,
        "crop_year_start_month": int(crop_year_start_month),
        "years_compared": len(rows),
        "first_year": rows[0]["year"], "last_year": rows[-1]["year"],
        "years_excluded": len(comparison["excluded"]),
        "station_mean_mm": round(st_mean, 1), "station_mean_in": round(units.mm_to_in(st_mean), 2),
        "grid_mean_mm": round(gr_mean, 1), "grid_mean_in": round(units.mm_to_in(gr_mean), 2),
        "percent_difference": round(pct, 1) if pct is not None else None,
        "correlation": round(corr, 3) if corr is not None else None,
        "typical_difference_mm": round(typical, 1),
        "typical_difference_in": round(units.mm_to_in(typical), 2),
        "agreement_tolerance_pct": agreement_tolerance_pct,
        "within_tolerance": pct is not None and abs(pct) <= agreement_tolerance_pct,
        "accumulations_used": comparison["runs_used"],
        "accumulations_rejected": comparison["runs_rejected"],
        "rows": rows,
        "excluded": comparison["excluded"],
        "text": summary_text(len(rows), pct or 0.0, name, km, agreement_tolerance_pct),
        "caveat": ("The grid (Daymet) is built by interpolating weather stations, very likely including "
                   "this one, so close agreement is partly by construction."),
    }


def _grid_period(grid_raw: dict) -> tuple[dt.date, dt.date]:
    dates = []
    for rec in (grid_raw or {}).get("days") or []:
        try:
            dates.append(dt.date.fromisoformat(str(rec["date"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not dates:
        raise ValueError("the gridded weather record has no days")
    return min(dates), max(dates)


def station_check(stations: list[dict], fetch_daily: Callable[[str, str, str], dict], grid_raw: dict,
                  lon: float, lat: float, *,
                  crop_year_start_month: int = DEFAULTS["crop_year_start_month"],
                  min_years: int = DEFAULTS["min_years"],
                  max_distance_km: float = DEFAULTS["max_distance_km"],
                  min_complete_fraction: float = DEFAULTS["min_complete_fraction"],
                  max_candidates: int = DEFAULTS["max_candidates"],
                  agreement_tolerance_pct: float = DEFAULTS["agreement_tolerance_pct"]) -> dict:
    """Choose the nearest usable long-record station and compare its crop-year totals with the grid.

    stations      AcisStations.stations(fips)["stations"] (several counties may be concatenated)
    fetch_daily   (station_id, "YYYY-MM-DD", "YYYY-MM-DD") -> AcisStations.daily() payload
    grid_raw      WeatherProvider.daily() payload for the field (Daymet)
    lon, lat      field centroid

    Returns summarize()'s dict plus "candidates_tried", or, when no station
    qualifies, {"status": "no_station", "text": str, "candidates_tried": [...],
    "parameters": {...}}. Every return carries "parameters".
    """
    params = {"crop_year_start_month": crop_year_start_month, "min_years": min_years,
              "max_distance_km": max_distance_km, "min_complete_fraction": min_complete_fraction,
              "max_candidates": max_candidates, "agreement_tolerance_pct": agreement_tolerance_pct}
    g_first, g_last = _grid_period(grid_raw)
    start = int(crop_year_start_month)
    # station request spans whole crop years inside the grid record
    cy_a, cy_b = whole_crop_years(g_first, g_last, start)
    if cy_a > cy_b:
        raise ValueError("the gridded weather record holds no whole crop year")
    req_a, req_b = _crop_year_bounds(cy_a, start)[0], _crop_year_bounds(cy_b, start)[1]

    tried = []
    for cand in candidate_stations(stations, lon, lat, period=(req_a, req_b), min_years=min_years,
                                   max_distance_km=max_distance_km)[:max(0, int(max_candidates))]:
        entry = {"id": cand["id"], "name": display_name(cand["name"]), "distance_km": cand["distance_km"],
                 "record_years": cand["record_years"]}
        try:
            payload = fetch_daily(cand["id"], req_a.isoformat(), req_b.isoformat())
        except Exception as exc:  # one station failing must not end the search
            tried.append({**entry, "years_compared": 0, "outcome": f"fetch failed: {exc}"})
            continue
        comp = compare_totals((payload or {}).get("days") or [], grid_raw, crop_year_start_month=start,
                              min_complete_fraction=min_complete_fraction)
        n = len(comp["rows"])
        if n < max(1, min_years):
            tried.append({**entry, "years_compared": n, "outcome": f"only {n} near-complete crop years"})
            continue
        tried.append({**entry, "years_compared": n, "outcome": "chosen"})
        out = summarize(cand, comp, crop_year_start_month=start, agreement_tolerance_pct=agreement_tolerance_pct,
                        grid_source=(grid_raw or {}).get("source"))
        out["candidates_tried"] = tried
        out["parameters"] = params
        return out
    return {
        "status": "no_station",
        "text": (f"No weather station within {round(max_distance_km / KM_PER_MI)} miles has "
                 f"{min_years} or more near-complete years to check the grid estimate against."),
        "candidates_tried": tried,
        "parameters": params,
    }
