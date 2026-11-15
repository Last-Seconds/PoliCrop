"""Fitting to the field (brief 3, parts B, C and E).

The model (section 3), for crop c in crop year t:

    expected(c, t) = level(c) × max(0, 1 + sensitivity(c) × index(t))

- index(t): core.yearindex, for a cereal sown in the crop's season in the position the crop held that year.
- sensitivity(c): measured by the validation tool (data/validation.json), else borrowed from the reference crops
  by similarity (part E), else 1.0 (assumed).
- level(c): the regional (zone) yield blended with the farmer's records by a weight that grows with them:

    weight(i)  = reason(i) × recency(i) × normal(i)
    recency(i) = 0.5 ^ (age(i) / 10)
    normal(i)  = 1 / (1 + (index(i) / 0.3)²)
    n_eff      = Σ weight(i);  w = n_eff / (n_eff + k)
    farm_level = weighted mean of yield(i) / (1 + sensitivity × index(i))
    level(c)   = w × farm_level + (1 − w) × regional_level(c)

A crop without records borrows a field factor from the reference crops that have them (part E).
"Fit to my field" (part C) then fits e_winter (5+ cereal records) and a storage factor (10+), shrinks the fit
toward the default by how much the records' years differ, and applies it only if leaving each record out
shows it predicts better than the farmer's own average.

Nothing here predicts a coming year: every output describes past years like those recorded.
Pure: no network, no web framework.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import units
from .content import Content, Crop
from .records import REASONS, Record
from .replay import build_replay
from .weather import DailySeries
from .yearindex import YearIndex, build_index, season_of

CEREALS = ("winter_wheat", "spring_wheat", "spring_barley")


# ------------------------------------------------------------------------------------------- inputs from files

def load_validation(data_dir: Path) -> dict | None:
    p = Path(data_dir) / "validation.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def load_similarity(data_dir: Path) -> dict:
    p = Path(data_dir) / "similarity.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def family(c: Crop) -> str:
    return {"cereal": "grass", "legume": "legume", "oilseed": "oilseed"}.get(c.role, c.role)


def harvest_month(c: Crop) -> int | None:
    hw = c.harvest_window
    return int(hw.end[:2]) if hw else None


def similarity_weights(crop: Crop, content: Content, sim: dict) -> dict[str, float]:
    """Weights of the reference crops for this crop (sum to one), from the five dimensions (part E)."""
    refs = [r for r in sim.get("references", []) if content.has_crop(r)]
    w = {k: float(v["value"]) for k, v in (sim.get("weights") or {}).items()}
    rank = (sim.get("water_use_rank") or {}).get("value", {})
    raw = {}
    for rid in refs:
        r = content.crop(rid)
        s = 0.0
        s += w.get("sowing_season", 0) * (crop.sown == r.sown)
        s += w.get("plant_family", 0) * (family(crop) == family(r))
        s += w.get("root_zone", 0) * ((crop.root_zone or {}).get("value") == (r.root_zone or {}).get("value"))
        if crop.id in rank and rid in rank:
            s += w.get("water_need", 0) * (1 - abs(rank[crop.id] - rank[rid]) / 4)
        hm, hr = harvest_month(crop), harvest_month(r)
        if hm and hr:
            s += w.get("harvest_month", 0) * max(0.0, 1 - abs(hm - hr) / 3)
        raw[rid] = s
    tot = sum(raw.values())
    return {k: v / tot for k, v in raw.items()} if tot > 0 else {}


def sensitivity_for(crop: Crop, content: Content, validation: dict | None, sim: dict) -> dict:
    """{value, basis, from}: measured, else similarity-weighted from the references (part E), else 1.0."""
    sens = (validation or {}).get("sensitivities") or {}
    own = sens.get(crop.id)
    if crop.id == "winter_wheat":
        return {"value": 1.0, "basis": "definition", "from": None}
    if own and own.get("basis") not in (None, "assumed"):
        return {"value": float(own["value"]), "basis": own["basis"], "from": None, "n_years": own.get("n_years")}
    ws = similarity_weights(crop, content, sim)
    measured = {r: sens[r] for r in ws if r in sens and sens[r].get("basis") not in (None, "assumed")} if sens else {}
    if crop.id not in ws and measured:
        tot = sum(ws[r] for r in measured)
        if tot > 0:
            v = sum(ws[r] * float(measured[r]["value"]) for r in measured) / tot
            return {"value": round(v, 3), "basis": "borrowed", "from": sorted(measured, key=lambda r: -ws[r])}
    return {"value": 1.0, "basis": "assumed", "from": None}


# ------------------------------------------------------------------------------------------- record weights

@dataclass
class Weighted:
    record: Record
    kind: str
    index: float | None
    reason_w: float
    recency: float
    normal: float

    @property
    def weight(self) -> float:
        return self.reason_w * self.recency * self.normal


def position_of(year: int, history: dict[int, str], content: Content) -> str:
    """The kind of slot before this crop year, from the crop history (fallow, cover, or a harvested crop)."""
    prev = history.get(year - 1)
    if prev and content.has_crop(prev):
        role = content.crop(prev).role
        return {"fallow": "fallow", "cover_crop": "cover"}.get(role, "harvested")
    return "harvested"


def weigh(records: list[Record], yi: YearIndex, history: dict[int, str], content: Content, now_year: int) -> list[Weighted]:
    s = content.settings
    half = float(s["fit.recency_half_life_years"])
    scale = float(s["fit.normal_scale"])
    unknown = float(s["fit.unknown_reason_weight"])
    out = []
    for r in records:
        crop = content.crop(r.crop)
        kind = position_of(r.year, history, content)
        idx = yi.at(r.year, season_of(crop), kind)
        reason_w = REASONS.get(r.reason, 1.0) if r.reason != "unknown" else unknown
        if r.reason is None:
            reason_w = 1.0
        age = max(0, now_year - r.year)
        recency = 0.5 ** (age / half)
        normal = 1.0 / (1.0 + (idx / scale) ** 2) if idx is not None else 0.0
        out.append(Weighted(r, kind, idx, reason_w, recency, normal if idx is not None else 0.0))
    return out


# ------------------------------------------------------------------------------------------- levels

@dataclass
class Level:
    crop: str
    regional_kg_ha: float | None
    level_kg_ha: float | None
    w: float = 0.0
    n_eff: float = 0.0
    n_records: int = 0
    farm_level_kg_ha: float | None = None
    borrowed_from: list[str] = field(default_factory=list)
    factor: float | None = None
    example: bool = False

    def to_dict(self) -> dict:
        lb = lambda v: None if v is None else round(units.kg_ha_to_lb_ac(v))  # noqa: E731
        return {"crop": self.crop, "regional_lb_ac": lb(self.regional_kg_ha), "level_lb_ac": lb(self.level_kg_ha),
                "w": round(self.w, 3), "n_eff": round(self.n_eff, 2), "n_records": self.n_records,
                "farm_level_lb_ac": lb(self.farm_level_kg_ha), "borrowed_from": self.borrowed_from,
                "factor": None if self.factor is None else round(self.factor, 3)}


def farm_levels(weighted: list[Weighted], sens: dict[str, float], content: Content, regional: dict[str, float]) -> dict[str, Level]:
    k = float(content.settings["fit.k"])
    out = {}
    by_crop: dict[str, list[Weighted]] = {}
    for w in weighted:
        by_crop.setdefault(w.record.crop, []).append(w)
    for cid, ws in by_crop.items():
        reg = regional.get(cid)
        s = sens.get(cid, 1.0)
        num = den = 0.0
        for w in ws:
            if w.index is None or w.weight <= 0:
                continue
            d = 1 + s * w.index
            if d < 0.05:  # a year so dry the model expects nothing: it cannot say what the field's level is
                continue
            num += w.weight * units.lb_ac_to_kg_ha(w.record.yield_lb_ac) / d
            den += w.weight
        n_eff = den
        if n_eff <= 0 or reg is None:
            out[cid] = Level(cid, reg, reg, 0.0, 0.0, len(ws))
            continue
        fl = num / den
        wt = n_eff / (n_eff + k)
        out[cid] = Level(cid, reg, wt * fl + (1 - wt) * reg, wt, n_eff, len(ws), fl)
    return out


def borrowed_level(crop: Crop, levels: dict[str, Level], regional: float | None, content: Content, sim: dict) -> Level | None:
    """Part E: a crop without records takes a field factor from reference crops that have them."""
    if regional is None:
        return None
    ws = similarity_weights(crop, content, sim)
    contrib = {r: levels[r] for r in ws if r in levels and levels[r].farm_level_kg_ha and levels[r].regional_kg_ha}
    if not contrib:
        return None
    tot = sum(ws[r] for r in contrib)
    factor = sum(ws[r] * contrib[r].farm_level_kg_ha / contrib[r].regional_kg_ha for r in contrib) / tot
    n_eff = sum(ws[r] * contrib[r].n_eff for r in contrib)
    k = float(content.settings["fit.k"])
    w = n_eff / (n_eff + k)
    return Level(crop.id, regional, regional * (1 + w * (factor - 1)), w, n_eff, 0,
                 borrowed_from=sorted(contrib, key=lambda r: -ws[r]), factor=factor)


# ------------------------------------------------------------------------------------------- expected against actual

def expected(level_kg_ha: float, sens: float, idx: float | None) -> float | None:
    if idx is None or level_kg_ha is None:
        return None
    return level_kg_ha * max(0.0, 1 + sens * idx)


def compare_records(weighted: list[Weighted], levels: dict[str, Level], sens: dict[str, float], content: Content) -> dict:
    """The chart under the records: per year, actual beside expected; which years disagree; one sentence."""
    s = content.settings
    rows = []
    for w in sorted(weighted, key=lambda x: (x.record.year, x.record.crop)):
        lv = levels.get(w.record.crop)
        e = expected(lv.level_kg_ha, sens.get(w.record.crop, 1.0), w.index) if lv else None
        rows.append({"year": w.record.year, "crop": w.record.crop, "actual_lb_ac": w.record.yield_lb_ac,
                     "expected_lb_ac": None if e is None else round(units.kg_ha_to_lb_ac(e)),
                     "index": None if w.index is None else round(w.index, 3), "after": w.kind,
                     "weight": round(w.weight, 3), "reason": w.record.reason,
                     "level_lb_ac": round(units.kg_ha_to_lb_ac(lv.level_kg_ha)) if lv and lv.level_kg_ha else None})
    gaps = [abs(r["actual_lb_ac"] - r["expected_lb_ac"]) for r in rows if r["expected_lb_ac"] is not None]
    typical = float(np.median(gaps)) if gaps else 0.0
    share = float(s["records.disagree_share_of_level"])
    times = float(s["records.disagree_times_typical_gap"])
    for r in rows:
        r["disagrees"] = bool(r["expected_lb_ac"] is not None and r["level_lb_ac"]
                              and abs(r["actual_lb_ac"] - r["expected_lb_ac"]) > share * r["level_lb_ac"]
                              and abs(r["actual_lb_ac"] - r["expected_lb_ac"]) > times * typical)
    # "our estimate was within 8 bu/ac of your yield in 6 of 8 years"
    within_bu = float(s["records.within_bu_ac"])
    hits = n = 0
    for r in rows:
        if r["expected_lb_ac"] is None:
            continue
        n += 1
        if r["crop"] in CEREALS:
            tol = within_bu * (48 if r["crop"] == "spring_barley" else 60)
        else:
            tol = 0.1 * (r["level_lb_ac"] or r["expected_lb_ac"])
        hits += abs(r["actual_lb_ac"] - r["expected_lb_ac"]) <= tol
    cereal_only = all(r["crop"] in CEREALS for r in rows)
    tol_text = f"{within_bu:g} bu/ac" if cereal_only else f"{within_bu:g} bu/ac (cereals) or 10% (other crops)"
    sentence = (f"Our estimate was within {tol_text} of your yield in {hits} of {n} year{'s' if n != 1 else ''}."
                if n else "No record could be compared: its year is outside the weather record.")
    return {"rows": rows, "typical_gap_lb_ac": round(typical), "sentence": sentence}


# ------------------------------------------------------------------------------------------- part C: fitting constants

@dataclass
class FitResult:
    applied: bool
    constants: dict[str, float]  # name -> value used (only those applied)
    fitted: dict[str, float]  # before shrinking
    shrunk: dict[str, float]
    w_fit: float
    spread: float
    typical_spread: float
    loo_error: float | None
    baseline_error: float | None
    message: str
    coverage: str | None
    usable: int

    def to_dict(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 4)  # noqa: E731
        return {"applied": self.applied, "constants": {k: r(v) for k, v in self.constants.items()},
                "fitted": {k: r(v) for k, v in self.fitted.items()}, "shrunk": {k: r(v) for k, v in self.shrunk.items()},
                "w_fit": r(self.w_fit), "spread": r(self.spread), "typical_spread": r(self.typical_spread),
                "loo_error_lb_ac": r(self.loo_error), "baseline_error_lb_ac": r(self.baseline_error),
                "message": self.message, "coverage": self.coverage, "usable_records": self.usable}


def _index_table(series: DailySeries, capacity: dict[str, float], content: Content, e_winter: float, factor: float) -> YearIndex:
    cap = {k: v * factor for k, v in capacity.items()}
    rp = build_replay(series, cap, content.settings)
    rp.constants["central"] = {**rp.constants["central"], "e_winter": e_winter}
    return build_index(series, cap, content.settings, replay=rp)


def _sse(recs: list[Weighted], yis: YearIndex, sens: dict[str, float], content: Content) -> tuple[float, dict[str, float]]:
    """Weighted squared error with each crop's level fitted in closed form for this index; returns (sse, levels)."""
    by: dict[str, list] = {}
    for w in recs:
        crop = content.crop(w.record.crop)
        x = yis.at(w.record.year, season_of(crop), w.kind)
        if x is None:
            continue
        by.setdefault(w.record.crop, []).append((w.reason_w * w.recency, 1 + sens.get(w.record.crop, 1.0) * x,
                                                 w.record.yield_lb_ac))
    sse, lv = 0.0, {}
    for cid, rows in by.items():
        wt = np.array([r[0] for r in rows]); x = np.maximum(0.0, np.array([r[1] for r in rows])); y = np.array([r[2] for r in rows])
        den = float((wt * x * x).sum())
        L = float((wt * x * y).sum() / den) if den > 0 else float(np.average(y, weights=wt))
        lv[cid] = L
        sse += float((wt * (y - L * x) ** 2).sum())
    return sse, lv


def fit_constants(weighted: list[Weighted], series: DailySeries, capacity: dict[str, float], content: Content,
                  sens: dict[str, float], var_index: float, _check: bool = True) -> FitResult:
    s = content.settings
    k = float(s["fit.k"])
    ew_lo, ew_c, ew_hi = s.range("water.e_winter")
    f_lo, f_c, f_hi = s.range("fit.storage_factor_range")
    usable = [w for w in weighted if w.record.crop in CEREALS and w.reason_w > 0 and w.index is not None]
    n = len(usable)
    defaults = {"e_winter": ew_c, "storage_factor": f_c}
    names = []
    if n >= int(s["fit.e_winter_min_records"]):
        names.append("e_winter")
    if n >= int(s["fit.storage_min_records"]):
        names.append("storage_factor")
    rr = np.array([w.reason_w * w.recency for w in usable]) if usable else np.array([])
    idx = np.array([w.index for w in usable]) if usable else np.array([])
    spread = float((rr * (idx - np.average(idx, weights=rr)) ** 2).sum()) if usable and rr.sum() > 0 else 0.0
    typical = float(rr.sum() * var_index) if usable else 0.0
    w_fit = spread / (spread + k * var_index) if (spread + k * var_index) > 0 else 0.0
    coverage = None
    if usable:
        side = np.sign(idx)
        if (side > 0).all() or (side < 0).all():
            word = "wetter" if (side > 0).all() else "drier"
            other = "dry" if word == "wetter" else "wet"
            coverage = (f"Your records are all from {word}-than-normal years, so we know little about how this field does "
                        f"when it is {other}. A {other} year's figure would help most.")
        elif spread < float(s["fit.coverage_quarter"]) * typical:
            coverage = ("Your records come from years that were much alike, so they say little about how this field "
                        "responds to water. A record from a very dry or very wet year would help most.")
    if not names:
        return FitResult(False, {}, {}, {}, w_fit, spread, typical, None, None,
                         f"Fitting needs at least {int(s['fit.e_winter_min_records'])} cereal records that can be used; "
                         f"you have {n}.", coverage, n)
    grid_e = np.round(np.arange(ew_lo, ew_hi + 1e-9, 0.0075), 4) if "e_winter" in names else [ew_c]
    grid_f = np.round(np.arange(f_lo, f_hi + 1e-9, 0.05), 3) if "storage_factor" in names else [f_c]
    cache: dict = {}

    def table(e, f):
        key = (round(float(e), 4), round(float(f), 3))
        if key not in cache:
            cache[key] = _index_table(series, capacity, content, key[0], key[1])
        return cache[key]

    def best(recs):
        scores = [(_sse(recs, table(e, f), sens, content)[0], e, f) for e in grid_e for f in grid_f]
        _, e, f = min(scores)
        return {"e_winter": float(e), "storage_factor": float(f)}

    fitted = best(usable)
    shrunk = {nm: defaults[nm] + w_fit * (fitted[nm] - defaults[nm]) for nm in names}
    if not _check:
        return FitResult(True, shrunk, fitted, shrunk, w_fit, spread, typical, None, None, "", coverage, n)

    # The self-check: leave each record out, fit on the rest, estimate the one left out.
    e_fit, e_avg = [], []
    for i, w in enumerate(usable):
        rest = usable[:i] + usable[i + 1:]
        same = [x for x in rest if x.record.crop == w.record.crop]
        if not same:
            continue
        sub = fit_constants(rest, series, capacity, content, sens, var_index, _check=False)
        cons = {**defaults, **sub.constants}
        yt = table(cons["e_winter"], cons["storage_factor"])
        _, lv = _sse(rest, yt, sens, content)
        crop = content.crop(w.record.crop)
        x = yt.at(w.record.year, season_of(crop), w.kind)
        if x is None or w.record.crop not in lv:
            continue
        pred = lv[w.record.crop] * max(0.0, 1 + sens.get(w.record.crop, 1.0) * x)
        avg = float(np.mean([x.record.yield_lb_ac for x in same]))
        e_fit.append(w.record.yield_lb_ac - pred)
        e_avg.append(w.record.yield_lb_ac - avg)
    if len(e_fit) < 3:
        return FitResult(False, {}, fitted, shrunk, w_fit, spread, typical, None, None,
                         "Too few records of the same crop to check a fit, so the regional values are kept.", coverage, n)
    rm = float(np.sqrt(np.mean(np.square(e_fit))))
    ra = float(np.sqrt(np.mean(np.square(e_avg))))
    gain = float(s["fit.self_check_min_gain"])
    if rm <= (1 - gain) * ra:
        return FitResult(True, shrunk, fitted, shrunk, w_fit, spread, typical, rm, ra, describe_fit(shrunk, defaults), coverage, n)
    return FitResult(False, {}, fitted, shrunk, w_fit, spread, typical, rm, ra,
                     "Your records don't show a pattern the water model can explain better than your average, so the "
                     "regional values are kept.", coverage, n)


def describe_fit(values: dict[str, float], defaults: dict[str, float]) -> str:
    parts = []
    if "e_winter" in values:
        d = values["e_winter"] - defaults["e_winter"]
        if abs(d) < 0.005:
            parts.append("we keep the regional figure for how much winter rain your soil keeps")
        else:
            amount = "a little " if abs(d) < 0.04 else ""
            parts.append(f"we now assume your soil keeps {amount}{'more' if d > 0 else 'less'} of the winter rain "
                         f"than the regional figure ({values['e_winter']:.0%} against {defaults['e_winter']:.0%})")
    if "storage_factor" in values:
        d = values["storage_factor"] - defaults["storage_factor"]
        if abs(d) >= 0.01:
            parts.append(f"that it holds {'more' if d > 0 else 'less'} water than the soil survey says "
                         f"({values['storage_factor']:.0%} of it)")
    return ("Fitted to your records: " + "; ".join(parts) + ".") if parts else "Fitted to your records: no change was needed."


# ------------------------------------------------------------------------------------------- the whole thing

@dataclass
class FieldFit:
    """Everything the records change, for one field and one set of inputs."""
    levels: dict[str, Level]  # crop id -> blended or borrowed level (crops with a regional figure)
    sensitivities: dict[str, dict]
    comparison: dict
    fit: FitResult | None
    constants: dict[str, float]  # applied constants (empty when not fitted or refused)
    example: bool = False

    def to_dict(self, content: Content) -> dict:
        return {"levels": {k: v.to_dict() for k, v in self.levels.items()},
                "sensitivities": self.sensitivities, "comparison": self.comparison,
                "fit": None if self.fit is None else self.fit.to_dict(), "constants": self.constants,
                "example": self.example}


def fit_field(records: list[Record], content: Content, series: DailySeries, capacity: dict[str, float],
              regional_kg_ha: dict[str, float], history: dict[int, str], now_year: int, fit_on: bool,
              example: bool = False) -> FieldFit:
    data_dir = content.data_dir
    validation = load_validation(data_dir)
    sim = load_similarity(data_dir)
    sens_info = {c.id: sensitivity_for(c, content, validation, sim) for c in content.offered_crops()
                 if c.role not in ("fallow", "cover_crop")}
    sens = {k: v["value"] for k, v in sens_info.items()}
    yi = build_index(series, capacity, content.settings)
    weighted = weigh(records, yi, history, content, now_year)
    levels = farm_levels(weighted, sens, content, regional_kg_ha)
    for c in content.offered_crops():
        if c.id in levels or c.id not in regional_kg_ha:
            continue
        b = borrowed_level(c, levels, regional_kg_ha.get(c.id), content, sim)
        if b is not None:
            levels[c.id] = b
    for lv in levels.values():
        lv.example = example
    comparison = compare_records(weighted, levels, sens, content)
    fit = None
    constants: dict[str, float] = {}
    if fit_on:
        var_index = float(np.var(yi.series("autumn", "harvested")))
        fit = fit_constants(weighted, series, capacity, content, sens, var_index)
        if fit.applied:
            constants = fit.constants
    return FieldFit(levels, sens_info, comparison, fit, constants, example)


def example_records(content: Content, series: DailySeries, capacity: dict[str, float], regional_kg_ha: dict[str, float],
                    history: dict[int, str], years: list[int], seed: int, noise: float = 0.12) -> list[dict]:
    """Records generated from the model plus noise (brief 3, section 10): never shown as real."""
    rng = np.random.default_rng(seed)
    yi = build_index(series, capacity, content.settings)
    validation = load_validation(content.data_dir)
    sim = load_similarity(content.data_dir)
    out = []
    for y in years:
        cid = history.get(y)
        if not cid or not content.has_crop(cid) or cid not in regional_kg_ha:
            continue
        crop = content.crop(cid)
        idx = yi.at(y, season_of(crop), position_of(y, history, content))
        if idx is None:
            continue
        s = sensitivity_for(crop, content, validation, sim)["value"]
        lb = units.kg_ha_to_lb_ac(regional_kg_ha[cid]) * 1.08 * max(0.05, 1 + s * idx) * (1 + rng.normal(0, noise))
        out.append({"year": int(y), "crop": cid, "yield_lb_ac": round(max(50.0, lb), 0)})
    return out
