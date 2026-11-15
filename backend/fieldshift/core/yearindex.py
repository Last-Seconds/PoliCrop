"""The year index (brief 3, section 4): how good or bad a crop year was for water, relative to a normal year.

    index(t) = Y(t) / median(Y) − 1

where Y is water-limited wheat yield from the regional study's month-by-month relationships [S7]
(yield in bu/acre, water in inches):

    Winter wheat after fallow:  Y = 6.7 SFW + 7.9 OWG + 4.4 A + 7.6 M + 12.2 J − 16.4
    Spring wheat after a crop:  Y = 5.4 OWG + 1.4 A + 6.4 M + 5.7 J − 10.6

SFW is the water stored during the fallow (brief 2's fallow store), OWG the water gained over winter to
late March after the soil's capacity limit, A, M, J the rain in April, May and June.

| case                                  | relationship                          | basis   |
| winter cereal after fallow            | the first                             | sourced |
| spring cereal after a harvested crop  | the second                            | sourced |
| winter cereal after a harvested crop  | the first with SFW = 0                | assumed |
| spring cereal after fallow            | the second, fallow water added to OWG | assumed |
| barley                                | as spring wheat                       | assumed |

A cover crop year is treated as fallow with the fallow store reduced by the cover crop's cost, as brief 2's
budget does. Non-cereals use the index of a cereal sown in the same season in the same position.

The simpler index (brief 3, section 4) is kept as the fallback, and used wherever the month-by-month
relationship gives a median yield of zero or less:

    index(t) = (supply(t) − 2.3) / (median_supply − 2.3) − 1

Pure: takes the daily series, the soil capacity and the settings.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from . import units
from .content import Settings
from .replay import Replay, build_replay
from .weather import DailySeries

KINDS = ("harvested", "fallow", "cover")
SEASONS = ("autumn", "spring")
# Coefficients (inches -> bu/acre) of [S7]; kept here with the formula they belong to.
WW = {"sfw": 6.7, "owg": 7.9, "a": 4.4, "m": 7.6, "j": 12.2, "c": -16.4}
SW = {"sfw": 0.0, "owg": 5.4, "a": 1.4, "m": 6.4, "j": 5.7, "c": -10.6}
CASE_BASIS = {("autumn", "fallow"): "sourced", ("spring", "harvested"): "sourced",
              ("autumn", "harvested"): "assumed", ("spring", "fallow"): "assumed",
              ("autumn", "cover"): "assumed", ("spring", "cover"): "assumed"}


@dataclass
class YearIndex:
    years: np.ndarray
    monthly: dict[tuple[str, str], np.ndarray]  # (season, kind) -> index per year
    simple: dict[str, np.ndarray]  # kind -> simple index per year
    wheat_y: dict[tuple[str, str], np.ndarray]  # (season, kind) -> Y in bu/acre per year
    used: dict[tuple[str, str], str] = field(default_factory=dict)  # (season, kind) -> "monthly" | "simple"
    notes: list[str] = field(default_factory=list)
    parts: dict[str, np.ndarray] = field(default_factory=dict)  # sfw, owg, a, m, j in inches

    def series(self, season: str, kind: str) -> np.ndarray:
        """The index used for a crop sown in `season` after a slot of `kind`."""
        key = (season if season in SEASONS else "spring", kind if kind in KINDS else "harvested")
        return self.monthly[key] if self.used.get(key) == "monthly" else self.simple[key[1]]

    def at(self, year: int, season: str, kind: str) -> float | None:
        i = np.where(self.years == year)[0]
        return None if not i.size else float(self.series(season, kind)[int(i[0])])

    def basis(self, season: str, kind: str) -> str:
        key = (season if season in SEASONS else "spring", kind)
        return CASE_BASIS.get(key, "assumed") if self.used.get(key) == "monthly" else "assumed"

    def to_dict(self) -> dict:
        return {"years": [int(y) for y in self.years],
                "cases": {f"{s}:{k}": {"index": [round(float(v), 4) for v in self.series(s, k)],
                                       "method": self.used.get((s, k)), "basis": self.basis(s, k)}
                          for s in SEASONS for k in KINDS},
                "notes": self.notes}


def month_sum_in(series: DailySeries, year: int, month: int) -> float | None:
    a = dt.date(year, month, 1)
    b = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    if not series.covers(a, b):
        return None
    total, missing = series.precip_sum(a, b)
    return None if missing else units.mm_to_in(total)


def build_index(series: DailySeries, capacity_mm: dict[str, float], settings: Settings,
                replay: Replay | None = None, end: str = "central") -> YearIndex:
    rp = replay or build_replay(series, capacity_mm, settings)
    c = rp.constants[end]
    cap = units.mm_to_in(rp.capacity_mm["0_150cm"])
    years, sfw, owg, a, m, j = [], [], [], [], [], []
    for k, y in enumerate(rp.years):
        am = [month_sum_in(series, int(y), mo) for mo in (4, 5, 6)]
        if any(v is None for v in am):
            continue
        years.append(int(y))
        fallow_store = c["e_fallow"] * units.mm_to_in(rp.p_fallow[k])
        winter_gain = c["e_winter"] * units.mm_to_in(rp.p_winter[k])
        sfw.append(min(cap, fallow_store))
        owg.append(winter_gain)
        a.append(am[0]); m.append(am[1]); j.append(am[2])
    yrs = np.array(years)
    sfw, owg, a, m, j = (np.array(v, dtype=float) for v in (sfw, owg, a, m, j))
    cover_cost = units.mm_to_in(c["cover_cost_mm"])
    out_m, out_y, used, notes = {}, {}, {}, []
    for season, co in (("autumn", WW), ("spring", SW)):
        for kind in KINDS:
            stored_fallow = {"harvested": np.zeros_like(sfw), "fallow": sfw,
                             "cover": np.maximum(0.0, sfw - cover_cost)}[kind]
            if season == "autumn":
                s_fw = stored_fallow
                g = np.minimum(owg, np.maximum(0.0, cap - s_fw))  # winter gain after the capacity limit
            else:  # spring cereal: the fallow water is added to the winter gain (assumed)
                s_fw = np.zeros_like(sfw)
                g = np.minimum(cap, owg + stored_fallow)
            y = co["sfw"] * s_fw + co["owg"] * g + co["a"] * a + co["m"] * m + co["j"] * j + co["c"]
            med = float(np.median(y)) if y.size else 0.0
            out_y[(season, kind)] = y
            if med > 0:
                out_m[(season, kind)] = y / med - 1
                used[(season, kind)] = "monthly"
                if (y <= 0).any():
                    notes.append(f"{season} cereal after {kind}: the relationship gives no grain in "
                                 f"{int((y <= 0).sum())} of {y.size} years.")
            else:
                out_m[(season, kind)] = np.zeros_like(y)
                used[(season, kind)] = "simple"
                notes.append(f"{season} cereal after {kind}: median yield from the relationship is not positive; "
                             "the simple index is used.")
    # The simple index, from brief 2's supply for a deep-rooted April–June crop.
    thr = units.in_to_mm(float(settings["water.wheat_threshold_in"]))
    mask = rp.mask(yrs)
    simple = {}
    for kind in KINDS:
        sup = rp.supply_for("0_150cm", "apr_jun", kind, end)[mask]
        med = float(np.median(sup))
        simple[kind] = (sup - thr) / (med - thr) - 1 if med > thr else np.zeros_like(sup)
    return YearIndex(years=yrs, monthly=out_m, simple=simple, wheat_y=out_y, used=used, notes=notes,
                     parts={"sfw": sfw, "owg": owg, "a": a, "m": m, "j": j})


def season_of(crop) -> str:
    return "autumn" if getattr(crop, "sown", "spring") == "autumn" else "spring"
