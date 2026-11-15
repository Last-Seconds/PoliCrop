"""The 2050 outlook: pure arithmetic over daily climate-model grids.

Used only by the offline tool ``tools/build_outlook.py``; the result is a data
file shown as a separate panel and never feeds the scoring.

Inputs are daily arrays shaped (days, cells) for one model year, in the source
units of NEX-GDDP-CMIP6: precipitation in kg m-2 s-1, temperature in kelvin.
Cells are combined with area weights (the share of the county each grid cell
covers). Everything here is numpy and the standard library.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np

from .units import MM_PER_IN, delta_c_to_f

SECONDS_PER_DAY = 86400.0  # kg m-2 s-1 of water is 1 mm s-1
KELVIN_OFFSET = 273.15
HOT_DAY_F = 90.0
SPRING_MONTHS = (4, 5, 6, 7)  # April–July precipitation
HOT_MONTHS = (6, 7)  # June–July hot days

_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def k_to_f(k):
    return (np.asarray(k, dtype=float) - KELVIN_OFFSET) * 9.0 / 5.0 + 32.0


def f_to_k(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0 + KELVIN_OFFSET


def flux_to_mm_day(pr):
    return np.asarray(pr, dtype=float) * SECONDS_PER_DAY


def months_for_year(n_days: int) -> np.ndarray:
    """Calendar month (1–12) of each day in a model year of 365, 366 or 360 days.

    365 covers both a common Gregorian year and the no-leap calendar; 366 is a
    Gregorian leap year; 360 is the 360-day calendar (twelve 30-day months).
    """
    if n_days == 360:
        lengths = [30] * 12
    elif n_days in (365, 366):
        lengths = list(_MONTH_DAYS)
        if n_days == 366:
            lengths[1] = 29
    else:
        raise ValueError(f"a model year must have 360, 365 or 366 days, not {n_days}")
    return np.repeat(np.arange(1, 13), lengths)


def normalise_weights(weights: Sequence[float]) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or w.size == 0 or np.any(w < 0) or not np.isfinite(w).all() or w.sum() <= 0:
        raise ValueError("cell weights must be a non-empty list of non-negative numbers with a positive sum")
    return w / w.sum()


def _check(arr, name: str, lo: float, hi: float) -> np.ndarray:
    a = np.asarray(arr, dtype=float)
    if a.ndim != 2:
        raise ValueError(f"{name} must be shaped (days, cells)")
    if not np.isfinite(a).all():
        raise ValueError(f"{name} has missing values")
    if a.min() < lo or a.max() > hi:
        raise ValueError(f"{name} is outside the plausible range {lo}..{hi}")
    return a


def year_summary(pr, tasmax, tasmin, weights) -> dict:
    """One model year over the county.

    - apr_jul_precip_mm: April–July total of the area-weighted daily precipitation.
    - hot_days: June–July days with daily maximum at or above 90 °F, counted in each
      grid cell, then area-weighted across cells (a typical spot in the county).
    - mean_temp_c: area-weighted annual mean of the daily (max + min) / 2.
    """
    pr = _check(pr, "pr", 0.0, 0.05)  # 0.05 kg m-2 s-1 is 4,320 mm/day
    tasmax = _check(tasmax, "tasmax", 180.0, 340.0)
    tasmin = _check(tasmin, "tasmin", 180.0, 340.0)
    if not (pr.shape == tasmax.shape == tasmin.shape):
        raise ValueError(f"pr, tasmax and tasmin shapes differ: {pr.shape}, {tasmax.shape}, {tasmin.shape}")
    w = normalise_weights(weights)
    if w.size != pr.shape[1]:
        raise ValueError("one weight per grid cell is required")
    months = months_for_year(pr.shape[0])

    spring = np.isin(months, SPRING_MONTHS)
    precip_mm = float((flux_to_mm_day(pr[spring]) @ w).sum())

    hot = np.isin(months, HOT_MONTHS)
    counts = (tasmax[hot] >= f_to_k(HOT_DAY_F)).sum(axis=0)  # per cell
    hot_days = float(counts @ w)

    mean_k = float((((tasmax + tasmin) / 2.0).mean(axis=0)) @ w)
    return {"apr_jul_precip_mm": precip_mm, "hot_days": hot_days, "mean_temp_c": mean_k - KELVIN_OFFSET}


def window_mean(years: Iterable[Mapping[str, float]]) -> dict:
    """Average of year summaries over a window of years."""
    rows = list(years)
    if not rows:
        raise ValueError("a window needs at least one year")
    keys = ("apr_jul_precip_mm", "hot_days", "mean_temp_c")
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


def model_change(hist: Mapping[str, float], future: Mapping[str, float]) -> dict:
    """Change from the historical window mean to the future window mean, for one model."""
    dp = future["apr_jul_precip_mm"] - hist["apr_jul_precip_mm"]
    pct = 100.0 * dp / hist["apr_jul_precip_mm"] if hist["apr_jul_precip_mm"] > 0 else float("nan")
    dt = future["mean_temp_c"] - hist["mean_temp_c"]
    return {
        "apr_jul_precip_change_pct": pct,
        "apr_jul_precip_change_mm": dp,
        "apr_jul_precip_change_in": dp / MM_PER_IN,
        "hot_days_change": future["hot_days"] - hist["hot_days"],
        "mean_temp_change_c": dt,
        "mean_temp_change_f": delta_c_to_f(dt),
    }


def spread(values: Iterable[float], digits: int = 2) -> dict:
    """Median, min, max and 25–75 % range across models (linear interpolation percentiles)."""
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        raise ValueError("no values to summarise")
    r = lambda x: round(float(x), digits)  # noqa: E731
    return {"median": r(np.median(v)), "min": r(v.min()), "max": r(v.max()),
            "p25": r(np.percentile(v, 25)), "p75": r(np.percentile(v, 75)), "n": int(v.size)}


CHANGE_KEYS = ("apr_jul_precip_change_pct", "apr_jul_precip_change_in", "apr_jul_precip_change_mm",
               "hot_days_change", "mean_temp_change_f", "mean_temp_change_c")


def scenario_summary(per_model: Mapping[str, Mapping[str, float]]) -> dict:
    """Spread of each change across models, plus the per-model rows (rounded)."""
    if not per_model:
        raise ValueError("no models")
    out = {k: spread(m[k] for m in per_model.values()) for k in CHANGE_KEYS}
    out["models_agree_on_precip_sign"] = _agreement(m["apr_jul_precip_change_pct"] for m in per_model.values())
    out["per_model"] = [{"model": name, **{k: round(float(v[k]), 2) for k in CHANGE_KEYS}}
                        for name, v in sorted(per_model.items())]
    return out


def _agreement(values: Iterable[float]) -> dict:
    v = [x for x in values if np.isfinite(x)]
    return {"wetter": sum(x > 0 for x in v), "drier": sum(x < 0 for x in v), "n": len(v)}


def baseline_summary(hist_by_model: Mapping[str, Mapping[str, float]]) -> dict:
    """Historical-window values: the median across models at the top level, the full spread under
    ``spread``; US units with the raw metric numbers kept."""
    p = [h["apr_jul_precip_mm"] for h in hist_by_model.values()]
    d = [h["hot_days"] for h in hist_by_model.values()]
    t = [h["mean_temp_c"] for h in hist_by_model.values()]
    full = {
        "apr_jul_precip_in": spread([x / MM_PER_IN for x in p]),
        "apr_jul_precip_mm": spread(p, 1),
        "hot_days": spread(d, 1),
        "mean_temp_f": spread([x * 9.0 / 5.0 + 32.0 for x in t]),
        "mean_temp_c": spread(t),
    }
    return {**{k: v["median"] for k, v in full.items()}, "spread": full}
