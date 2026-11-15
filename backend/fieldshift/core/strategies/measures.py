"""The four measures (brief sections 6.2–6.5): water, soil protection, nitrogen, crop variety.

Each measure returns a Quantity: a physical quantity as low / central / high,
its unit, which direction is better, the assumed values that fed it, and the
pieces of its explanation. Everything is in internal units (mm, kg/ha); the
presentation layer converts to US units.

The FieldModel holds what every measure needs for one field and one set of
farmer inputs; it caches per-crop results so thousands of candidates can be
scored by lookup.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import units
from ..content import Content, Crop
from ..replay import ENDS, Replay
from ..soil import FieldSoil
from .model import Strategy, kind_of
from .scoring import register_scorer

MEASURES = ("water", "soil", "nitrogen", "variety")
MEASURE_LABELS = {"water": "Water", "soil": "Soil protection", "nitrogen": "Nitrogen", "variety": "Crop variety"}
GROUPS = (("grass", "autumn"), ("grass", "spring"), ("broadleaf", "autumn"), ("broadleaf", "spring"))
GROUP_LABELS = {("grass", "autumn"): "winter grass crop", ("grass", "spring"): "spring grass crop",
                ("broadleaf", "autumn"): "winter broadleaf crop", ("broadleaf", "spring"): "spring broadleaf crop"}


@dataclass
class Assumed:
    """An assumed value that fed a quantity; shown wherever it affects a result."""
    key: str
    text: str

    def to_dict(self) -> dict:
        return {"key": self.key, "text": self.text}


@dataclass
class Quantity:
    measure: str
    low: float
    central: float
    high: float
    higher_is_better: bool
    unit: str  # internal unit
    assumed: list[Assumed] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    assessed: bool = True
    not_assessed_reason: str | None = None

    def favourable(self) -> float:
        return self.high if self.higher_is_better else self.low

    def unfavourable(self) -> float:
        return self.low if self.higher_is_better else self.high


def not_assessed(measure: str, reason: str, higher_is_better: bool, unit: str) -> Quantity:
    return Quantity(measure, float("nan"), float("nan"), float("nan"), higher_is_better, unit,
                    assessed=False, not_assessed_reason=reason)


def _uniq(items: list[Assumed]) -> list[Assumed]:
    seen, out = set(), []
    for a in items:
        if a.key not in seen:
            seen.add(a.key)
            out.append(a)
    return out


def _note(b) -> str:
    """A basis note as a clause: no trailing full stop."""
    return (b.note or "").strip().rstrip(".")


def _fmt_in(mm: float) -> str:
    return f"{units.mm_to_in(mm):.1f} in"


def _fmt_lb(kg_ha: float) -> str:
    return f"{units.kg_ha_to_lb_ac(kg_ha):,.0f} lb/ac"


# ------------------------------------------------------------------------------------------- yields

ZONE_WORDS = {"annual_crop": "Annual Crop", "transition": "Transition", "grain_fallow": "Grain-Fallow"}


@dataclass
class ExpectedYield:
    kg_ha: float | None
    tag: str  # farmer | records | borrowed | regional | zone | zone_after_crop | water_relationship | regional_wetter | none
    assumed: list[Assumed] = field(default_factory=list)
    zone: str | None = None
    level: Any = None  # fitting.Level behind a "records" or "borrowed" figure

    @property
    def text(self) -> str:
        z = ZONE_WORDS.get(self.zone or "", "")
        return {
            "farmer": "your typical yield",
            "regional": "the regional typical yield (2011–2015)",
            "zone": f"the typical yield in the {z} zone",
            "zone_after_crop": f"the typical yield in the {z} zone after a harvested crop",
            "records": "the regional figure blended with your harvest records",
            "borrowed": "the regional figure adjusted by your records of similar crops",
            "water_relationship": "the yield this field's usual water supports, from the wheat water relationship",
            "regional_wetter": "the typical yield from a wetter zone",
            "none": "no yield figure",
        }[self.tag]


# ------------------------------------------------------------------------------------------- field model

@dataclass
class FieldModel:
    content: Content
    base: Replay  # unchanged weather (needs are calibrated here)
    replay: Replay  # scenario weather (supplies are read here)
    soil: FieldSoil
    reference: list[Crop]  # the farmer's current rotation (one cycle), for cereal needs
    tillage: str
    tillage_from_farmer: bool
    yields_kg_ha: dict[str, float]  # farmer's own typical yields
    ph: float | None = None
    dry_mode: bool = False
    extremes: dict[str, dict[int, bool | None]] = field(default_factory=dict)  # warning id -> year -> hit
    nearby: Any = None  # optional NearbyUse (stage 4)
    levels: dict = field(default_factory=dict)  # crop id -> fitting.Level from the farmer's records (brief 3, B/E)
    fitted: dict = field(default_factory=dict)  # constants fitted to the farmer's records (brief 3, C)
    example: bool = False  # the records are example data, not a real farm
    _cache: dict = field(default_factory=dict)

    # ---- years
    @property
    def settings(self):
        return self.content.settings

    @property
    def recent_years(self) -> list[int]:
        return self.replay.recent_years(int(self.settings["water.recent_years"]))

    @property
    def window_years(self) -> list[int]:
        """Years the water measure is judged on: the recent 15, or the driest 5 of them in dry region mode."""
        if self.dry_mode:
            return self.replay.driest_years(self.recent_years, int(self.settings["water.dry_mode_years"]))
        return self.recent_years

    @property
    def mean_precip_mm(self) -> float:
        return float(np.mean(self.base.crop_year_precip_mm))

    @property
    def zone(self) -> str:
        """Rainfall zone by the field's mean yearly precipitation (addendum item 1)."""
        p = units.mm_to_in(self.mean_precip_mm)
        if p >= float(self.settings["residue.regional_yield_min_precip_in"]):
            return "annual_crop"
        if p >= float(self.settings["residue.zone_transition_min_precip_in"]):
            return "transition"
        return "grain_fallow"

    # ---- water needs
    def reference_kinds(self, crop_id: str) -> list[str]:
        """Previous-slot kinds of this crop in the current rotation; 'harvested' if absent."""
        ref = self.reference
        kinds = sorted({kind_of(ref[i - 1].role) for i, c in enumerate(ref) if c.id == crop_id}) if len(ref) > 1 else []
        return kinds or ["harvested"]

    def need(self, crop: Crop) -> dict[str, float] | None:
        """Water need per end of the constant ranges (mm), or None if no figure."""
        key = ("need", crop.id)
        if key in self._cache:
            return self._cache[key]
        wn = crop.water_need
        out = None
        if wn is None or crop.root_zone is None or crop.growing_season is None:
            out = None
        else:  # brief 3, S1: every crop is self-calibrated, as brief 2 did for cereals
            root, gs = crop.root_zone["value"], crop.growing_season["value"]
            out = {e: float(np.median(np.concatenate([self.base.supply_for(root, gs, k, e)
                                                      for k in self.reference_kinds(crop.id)])))
                   for e in ENDS}
        self._cache[key] = out
        return out

    def too_dry(self, crop: Crop) -> dict | None:
        """The "may be too dry here" check (brief 3, S1): the crop's median supply on this field, in its
        reference position, against its sourced water use plus the shortfall margin. None if no figure."""
        use = crop.water_use
        need = self.need(crop)
        if use is None or need is None:
            return None
        margin = units.in_to_mm(float(self.settings["water.short_threshold_in"]))
        median = need["central"]
        if use["method"] == "from_yield":
            y = self.expected_yield(crop)
            if y.kg_ha is None:
                return None
            lb = units.kg_ha_to_lb_ac(y.kg_ha)
            use_mm = units.in_to_mm(lb / use["lb_per_in_high"])
            use_range = (use_mm, units.in_to_mm(lb / use["lb_per_in_low"]))
        else:
            use_mm = use["use_mm"]
            use_range = (use_mm, use_mm)
        return {"median_supply_mm": median, "use_mm": use_mm, "use_range_mm": use_range, "margin_mm": margin,
                "dry": median < use_mm + margin, "basis": use["basis"], "method": use["method"]}

    def shortfall(self, crop: Crop, kind: str, end: str) -> np.ndarray | None:
        key = ("short", crop.id, kind, end)
        if key not in self._cache:
            need = self.need(crop)
            if need is None:
                self._cache[key] = None
            else:
                sup = self.replay.supply_for(crop.root_zone["value"], crop.growing_season["value"], kind, end)
                self._cache[key] = np.maximum(0.0, need[end] - sup)
        return self._cache[key]

    def short_counts(self, crop: Crop, kind: str) -> dict | None:
        """Short years per end, in the judged window and the full record."""
        key = ("counts", crop.id, kind)
        if key not in self._cache:
            thr = units.in_to_mm(float(self.settings["water.short_threshold_in"]))
            win = self.replay.mask(self.window_years)
            res = {}
            for e in ENDS:
                sf = self.shortfall(crop, kind, e)
                if sf is None:
                    self._cache[key] = None
                    return None
                short = sf > thr
                res[e] = (int(short[win].sum()), int(short.sum()))
            self._cache[key] = res
        return self._cache[key]

    def water_assumed(self, crop: Crop) -> list[Assumed]:
        out = []
        wn = crop.water_need or {}
        if wn.get("basis") and wn["basis"].assumed:
            out.append(Assumed(f"water_need:{crop.id}", f"{crop.name} needs what it usually gets here, "
                                                        "as cereals do (assumed)."))
        for blk, what in ((crop.growing_season, "growing season"), (crop.root_zone, "rooting depth")):
            if blk and blk["basis"].assumed:
                out.append(Assumed(f"{what}:{crop.id}", f"{crop.name} {what}: {_note(blk['basis'])} (assumed)."))
        return out

    # ---- yields
    def expected_yield(self, crop: Crop) -> ExpectedYield:
        key = ("yield", crop.id)
        if key in self._cache:
            return self._cache[key]
        s = self.settings
        lv = self.levels.get(crop.id)
        if crop.id in self.yields_kg_ha:
            out = ExpectedYield(self.yields_kg_ha[crop.id], "farmer")
        elif lv is not None and lv.level_kg_ha is not None and (lv.n_records or lv.borrowed_from):
            out = ExpectedYield(lv.level_kg_ha, "borrowed" if lv.borrowed_from else "records", [], self.zone)
            out.level = lv
        elif crop.regional_yield is None:
            out = ExpectedYield(None, "none")
        else:
            reg = crop.regional_yield
            assumed = [Assumed(f"yield:{crop.id}", f"{crop.name} typical yield: {_note(reg['basis'])} (assumed).")] \
                if reg["basis"].assumed else []
            zone = self.zone
            zones = reg.get("zones") or {}
            if zone == "annual_crop":
                out = ExpectedYield(reg["kg_ha"], "regional", assumed)
            elif zone in zones:
                kg, tag = zones[zone], "zone"
                zb = reg["zone_basis"]
                za = [Assumed(f"yield:{crop.id}", f"{crop.name} typical yield: {_note(zb)} (assumed).")] \
                    if zb.assumed else []
                if zone == "transition" and "after_crop_kg_ha" in reg and "fallow" not in self.reference_kinds(crop.id):
                    kg, tag = reg["after_crop_kg_ha"], "zone_after_crop"
                    if reg["after_crop_basis"].assumed:
                        za = [Assumed(f"yield:{crop.id}", f"{crop.name} typical yield after a harvested crop in the "
                                                          f"Transition zone: {_note(reg['after_crop_basis'])} (assumed).")]
                out = ExpectedYield(kg, tag, za, zone)
            elif crop.role == "cereal" and (crop.water_need or {}).get("method") == "self_calibrated":
                need_in = units.mm_to_in(self.need(crop)["central"])
                lb = max(0.0, need_in - float(s["water.wheat_threshold_in"])) * float(s["water.wheat_bu_per_in"]) * 60
                extra = []
                if crop.water_need["basis"].assumed:
                    extra = [Assumed(f"yield:{crop.id}", f"{crop.name} yield from the wheat water relationship "
                                                         "(assumed to apply to it).")]
                out = ExpectedYield(units.lb_ac_to_kg_ha(lb), "water_relationship", extra, zone)
            else:  # the nearest wetter zone's figure
                kg = zones.get("transition") if zone == "grain_fallow" and "transition" in zones else reg["kg_ha"]
                out = ExpectedYield(kg, "regional_wetter", assumed, zone)
        self._cache[key] = out
        return out

    # ---- residue
    def residue(self, crop: Crop) -> tuple[tuple[float, float, float] | None, list[Assumed]]:
        """Residue at harvest (low, central, high) kg/ha, and the assumed values behind it."""
        key = ("residue", crop.id)
        if key in self._cache:
            return self._cache[key]
        r = crop.residue
        assumed: list[Assumed] = []
        out = None
        if r is None:
            out = None
        elif r["method"] == "none":
            out = (0.0, 0.0, 0.0)
        else:
            if r["basis"].assumed:
                assumed.append(Assumed(f"residue:{crop.id}", f"{crop.name} residue: {_note(r['basis'])} (assumed)."))
            if r["method"] == "range_kg_ha" or r["method"] == "range_lb_ac":
                lo, hi = r["low_kg_ha"], r["high_kg_ha"]
                out = (lo, (lo + hi) / 2, hi)
            else:
                y = self.expected_yield(crop)
                assumed += y.assumed
                if y.kg_ha is None:
                    out = None
                elif r["method"] == "linear_kg_ha":
                    v = max(0.0, r["slope"] * y.kg_ha + r["intercept_kg_ha"])
                    out = (v, v, v)
                elif r["method"] == "harvest_index":
                    hs = (r["h_high"], (r["h_low"] + r["h_high"]) / 2, r["h_low"])  # higher h -> less residue
                    out = tuple(y.kg_ha * (1 - h) / h for h in hs)
        self._cache[key] = (out, assumed)
        return self._cache[key]

    def persist(self, crop: Crop) -> tuple[tuple[float, float, float], list[Assumed]]:
        s = self.settings
        if crop.role == "legume":
            return s.range("residue.persist_legume"), []
        if crop.role in ("cereal", "oilseed"):
            v = s.central("residue.persist_cereal_oilseed")
            return (v, v, v), [Assumed("residue.persist_cereal_oilseed",
                                       f"Cereal and canola residue all stays through the first winter ({v:.0%}, assumed).")]
        return (0.0, 0.0, 0.0), []

    def carry(self, crop: Crop) -> tuple[float, list[Assumed]]:
        s = self.settings
        if crop.role in ("cereal", "oilseed"):
            v = s.central("residue.carry_cereal_oilseed")
            return v, [Assumed("residue.carry_cereal_oilseed",
                               f"{v:.0%} of cereal and canola residue is still there a second winter (assumed).")]
        if crop.role == "legume":
            v = s.central("residue.carry_legume")
            return v, [Assumed("residue.carry_legume", "Legume residue is gone by a second winter (assumed).")]
        return 0.0, []

    def tillage_factor(self) -> tuple[float, list[Assumed]]:
        key = f"residue.tillage_{self.tillage}"
        v = self.settings.central(key)
        out = []
        if self.settings.assumed(key):
            out.append(Assumed(key, f"{TILLAGE_LABELS[self.tillage].capitalize()} leaves {v:.0%} of residue on the surface (assumed)."))
        if not self.tillage_from_farmer:
            out.append(Assumed("residue.default_tillage",
                               f"Tillage is taken as {TILLAGE_LABELS[self.tillage]} because you have not said (assumed default)."))
        return v, out

    # ---- warnings support
    def heat_frequency(self, wid: str) -> tuple[int, int] | None:
        hits = self.extremes.get(wid)
        if not hits:
            return None
        ys = [y for y in self.recent_years if hits.get(y) is not None]
        return sum(1 for y in ys if hits[y]), len(ys)


TILLAGE_LABELS = {"no_till": "no-till", "reduced": "reduced tillage", "conventional": "conventional tillage"}


def crops_of(strategy: Strategy, content: Content, extra: dict[str, Crop] | None = None) -> list[Crop]:
    out = []
    for s in strategy.steps:
        if content.has_crop(s.crop_id):
            out.append(content.crop(s.crop_id))
        elif extra and s.crop_id in extra:
            out.append(extra[s.crop_id])
        else:
            out.append(Crop(id=s.crop_id, name=s.crop_id, role=s.role, class_codes={}))
    return out


# ------------------------------------------------------------------------------------------- water

@register_scorer("water")
def water_measure(crops: list[Crop], fm: FieldModel) -> Quantity:
    n = len(crops)
    slots, missing = [], []
    for i, c in enumerate(crops):
        if c.role in ("fallow", "cover_crop"):
            continue
        kind = kind_of(crops[i - 1].role) if n > 1 else "harvested"
        if fm.need(c) is None:
            missing.append(c.name)
            continue
        slots.append((i, c, kind))
    if not slots:
        return not_assessed("water", "No crop in this rotation has a water figure." if missing else
                            "This rotation grows no crop.", False, "share")
    win_n = len(fm.window_years)
    full_n = len(fm.replay.years)
    shares = {}
    full = {}
    for e in ENDS:
        w = f = 0
        for _, c, k in slots:
            cw, cf = fm.short_counts(c, k)[e]
            w += cw
            f += cf
        shares[e] = w / (len(slots) * win_n)
        full[e] = f / (len(slots) * full_n)
    thr = units.in_to_mm(float(fm.settings["water.short_threshold_in"]))
    win_mask = fm.replay.mask(fm.window_years)
    depths, per_crop = [], []
    hl = int(fm.settings["water.highlight_year"])
    hl_idx = np.where(fm.replay.years == hl)[0]
    highlight = []
    for i, c, k in slots:
        sf = fm.shortfall(c, k, "central")
        sup = fm.replay.supply_for(c.root_zone["value"], c.growing_season["value"], k, "central")
        short = sf > thr
        depths += list(sf[win_mask & short])
        per_crop.append({
            "position": i + 1, "crop": c.name, "after": k,
            "need_mm": fm.need(c)["central"], "median_supply_mm": float(np.median(sup[win_mask])),
            "short_years": int(short[win_mask].sum()), "years": win_n,
            "need_method": c.water_need["method"],
            "need_reference": fm.reference_kinds(c.id),
        })
        if hl_idx.size:
            j = int(hl_idx[0])
            highlight.append({"crop": c.name, "shortfall_mm": float(sf[j]), "short": bool(short[j])})
    assumed = [Assumed("water.short_threshold_in",
                       f"A crop counts as short of water when it is more than "
                       f"{fm.settings['water.short_threshold_in']} in short (assumed).")]
    for _, c, _ in slots:
        assumed += fm.water_assumed(c)
    # Cereal needs are calibrated at each end of the constant ranges too, so the ends of
    # the share are not ordered by supply: the range is simply the lowest and highest.
    return Quantity(
        "water", min(shares.values()), shares["central"], max(shares.values()), False, "share", _uniq(assumed),
        details={
            "window_years": fm.window_years, "dry_mode": fm.dry_mode,
            "full_record": {"low": min(full.values()), "central": full["central"], "high": max(full.values()),
                            "first": int(fm.replay.years[0]), "last": int(fm.replay.years[-1])},
            "typical_shortfall_mm": float(statistics.median(depths)) if depths else None,
            "crops": per_crop, "highlight_year": hl if hl_idx.size else None, "highlight": highlight,
            "not_assessed_crops": missing, "slots": len(slots),
        })


# ------------------------------------------------------------------------------------------- soil protection

@register_scorer("soil")
def soil_measure(crops: list[Crop], fm: FieldModel) -> Quantity:
    n = len(crops)
    till, till_assumed = fm.tillage_factor()
    cover_kg = units.lb_ac_to_kg_ha(fm.settings.central("residue.cover_crop_winter_lb_ac"))
    winters = []
    for k, c in enumerate(crops):
        prev = crops[k - 1] if n > 1 else None
        assumed: list[Assumed] = []
        if c.role == "cover_crop":
            vals = (cover_kg,) * 3
            assumed.append(Assumed("residue.cover_crop_winter_lb_ac",
                                   f"The winter after a cover crop counts as {_fmt_lb(cover_kg)} of cover (assumed)."))
        else:
            res, a1 = fm.residue(c)
            if res is None:
                return not_assessed("soil", f"No residue figure for {c.name}.", True, "kg_ha")
            per, a2 = fm.persist(c) if res[1] > 0 else ((0.0, 0.0, 0.0), [])
            carry_res = (0.0, 0.0, 0.0)
            a3: list[Assumed] = []
            if prev is not None and prev.role not in ("cover_crop",):
                pres, a4 = fm.residue(prev)
                if pres is None:
                    return not_assessed("soil", f"No residue figure for {prev.name}.", True, "kg_ha")
                cf, a5 = fm.carry(prev)
                if pres[1] > 0:
                    carry_res = tuple(cf * x for x in pres)
                    a3 = a4 + a5
            vals = tuple(till * (res[i] * per[i] + carry_res[i]) for i in range(3))
            assumed += a1 + (a2 if res[1] > 0 else []) + (a3 if carry_res[1] > 0 else []) + till_assumed
        winters.append({"after_position": k + 1, "after_crop": c.name, "after_role": c.role,
                        "low": vals[0], "central": vals[1], "high": vals[2], "assumed": assumed})
    lo = min(w["low"] for w in winters)
    ce = min(w["central"] for w in winters)
    hi = min(w["high"] for w in winters)
    weakest = [w for w in winters if w["central"] <= ce + 1e-9]
    assumed = []
    for w in winters:
        if w["central"] <= ce + 1e-9 or w["low"] <= lo + 1e-9 or w["high"] <= hi + 1e-9:
            assumed += w["assumed"]
    yields = {}
    for c in crops:
        if c.residue and c.residue.get("method") in ("linear_kg_ha", "harvest_index"):
            y = fm.expected_yield(c)
            yields[c.name] = {"kg_ha": y.kg_ha, "tag": y.tag, "text": y.text,
                              "borrowed_from": list(y.level.borrowed_from) if y.level is not None else []}
    return Quantity("soil", lo, ce, hi, True, "kg_ha", _uniq(assumed), details={
        "winters": [{k: v for k, v in w.items() if k != "assumed"} for w in winters],
        "weakest": [w["after_position"] for w in weakest],
        "tillage": fm.tillage, "tillage_from_farmer": fm.tillage_from_farmer, "tillage_factor": till,
        "sensitivity": fm.soil.sensitivity(fm.settings), "slope_rep": fm.soil.slope_rep,
        "yields": yields,
    })


# ------------------------------------------------------------------------------------------- nitrogen

def legume_credit(crop: Crop, fm: FieldModel) -> tuple[tuple[float, float, float], list[Assumed], dict]:
    nc = crop.nitrogen_credit
    assumed = []
    if nc is None:
        return (0.0, 0.0, 0.0), [], {}
    if nc["basis"].assumed:
        assumed.append(Assumed(f"nitrogen:{crop.id}", f"{crop.name} nitrogen credit: {_note(nc['basis'])} (assumed)."))
    info: dict = {}
    if nc["method"] == "fixed":
        v = nc["credit_kg_ha"]
        return (v, v, v), assumed, info
    if nc["method"] == "range":
        return (nc["low_kg_ha"], (nc["low_kg_ha"] + nc["high_kg_ha"]) / 2, nc["high_kg_ha"]), assumed, info
    y = fm.expected_yield(crop)
    assumed += y.assumed
    info = {"yield_kg_ha": y.kg_ha, "yield_tag": y.tag, "yield_text": y.text,
            "borrowed_from": list(y.level.borrowed_from) if y.level is not None else []}
    if y.kg_ha is None:
        return (float("nan"),) * 3, assumed, info
    for t in nc["tiers"]:
        if t["below_kg_ha"] is None or y.kg_ha < t["below_kg_ha"]:
            v = t["credit_kg_ha"]
            return (v, v, v), assumed, info
    raise AssertionError("unreachable: the last tier has no bound")


@register_scorer("nitrogen")
def nitrogen_measure(crops: list[Crop], fm: FieldModel) -> Quantity:
    n = len(crops)
    tot = [0.0, 0.0, 0.0]
    assumed: list[Assumed] = []
    per = []
    for i, c in enumerate(crops):
        if c.role != "legume":
            continue
        if c.nitrogen_credit is None:
            return not_assessed("nitrogen", f"No nitrogen figure for {c.name}.", True, "kg_ha_yr")
        v, a, info = legume_credit(c, fm)
        if any(x != x for x in v):
            return not_assessed("nitrogen", f"No yield figure to set the {c.name} nitrogen credit.", True, "kg_ha_yr")
        tot = [tot[j] + v[j] for j in range(3)]
        assumed += a
        per.append({"position": i + 1, "crop": c.name, "low": v[0], "central": v[1], "high": v[2], **info})
    demanding = sum(1 for c in crops if c.role in ("cereal", "oilseed"))
    return Quantity("nitrogen", tot[0] / n, tot[1] / n, tot[2] / n, True, "kg_ha_yr", _uniq(assumed), details={
        "legumes": per, "demanding_years": demanding, "years": n,
    })


# ------------------------------------------------------------------------------------------- variety

def crop_group(c: Crop) -> tuple[str, str] | None:
    g = (c.plant_type, c.sown)
    return g if g in GROUPS else None


@register_scorer("variety")
def variety_measure(crops: list[Crop], fm: FieldModel | None = None) -> Quantity:
    groups = {g for g in (crop_group(c) for c in crops) if g}
    n = len(crops)
    grass = [c.plant_type == "grass" for c in crops]
    if all(grass):
        run = n
    else:
        run, best = 0, 0
        for g in grass + grass:  # twice round the cycle catches runs across the wrap
            run = run + 1 if g else 0
            best = max(best, run)
        run = min(best, n)
    score = len(groups) * 100 - run  # more groups first; then a shorter grass run
    return Quantity("variety", score, score, score, True, "score", [], details={
        "groups": len(groups), "group_names": [GROUP_LABELS[g] for g in GROUPS if g in groups],
        "missing_groups": [GROUP_LABELS[g] for g in GROUPS if g not in groups],
        "grass_run": run,
    })


def score_all(crops: list[Crop], fm: FieldModel, scorers: dict | None = None) -> dict[str, Quantity]:
    if scorers is None:
        from .scoring import SCORER_REGISTRY
        scorers = {m: SCORER_REGISTRY[m] for m in MEASURES}
    return {m: fn(crops, fm) for m, fn in scorers.items()}


def margins(settings) -> dict[str, float]:
    return {
        "water": float(settings["water.margin_points"]) / 100.0,
        "soil": units.lb_ac_to_kg_ha(float(settings["residue.margin_lb_ac"])),
        "nitrogen": units.lb_ac_to_kg_ha(float(settings["nitrogen.margin_lb_ac_yr"])),
        "variety": 0.0,
    }
