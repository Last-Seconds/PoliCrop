"""Vegetation index series for a field, gaps, and bare periods (historical data only)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .content import Settings


@dataclass(frozen=True)
class Obs:
    date: dt.date
    ndvi: float | None
    valid_fraction: float
    scene: str


def validate_observations(raw_years: list[dict]) -> list[Obs]:
    """Merge yearly provider outputs; drop malformed records; one observation per date."""
    by_date: dict[dt.date, Obs] = {}
    for raw in raw_years:
        for rec in (raw or {}).get("observations") or []:
            try:
                d = dt.date.fromisoformat(str(rec["date"])[:10])
                vf = float(rec.get("valid_fraction") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            ndvi = rec.get("ndvi")
            try:
                ndvi = None if ndvi is None else float(ndvi)
            except (TypeError, ValueError):
                ndvi = None
            if ndvi is not None and not (-1.0 <= ndvi <= 1.0):
                ndvi = None
            vf = min(max(vf, 0.0), 1.0)
            o = Obs(d, ndvi, vf, str(rec.get("scene", "")))
            prev = by_date.get(d)
            if prev is None or o.valid_fraction > prev.valid_fraction:
                by_date[d] = o
    return [by_date[d] for d in sorted(by_date)]


def usable(obs: list[Obs], settings: Settings) -> list[Obs]:
    minf = float(settings["vegetation.min_valid_fraction"])
    return [o for o in obs if o.ndvi is not None and o.valid_fraction >= minf]


def segments(valid: list[Obs], max_gap_days: int) -> list[list[Obs]]:
    """Split the series wherever two usable images are further apart than max_gap_days."""
    out: list[list[Obs]] = []
    for o in valid:
        if out and (o.date - out[-1][-1].date).days <= max_gap_days:
            out[-1].append(o)
        else:
            out.append([o])
    return out


def gaps(valid: list[Obs], max_gap_days: int, start: dt.date, end: dt.date) -> list[dict]:
    """Periods longer than max_gap_days with no usable image (including at the ends)."""
    out = []
    points = [start] + [o.date for o in valid] + [end]
    for a, b in zip(points, points[1:]):
        if (b - a).days > max_gap_days:
            out.append({"start": a.isoformat(), "end": b.isoformat(), "days": (b - a).days})
    return out


def bare_periods(valid: list[Obs], settings: Settings) -> list[dict]:
    """Runs of consecutive usable images below the bare threshold.

    A period spans only the observed dates (first to last bare image), and is
    never carried across a gap in the imagery: unknown is not the same as bare.
    """
    thr = float(settings["vegetation.bare_ndvi_threshold"])
    min_obs = int(settings["vegetation.min_bare_observations"])
    max_gap = int(settings["vegetation.max_gap_days"])
    periods = []
    for seg in segments(valid, max_gap):
        run: list[Obs] = []
        for o in seg + [None]:
            if o is not None and o.ndvi < thr:
                run.append(o)
                continue
            if len(run) >= min_obs:
                periods.append({
                    "start": run[0].date.isoformat(),
                    "end": run[-1].date.isoformat(),
                    "days": (run[-1].date - run[0].date).days + 1,
                    "observations": len(run),
                    "mean_ndvi": round(sum(r.ndvi for r in run) / len(run), 3),
                })
            run = []
    return periods


def vegetation_summary(raw_years: list[dict], settings: Settings, start: dt.date, end: dt.date) -> dict:
    obs = validate_observations(raw_years)
    valid = usable(obs, settings)
    max_gap = int(settings["vegetation.max_gap_days"])
    used = set(valid)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "observations": [
            {"date": o.date.isoformat(), "ndvi": round(o.ndvi, 4) if o.ndvi is not None else None,
             "valid_fraction": round(o.valid_fraction, 3), "used": o in used}
            for o in obs
        ],
        "segments": [[{"date": o.date.isoformat(), "ndvi": round(o.ndvi, 4)} for o in seg]
                     for seg in segments(valid, max_gap)],
        "gaps": gaps(valid, max_gap, start, end),
        "bare_periods": bare_periods(valid, settings),
        "counts": {"images_read": len(obs), "images_used": len(valid)},
    }
