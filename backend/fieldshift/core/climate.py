"""Climate indicators from a daily weather record (historical data only).

All values here are in internal units (mm, °C); the service converts at the
display edge. Dates a source leaves out by design (Daymet's 31 December in leap
years, `calendar: "365_day"`) do not make a month or year incomplete.
"""
from __future__ import annotations

import calendar as cal
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from . import units
from .content import Settings

# Plausible physical ranges; values outside are treated as missing.
PRECIP_RANGE = (0.0, 500.0)  # mm/day
TEMP_RANGE = (-70.0, 60.0)  # deg C


@dataclass(frozen=True)
class Day:
    date: dt.date
    precip_mm: float | None
    tmax_c: float | None
    tmin_c: float | None


def _clean(value, lo: float, hi: float) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v <= -999 or not (lo <= v <= hi):  # NaN, fill value, out of range
        return None
    return v


def validate_days(raw: dict) -> list[Day]:
    days: dict[dt.date, Day] = {}
    for rec in (raw or {}).get("days") or []:
        try:
            d = dt.date.fromisoformat(str(rec["date"]))
        except (KeyError, TypeError, ValueError):
            continue
        tmax = _clean(rec.get("tmax_c"), *TEMP_RANGE)
        tmin = _clean(rec.get("tmin_c"), *TEMP_RANGE)
        if tmax is not None and tmin is not None and tmin > tmax + 0.5:
            tmax = tmin = None  # inconsistent pair
        days[d] = Day(d, _clean(rec.get("precip_mm"), *PRECIP_RANGE), tmax, tmin)
    return [days[d] for d in sorted(days)]


def _complete(n_valid: int, n_days: int, min_fraction: float) -> bool:
    return n_days > 0 and n_valid / n_days >= min_fraction


def _is_leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _dropped_in_month(y: int, m: int, calendar: str | None) -> int:
    return 1 if calendar == "365_day" and m == 12 and _is_leap(y) else 0


def crop_year_of(d: dt.date, start_month: int) -> int:
    """Crop year labelled by its harvest year: Sep 2023-Aug 2024 -> 2024 (start_month=9)."""
    if start_month == 1:
        return d.year
    return d.year + 1 if d.month >= start_month else d.year


def crop_year_label(year: int, start_month: int) -> str:
    if start_month == 1:
        return str(year)
    return f"{year - 1}–{str(year)[-2:]}"


def _days_in_crop_year(cy: int, start_month: int, calendar: str | None = None) -> int:
    if start_month == 1:
        first, last = dt.date(cy, 1, 1), dt.date(cy, 12, 31)
    else:
        first = dt.date(cy - 1, start_month, 1)
        last = dt.date(cy, start_month, 1) - dt.timedelta(days=1)
    n = (last - first).days + 1
    if calendar == "365_day":
        for y in {first.year, last.year}:
            d31 = dt.date(y, 12, 31)
            if first <= d31 <= last and _is_leap(y):
                n -= 1
    return n


def monthly_rainfall(days: list[Day], settings: Settings, calendar: str | None = None) -> dict:
    """Average precipitation per calendar month with the driest and wettest year's value."""
    minf = float(settings["climate.min_complete_fraction"])
    totals: dict[tuple[int, int], list[float]] = defaultdict(list)
    for d in days:
        if d.precip_mm is not None:
            totals[(d.date.year, d.date.month)].append(d.precip_mm)
    per_month: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for (y, m), vals in totals.items():
        expected = cal.monthrange(y, m)[1] - _dropped_in_month(y, m, calendar)
        if _complete(len(vals), expected, minf):
            per_month[m].append((y, sum(vals)))
    rows = []
    for m in range(1, 13):
        vals = per_month.get(m, [])
        if not vals:
            rows.append({"month": m, "mean_mm": None, "min_mm": None, "max_mm": None, "years": 0})
            continue
        lo = min(vals, key=lambda t: t[1])
        hi = max(vals, key=lambda t: t[1])
        rows.append({
            "month": m,
            "mean_mm": round(mean(v for _, v in vals), 1),
            "min_mm": round(lo[1], 1), "min_year": lo[0],
            "max_mm": round(hi[1], 1), "max_year": hi[0],
            "years": len(vals),
        })
    years = sorted({y for vals in per_month.values() for y, _ in vals})
    return {"months": rows, "first_year": years[0] if years else None, "last_year": years[-1] if years else None}


def yearly_rainfall(days: list[Day], settings: Settings, calendar: str | None = None) -> dict:
    start = int(settings["climate.crop_year_start_month"])
    minf = float(settings["climate.min_complete_fraction"])
    sums: dict[int, float] = defaultdict(float)
    valid: dict[int, int] = defaultdict(int)
    n_days: dict[int, int] = defaultdict(int)
    for d in days:
        cy = crop_year_of(d.date, start)
        n_days[cy] += 1
        if d.precip_mm is not None:
            sums[cy] += d.precip_mm
            valid[cy] += 1
    rows = []
    for cy in sorted(n_days):
        expected = _days_in_crop_year(cy, start, calendar)
        complete = _complete(valid[cy], expected, minf)
        rows.append({
            "year": cy, "label": crop_year_label(cy, start),
            "total_mm": round(sums[cy], 1) if complete else None,
            "complete": complete, "days_with_data": valid[cy], "days_expected": expected,
        })
    return {"years": rows, "crop_year_start_month": start}


def monthly_temperature(days: list[Day], settings: Settings, calendar: str | None = None) -> dict:
    minf = float(settings["climate.min_complete_fraction"])
    acc: dict[tuple[int, int], tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for d in days:
        if d.tmax_c is not None and d.tmin_c is not None:
            hi, lo = acc[(d.date.year, d.date.month)]
            hi.append(d.tmax_c)
            lo.append(d.tmin_c)
    per_month: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for (y, m), (hi, lo) in acc.items():
        expected = cal.monthrange(y, m)[1] - _dropped_in_month(y, m, calendar)
        if _complete(len(hi), expected, minf):
            per_month[m].append((mean(hi), mean(lo)))
    rows = []
    for m in range(1, 13):
        vals = per_month.get(m, [])
        rows.append({
            "month": m,
            "mean_tmax_c": round(mean(v[0] for v in vals), 1) if vals else None,
            "mean_tmin_c": round(mean(v[1] for v in vals), 1) if vals else None,
            "years": len(vals),
        })
    return {"months": rows}


def frost_days(days: list[Day], settings: Settings, calendar: str | None = None) -> dict:
    start = int(settings["climate.crop_year_start_month"])
    minf = float(settings["climate.min_complete_fraction"])
    thr = units.f_to_c(float(settings["climate.frost_threshold_f"]))
    count: dict[int, int] = defaultdict(int)
    valid: dict[int, int] = defaultdict(int)
    seen: set[int] = set()
    for d in days:
        cy = crop_year_of(d.date, start)
        seen.add(cy)
        if d.tmin_c is not None:
            valid[cy] += 1
            if d.tmin_c < thr:
                count[cy] += 1
    rows = []
    for cy in sorted(seen):
        complete = _complete(valid[cy], _days_in_crop_year(cy, start, calendar), minf)
        rows.append({"year": cy, "label": crop_year_label(cy, start),
                     "frost_days": count[cy] if complete else None, "complete": complete})
    return {"years": rows, "threshold_c": thr, "crop_year_start_month": start}


def growing_season_periods(days: list[Day], settings: Settings, calendar: str | None = None) -> dict:
    """April–July precipitation and June–July hot days, averaged over the configured periods.

    This is where the change in the record shows (docs/DATA_SOURCES.md): yearly
    precipitation is flat while spring rain falls and summer heat rises.
    """
    hot_c = units.f_to_c(float(settings["climate.hot_day_threshold_f"]))
    start = int(settings["climate.crop_year_start_month"])
    by_year_rain: dict[int, list[float]] = defaultdict(list)
    by_year_hot: dict[int, int] = defaultdict(int)
    by_year_t: dict[int, int] = defaultdict(int)
    for d in days:
        y, m = d.date.year, d.date.month
        if 4 <= m <= 7 and d.precip_mm is not None:
            by_year_rain[y].append(d.precip_mm)
        if m in (6, 7) and d.tmax_c is not None:
            by_year_t[y] += 1
            if d.tmax_c >= hot_c:
                by_year_hot[y] += 1
    rain = {y: sum(v) for y, v in by_year_rain.items() if len(v) == 122}
    hot = {y: by_year_hot[y] for y, n in by_year_t.items() if n == 61}
    yearly = {r["year"]: r["total_mm"] for r in yearly_rainfall(days, settings, calendar)["years"] if r["complete"]}
    periods = []
    for a, b in settings["climate.trend_periods"]:
        ys = range(int(a), int(b) + 1)
        r = [rain[y] for y in ys if y in rain]
        h = [hot[y] for y in ys if y in hot]
        t = [yearly[y] for y in ys if y in yearly]
        periods.append({
            "first": int(a), "last": int(b),
            "apr_jul_mm": round(mean(r), 1) if r else None, "rain_years": len(r),
            "hot_days": round(mean(h), 1) if h else None, "hot_years": len(h),
            "crop_year_mm": round(mean(t), 1) if t else None, "crop_years": len(t),
        })
    return {"periods": periods, "hot_threshold_c": hot_c,
            "per_year": [{"year": y, "apr_jul_mm": round(rain.get(y), 1) if y in rain else None,
                          "hot_days": hot.get(y)} for y in sorted(set(rain) | set(hot))],
            "crop_year_start_month": start}


def climate_summary(raw: dict, settings: Settings) -> dict:
    days = validate_days(raw)
    if not days:
        raise ValueError("The weather record contained no usable days.")
    calendar = (raw or {}).get("calendar")
    valid_precip = sum(1 for d in days if d.precip_mm is not None)
    return {
        "record": {
            "first_date": days[0].date.isoformat(),
            "last_date": days[-1].date.isoformat(),
            "days": len(days),
            "days_missing_precip": len(days) - valid_precip,
            "calendar": calendar,
        },
        "rainfall_monthly": monthly_rainfall(days, settings, calendar),
        "rainfall_yearly": yearly_rainfall(days, settings, calendar),
        "temperature_monthly": monthly_temperature(days, settings, calendar),
        "frost_days": frost_days(days, settings, calendar),
        "growing_season": growing_season_periods(days, settings, calendar),
    }
