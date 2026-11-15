"""The judgment pipeline (brief 3 "Selection pipeline"):

filter by rules -> score -> drop dominated -> order by the farmer's priorities
-> show three at different distances from the current rotation, plus the
current rotation.

Pure logic: takes the weather series, soil facts, crop pool and farmer inputs;
returns a PlanResult that core.present turns into the farmer's screen.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .. import units
from ..content import Content, Crop, SeasonWindow
from ..replay import Replay, build_replay, years_with_extreme
from ..soil import FieldSoil
from ..weather import DailySeries
from . import warnings as warnings_mod
from .compare import SAME, BETTER, WORSE, Table, Verdict, band_of, order_key, select, verdict
from .generate import (Candidate, CropPool, best_alignment, canonical, check_rules, describe_differences,
                       enumerate_candidates)
from .inputs import FarmerInputs
from .measures import FieldModel, MEASURES, Quantity, crops_of, margins, score_all
from .model import Strategy, make_steps
from .rules import Rule
from .scoring import build_scorers


@dataclass
class Option:
    strategy: Strategy
    crops: list[Crop]
    scores: dict[str, Quantity]
    verdicts: dict[str, Verdict] = field(default_factory=dict)  # against the current rotation
    band: int | None = None
    warnings: list = field(default_factory=list)
    nearby: float | None = None  # share of nearby cropland with this role pattern (stage 4)
    prevalence: float = 0.0


@dataclass
class PlanResult:
    current: Option
    shown: list[Option]
    more: list[Option]
    kept: list[Option]
    field_model: FieldModel
    inputs: FarmerInputs
    priorities: list[str]
    stats: dict
    outcomes: dict
    replay_info: dict


def _extremes(series: DailySeries, years: list[int], configs) -> dict[str, dict]:
    out = {}
    for cfg in configs:
        if not cfg.enabled:
            continue
        if cfg.id == "chickpea_heat":
            out["W5"] = years_with_extreme(series, years, cfg.params.get("months", [6, 7]),
                                           units.f_to_c(float(cfg.params.get("limit_f", 98))), hot=True)
        elif cfg.id == "winter_pea_cold":
            months, lim = cfg.params.get("months", [11, 12, 1, 2, 3]), units.f_to_c(float(cfg.params.get("limit_f", -6)))
            snow = cfg.params.get("snow_below_kg_m2")
            out["W6"] = years_with_extreme(series, years, months, lim, hot=False,
                                           swe_below=None if snow is None else float(snow))
            out["W6_any"] = years_with_extreme(series, years, months, lim, hot=False)
            out["W6_snow_known"] = {y: series.swe is not None for y in years}
    return out


def build_field_model(content: Content, series: DailySeries, soil: FieldSoil, reference: list[Crop],
                      inputs: FarmerInputs, fitted: dict[str, float] | None = None) -> FieldModel:
    """`fitted` (brief 3, part C): e_winter and storage_factor fitted to the farmer's records, when applied."""
    s = content.settings
    fitted = fitted or {}
    cap = {k: v * float(fitted.get("storage_factor", 1.0)) for k, v in soil.capacity_mm.items()}

    def replay_of(ser, **kw):
        rp = build_replay(ser, cap, s, **kw)
        if "e_winter" in fitted:
            rp.constants["central"] = {**rp.constants["central"], "e_winter": float(fitted["e_winter"])}
        return rp

    base = replay_of(series)
    if inputs.has_scenario:
        scn_series = series.adjusted(1 + inputs.rain_pct / 100.0, tuple(s["scenario.rain_months"]),
                                     units.delta_f_to_c(inputs.temp_f))
        replay = replay_of(scn_series, last_year=int(base.years[-1]))
    else:
        scn_series, replay = series, base
    fm = FieldModel(content=content, base=base, replay=replay, soil=soil, reference=reference,
                    tillage=inputs.effective_tillage(content), tillage_from_farmer=inputs.tillage is not None,
                    yields_kg_ha=inputs.yields_kg_ha(content), ph=inputs.ph, dry_mode=inputs.dry_mode)
    fm.extremes = _extremes(scn_series, fm.recent_years, content.warnings)
    fm.fitted = dict(fitted)
    return fm


def run_plan(content: Content, existing_crops: list[Crop], reference: list[Crop], pool: CropPool,
             rules: list[Rule], series: DailySeries, soil: FieldSoil, inputs: FarmerInputs,
             first_harvest_year: int, nearby: Any = None, fit_hook=None) -> PlanResult:
    t0 = time.time()
    s = content.settings
    scorers = build_scorers(list(s["comparison.measures"]))
    fm = build_field_model(content, series, soil, reference, inputs)
    if fit_hook is not None:  # brief 3, parts B, C and E: the farmer's records change levels and constants
        fm = fit_hook(fm) or fm
    fm.nearby = nearby
    priorities = inputs.effective_priorities(content)
    mg = margins(s)
    default_window = SeasonWindow.parse(s["generation.default_step_window"], "settings")

    # The current rotation: never discarded; its rule results are shown gently.
    cur = Strategy("current", "existing", make_steps(existing_crops, first_harvest_year, default_window))
    cur.label = "Your current rotation"
    check_rules(cur, rules, content)
    current = Option(cur, existing_crops, score_all(existing_crops, fm, scorers))
    current.verdicts = {m: Verdict(SAME, False, SAME) for m in MEASURES}

    enum = enumerate_candidates(existing_crops, pool, content, rules, first_harvest_year,
                                set(inputs.exclude), set(inputs.keep))
    t1 = time.time()
    options: list[Option] = []
    for cand in enum.candidates:
        opt = Option(cand.strategy, cand.crops, score_all(cand.crops, fm, scorers), prevalence=cand.prevalence)
        options.append(opt)
    t2 = time.time()

    n = len(existing_crops)
    small_max = float(s["comparison.band_small_max"])
    mod_max = float(s["comparison.band_moderate_max"])
    for o in options:
        o.verdicts = {m: verdict(o.scores[m], current.scores[m], mg[m]) for m in MEASURES}
        o.band = band_of(o.strategy.distance, n, small_max, mod_max)
        if nearby is not None:
            o.nearby = nearby.share(o.crops)
    if nearby is not None:
        current.nearby = nearby.share(existing_crops)

    def tie(o: Option) -> float:
        return o.nearby if o.nearby is not None else o.prevalence

    seen_min = next((float(w.params.get("min_share", 0.01)) for w in content.warnings
                     if w.id == "not_seen_nearby" and w.enabled), None)

    def seen(o: Option) -> bool:
        return o.nearby is None or seen_min is None or o.nearby >= seen_min

    # Addendum 2, A1: options with a serious caution go after every option without one.
    serious_cache: dict = {}

    def serious(o: Option) -> bool:
        key = tuple(c.id for c in o.crops)
        if key not in serious_cache:
            serious_cache[key] = any(w.serious for w in warnings_mod.evaluate(o.crops, fm, content.warnings))
        return serious_cache[key]

    order = sorted(range(len(options)), key=lambda i: order_key(
        options[i].verdicts, options[i].scores, priorities, options[i].strategy.harvests, tie(options[i]),
        inputs.dry_mode, seen(options[i]), serious(options[i])))
    table = Table.build([o.scores for o in options] + [current.scores],
                        [o.strategy.harvests for o in options] + [current.strategy.harvests], mg)
    k = int(s["comparison.alternatives_shown"])
    k_more = int(s["comparison.more_shown"])
    sel = select(order, [o.band for o in options], table, len(options), k, k_more)
    t3 = time.time()

    sel.shown, sel.more = vary_new_crops(sel.shown, sel.more, order, options, existing_crops, table)
    # Addendum 2, A1: an option with a serious caution is never put before one without (stable otherwise).
    sel.shown = sorted(sel.shown, key=lambda i: serious(options[i]))
    sel.more = sorted(sel.more, key=lambda i: serious(options[i]))
    shown = [options[i] for i in sel.shown]
    more = [options[i] for i in sel.more]
    letters = "ABCDEFGHIJKLMNOP"
    for j, o in enumerate(shown + more):
        o.strategy.id = letters[j] if j < len(letters) else f"S{j + 1}"
        o.strategy.label = f"Option {o.strategy.id}"
        o.strategy.differences, o.strategy.summary = describe_differences(existing_crops, o.crops, content)
    kept = kept_options(content, inputs, existing_crops, shown + more, rules, fm, scorers, current, mg,
                        first_harvest_year, default_window, nearby)
    for o in [current] + shown + more + kept:
        o.warnings = warnings_mod.evaluate(o.crops, fm, content.warnings)
    # The farmer's own rotation is what they grow: "not seen nearby" says nothing useful about it.
    current.warnings = [w for w in current.warnings if w.code != "W11"]

    # Honest outcomes (brief 6.6).
    top = priorities[0]
    first_surviving = shown[0] if shown else None
    best_on_top = None
    elite: list[int] = []
    for i in order:  # the first non-dominated option in order is the best on the top priority
        if not table.dominated(i, elite):
            best_on_top = options[i]
            break
    holds_up = best_on_top is None or best_on_top.verdicts[top].value != BETTER
    at_least_as_good = [o for o in shown + more
                        if all((o.verdicts[m].value or 0) >= SAME for m in MEASURES)
                        and any(o.verdicts[m].value == BETTER for m in MEASURES)]
    outcomes = {
        "top_priority": top,
        "holds_up": holds_up,
        "at_least_as_good": [o.strategy.id for o in at_least_as_good],
        "current_breaks_rules": [r.to_dict() for r in cur.rule_results if not r.passed],
        "no_options": not shown,
    }
    stats = {
        **enum.stats,
        "surviving_checked": sel.surviving,
        "band_counts_seen": sel.band_counts,
        "filled_from_other_band": [options[i].strategy.id for i in sel.filled_from_other_band],
        "timing_s": {"enumerate": round(t1 - t0, 2), "score": round(t2 - t1, 2), "select": round(t3 - t2, 2)},
    }
    replay_info = {
        "years": [int(y) for y in fm.replay.years],
        "recent_years": fm.recent_years,
        "window_years": fm.window_years,
        "dropped_years": fm.base.dropped_years,
        "mean_precip_mm": fm.mean_precip_mm,
        "scenario": {"rain_pct": inputs.rain_pct, "temp_f": inputs.temp_f},
    }
    return PlanResult(current, shown, more, kept, fm, inputs, priorities, stats, outcomes, replay_info)


def new_crops(o: Option, existing: list[Crop]) -> set[str]:
    have = {c.id for c in existing}
    return {c.id for c in o.crops if c.id not in have and c.role not in ("fallow",)}


def vary_new_crops(shown: list[int], more: list[int], order: list[int], options: list[Option],
                   existing: list[Crop], table) -> tuple[list[int], list[int]]:
    """Addendum 2, A4: among the three options shown, at most two introduce the same new crop. The third place
    goes to the best-ordered option (not beaten by another) that does not."""
    if len(shown) < 3:
        return shown, more
    common = set.intersection(*(new_crops(options[i], existing) for i in shown))
    if not common:
        return shown, more
    import numpy as np
    elite: list[int] = []
    first_two = new_crops(options[shown[0]], existing) & new_crops(options[shown[1]], existing)
    pool = [i for i in list(more) + [j for j in order if j not in more]
            if i not in shown and not (new_crops(options[i], existing) & first_two)]  # else all three share a crop
    current_row = np.array([len(options)])
    # First choice: not beaten by any option. Failing that: not beaten by the current rotation.
    for strict in (True, False):
        for i in pool:
            if i not in more and (table.dominated(i, elite) if strict else table.dominators(i, current_row).size):
                continue
            out = shown[:2] + [i]
            rest = [shown[2]] + [m for m in more if m != i]
            return out, rest[:len(more)]
    return shown, more


def kept_options(content: Content, inputs: FarmerInputs, existing: list[Crop], listed: list[Option], rules,
                 fm: FieldModel, scorers, current: Option, mg: dict, first_harvest_year: int,
                 default_window: SeasonWindow, nearby) -> list[Option]:
    """Rotations the farmer marked "keep" (brief 3, F). One already listed is marked kept rather than repeated;
    the rest are scored like any option and compared with the current rotation. They are never dropped, even if
    they break a rule now (the rule result is shown instead)."""
    s = content.settings
    weights = dict(s["generation.distance_weights"])
    small_max, mod_max = float(s["comparison.band_small_max"]), float(s["comparison.band_moderate_max"])
    by_canon = {canonical(o.strategy.crop_ids): o for o in listed}
    out = []
    for j, ids in enumerate(inputs.kept):
        hit = by_canon.get(canonical(tuple(ids)))
        if hit is not None:
            hit.strategy.extra["kept"] = True
            continue
        crops = [content.crop(i) for i in ids]
        if len(crops) == len(existing):
            crops, d = best_alignment(existing, crops, weights)
        else:
            d = float(len(crops))
        st = Strategy(f"K{j + 1}", "kept", make_steps(crops, first_harvest_year, default_window), distance=d)
        st.label = f"Kept option {j + 1}"
        st.extra["kept"] = True
        check_rules(st, rules, content)
        st.differences, st.summary = describe_differences(existing, crops, content)
        o = Option(st, crops, score_all(crops, fm, scorers))
        o.verdicts = {m: verdict(o.scores[m], current.scores[m], mg[m]) for m in MEASURES}
        o.band = band_of(d, len(existing), small_max, mod_max)
        if nearby is not None:
            o.nearby = nearby.share(crops)
        out.append(o)
    return out
