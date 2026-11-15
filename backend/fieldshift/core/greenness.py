"""Peak greenness per year from 250 m MODIS composites (historical data only).

Input: the yearly payloads of a MODIS NDVI provider, each
`{"year", "observations": [{"date", "ndvi", "pixels", "good_pixels", "platform"}],
"pixel_size_m", "source"}`, where `pixels` counts the 250 m pixels wholly inside
the field and `good_pixels` those of good quality in that composite.

Method, per year:
1. A composite is usable if it has an NDVI value and at least
   `min_good_fraction` of the field's whole pixels are good quality.
2. Terra and Aqua composites are merged into one series (they are offset by
   8 days). Only composites starting inside the season window are used.
3. The series is smoothed with a running mean of `smooth` consecutive usable
   composites, a window being accepted only if it spans at most
   `(smooth - 1) * pair_max_days` days (32 by default, so that in Terra-only
   years, 2000 to mid-2002, two good composites either side of an unusable
   one still pair up). Each composite is already the
   maximum of 16 days of looks, so a single composite is biased high and
   noisy; averaging two neighbours damps one-off spikes without flattening
   the season. The peak is the largest window mean; the peak date is the date
   of the greenest composite in that window. The highest single composite is
   reported beside it.
4. The mean of usable composites in a fixed late-spring window (1 May to
   30 June by default) is reported too. For winter wheat the peak saturates
   in April or May, before late-spring drought and heat bite; the window mean
   catches an early dry-down that the peak misses (2021 at the demo fields).
   It depends on crop timing, so compare it only between years of the same crop.
5. A year is reliable only if it has at least `min_good_composites` usable
   composites in the season and no gap longer than `max_gap_days` between
   usable composites (counting from the season's first day and to its last),
   since a longer gap could hide the peak.

If the field holds fewer than `min_whole_pixels` whole pixels, nothing is
computed and the status is "too_small", so the interface can say the field is
too small for 250 m pixels.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

PLATFORMS = ("terra", "aqua")

# Defaults (see the parameter descriptions in `peak_greenness`).
DEFAULTS = {
    "min_good_fraction": 0.5,
    "min_whole_pixels": 1,
    "season_start": (4, 1),
    "season_end": (8, 31),
    "smooth": 2,
    "pair_max_days": 32,
    "min_good_composites": 6,
    "max_gap_days": 40,
    "window_start": (5, 1),
    "window_end": (6, 30),
    "min_window_composites": 3,
}


@dataclass(frozen=True)
class Composite:
    date: dt.date
    platform: str
    ndvi: float | None
    pixels: int
    good_pixels: int


def validate_payloads(raw_years: list[dict]) -> tuple[dict[int, list[Composite]], float | None, str]:
    """Clean yearly payloads into {year: composites sorted by date}, plus pixel size and source.

    Malformed records are dropped; NDVI outside [-1, 1] becomes None; good
    pixels are capped at pixels; one composite is kept per (date, platform),
    the one with most good pixels. A composite is filed under the year of its
    date, whatever year the payload claimed.
    """
    by_key: dict[tuple[dt.date, str], Composite] = {}
    pixel_size = None
    source = ""
    for raw in raw_years or []:
        if not isinstance(raw, dict):
            continue
        try:
            ps = float(raw.get("pixel_size_m"))
            if ps > 0:
                pixel_size = ps
        except (TypeError, ValueError):
            pass
        source = source or str(raw.get("source") or "")
        for rec in raw.get("observations") or []:
            try:
                d = dt.date.fromisoformat(str(rec["date"])[:10])
                platform = str(rec.get("platform", "")).lower()
                pixels = int(rec.get("pixels") or 0)
                good = int(rec.get("good_pixels") or 0)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if platform not in PLATFORMS or pixels < 0 or good < 0:
                continue
            good = min(good, pixels)
            ndvi = rec.get("ndvi")
            try:
                ndvi = None if ndvi is None else float(ndvi)
            except (TypeError, ValueError):
                ndvi = None
            if ndvi is not None and not (-1.0 <= ndvi <= 1.0):
                ndvi = None
            if good == 0:
                ndvi = None
            c = Composite(d, platform, ndvi, pixels, good)
            prev = by_key.get((d, platform))
            if prev is None or c.good_pixels > prev.good_pixels:
                by_key[(d, platform)] = c
    years: dict[int, list[Composite]] = {}
    for key in sorted(by_key):
        c = by_key[key]
        years.setdefault(c.date.year, []).append(c)
    return years, pixel_size, source


def _usable(c: Composite, min_good_fraction: float) -> bool:
    return c.ndvi is not None and c.pixels > 0 and c.good_pixels / c.pixels >= min_good_fraction


def year_peak(composites: list[Composite], year: int, *,
              min_good_fraction: float = DEFAULTS["min_good_fraction"],
              season_start: tuple[int, int] = DEFAULTS["season_start"],
              season_end: tuple[int, int] = DEFAULTS["season_end"],
              smooth: int = DEFAULTS["smooth"],
              pair_max_days: int = DEFAULTS["pair_max_days"],
              min_good_composites: int = DEFAULTS["min_good_composites"],
              max_gap_days: int = DEFAULTS["max_gap_days"],
              window_start: tuple[int, int] = DEFAULTS["window_start"],
              window_end: tuple[int, int] = DEFAULTS["window_end"],
              min_window_composites: int = DEFAULTS["min_window_composites"]) -> dict:
    """Peak greenness for one year's composites (see the module docstring)."""
    start = dt.date(year, *season_start)
    end = dt.date(year, *season_end)
    season = [c for c in composites if start <= c.date <= end]
    good = sorted((c for c in season if _usable(c, min_good_fraction)), key=lambda c: c.date)

    peak = peak_date = None
    k = max(int(smooth), 1)
    for i in range(len(good) - k + 1):
        win = good[i:i + k]
        if (win[-1].date - win[0].date).days > (k - 1) * pair_max_days:
            continue
        mean = sum(c.ndvi for c in win) / k
        if peak is None or mean > peak:
            peak = mean
            peak_date = max(win, key=lambda c: c.ndvi).date
    single = max(good, key=lambda c: c.ndvi) if good else None
    w0, w1 = dt.date(year, *window_start), dt.date(year, *window_end)
    in_window = [c.ndvi for c in composites if w0 <= c.date <= w1 and _usable(c, min_good_fraction)]
    window_mean = sum(in_window) / len(in_window) if len(in_window) >= min_window_composites else None

    points = [start] + [c.date for c in good] + [end]
    longest_gap = max((b - a).days for a, b in zip(points, points[1:]))
    reasons = []
    if len(good) < min_good_composites:
        reasons.append("few_good_composites")
    if longest_gap > max_gap_days:
        reasons.append("gap_in_season")
    if peak is None:
        reasons.append("no_peak")
    return {
        "year": year,
        "peak_ndvi": round(peak, 4) if peak is not None else None,
        "peak_date": peak_date.isoformat() if peak_date else None,
        "peak_single_ndvi": round(single.ndvi, 4) if single else None,
        "peak_single_date": single.date.isoformat() if single else None,
        "window_mean_ndvi": round(window_mean, 4) if window_mean is not None else None,
        "window_composites": len(in_window),
        "good_composites": len(good),
        "season_composites": len(season),
        "longest_gap_days": longest_gap,
        "reliable": not reasons,
        "reasons": reasons,
    }


def peak_greenness(raw_years: list[dict], *,
                   min_good_fraction: float = DEFAULTS["min_good_fraction"],
                   min_whole_pixels: int = DEFAULTS["min_whole_pixels"],
                   season_start: tuple[int, int] = DEFAULTS["season_start"],
                   season_end: tuple[int, int] = DEFAULTS["season_end"],
                   smooth: int = DEFAULTS["smooth"],
                   pair_max_days: int = DEFAULTS["pair_max_days"],
                   min_good_composites: int = DEFAULTS["min_good_composites"],
                   max_gap_days: int = DEFAULTS["max_gap_days"],
                   window_start: tuple[int, int] = DEFAULTS["window_start"],
                   window_end: tuple[int, int] = DEFAULTS["window_end"],
                   min_window_composites: int = DEFAULTS["min_window_composites"]) -> dict:
    """Peak greenness per year since the first payload.

    Parameters (defaults in DEFAULTS):
    - min_good_fraction: share of the field's whole pixels that must be good
      quality for a composite to count (0.5).
    - min_whole_pixels: fewer whole 250 m pixels than this means "too_small" (1).
    - season_start, season_end: (month, day) bounds of the window searched for
      the peak (1 April to 31 August: winter wheat peaks late May to June,
      spring crops and canola June to July in the Palouse).
    - smooth: composites in the running mean (2; 1 means the plain maximum).
    - pair_max_days: most days between neighbouring usable composites in a
      smoothing window, per step (32: two Terra periods, so Terra-only years
      with one unusable composite still smooth; normally they are 8 apart).
    - min_good_composites: usable composites needed in the season (6).
    - max_gap_days: longest allowed gap between usable composites in the
      season, edges included (40).
    - window_start, window_end: (month, day) bounds of the late-spring window
      whose mean greenness is also reported (1 May to 30 June).
    - min_window_composites: usable composites needed for that mean (3).

    Returns {"status": "ok"|"too_small"|"no_data", "whole_pixels", "pixel_size_m",
    "years": [year_peak dicts, ascending], "source", "parameters"}.
    """
    params = dict(min_good_fraction=min_good_fraction, season_start=season_start, season_end=season_end,
                  smooth=smooth, pair_max_days=pair_max_days, min_good_composites=min_good_composites,
                  max_gap_days=max_gap_days, window_start=window_start, window_end=window_end,
                  min_window_composites=min_window_composites)
    years, pixel_size, source = validate_payloads(raw_years)
    all_comps = [c for comps in years.values() for c in comps]
    whole = max((c.pixels for c in all_comps), default=0)
    out = {"status": "ok", "whole_pixels": whole, "pixel_size_m": pixel_size, "years": [],
           "source": source, "parameters": dict(params, min_whole_pixels=min_whole_pixels)}
    if not all_comps:
        out["status"] = "no_data"
        return out
    if whole < min_whole_pixels:
        out["status"] = "too_small"
        return out
    out["years"] = [year_peak(years[y], y, **params) for y in sorted(years)]
    return out
