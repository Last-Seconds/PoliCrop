"""This year so far (brief 3, part D): what the winter's precipitation says about the year starting.

Daymet stops at the end of the last calendar year, so the season in progress comes from the nearest
long-record weather station, scaled to the field:

    field(day) = station(day) × (field's Daymet average / station's average, same months, common years)

The check is unavailable when more than 10% of the season's days are missing at the station.

From that it reports, always with its date:
- stored water so far, by brief 2's budget, for the next slot of the current rotation;
- where that stands among the same date in past years ("wetter than 11 of the last 15 winters at this date");
- among past years whose stored water at the end of March was within 1 in of this year's, how often the next
  crop ran short ("in 9 past years that started like this one, a spring crop ran short in 6");
- the minimum stored water before planting for the field's precipitation, a guideline only [S27, Table 5-11];
- the farmer's records from those look-alike years.
Where stored water reached the soil's capacity in two thirds or more of past years, no odds are given:
"your soil usually refills over winter; spring rain decides the year here".

None of this predicts the harvest: it says how past years that started alike turned out.
Pure: no network.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from . import units
from .climate import crop_year_of
from .content import Settings
from .replay import Replay
from .station import usable_for_totals, _parse_station_days
from .weather import DailySeries

REFILL_SHARE = 2 / 3  # assumed (brief 3, part D)
LOOKALIKE_IN = 1.0  # assumed
MAX_MISSING = 0.10
SHOW_FROM, SHOW_TO = (1, 1), (5, 31)  # assumed: the line shows from 1 January to 31 May


def in_window(today: dt.date) -> bool:
    return SHOW_FROM <= (today.month, today.day) <= SHOW_TO


def _winter_end(cy: int) -> dt.date:
    return dt.date(cy, 3, 31)


def gain_to(series: DailySeries, cy: int, upto: dt.date) -> float | None:
    """Precipitation from 1 September before crop year `cy` to `upto` (capped at 31 March), mm."""
    a, b = dt.date(cy - 1, 9, 1), min(upto, _winter_end(cy))
    if b < a or not series.covers(a, b):
        return None
    total, missing = series.precip_sum(a, b)
    return None if missing else total


def same_date(cy: int, today: dt.date) -> dt.date:
    """The same day of the season in crop year `cy` (29 February falls back to the 28th)."""
    year = cy - 1 if today.month >= 9 else cy
    try:
        return dt.date(year, today.month, today.day)
    except ValueError:
        return dt.date(year, today.month, 28)


def stored(gain_mm: float, fallow_mm: float, capacity_mm: float, kind: str, c: dict) -> float:
    g = c["e_winter"] * gain_mm
    if kind == "fallow":
        return min(capacity_mm, c["e_fallow"] * fallow_mm + g)
    if kind == "cover":
        return min(capacity_mm, max(0.0, c["e_fallow"] * fallow_mm - c["cover_cost_mm"]) + g)
    return min(capacity_mm, g)


def min_stored_guideline(settings: Settings, mean_precip_in: float) -> dict:
    """The row of [S27] Table 5-11 for the field's mean yearly precipitation (addendum item 5)."""
    rows = settings["season.min_stored_water_in"]
    for r in rows:
        if r["below_precip_in"] is None or mean_precip_in < float(r["below_precip_in"]):
            lo = None
            prev = [x for x in rows if x["below_precip_in"] is not None and float(x["below_precip_in"]) <= mean_precip_in]
            if prev:
                lo = max(float(x["below_precip_in"]) for x in prev)
            band = (f"{lo:g} to {float(r['below_precip_in']):g} in" if lo is not None and r["below_precip_in"] is not None
                    else f"under {float(r['below_precip_in']):g} in" if r["below_precip_in"] is not None
                    else f"over {lo:g} in")
            return {"band": band, "autumn_in": float(r["autumn"]), "spring_in": float(r["spring"])}
    return {}


@dataclass
class PastYears:
    years: np.ndarray
    stored_mar31: np.ndarray  # mm, for the slot's kind
    short: np.ndarray  # the slot's crop ran short that year
    refilled: np.ndarray  # stored reached capacity by the end of March
    supply: np.ndarray  # mm


def past_years(rp: Replay, kind: str, root: str, season: str, threshold_mm: float) -> PastYears:
    """Stored water at the end of March and whether a crop in this slot ran short, every past year."""
    c = rp.constants["central"]
    cap = rp.capacity_mm[root]
    st = np.array([stored(pw, pf, cap, kind, c) for pw, pf in zip(rp.p_winter, rp.p_fallow)])
    sup = rp.supply_for(root, season, kind)
    need = float(np.median(sup))
    return PastYears(rp.years, st, (need - sup) > threshold_mm, st >= cap - 1e-6, sup)


def lookalike(pyrs: PastYears, value_mm: float, exclude: int | None = None) -> np.ndarray:
    m = np.abs(pyrs.stored_mar31 - value_mm) <= units.in_to_mm(LOOKALIKE_IN)
    if exclude is not None:
        m &= pyrs.years != exclude
    return m


def replay_check(pyrs: PastYears) -> dict:
    """Brief 3 part D, done-criteria: replayed over past years, does the end-of-March check flag short years?

    A year is flagged when, among the other past years that started like it, the crop ran short in half or more.
    """
    flagged = np.zeros(len(pyrs.years), dtype=bool)
    for i, y in enumerate(pyrs.years):
        m = lookalike(pyrs, float(pyrs.stored_mar31[i]), exclude=int(y))
        if m.sum() >= 3:
            flagged[i] = pyrs.short[m].mean() >= 0.5
    short = pyrs.short
    return {"short_years": int(short.sum()), "caught": int((flagged & short).sum()),
            "false_alarms": int((flagged & ~short).sum()), "years": int(len(short)),
            "refill_share": round(float(pyrs.refilled.mean()), 3),
            "variance_share_mar31": _var_share(pyrs)}


def _var_share(pyrs: PastYears) -> float | None:
    """Share of the year's supply variance fixed by stored water on 31 March (as docs/EXPERIMENTS.md test 3)."""
    if pyrs.stored_mar31.std() == 0 or pyrs.supply.std() == 0:
        return None
    return round(float(np.corrcoef(pyrs.stored_mar31, pyrs.supply)[0, 1] ** 2), 3)


def station_season(station_days: list[dict], grid: DailySeries, today: dt.date, start_month: int = 9) -> dict:
    """The season's daily precipitation at the station, scaled to the field. Returns status and a daily series."""
    dates, vals, flags = _parse_station_days(station_days)
    if not dates:
        return {"status": "unavailable", "reason": "the station sent no data"}
    use = usable_for_totals(dates, vals, flags, start_month)
    amount = np.array(use["amount"])
    usable = np.array(use["usable"], dtype=bool)
    cy = crop_year_of(today, start_month)
    s0 = dt.date(cy - 1, start_month, 1)
    end = today - dt.timedelta(days=1)
    if end < s0:
        return {"status": "unavailable", "reason": "the season has only just begun"}
    first = dates[0]

    def idx(d):
        return (d - first).days

    if s0 < first or end > dates[-1]:
        return {"status": "unavailable", "reason": "the station's record does not cover this season"}
    seas = slice(idx(s0), idx(end) + 1)
    n_days = (end - s0).days + 1
    missing = 1 - usable[seas].sum() / n_days
    if missing > MAX_MISSING:
        return {"status": "unavailable", "reason": f"{missing:.0%} of this season's days are missing at the station"}
    # Scale: field's Daymet average over the same months against the station's, in their common years.
    ratios_f, ratios_s = [], []
    for y in range(cy - 30, cy):
        a, b = dt.date(y - 1, start_month, 1), same_date(y, end) if same_date(y, end) >= dt.date(y - 1, start_month, 1) else None
        if b is None or a < first or b > dates[-1] or not grid.covers(a, b):
            continue
        sl = slice(idx(a), idx(b) + 1)
        if usable[sl].mean() < 0.9:
            continue
        g, gmiss = grid.precip_sum(a, b)
        if gmiss:
            continue
        ratios_f.append(g)
        ratios_s.append(float(amount[sl][usable[sl]].sum() / usable[sl].mean()))
    if len(ratios_f) < 5 or sum(ratios_s) <= 0:
        return {"status": "unavailable", "reason": "too few years in common with the field's grid weather to scale the station"}
    ratio = sum(ratios_f) / sum(ratios_s)
    total = float(amount[seas][usable[seas]].sum() / max(1e-9, usable[seas].mean())) * ratio
    return {"status": "ok", "season_mm": total, "ratio": round(ratio, 3), "common_years": len(ratios_f),
            "missing_share": round(float(missing), 3), "through": end.isoformat()}


def season_summary(*, today: dt.date, season_mm: float | None, rp: Replay, series: DailySeries, kind: str, root: str,
                   season: str, crop_name: str, crop_role: str, settings: Settings, mean_precip_in: float,
                   alternatives: list[dict], records: list[dict], source: dict) -> dict:
    """What the panel says. `season_mm`: precipitation since 1 September to today on the field (scaled station)."""
    thr = units.in_to_mm(float(settings["water.short_threshold_in"]))
    pyrs = past_years(rp, kind, root, season, thr)
    cy = crop_year_of(today, 9)
    c = rp.constants["central"]
    cap = rp.capacity_mm[root]
    out = {"date": today.isoformat(), "crop_year": cy, "next_crop": crop_name, "next_role": crop_role, "kind": kind,
           "source": source, "guideline": min_stored_guideline(settings, mean_precip_in),
           "capacity_in": round(units.mm_to_in(cap), 1)}
    refill = float(pyrs.refilled.mean())
    out["refill_share"] = round(refill, 3)
    if season_mm is None:
        return {**out, "status": "unavailable"}
    fallow_mm = 0.0
    if kind in ("fallow", "cover"):
        # The fallow window ended on 31 August, before this season: it is in the grid record if the grid reaches it.
        a, b = dt.date(cy - 2, 8, 1), dt.date(cy - 1, 8, 31)
        if series.covers(a, b):
            fallow_mm, miss = series.precip_sum(a, b)
            if miss:
                return {**out, "status": "unavailable", "reason": "the fallow year's precipitation is incomplete"}
        else:
            return {**out, "status": "unavailable", "reason": "the fallow year's precipitation is not in the record yet"}
    now_stored = stored(season_mm, fallow_mm, cap, kind, c)
    out["stored_in"] = round(units.mm_to_in(now_stored), 1)
    # The same date in past years
    past = []
    recent = [int(y) for y in rp.years[-15:]]
    for k, y in enumerate(rp.years):
        if int(y) not in recent:
            continue
        g = gain_to(series, int(y), same_date(int(y), today))
        if g is None:
            continue
        past.append(stored(g, float(rp.p_fallow[k]), cap, kind, c))
    eps = units.in_to_mm(0.05)
    out["rank"] = {"wetter_than": int(sum(now_stored > p + eps for p in past)),
                   "as_wet": int(sum(abs(now_stored - p) <= eps for p in past)), "of": len(past),
                   "full": bool(now_stored >= cap - eps)}
    if refill >= REFILL_SHARE:
        return {**out, "status": "refills",
                "message": "Your soil usually refills over winter; spring rain decides the year here."}
    # Look-alike years by stored water at the end of March (today's figure if it is not yet the end of March).
    m = lookalike(pyrs, now_stored)
    years = [int(y) for y in pyrs.years[m]]
    short = int(pyrs.short[m].sum())
    out.update({"status": "ok", "lookalike_years": years, "lookalike_short": short,
                "lookalike_note": "Stored water so far; more may still come before the end of March."
                if (today.month, today.day) < (4, 1) else None})
    out["records"] = [r for r in records if r["year"] in years]
    out["alternatives"] = []
    for alt in alternatives:
        apy = past_years(rp, alt["kind"], alt["root"], alt["season"], thr)
        am = lookalike(apy, stored(season_mm, fallow_mm, rp.capacity_mm[alt["root"]], alt["kind"], c))
        out["alternatives"].append({"crop": alt["name"], "short": int(apy.short[am].sum()), "of": int(am.sum())})
    return out


def enso_summary(oni_text: str, series: DailySeries, years: list[int]) -> dict:
    """El Niño on the About tab (information only): the current state, and Sep–Mar precipitation by phase here."""
    rows = []
    for line in oni_text.splitlines()[1:]:
        p = line.split()
        if len(p) == 4:
            try:
                rows.append((p[0], int(p[1]), float(p[3])))
            except ValueError:
                continue
    if not rows:
        return {"status": "unavailable"}
    season, yr, anom = rows[-1]
    state = "El Niño" if anom >= 0.5 else "La Niña" if anom <= -0.5 else "neutral"
    djf = {y: a for s, y, a in rows if s == "DJF"}
    phase_p: dict[str, list[float]] = {"el_nino": [], "other": []}
    for cy in years:
        a = djf.get(cy)
        if a is None:
            continue
        tot, miss = series.precip_sum(dt.date(cy - 1, 9, 1), dt.date(cy, 3, 31)) if series.covers(dt.date(cy - 1, 9, 1), dt.date(cy, 3, 31)) else (None, True)
        if miss or tot is None:
            continue
        phase_p["el_nino" if a >= 0.5 else "other"].append(units.mm_to_in(tot))
    en, ot = phase_p["el_nino"], phase_p["other"]
    return {"status": "ok", "season": season, "year": yr, "anomaly": anom, "state": state,
            "el_nino_sep_mar_in": round(float(np.mean(en)), 1) if en else None, "el_nino_years": len(en),
            "other_sep_mar_in": round(float(np.mean(ot)), 1) if ot else None, "other_years": len(ot),
            "note": "In the quick tests El Niño winters here were about 12% drier, and the index explained about 3% of "
                    "the year's water. It is shown for information and never changes the comparison or the odds."}
