"""The display edge: turns a PlanResult into the farmer's screen, in plain words and US units.

Explanations are templates filled with computed values (no trained model).
Word list (brief section 9): no "NDVI", "candidate", "dominated", "replay",
"precipitation", "provisional" or metric units reach the farmer's view.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction

from . import units
from .content import Content
from .strategies.compare import BAND_LABELS, BETTER, SAME, WORSE
from .strategies.measures import MEASURE_LABELS, MEASURES, TILLAGE_LABELS, Assumed, Quantity
from .strategies.plan import Option, PlanResult

SYMBOL = {BETTER: "▲", SAME: "●", WORSE: "▼", None: "–"}
QUESTIONS = {
    "water": "Does the field's water cover what the crops need, including in dry years?",
    "soil": "How well is the soil covered in its least-protected winter, and how much does that matter on this field's slopes?",
    "nitrogen": "How much nitrogen do legumes in the rotation supply to the following crops?",
    "variety": "Does the rotation mix crop types and seasons enough to break weed and disease cycles?",
}
BETTER_PHRASE = {"water": "short of water less often", "soil": "more crop residue on the soil over winter",
                 "nitrogen": "more nitrogen from legumes", "variety": "more crop variety"}
WORSE_PHRASE = {"water": "short of water more often", "soil": "less crop residue on the soil over winter",
                "nitrogen": "less nitrogen from legumes", "variety": "less crop variety"}
KIND_WORDS = {"harvested": "a harvested crop", "fallow": "fallow", "cover": "a cover crop"}
MODEL_GAPS = [
    "Heat and evaporation are not in the water estimate. A hot, dry spring hurts crops more than the missing rain "
    "alone suggests.",
    "Every crop is assumed to need what it usually gets on this field, as cereals are. Peas, lentils, chickpeas "
    "and canola may swing more or less with the year than wheat; that is not in the water verdict yet.",
    "Water left behind by shallow-rooted crops is ignored. Peas, lentils and chickpeas \u201cgenerally use 15\u201335% "
    "less water than cereals or oilseeds, leaving more water in the profile for subsequent crops\u201d [S27].",
    "Weather is a 1 km grid estimate (Daymet), and soil water storage comes from the soil survey, not from your field.",
]


# ------------------------------------------------------------------------------------------- formatting

def inch(mm: float, digits: int = 1) -> str:
    return f"{units.mm_to_in(mm):.{digits}f} in"


def lbac(kg_ha: float) -> str:
    v = units.kg_ha_to_lb_ac(kg_ha)
    return f"{_round_sig(v):,.0f} lb/acre"


def _round_sig(v: float) -> float:
    if v >= 1000:
        return round(v / 100) * 100
    if v >= 100:
        return round(v / 10) * 10
    return round(v)


def _n(v: float) -> str:
    return f"{v:.0f}" if v >= 10 or v == 0 else f"{v:.1f}".rstrip("0").rstrip(".")


def lbac_yr(kg_ha: float) -> str:
    return f"{_n(units.kg_ha_to_lb_ac(kg_ha))} lb/acre a year"


def lbac_range(lo_kg: float, hi_kg: float) -> str:
    return f"{_round_sig(units.kg_ha_to_lb_ac(lo_kg)):,.0f} to {lbac(hi_kg)}"


def lbac_yr_range(lo_kg: float, hi_kg: float) -> str:
    return f"{_n(units.kg_ha_to_lb_ac(lo_kg))} to {lbac_yr(hi_kg)}"


def years_grow(k: int, n: int) -> str:
    return f"{k} of {n} years grow{'s' if k == 1 else ''}"


def share_words(p: float, noun: str = "crop") -> str:
    """'about 1 crop in 5', as people say it."""
    if p is None or p != p:
        return "not known"
    if p <= 0.0:
        return f"no {noun}"
    if p >= 0.995:
        return f"every {noun}"
    if p < 0.05:
        return f"fewer than 1 {noun} in 20"
    best = min((Fraction(a, b) for b in range(2, 11) for a in range(1, b)), key=lambda f: (abs(float(f) - p), f.denominator))
    a, b = best.numerator, best.denominator
    return f"about {a} {noun}{'s' if a > 1 else ''} in {b}"


def pct(p: float) -> str:
    return f"{p * 100:.0f}%"


def join_words(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def rotation_words(names: list[str]) -> str:
    if not names:
        return ""
    first = names[0]
    rest = [n.lower() for n in names[1:]]
    return ", then ".join([first] + rest) if len(names) <= 2 else f"{first}, " + ", ".join(rest[:-1]) + f", then {rest[-1]}"


# ------------------------------------------------------------------------------------------- measure lines

def _years_phrase(q: Quantity) -> str:
    d = q.details
    ys = d["window_years"]
    if d.get("dry_mode"):
        return f"in the {len(ys)} driest of the last 15 years"
    return f"over the last {len(ys)} years ({ys[0]}–{ys[-1]})"


def water_text(q: Quantity) -> dict:
    if not q.assessed:
        return {"value": f"Not assessed: {q.not_assessed_reason}", "range": None}
    v = f"{share_words(q.central).capitalize()} was short of water {_years_phrase(q)}"
    rng = None if abs(q.high - q.low) < 0.005 else f"{pct(q.low)} to {pct(q.high)} of crops, depending on how much winter rain the soil keeps"
    return {"value": v, "range": rng}


def soil_text(q: Quantity) -> dict:
    if not q.assessed:
        return {"value": f"Not assessed: {q.not_assessed_reason}", "range": None}
    w = [x for x in q.details["winters"] if x["after_position"] in q.details["weakest"]][0]
    after = "after the cover crop" if w["after_role"] == "cover_crop" else (
        "at the end of the fallow year" if w["after_role"] == "fallow" else f"after the {w['after_crop'].lower()}")
    v = f"About {lbac(q.central)} of crop residue in the winter with least cover, {after}"
    rng = None if abs(q.high - q.low) < 1 else lbac_range(q.low, q.high)
    return {"value": v, "range": rng}


def nitrogen_text(q: Quantity) -> dict:
    if not q.assessed:
        return {"value": f"Not assessed: {q.not_assessed_reason}", "range": None}
    if q.central <= 0:
        v = "No nitrogen from legumes (no legume in the rotation)"
    else:
        v = f"About {lbac_yr(q.central)} of nitrogen left by legumes for the next crop"
    rng = None if abs(q.high - q.low) < 0.05 else lbac_yr_range(q.low, q.high)
    return {"value": v, "range": rng}


def variety_text(q: Quantity) -> dict:
    d = q.details
    run = d["grass_run"]
    run_t = "no grass crops" if run == 0 else (f"at most {run} grass crop{'s' if run > 1 else ''} in a row")
    return {"value": f"{d['groups']} of 4 kinds of crop; {run_t}", "range": None}


TEXT = {"water": water_text, "soil": soil_text, "nitrogen": nitrogen_text, "variety": variety_text}


def sensitivity_note(fm) -> str | None:
    sens = fm.soil.sensitivity(fm.settings)
    if sens == "high":
        return f"This field is steep (about {fm.soil.slope_rep:g}% slope), so winter cover matters more here."
    if sens == "low":
        return f"This field is fairly flat (about {fm.soil.slope_rep:g}% slope), so winter cover matters less here."
    if sens == "moderate":
        return f"This field has moderate slopes (about {fm.soil.slope_rep:g}%)."
    return None


def measure_lines(opt: Option, current: Option, fm) -> list[dict]:
    out = []
    for m in MEASURES:
        q = opt.scores[m]
        v = opt.verdicts.get(m)
        t = TEXT[m](q)
        now = None if opt is current else TEXT[m](current.scores[m])["value"]
        note = sensitivity_note(fm) if m == "soil" else None
        if m == "nitrogen" and q.assessed:
            note = f"{years_grow(q.details['demanding_years'], q.details['years'])} a crop that needs nitrogen."
        out.append({
            "measure": m, "label": MEASURE_LABELS[m],
            "verdict": None if opt is current else v.value,
            "verdict_word": None if opt is current else ("about the same" if v.value == SAME else v.word),
            "symbol": None if opt is current else SYMBOL[v.value],
            "held_by_assumed": bool(v and v.held_by_assumed),
            "assessed": q.assessed,
            "value_text": t["value"], "range_text": t["range"], "now_text": now, "note": note,
        })
    return out


# ------------------------------------------------------------------------------------------- details

def _src(content: Content, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        s = content.sources.get(i)
        if s:
            out.append({"id": i, "citation": s.get("citation"), "url": s.get("url")})
    return out


def evidence(opt: Option, res: PlanResult, content: Content) -> list[dict]:
    fm = res.field_model
    s = content.settings
    out = []
    # Water
    q = opt.scores["water"]
    lines = []
    if q.assessed:
        d = q.details
        lines.append(f"{water_text(q)['value']}." + (f" Range: {water_text(q)['range']}." if water_text(q)['range'] else ""))
        fr = d["full_record"]
        lines.append(f"Over the whole record ({fr['first']}–{fr['last']}): {share_words(fr['central'])} "
                     f"({pct(fr['central'])}).")
        if d["typical_shortfall_mm"] is not None:
            lines.append(f"When short, typically by {inch(d['typical_shortfall_mm'])}. For wheat, each inch is worth "
                         f"about {s['water.wheat_bu_per_in']} bu/acre (an illustration, not a yield forecast).")
        if d.get("highlight_year"):
            hy = d["highlight_year"]
            hs = [h for h in d["highlight"]]
            short = [h for h in hs if h["short"]]
            if short:
                lines.append(f"In {hy}, the driest and hottest year on record here: " + join_words(
                    [f"{h['crop'].lower()} short by {inch(h['shortfall_mm'])}" for h in short]) + ".")
            else:
                lines.append(f"In {hy}, the driest and hottest year on record here, no crop in this rotation came out "
                             "short by this water estimate, which has no heat term (see What we don't know).")
        for c in d["crops"]:
            ref = join_words([KIND_WORDS[k] for k in c["need_reference"]])
            how = f"what it usually gets here after {ref}"
            lines.append(f"{c['crop']} after {KIND_WORDS[c['after']]}: needs about {inch(c['need_mm'])} ({how}); "
                         f"usually gets {inch(c['median_supply_mm'])}; short in {c['short_years']} of {c['years']} years.")
        if d["not_assessed_crops"]:
            lines.append(f"Not assessed for water (no figure): {join_words(sorted(set(d['not_assessed_crops'])))}.")
        if fm.fitted:
            lines.append("✎ Fitted to your records: " + "; ".join(
                f"{FIT_WORDS[k]} {v:.0%}" for k, v in fm.fitted.items()) + "." + _example(fm, "records"))
    else:
        lines.append(f"Not assessed: {q.not_assessed_reason}")
    out.append({"measure": "water", "label": MEASURE_LABELS["water"], "lines": lines,
                "sources": _src(content, ["S6", "S7", "S14", "S3", "S4"])})
    # Soil protection
    q = opt.scores["soil"]
    lines = []
    if q.assessed:
        lines.append("Crop residue means the straw and stubble left on the field. Erosion here happens in winter, "
                     "from rain and snowmelt on frozen ground, so the winter with least cover is what counts.")
        for w in q.details["winters"]:
            after = ("a cover crop" if w["after_role"] == "cover_crop" else
                     "the fallow year" if w["after_role"] == "fallow" else f"the {w['after_crop'].lower()}")
            rng = "" if abs(w["high"] - w["low"]) < 1 else f" ({lbac_range(w['low'], w['high'])})"
            lines.append(f"Winter after {after} (year {w['after_position']}): about {lbac(w['central'])}{rng}.")
        t = q.details["tillage"]
        lines.append(f"Tillage: {TILLAGE_LABELS[t]}" + ("" if q.details["tillage_from_farmer"] else " (the default; change it under Adjust)")
                     + f", leaving {q.details['tillage_factor']:.0%} of residue on the surface.")
        for name, y in q.details["yields"].items():
            if y["kg_ha"] is not None:
                lines.append(f"{name} residue is estimated from {y['text']}{_borrowed(y, fm)}: {lbac(y['kg_ha'])} of grain."
                             + _example(fm, y["tag"]))
        note = sensitivity_note(fm)
        if note:
            lines.append(note + " No tons-per-acre erosion figure is given: the standard formula handles "
                                "runoff on frozen ground poorly.")
    else:
        lines.append(f"Not assessed: {q.not_assessed_reason}")
    out.append({"measure": "soil", "label": MEASURE_LABELS["soil"], "lines": lines,
                "sources": _src(content, ["S6", "S8", "S9", "S19"])})
    # Nitrogen
    q = opt.scores["nitrogen"]
    lines = []
    if q.assessed:
        lines.append(f"{nitrogen_text(q)['value']}." + (f" Range: {nitrogen_text(q)['range']}." if nitrogen_text(q)['range'] else ""))
        for l in q.details["legumes"]:
            rng = "" if abs(l["high"] - l["low"]) < 0.1 else f" ({units.kg_ha_to_lb_ac(l['low']):.0f}–{units.kg_ha_to_lb_ac(l['high']):.0f})"
            yt = (f", at {lbac(l['yield_kg_ha'])} from {l['yield_text']}{_borrowed({'borrowed_from': l.get('borrowed_from')}, fm)}"
                  + _example(fm, l.get("yield_tag"))) if l.get("yield_kg_ha") else ""
            lines.append(f"{l['crop']} (year {l['position']}): about {units.kg_ha_to_lb_ac(l['central']):.0f} lb/acre{rng} "
                         f"for the next crop{yt}.")
        lines.append(f"{years_grow(q.details['demanding_years'], q.details['years'])} a crop that needs nitrogen "
                     "(a cereal or canola).")
        wn = s["nitrogen.wheat_need_lb_per_bu"]
        lines.append(f"For scale: winter wheat needs {wn['low']} to {wn['high']} lb of nitrogen per bushel; canola needs "
                     "more per pound of seed than wheat. Less fertiliser also slows soil acidification.")
        b = s["nitrogen.wheat_boost_after_legume_pct"]
        lines.append(f"Wheat after a legume may also yield more: {b['low']} to {b['high']}% in different studies "
                     "(19% after peas in regional research; no difference in a 2023–2024 Pullman trial). Not scored.")
    else:
        lines.append(f"Not assessed: {q.not_assessed_reason}")
    out.append({"measure": "nitrogen", "label": MEASURE_LABELS["nitrogen"], "lines": lines,
                "sources": _src(content, ["S11", "S23", "S10", "S22", "S12", "S18", "S15"])})
    # Variety
    q = opt.scores["variety"]
    d = q.details
    lines = [f"Grows {d['groups']} of the 4 kinds of crop: {join_words(d['group_names']) or 'none'}."]
    if d["missing_groups"]:
        lines.append(f"Missing: {join_words(d['missing_groups'])}.")
    lines.append(f"Longest run of grass crops (wheat, barley) in a row: {d['grass_run']}.")
    lines.append("Why kinds, not crop names: the main grass weeds here (downy brome, jointed goatgrass) share "
                 "winter wheat's life cycle, and broadleaf crops allow selective control of grass weeds.")
    out.append({"measure": "variety", "label": MEASURE_LABELS["variety"], "lines": lines,
                "sources": _src(content, ["S4", "S3"])})
    return out


FIT_WORDS = {"e_winter": "share of winter rain and snow the soil keeps", "storage_factor": "soil water storage, as a share of the soil survey's"}


def _borrowed(y: dict, fm) -> str:
    names = [fm.content.crop(c).name.lower() for c in (y.get("borrowed_from") or []) if fm.content.has_crop(c)]
    return f" (borrowed: estimated from your {join_words(names)} records)" if names else ""


def _example(fm, tag) -> str:
    return " Example data, not a real farm." if fm.example and tag in ("records", "borrowed") else ""


def records_mark(m: str, opt: Option, fm) -> str:
    """A short mark on a first-layer line whose figure came from the farmer's records (brief 3, part C)."""
    if m == "water" and fm.fitted:
        mark = "fitted to your records"
    elif m in ("soil", "nitrogen"):
        tags = set()
        src = opt.scores[m].details.get("yields", {}).values() if m == "soil" else opt.scores[m].details.get("legumes", [])
        for y in src:
            tags.add(y.get("tag") or y.get("yield_tag"))
        if not tags & {"records", "borrowed"}:
            return ""
        mark = "uses your records" if "records" in tags else "borrowed from your records"
    else:
        return ""
    return f" ✎ {mark}" + (" (example data, not a real farm)" if fm.example else "") + "."


def why(opt: Option, current: Option) -> list[str]:
    b = [m for m in MEASURES if opt.verdicts[m].value == BETTER]
    w = [m for m in MEASURES if opt.verdicts[m].value == WORSE]
    same = [m for m in MEASURES if opt.verdicts[m].value == SAME]
    out = []
    if b:
        out.append(f"Better than now on {join_words([MEASURE_LABELS[m].lower() for m in b])}.")
        parts = []
        for m in b:
            q, c = opt.scores[m], current.scores[m]
            if m == "water":
                parts.append(f"{share_words(q.central)} short of water against {share_words(c.central)} now")
            elif m == "soil":
                parts.append(f"about {lbac(q.central)} of residue in the winter with least cover against {lbac(c.central)} now")
            elif m == "nitrogen":
                parts.append(f"about {lbac_yr(q.central)} of nitrogen from legumes against {lbac_yr(c.central)} now")
            elif m == "variety":
                if q.details["groups"] != c.details["groups"]:
                    parts.append(f"{q.details['groups']} of 4 kinds of crop against {c.details['groups']} now")
                else:
                    def run(r):
                        return "no grass crops" if r == 0 else f"at most {r} grass crop{'s' if r > 1 else ''} in a row"
                    parts.append(f"{run(q.details['grass_run'])}, against {run(c.details['grass_run'])} now")
        out.append(parts[0][:1].upper() + parts[0][1:] + ("; " + "; ".join(parts[1:]) if parts[1:] else "") + ".")
    else:
        out.append("Not better than now on any of the four measures; it is shown because it changes the rotation by a "
                   "different amount and is not beaten by another option.")
    if w:
        out.append(f"Worse on {join_words([MEASURE_LABELS[m].lower() for m in w])}.")
    held = [m for m in MEASURES if opt.verdicts[m].held_by_assumed]
    if held:
        out.append(f"Called about the same on {join_words([MEASURE_LABELS[m].lower() for m in held])} because the "
                   "difference depends on an assumed figure.")
    return out


def gains(opt: Option, current: Option, res: PlanResult, content: Content) -> list[str]:
    out = []
    fm = res.field_model
    for m in MEASURES:
        if opt.verdicts[m].value != BETTER:
            continue
        if m == "water":
            out.append("Fewer years in which a crop runs short of water.")
        elif m == "soil":
            sens = fm.soil.sensitivity(fm.settings)
            out.append("More straw and stubble on the field over winter, when erosion happens here."
                       + (" That matters more on this field's slopes." if sens == "high" else ""))
        elif m == "nitrogen":
            gain = units.kg_ha_to_lb_ac(opt.scores[m].central - current.scores[m].central)
            out.append(f"About {gain:.0f} lb/acre a year more nitrogen left for the following crops, so less to buy; "
                       "less fertiliser also slows soil acidification.")
        elif m == "variety":
            out.append("More ways to break weed and disease cycles, including selective control of grass weeds in "
                       "broadleaf years.")
    h, hc = opt.strategy.harvests, current.strategy.harvests
    n = len(opt.strategy.steps)
    if h != hc:
        out.append(f"{h} harvests in {n} years, against {hc} now.")
    if not out:
        out.append("No measured gain over your current rotation; see Why this option.")
    return out


def assumed_for(opt: Option, current: Option) -> list[dict]:
    """Assumed values behind this option's measures and the current rotation's, by measure."""
    out = []
    seen = set()
    for m in MEASURES:
        items: list[Assumed] = list(opt.scores[m].assumed) + ([] if opt is current else list(current.scores[m].assumed))
        for a in items:
            if a.key in seen:
                continue
            seen.add(a.key)
            out.append({"measure": m, "measure_label": MEASURE_LABELS[m], "text": a.text,
                        "decided": (opt is not current) and opt.verdicts[m].held_by_assumed})
    return out


def unknowns(opt: Option, current: Option, res: PlanResult) -> list[str]:
    out = []
    for m in MEASURES:
        q = opt.scores[m]
        if not q.assessed:
            out.append(f"{MEASURE_LABELS[m]} not assessed: {q.not_assessed_reason}")
    wq = opt.scores["water"]
    if wq.assessed and wq.details["not_assessed_crops"]:
        out.append(f"No water figure for {join_words(sorted(set(wq.details['not_assessed_crops'])))}.")
    for a in assumed_for(opt, current):
        out.append(f"{a['measure_label']}: {a['text']}")
    fm = res.field_model
    for name, y in (opt.scores["soil"].details.get("yields") or {}).items():
        if y["tag"] == "regional_wetter":
            out.append(f"The {name.lower()} yield is a typical figure from a wetter zone: none is published for this one.")
    for l in opt.scores["nitrogen"].details.get("legumes", []) if opt.scores["nitrogen"].assessed else []:
        if l.get("yield_tag") == "regional_wetter":
            out.append(f"The {l['crop'].lower()} yield behind its nitrogen credit is a typical figure from a wetter zone.")
    if fm.soil.capacity_default:
        out.append("The soil database could not be read, so soil water storage uses a stated default "
                   f"({inch(fm.soil.capacity_mm['0_150cm'])} in the top 5 ft).")
    out += MODEL_GAPS
    if res.inputs.temp_f:
        out.append("The temperature setting changes how often the heat and cold limits are reached; it does not raise "
                   "crop water demand, because the water estimate has no evaporation term. That understates the effect of warming.")
    return list(dict.fromkeys(out))


# A crop's listed limits repeat what these warnings say; show the limit only when its warning did not fire.
LIMIT_WARNINGS = {"chickpeas": ("W1", "W5"), "winter_peas": ("W6",), "spring_peas": ("W7", "W9"),
                  "spring_canola": ("W3",), "winter_canola": ()}


def check_items(opt: Option, content: Content) -> list[str]:
    out = [w.text for w in opt.warnings]
    fired = {w.code for w in opt.warnings}
    for r in opt.strategy.rule_results:
        if not r.passed:
            out.append(f"{r.label}: {r.reason}")
    for c in opt.crops:
        if fired & set(LIMIT_WARNINGS.get(c.id, ())):
            continue
        for lim in getattr(c, "limits", ()) or ():
            t = lim.get("text") if isinstance(lim, dict) else str(lim)
            if t:
                out.append(f"{c.name}: {t[:1].lower() + t[1:]}")
    out.append(str(content.settings["assessment.check_locally"]))
    return list(dict.fromkeys(out))


# ------------------------------------------------------------------------------------------- notes

def income_note(opt: Option, content: Content) -> dict:
    rows, missing = [], []
    for c in opt.crops:
        inc = getattr(c, "income", None)
        if inc:
            rows.append({"crop": c.name, "label": inc["label"], "usd_ac": inc["return_usd_ac"]})
        else:
            missing.append(c.name)
    avg = None
    if not missing and rows:
        avg = sum(r["usd_ac"] for r in rows) / len(opt.crops)
    return {
        "label": "2011–2015 regional averages",
        "rows": rows, "missing": sorted(set(missing)), "average_usd_ac_yr": avg,
        "context": ["In 2016 winter wheat lost money while peas, chickpeas and lentils did not.",
                    "A crop that loses money in its own year can still raise the rotation's return, through weed "
                    "control and better wheat yields afterwards."],
        "source": "S18",
    }


def notes(opt: Option, current: Option, content: Content) -> dict:
    n = len(opt.strategy.steps)
    h, hc = opt.strategy.harvests, current.strategy.harvests
    changed = opt.strategy.years_changed(current.strategy)
    harvest_text = f"{h} harvest{'s' if h != 1 else ''} in {n} years"
    if opt is not current:
        harvest_text += f" (now {hc})"
    nearby = None
    if opt.nearby is not None:
        nearby = {"share": opt.nearby, "text": f"{pct(opt.nearby)} of nearby cropland followed this kind of rotation "
                                               "recently: evidence it is workable here, not proof it is good."}
    return {
        "harvests": h, "years": n, "harvests_text": harvest_text,
        "years_changed": changed, "changes_text": "No change" if opt is current else f"Changes {changed} of {n} years",
        "change_details": opt.strategy.differences,
        "income": income_note(opt, content),
        "nearby": nearby,
    }


# ------------------------------------------------------------------------------------------- cards

def summary_sentence(opt: Option, current: Option) -> str:
    if opt is current:
        return "Your rotation as the crop map shows it, continued as it is."
    b = [BETTER_PHRASE[m] for m in MEASURES if opt.verdicts[m].value == BETTER]
    w = [WORSE_PHRASE[m] for m in MEASURES if opt.verdicts[m].value == WORSE]
    change = opt.strategy.summary
    if b and w:
        reason = f"{join_words(b)}, but {join_words(w)}"
    elif b:
        reason = join_words(b)
    elif w:
        reason = f"about the same otherwise, but {join_words(w)}"
    else:
        reason = "about the same on all four measures"
    return f"{change}: {reason}."


VERDICT_WORDS = {BETTER: "better", SAME: "about the same", WORSE: "worse", None: "not assessed"}
SHORT_NAMES = {"Winter wheat": "Winter wheat", "Spring wheat": "Spring wheat", "Spring barley": "Barley"}


def word_count(*texts) -> int:
    """Words as the brief counts them: runs of letters or digits (symbols such as ▲ do not count)."""
    n = 0
    for t in texts:
        if isinstance(t, (list, tuple)):
            n += word_count(*t)
        elif t:
            n += len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.,–-]*", str(t)))
    return n


def closed_card(opt: Option, current: Option, cautions: list[dict]) -> dict:
    """What a closed card shows (brief 3, S2 target 3): 45 words or fewer."""
    is_cur = opt is current
    verdicts = []
    for m in MEASURES:
        v = None if is_cur else opt.verdicts[m].value
        verdicts.append({"measure": m, "label": SHORT_MEASURE[m], "value": v,
                         "symbol": "" if is_cur else SYMBOL[v],
                         "word": "" if is_cur else ("about the same*" if opt.verdicts[m].held_by_assumed
                                                     else VERDICT_WORDS[v])})
    h, hc, n = opt.strategy.harvests, current.strategy.harvests, len(opt.strategy.steps)
    harvest = None if (is_cur or h == hc) else f"{h} harvest{'s' if h != 1 else ''} in {n} years (now {hc})"
    out = {
        "title": "Your rotation now" if is_cur else opt.strategy.label,
        "band": None if is_cur else BAND_LABELS[opt.band].capitalize(),
        "chips": [{"name": SHORT_NAMES.get(c.name, c.name), "role": c.role} for c in opt.crops],
        "verdicts": verdicts,
        "caution": cautions[0]["short"] if cautions else None,
        "more_cautions": max(0, len(cautions) - 1),
        "harvest": harvest,
    }
    # Long plans: the band, then the harvest line, give way (both stay in the details).
    for key in ("band", "harvest"):
        if closed_words(out) > CLOSED_MAX_WORDS:
            out[key] = None
    return out


CLOSED_MAX_WORDS = 45
SHORT_MEASURE = {"water": "Water", "soil": "Soil", "nitrogen": "Nitrogen", "variety": "Variety"}


def closed_words(cl: dict) -> int:
    """Words on a closed card as the page shows it, including its fixed labels."""
    return word_count(cl["title"], cl["band"], [x["name"] for x in cl["chips"]], [v["label"] for v in cl["verdicts"]],
                      [v["word"] for v in cl["verdicts"]], cl["caution"],
                      f"{cl['more_cautions']} more cautions" if cl["more_cautions"] else "", cl["harvest"],
                      "Why and details")


def _evidence_short(m: str, opt: Option, current: Option) -> str:
    """One line per measure for the first details layer, with the current rotation's figure."""
    q, c = opt.scores[m], current.scores[m]
    now = opt is not current and c.assessed
    if not q.assessed:
        return f"Not assessed: {q.not_assessed_reason}"
    if m == "water":
        t = f"{share_words(q.central).capitalize()} short of water"
        return t + (f"; now {re.sub(r' crops?', '', share_words(c.central))}." if now else ".")
    if m == "soil":
        t = f"About {lbac(q.central)} of residue in the winter with least cover"
        return t + (f"; now {_round_sig(units.kg_ha_to_lb_ac(c.central)):,.0f}." if now else ".")
    if m == "nitrogen":
        t = "No nitrogen from legumes" if q.central <= 0 else f"About {lbac_yr(q.central)} of nitrogen from legumes"
        return t + (f"; now {_n(units.kg_ha_to_lb_ac(c.central))}." if now else ".")
    return f"{q.details['groups']} of 4 kinds of crop" + (f"; now {c.details['groups']}." if now else ".")


FIRST_LAYER_MAX_WORDS = 150
HEADINGS = ("Why this option", "The evidence", "What it may gain you", "What we don't know", "Check locally")


def first_layer(opt: Option, res: PlanResult, cautions: list[dict]) -> dict:
    """The five headings of brief 2 in 150 words or fewer altogether (brief 3, S2 target 4)."""
    current = res.current
    is_cur = opt is current
    if is_cur:
        why = "What you grow now, as the crop map shows it; every option is compared with it."
        gain = "This is your current rotation."
    else:
        why = summary_sentence(opt, current)
        g = gains(opt, current, res, None)
        gain = g[0] if g else ""
    held = [m for m in MEASURES if not is_cur and opt.verdicts[m].held_by_assumed]
    deciding = [a["text"] for a in assumed_for(opt, current) if a["measure"] in held][:3]
    fm = res.field_model
    evidence = [{"measure": m, "label": MEASURE_LABELS[m], "text": _evidence_short(m, opt, current) + records_mark(m, opt, fm)}
                for m in MEASURES]
    check = [c["short"] for c in cautions[:2]] or ["Ask a local agronomist before changing a rotation."]
    base = word_count(HEADINGS, why, [e["label"] for e in evidence], [e["text"] for e in evidence], gain, check)
    unknown: list[str] = []
    for t in deciding:  # those that changed a verdict, as many as the word limit allows (at least one)
        if unknown and base + word_count(unknown, t) > FIRST_LAYER_MAX_WORDS:
            break
        unknown.append(t)
    if not unknown:
        unknown = ["Nothing we don't know changed a verdict here."]
    return {
        "why": why,
        "evidence": evidence,
        "gains": gain,
        "unknowns": unknown,
        "unknowns_more": max(0, len(unknowns(opt, current, res)) - len(deciding[:len(unknown)])),
        "check": check,
    }


def card(opt: Option, res: PlanResult, content: Content) -> dict:
    current = res.current
    is_cur = opt is current
    fm = res.field_model
    cautions = [w.to_dict() for w in opt.warnings]
    if is_cur:
        failed = [r for r in opt.strategy.rule_results if not r.passed]
        if failed:  # one caution for all of them; the details list each rule
            cautions.insert(0, {"code": "/".join(r.code for r in failed), "key": "rules:current", "priority": 5,
                                "short": f"Breaks {len(failed)} rule{'s' if len(failed) > 1 else ''} as mapped",
                                "text": " ".join(f"{r.label}: {r.reason}" for r in failed)
                                        + " The crop map may be wrong; check the crop history.",
                                "basis": "sourced", "source": None})
    cautions = sorted(cautions, key=lambda c: c["priority"])
    return {
        "closed": closed_card(opt, current, cautions),
        "first": first_layer(opt, res, cautions),
        "id": opt.strategy.id,
        "kind": opt.strategy.kind,
        "kept": bool(opt.strategy.extra.get("kept")),
        "label": opt.strategy.label,
        "band": None if is_cur else opt.band,
        "band_label": None if is_cur else BAND_LABELS[opt.band].capitalize(),
        "summary": summary_sentence(opt, current),
        "steps": [s.to_dict(content) for s in opt.strategy.steps],
        "crop_ids": [c.id for c in opt.crops],
        "lines": measure_lines(opt, current, fm),
        "notes": notes(opt, current, content),
        "cautions": cautions,
        "details": {
            "why": why(opt, current) if not is_cur else ["This is what you grow now, as the crop map shows it. "
                                                         "Every option is compared with it."],
            "evidence": evidence(opt, res, content),
            "gains": gains(opt, current, res, content) if not is_cur else [],
            "unknowns": unknowns(opt, current, res),
            "assumed": assumed_for(opt, current),
            "check": check_items(opt, content),
        },
        "rules": [r.to_dict() for r in opt.strategy.rule_results],
        "distance": round(opt.strategy.distance, 2),
    }


def headline(res: PlanResult, content: Content, rotation_text: str) -> list[str]:
    """One sentence, 25 words or fewer, stating the finding (brief 3, S2). Notes about the crop map and the
    current rotation breaking a rule live in the current rotation's card; settings notes in `settings_notes`."""
    o = res.outcomes
    top = MEASURE_LABELS[o["top_priority"]].lower()
    if o["no_options"]:
        return ["No option passed the rules with the crops grown near this field and your settings."]
    good = o["at_least_as_good"][0] if o["at_least_as_good"] else None
    if not o["holds_up"]:
        best = next((x for x in res.shown if x.verdicts[o["top_priority"]].value == BETTER), None)
        if best:
            if good == best.strategy.id:
                return [f"{best.strategy.label} is better than now on {top}, your top priority, and no worse on anything."]
            return [f"{best.strategy.label} is better than now on {top}, your top priority, but gives something up."]
    if good:
        return [f"Your rotation holds up on {top}; {_label_of(res, good)} is at least as good on all four measures."]
    return [f"Your rotation holds up on {top}; the options trade one thing for another."]


def _label_of(res: PlanResult, oid: str) -> str:
    return next(o.strategy.label for o in res.shown + res.more if o.strategy.id == oid)


def settings_notes(res: PlanResult) -> list[str]:
    out = []
    if res.inputs.dry_mode:
        out.append(f"Dry region mode is on: water is judged on the {len(res.field_model.window_years)} driest of the "
                   "last 15 years and put first; ties go to more harvests.")
    if res.inputs.has_scenario:
        parts = []
        if res.inputs.rain_pct:
            parts.append(f"{res.inputs.rain_pct:+.0f}% rain from April to July".replace("-", "−"))
        if res.inputs.temp_f:
            parts.append(f"{res.inputs.temp_f:+.0f} °F".replace("-", "−"))
        out.append(f"Weather changed to: {join_words(parts)}. Water needs stay as they were, so a drier setting shows "
                   "more shortfalls.")
    return out


def current_card(res: PlanResult, content: Content, rotation_text: str, caveats: list[dict]) -> dict:
    """The current rotation's card. Notes about the crop map's coverage and about the rotation breaking a rule
    live here, not in the headline (brief 3, S2 target 2)."""
    c = card(res.current, res, content)
    notes = []
    for r in res.outcomes["current_breaks_rules"]:
        notes.append(f"The crop map shows {rotation_text.lower()}, which breaks the rule \u201c{r['label'].lower()}\u201d. "
                     "The map may be wrong: check the crop history.")
    notes += [cv["text"] for cv in caveats]
    c["details"]["map_notes"] = notes
    return c


def present(res: PlanResult, content: Content, extra: dict) -> dict:
    cur_names = [c.name for c in res.current.crops]
    rot_text = rotation_words(cur_names)
    pr = res.priorities
    return {
        "status": "ok",
        "headline": headline(res, content, rot_text),
        "settings_notes": settings_notes(res),
        "current_rotation_text": rot_text,
        "priorities": [{"id": m, "label": MEASURE_LABELS[m]} for m in pr],
        "measures": [{"id": m, "label": MEASURE_LABELS[m], "question": QUESTIONS[m]} for m in MEASURES],
        "current": current_card(res, content, rot_text, extra.get("caveats") or []),
        "options": [card(o, res, content) for o in res.shown],
        "more": [card(o, res, content) for o in res.more],
        "kept": [card(o, res, content) for o in res.kept],
        "inputs": res.inputs.to_dict(content),
        "outcomes": res.outcomes,
        "looking_back": {
            "recent_years": res.replay_info["recent_years"],
            "window_years": res.replay_info["window_years"],
            "first_year": res.replay_info["years"][0],
            "last_year": res.replay_info["years"][-1],
            "highlight_year": int(content.settings["water.highlight_year"]),
            "mean_precip_in": round(units.mm_to_in(res.replay_info["mean_precip_mm"]), 1),
            "dropped_years": res.replay_info["dropped_years"],
        },
        "model_gaps": MODEL_GAPS,
        "check_locally": content.settings["assessment.check_locally"],
        "generation": res.stats,
        **extra,
    }
