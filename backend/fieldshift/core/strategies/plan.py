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
from .generate import Candidate, CropPool, check_rules, describe_differences, enumerate_candidates
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
            out["W6"] = years_with_extreme(series, years, cfg.params.get("months", [11, 12, 1, 2, 3]),
                                           units.f_to_c(float(cfg.params.get("limit_f", -6))), hot=False)
    return out


def build_field_model(content: Content, series: DailySeries, soil: FieldSoil, reference: list[Crop],
                      inputs: FarmerInputs) -> FieldModel:
    s = content.settings
    base = build_replay(series, soil.capacity_mm, s)
    if inputs.has_scenario:
        scn_series = series.adjusted(1 + inputs.rain_pct / 100.0, tuple(s["scenario.rain_months"]),
                                     units.delta_f_to_c(inputs.temp_f))
        replay = build_replay(scn_series, soil.capacity_mm, s, last_year=int(base.years[-1]))
    else:
        scn_series, replay = series, base
    fm = FieldModel(content=content, base=base, replay=replay, soil=soil, reference=reference,
                    tillage=inputs.effective_tillage(content), tillage_from_farmer=inputs.tillage is not None,
                    yields_kg_ha=inputs.yields_kg_ha(content), ph=inputs.ph, dry_mode=inputs.dry_mode)
    fm.extremes = _extremes(scn_series, fm.recent_years, content.warnings)
    return fm


def run_plan(content: Content, existing_crops: list[Crop], reference: list[Crop], pool: CropPool,
             rules: list[Rule], series: DailySeries, soil: FieldSoil, inputs: FarmerInputs,
             first_harvest_year: int, nearby: Any = None) -> PlanResult:
    t0 = time.time()
    s = content.settings
    scorers = build_scorers(list(s["comparison.measures"]))
    fm = build_field_model(content, series, soil, reference, inputs)
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

    order = sorted(range(len(options)), key=lambda i: order_key(
        options[i].verdicts, options[i].scores, priorities, options[i].strategy.harvests, tie(options[i]),
        inputs.dry_mode))
    table = Table.build([o.scores for o in options] + [current.scores],
                        [o.strategy.harvests for o in options] + [current.strategy.harvests], mg)
    k = int(s["comparison.alternatives_shown"])
    k_more = int(s["comparison.more_shown"])
    sel = select(order, [o.band for o in options], table, len(options), k, k_more)
    t3 = time.time()

    shown = [options[i] for i in sel.shown]
    more = [options[i] for i in sel.more]
    letters = "ABCDEFGHIJKLMNOP"
    for j, o in enumerate(shown + more):
        o.strategy.id = letters[j] if j < len(letters) else f"S{j + 1}"
        o.strategy.label = f"Option {o.strategy.id}"
        o.strategy.differences, o.strategy.summary = describe_differences(existing_crops, o.crops, content)
    for o in [current] + shown + more:
        o.warnings = warnings_mod.evaluate(o.crops, fm, content.warnings)

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
    return PlanResult(current, shown, more, fm, inputs, priorities, stats, outcomes, replay_info)
