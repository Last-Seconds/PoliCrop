"""Replay and the water budget (brief section 6.2).

Every slot of a rotation is evaluated in every past crop year of weather, as if
the farm had one field in each phase. For the crop in a slot, in crop year y:

    winter_gain  = e_winter × P(1 Sep y−1 … 31 Mar y)
    after a harvested crop:  stored = min(capacity, winter_gain)
    after fallow:            stored = min(capacity, e_fallow × P(1 Aug y−2 … 31 Aug y−1) + winter_gain)
    after a cover crop:      as fallow, the fallow store reduced by cover_cost (never below zero)
    supply = stored + P(growing season)

Supply depends only on (root zone, growing season, kind of previous slot, year),
so that small table is computed once per field and candidates are scored by
lookup. Each table entry exists at three ends of the sourced constant ranges:
"low" (least water: e_winter low, cover_cost high), "central" and "high".
All depths are mm internally.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from . import units
from .content import Settings
from .weather import DailySeries

KINDS = ("harvested", "fallow", "cover")
ENDS = ("low", "central", "high")  # of the water supply


def supply_mm(p_winter: float | np.ndarray, p_fallow: float | np.ndarray, p_season: float | np.ndarray,
              capacity: float, kind: str, e_winter: float, e_fallow: float, cover_cost: float):
    """The budget for one slot. Works on scalars or arrays (all in the same depth unit)."""
    winter_gain = e_winter * np.asarray(p_winter, dtype=float)
    if kind == "harvested":
        stored = np.minimum(capacity, winter_gain)
    elif kind == "fallow":
        stored = np.minimum(capacity, e_fallow * np.asarray(p_fallow, dtype=float) + winter_gain)
    elif kind == "cover":
        fallow_store = np.maximum(0.0, e_fallow * np.asarray(p_fallow, dtype=float) - cover_cost)
        stored = np.minimum(capacity, fallow_store + winter_gain)
    else:
        raise ValueError(f"unknown previous-slot kind {kind!r}")
    out = stored + np.asarray(p_season, dtype=float)
    return float(out) if out.ndim == 0 else out


def _mmdd(year: int, mmdd: str) -> dt.date:
    return dt.date(year, int(mmdd[:2]), int(mmdd[3:]))


@dataclass
class Replay:
    years: np.ndarray  # crop years, ascending
    crop_year_precip_mm: np.ndarray
    p_winter: np.ndarray
    p_fallow: np.ndarray
    p_season: dict[str, np.ndarray]  # growing-season id -> mm
    capacity_mm: dict[str, float]  # root zone id -> mm
    constants: dict[str, dict[str, float]]  # end -> {e_winter, e_fallow, cover_cost_mm}
    tmax: DailySeries | None = None  # kept for heat / cold frequencies
    supply: dict[tuple[str, str, str, str], np.ndarray] = field(default_factory=dict)
    dropped_years: list[int] = field(default_factory=list)

    def supply_for(self, root: str, season: str, kind: str, end: str = "central") -> np.ndarray:
        key = (root, season, kind, end)
        if key not in self.supply:
            c = self.constants[end]
            self.supply[key] = supply_mm(self.p_winter, self.p_fallow, self.p_season[season],
                                         self.capacity_mm[root], kind, c["e_winter"], c["e_fallow"],
                                         c["cover_cost_mm"])
        return self.supply[key]

    def mask(self, years: list[int] | np.ndarray) -> np.ndarray:
        return np.isin(self.years, np.asarray(list(years)))

    def recent_years(self, n: int) -> list[int]:
        return [int(y) for y in self.years[-n:]]

    def driest_years(self, among: list[int], n: int) -> list[int]:
        m = self.mask(among)
        pairs = sorted(zip(self.crop_year_precip_mm[m], self.years[m]))
        return sorted(int(y) for _, y in pairs[:n])


def constant_ends(settings: Settings) -> dict[str, dict[str, float]]:
    ew = settings.range("water.e_winter")
    ef = settings.central("water.e_fallow")
    cc = settings.range("water.cover_cost_in")
    # "low" = least water: lowest winter storage share, highest cover-crop cost.
    return {
        "low": {"e_winter": ew[0], "e_fallow": ef, "cover_cost_mm": units.in_to_mm(cc[2])},
        "central": {"e_winter": ew[1], "e_fallow": ef, "cover_cost_mm": units.in_to_mm(cc[1])},
        "high": {"e_winter": ew[2], "e_fallow": ef, "cover_cost_mm": units.in_to_mm(cc[0])},
    }


def build_replay(series: DailySeries, capacity_mm: dict[str, float], settings: Settings,
                 last_year: int | None = None) -> Replay:
    first = int(settings["water.replay_first_year"])
    ww = settings["water.winter_window"]
    fw = settings["water.fallow_window"]
    seasons = settings["water.growing_seasons"]
    if last_year is None:
        last_year = series.last.year if series.last >= dt.date(series.last.year, 8, 31) else series.last.year - 1
    years, pw, pf, ps, cy = [], [], [], {k: [] for k in seasons}, []
    dropped = []
    for y in range(first, last_year + 1):
        windows = {
            "winter": (_mmdd(y - 1, ww["start"]), _mmdd(y, ww["end"])),
            "fallow": (_mmdd(y - 2, fw["start"]), _mmdd(y - 1, fw["end"])),
            "year": (dt.date(y - 1, 9, 1), dt.date(y, 8, 31)),
            **{f"gs:{k}": (_mmdd(y, v["start"]), _mmdd(y, v["end"])) for k, v in seasons.items()},
        }
        if not all(series.covers(a, b) for a, b in windows.values()):
            dropped.append(y)
            continue
        sums = {k: series.precip_sum(a, b) for k, (a, b) in windows.items()}
        if any(missing for _, missing in sums.values()):
            dropped.append(y)  # gaps are left out, not estimated
            continue
        years.append(y)
        pw.append(sums["winter"][0])
        pf.append(sums["fallow"][0])
        cy.append(sums["year"][0])
        for k in seasons:
            ps[k].append(sums[f"gs:{k}"][0])
    if not years:
        raise ValueError("The weather record is too short or too gappy for the replay.")
    return Replay(
        years=np.array(years), crop_year_precip_mm=np.array(cy), p_winter=np.array(pw), p_fallow=np.array(pf),
        p_season={k: np.array(v) for k, v in ps.items()}, capacity_mm=dict(capacity_mm),
        constants=constant_ends(settings), tmax=series, dropped_years=dropped)


def years_with_extreme(series: DailySeries, years: list[int], months: list[int], limit_c: float,
                       hot: bool, swe_below: float | None = None) -> dict[int, bool | None]:
    """Per crop year: did any day in `months` reach the limit (tmax >= limit if hot, tmin <= limit if not)?

    Months from September onward belong to the calendar year before the crop year
    (a November–March winter is the winter before harvest year y). None = no data.
    """
    out: dict[int, bool | None] = {}
    arr = series.tmax if hot else series.tmin
    for y in years:
        hit, seen = False, 0
        for m in months:
            cal_year = y - 1 if m >= 9 else y
            a = dt.date(cal_year, m, 1)
            b = (dt.date(cal_year + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1))
            if not series.covers(a, b):
                continue
            w = series.window(arr, a, b)
            ok = ~np.isnan(w)
            seen += int(ok.sum())
            cond = (w >= limit_c) if hot else (w <= limit_c)
            if swe_below is not None and series.swe is not None:
                # addendum 2, A3: a cold night counts only with little snow (modelled snow water equivalent)
                sw = series.window(series.swe, a, b)
                cond = cond & ~np.isnan(sw) & (sw < swe_below)
            if (cond & ok).any():
                hit = True
        out[y] = hit if seen else None
    return out
