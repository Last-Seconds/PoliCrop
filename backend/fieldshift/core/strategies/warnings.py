"""Warnings W1–W9 (brief section 6.1): shown beside an option, never removing it.

Each warning has a priority (lower = shown first); the card shows at most two
and puts the rest behind "more". `key` identifies the same caution on several
cards so the page can show it only once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import units
from ..content import Content, Crop, RuleConfig
from .measures import FieldModel

# Lower = more important. Field-specific risks first; standing notes last.
PRIORITY = {"W7": 10, "W10": 11, "W3": 12, "W9": 12, "W5": 14, "W6": 14, "W4": 16, "W1": 20, "W11": 30, "W4u": 60,
            "W8": 70}


@dataclass
class Warning:
    code: str
    key: str
    short: str  # one line for the card
    text: str  # fuller text for the details ("Check locally")
    priority: int
    basis: str
    source: str | None
    serious: bool = False  # addendum 2, A1: ranks the option last and is never hidden

    def to_dict(self) -> dict:
        return {"code": self.code, "key": self.key, "short": self.short, "text": self.text,
                "priority": self.priority, "basis": self.basis, "source": self.source, "serious": self.serious}


SERIOUS_HEAT_YEARS = 5  # addendum 2, A1 (assumed): chickpea heat counts as serious in 5 or more of 15 years


def is_serious(w: Warning) -> bool:
    return w.serious


WARNING_REGISTRY: dict[str, Callable] = {}


def register(wid: str):
    def deco(fn):
        WARNING_REGISTRY[wid] = fn
        return fn
    return deco


def _gaps(positions: list[int], n: int) -> list[int]:
    """Cyclic gaps between occurrences (in years)."""
    if not positions:
        return []
    if len(positions) == 1:
        return [n]
    ps = sorted(positions)
    return [b - a for a, b in zip(ps, ps[1:])] + [ps[0] + n - ps[-1]]


def _deg(v) -> str:
    """A temperature with a true minus sign."""
    v = float(v)
    return f"{'−' if v < 0 else ''}{abs(v):g} °F"


def _freq(hit: int, of: int) -> str:
    return f"in {hit} of the last {of} years"


@register("chickpeas_every_third_year")
def w1(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    pos = [i for i, c in enumerate(crops) if c.id == p.get("crop", "chickpeas")]
    if pos and int(p.get("gap_years", 3)) in _gaps(pos, len(crops)):
        return [Warning(cfg.code, "W1", "Chickpeas every third year",
                        "Chickpeas come back every third year. Guides say once in 3 to 5 years, and 4 to 5 years "
                        "where Fusarium wilt is present, because of disease (Ascochyta blight).",
                        PRIORITY["W1"], cfg.basis, cfg.source)]
    return []


def _dry(crop_id: str, label: str, wid: str):
    def fn(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
        if not any(c.id == p.get("crop", crop_id) for c in crops):
            return []
        limit = float(p["min_precip_in"])
        mean_in = units.mm_to_in(fm.mean_precip_mm)
        if mean_in >= limit:
            return []
        name = fm.content.crop(p.get("crop", crop_id)).name
        why = {"W3": "Spring canola is uncommon where yearly rain and snow is under 12 in.",
               "W9": "Very little spring pea is grown below about 17.7 in (450 mm) a year: water and heat stress "
                     "at flowering limit it."}[wid]
        return [Warning(cfg.code, wid, f"{name} in a dry place",
                        f"This field gets about {mean_in:.1f} in of rain and snow a year. {why}",
                        PRIORITY[wid], cfg.basis, cfg.source)]
    return fn


WARNING_REGISTRY["spring_canola_dry"] = _dry("spring_canola", "Spring canola", "W3")
WARNING_REGISTRY["spring_peas_dry"] = _dry("spring_peas", "Spring peas", "W9")


@register("may_be_too_dry")
def w10(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    """Brief 3, S1: a crop's median supply here is under its sourced water use plus the shortfall margin."""
    dry = []
    for c in {x.id: x for x in crops}.values():
        t = fm.too_dry(c)
        if t and t["dry"]:
            dry.append((c, t))
    if not dry:
        return []
    c, t = dry[0]
    names = [x.name.lower() for x, _ in dry]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    def used(tt):
        if tt["method"] == "from_yield":
            lo, hi = (units.mm_to_in(v) for v in tt["use_range_mm"])
            return f"would use about {lo:.1f} to {hi:.1f} in at its typical yield here"
        return f"used about {units.mm_to_in(tt['use_mm']):.1f} in in a trial"
    per = "; ".join(f"{x.name.lower()} usually gets about {units.mm_to_in(tt['median_supply_mm']):.1f} in here and "
                    f"{used(tt)}" for x, tt in dry)
    return [Warning(cfg.code, "W10", f"{who[:1].upper() + who[1:]} may be too dry here",
                    f"{per[:1].upper() + per[1:]}. With less than that plus "
                    f"{units.mm_to_in(t['margin_mm']):.1f} in to spare, a crop here is often short of water.",
                    PRIORITY["W10"], cfg.basis, cfg.source, serious=True)]


@register("not_seen_nearby")
def w11(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    """Brief 3, S1: under `min_share` of nearby cropland follows this kind of rotation."""
    if fm.nearby is None:
        return []
    share = fm.nearby.share(crops)
    lim = float(p.get("min_share", 0.01))
    if share is None or share >= lim:
        return []
    return [Warning(cfg.code, "W11", "Not seen nearby",
                    f"Under {lim:.0%} of the cropland near this field followed this kind of rotation in recent "
                    f"years ({share:.1%}). That does not make it wrong, but nobody nearby shows it works here.",
                    PRIORITY["W11"], cfg.basis, cfg.source)]


@register("soil_acidity")
def w4(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    sensitive = [c for c in crops if c.critical_ph is not None]
    if not sensitive:
        return []
    if fm.ph is None:
        names = sorted({c.name.lower() for c in sensitive})
        names = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
        return [Warning(cfg.code, "W4u", "Soil acidity not checked",
                        f"Soil pH is not known, so acid soil was not checked for {names}. Measured pH in the region "
                        "has fallen below 5 in places; the soil survey's figure describes the soil as surveyed and "
                        "is not used. Add a soil test pH under Adjust, more settings.", PRIORITY["W4u"], cfg.basis, cfg.source)]
    out = []
    unique = list({c.id: c for c in sensitive}.values())
    for c in sorted(unique, key=lambda c: -c.critical_ph["high"]):
        lo, hi = c.critical_ph["low"], c.critical_ph["high"]
        if fm.ph < hi:
            crit = f"{lo}" if lo == hi else f"{lo}–{hi}"
            out.append(Warning(cfg.code, f"W4:{c.id}", f"Soil may be too acid for {c.name.lower()}",
                               f"Your soil test pH is {fm.ph:g}; {c.name.lower()} loses significant yield below "
                               f"about pH {crit}. No absolute cutoff exists; it depends on the soil and the variety.",
                               PRIORITY["W4"], cfg.basis, cfg.source))
    return out[:1] + [Warning(w.code, w.key, w.short, w.text, w.priority + 1, w.basis, w.source) for w in out[1:]]


@register("chickpea_heat")
def w5(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    if not any(c.id == p.get("crop", "chickpeas") for c in crops):
        return []
    f = fm.heat_frequency("W5")
    if f is None:
        return []
    hit, of = f
    lim = _deg(p.get("limit_f", 98))
    return [Warning(cfg.code, "W5", f"Chickpea heat in {hit} of {of} years",
                    f"Chickpeas are stressed at or above {lim} in early flowering and pod fill. A day that hot came "
                    f"in June or July {_freq(hit, of)} here (the June–July window is assumed).",
                    PRIORITY["W5"] + (0 if hit else 30), cfg.basis, cfg.source, serious=hit >= SERIOUS_HEAT_YEARS)]


@register("winter_pea_cold")
def w6(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    if not any(c.id == p.get("crop", "winter_peas") for c in crops):
        return []
    f = fm.heat_frequency("W6")
    if f is None:
        return []
    hit, of = f
    lim = _deg(p.get("limit_f", -6))
    snow_known = any((fm.extremes.get("W6_snow_known") or {}).values())
    anyf = fm.heat_frequency("W6_any")
    if snow_known:  # addendum 2, A3
        short = f"Cold enough to kill, with little snow, in {hit} of {of} winters"
        how = (f"A night at or below {lim} came with little or no snow on the ground (under {p.get('snow_below_kg_m2', 10)} "
               f"kg/m² of snow water, a modelled estimate from Daymet) between November and March in {hit} of the last "
               f"{of} winters here" + (f"; a night that cold with any snow cover came in {anyf[0]}." if anyf else "."))
    else:
        short = f"Winter-kill risk in {hit} of {of} years"
        how = (f"A night that cold came between November and March {_freq(hit, of)} here. Snow cover, which protects "
               "the crop, is not known.")
    return [Warning(cfg.code, "W6", short,
                    f"Winter hardiness depends on the variety: from −5 °F ('Lynx') to +10 °F (Austrian winter pea); "
                    f"{lim} is the limit for 'Windham', the variety in the regional trials. " + how,
                    PRIORITY["W6"] + (0 if hit else 30), cfg.basis, cfg.source, serious=hit > 0)]


@register("peas_poor_drainage")
def w7(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    peas = [c for c in crops if c.id in p.get("crops", [])]
    d = fm.soil.drainage
    if not peas or not d or d not in p.get("drainage", []):
        return []
    return [Warning(cfg.code, "W7", "Peas on poorly drained soil",
                    f"The main soil on this field ({fm.soil.main_component or 'from the soil survey'}) is {d.lower()}. "
                    "Peas are not planted on poorly drained soils: they die after 24–48 hours of waterlogging.",
                    PRIORITY["W7"], cfg.basis, cfg.source)]


@register("herbicide_carryover")
def w8(crops: list[Crop], fm: FieldModel, p: dict, cfg: RuleConfig) -> list[Warning]:
    n = len(crops)
    hit = False
    for i, c in enumerate(crops):
        prev = crops[i - 1] if n > 1 else None
        if prev is None:
            continue
        if prev.role == "cereal" and c.role in ("legume", "oilseed"):
            hit = True
        if prev.role == "legume" and c.role == "oilseed":
            hit = True
    if not hit:
        return []
    return [Warning(cfg.code, "W8", "Check herbicide carryover",
                    "Some herbicides limit what can follow them for years: for example, after chlorsulfuron (Glean) on "
                    "cereals the label restricts lentils for 36 months and peas for 24; imazethapyr (Pursuit), used on "
                    "legumes, has damaged canola up to six years later. This tool cannot know what was sprayed.",
                    PRIORITY["W8"], cfg.basis, cfg.source)]


def evaluate(crops: list[Crop], fm: FieldModel, configs: list[RuleConfig]) -> list[Warning]:
    out = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        fn = WARNING_REGISTRY.get(cfg.id)
        if fn is None:
            raise ValueError(f"rules.yaml enables unknown warning {cfg.id!r}; known: {sorted(WARNING_REGISTRY)}")
        out += fn(crops, fm, cfg.params, cfg)
    return sorted(out, key=lambda w: w.priority)


def check_configs(configs: list[RuleConfig]) -> None:
    for cfg in configs:
        if cfg.enabled and cfg.id not in WARNING_REGISTRY:
            raise ValueError(f"rules.yaml enables unknown warning {cfg.id!r}; known: {sorted(WARNING_REGISTRY)}")


def content_check(content: Content) -> None:
    check_configs(content.warnings)
