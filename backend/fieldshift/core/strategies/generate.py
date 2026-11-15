"""Generate-and-filter: role sequences -> filled with crops -> hard rules -> a spread of distances.

Nothing here ranks strategies by quality. Distance from the existing rotation
is a description of how much would change, and is used only to pick
alternatives that differ by different amounts.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..content import Content, Crop, SeasonWindow
from .model import Strategy, make_steps
from .rules import Rule
from .scoring import Scorer, assess

UNKNOWN_ROLE = "unknown"


@dataclass
class CropPool:
    """Crops that may fill roles: those grown in the surrounding area plus 'always' crops."""
    crops: list[Crop]
    shares: dict[str, float]  # crop id -> share of surrounding cropland (None-able for 'always' crops)
    description: str
    years: list[int] = field(default_factory=list)

    def by_role(self, roles: set[str]) -> dict[str, list[Crop]]:
        out: dict[str, list[Crop]] = defaultdict(list)
        for c in self.crops:
            if c.role in roles:
                out[c.role].append(c)
        return out


def build_pool(area_counts: dict[int, int], content: Content, classification: str,
               years: list[int], radius_km: float) -> CropPool:
    min_share = float(content.settings["crop_pool.min_share"])
    crop_pixels: Counter = Counter()
    for code, n in area_counts.items():
        crop = content.crop_for_code(classification, code)
        if crop:
            crop_pixels[crop.id] += n
    total = sum(crop_pixels.values())
    shares = {cid: n / total for cid, n in crop_pixels.items()} if total else {}
    crops = [c for c in content.crops if c.pool == "always" or shares.get(c.id, 0.0) >= min_share]
    yr = f"{years[0]}–{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "?")
    desc = (f"Crops covering at least {min_share:.1%} of crop-table cropland within {radius_km:g} km "
            f"of the field in the crop-type map ({yr}), plus crops always offered (cover crops).")
    return CropPool(crops, {k: round(v, 4) for k, v in shares.items()}, desc, years)


def pseudo_crop(code: int | None, name: str) -> Crop:
    """A placeholder for a detected class that is not in the crop table (e.g. grass)."""
    return Crop(id=f"class:{code}", name=name, role=UNKNOWN_ROLE, class_codes={})


def step_cost(a: Crop, b: Crop, weights: dict) -> float:
    if a.id == b.id:
        return float(weights.get("same_crop", 0.0))
    if a.role == b.role and a.role != UNKNOWN_ROLE:
        return float(weights.get("same_role_other_crop", 0.5))
    return float(weights.get("other_role", 1.0))


def distance(existing: list[Crop], candidate: list[Crop], weights: dict) -> float:
    return sum(step_cost(a, b, weights) for a, b in zip(existing, candidate))


def best_alignment(existing: list[Crop], candidate: list[Crop], weights: dict) -> tuple[list[Crop], float]:
    """A rotation repeats, so a cyclic shift of it is the same rotation.

    Returns the shift of `candidate` closest to `existing` (ties: smallest shift).
    """
    best = (candidate, distance(existing, candidate, weights))
    for k in range(1, len(candidate)):
        rotated = candidate[k:] + candidate[:k]
        d = distance(existing, rotated, weights)
        if d < best[1] - 1e-9:
            best = (rotated, d)
    return best


def canonical(crop_ids: tuple[str, ...]) -> tuple[str, ...]:
    return min(crop_ids[k:] + crop_ids[:k] for k in range(len(crop_ids)))


def describe_differences(existing: list[Crop], candidate: list[Crop], content: Content) -> tuple[list[str], str]:
    def short(role: str) -> str:
        return content.role(role).short_label if content.has_role(role) else "unclassified land"

    details, phrases = [], []
    ex_roles = Counter(c.role for c in existing)
    ca_roles = Counter(c.role for c in candidate)
    changed_role_positions: dict[str, list[int]] = defaultdict(list)
    same_role_swaps: list[int] = []
    for i, (e, c) in enumerate(zip(existing, candidate), start=1):
        if e.id == c.id:
            continue
        if e.role == c.role:
            details.append(f"Year {i}: {c.name} instead of {e.name} (both {short(c.role)})")
            same_role_swaps.append(i)
        else:
            details.append(f"Year {i}: {c.name} ({short(c.role)}) instead of {e.name} ({short(e.role)})")
            changed_role_positions[c.role].append(i)

    def years(ps: list[int]) -> str:
        return ("year " + str(ps[0])) if len(ps) == 1 else ("years " + ", ".join(map(str, ps[:-1])) + f" and {ps[-1]}")

    for role, ps in changed_role_positions.items():
        article = "an" if short(role)[0] in "aeiou" else "a"
        if ex_roles[role] == 0:
            phrases.append(f"adds {article} {short(role)} in {years(ps)}")
        else:
            article = "an" if short(role)[0] in "aeiou" else "a"
            phrases.append(f"{article} {short(role)} in {years(ps)} too ({ca_roles[role]} {short(role)} years "
                           f"instead of {ex_roles[role]})")
    for role, n in ex_roles.items():
        if ca_roles[role] == 0:
            phrases.append(f"drops the {short(role)}")
    if same_role_swaps and not changed_role_positions:
        phrases.append(f"same crop types, different crop in {years(same_role_swaps)}")
    elif same_role_swaps:
        phrases.append(f"a different crop of the same type in {years(same_role_swaps)}")
    summary = "; ".join(phrases)
    return details, (summary[:1].upper() + summary[1:]) if summary else "Same as the existing rotation"


@dataclass
class GenerationResult:
    existing: Strategy
    alternatives: list[Strategy]
    stats: dict
    pool: CropPool


def _check(strategy: Strategy, rules: list[Rule], content: Content) -> None:
    strategy.rule_results = [r.check(strategy, content) for r in rules]


def generate(existing_crops: list[Crop], pool: CropPool, content: Content, rules: list[Rule],
             scorers: list[Scorer], first_harvest_year: int, alternatives_wanted: int | None = None,
             context: dict | None = None) -> GenerationResult:
    s = content.settings
    weights = dict(s["generation.distance_weights"])
    default_window = SeasonWindow.parse(s["generation.default_step_window"], "settings generation.default_step_window")
    max_candidates = int(s["generation.max_candidates"])
    k_wanted = int(alternatives_wanted or s["generation.alternatives_shown"])
    n = len(existing_crops)
    context = context or {}

    existing = Strategy("existing", "existing", make_steps(existing_crops, first_harvest_year, default_window))
    existing.label = "Existing rotation (as detected)"
    existing.summary = "Your current rotation, continued as it is"
    _check(existing, rules, content)
    assess(existing, context, content, scorers)

    gen_roles = {r.id for r in content.roles if r.generate}
    by_role = pool.by_role(gen_roles)
    role_ids = sorted(r for r in gen_roles if by_role.get(r))
    ex_roles = [c.role for c in existing_crops]

    # Group role sequences by how many positions differ from the existing roles,
    # and give each group an equal share of the candidate budget, so that small
    # and large changes are both explored even when the space is large.
    groups: dict[int, list[tuple[str, ...]]] = defaultdict(list)
    for seq in itertools.product(role_ids, repeat=n):
        groups[sum(a != b for a, b in zip(seq, ex_roles))].append(seq)
    budget = max(1, max_candidates // max(1, len(groups)))

    seen: set[tuple[str, ...]] = {canonical(tuple(c.id for c in existing_crops))}
    generated = 0
    truncated = False
    passers: list[tuple[float, float, int, Strategy, list[Crop]]] = []
    fail_reasons: Counter = Counter()
    order = 0
    for hd in sorted(groups):
        used = 0
        for seq in groups[hd]:
            options = []
            for pos, role in enumerate(seq):
                opts = list(by_role[role])
                ex = existing_crops[pos]
                if ex.role == role and ex in opts:
                    opts.remove(ex)
                    opts.insert(0, ex)  # keep the existing crop first where the role is unchanged
                options.append(opts)
            for combo in itertools.product(*options):
                if used >= budget:
                    truncated = True
                    break
                ids = tuple(c.id for c in combo)
                key = canonical(ids)
                if key in seen:
                    continue
                seen.add(key)
                used += 1
                generated += 1
                aligned, d = best_alignment(existing_crops, list(combo), weights)
                if d <= 0:
                    continue
                cand = Strategy(f"c{generated}", "generated", make_steps(aligned, first_harvest_year, default_window),
                                distance=d)
                _check(cand, rules, content)
                if not cand.passed:
                    for r in cand.rule_results:
                        if not r.passed:
                            fail_reasons[r.label] += 1
                    continue
                prevalence = sum(math.log(max(pool.shares.get(c.id, 0.0), 1e-3)) for c in aligned) / n
                order += 1
                passers.append((d, -prevalence, order, cand, aligned))
            if used >= budget:
                break

    chosen = _spread(passers, k_wanted)
    labels = _labels(len(chosen))
    alternatives = []
    for idx, (d, _, _, cand, aligned) in enumerate(chosen):
        cand.id = "ABCDEFGHIJ"[idx] if idx < 10 else f"S{idx + 1}"
        cand.label = f"Alternative {cand.id}: {labels[idx]}"
        cand.differences, cand.summary = describe_differences(existing_crops, aligned, content)
        assess(cand, context, content, scorers)
        alternatives.append(cand)

    stats = {
        "plan_length": n,
        "roles_used": role_ids,
        "candidates_generated": generated,
        "candidates_passed": len(passers),
        "candidates_failed": generated - len(passers),
        "failures_by_rule": dict(fail_reasons),
        "truncated": truncated,
        "max_candidates": max_candidates,
        "selection": (
            "Alternatives are picked to differ from the existing rotation by different amounts "
            "(spread of distance values). Among candidates at the same distance, the one using crops "
            "most common in the surrounding area is shown. This is not a ranking."
        ),
    }
    return GenerationResult(existing, alternatives, stats, pool)


def _spread(passers: list, k: int) -> list:
    if not passers or k <= 0:
        return []
    by_d: dict[float, list] = defaultdict(list)
    for p in passers:
        by_d[round(p[0], 6)].append(p)
    for lst in by_d.values():
        lst.sort(key=lambda p: (p[1], p[2]))
    ds = sorted(by_d)
    if k == 1:
        targets = [ds[0]]
    else:
        targets = [ds[round(i * (len(ds) - 1) / (k - 1))] for i in range(k)]
    chosen, used_ids, used_roles = [], set(), set()
    for t in targets:
        # nearest distance to the target that still has an unused candidate
        for d in sorted(ds, key=lambda x: (abs(x - t), x)):
            pick = next((p for p in by_d[d] if p[3].crop_ids not in used_ids and p[3].roles not in used_roles), None)
            pick = pick or next((p for p in by_d[d] if p[3].crop_ids not in used_ids), None)
            if pick:
                chosen.append(pick)
                used_ids.add(pick[3].crop_ids)
                used_roles.add(pick[3].roles)
                break
    chosen.sort(key=lambda p: (p[0], p[2]))
    return chosen


def _labels(k: int) -> list[str]:
    if k == 1:
        return ["a change"]
    if k == 2:
        return ["smaller change", "larger change"]
    if k == 3:
        return ["small change", "moderate change", "large change"]
    return [f"change level {i + 1} of {k}" for i in range(k)]
