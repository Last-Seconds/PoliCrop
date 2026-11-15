"""Generate-and-filter: role sequences -> filled with crops -> hard rules.

Every candidate carries its distance from the current rotation (how much would
change). Judging and choosing among candidates happens in compare.py / plan.py.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..content import Content, Crop, SeasonWindow
from .model import Strategy, make_steps
from .rules import Rule

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
    table_codes = {code for c in content.crops for code in c.codes(classification)}
    code_pixels = {code: n for code, n in area_counts.items() if code in table_codes}
    total = sum(code_pixels.values())
    shares: dict[str, float] = {}
    if total:
        for c in content.crops:
            n = sum(code_pixels.get(code, 0) for code in c.presence_codes(classification))
            if n:
                shares[c.id] = n / total
    # Offered crops only: history-only crops (dry beans, alfalfa) are never generated.
    crops = [c for c in content.offered_crops() if c.pool == "always" or shares.get(c.id, 0.0) >= min_share]
    yr = f"{years[0]}–{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "?")
    desc = (f"Crops covering at least {min_share:.1%} of cropland within {radius_km:g} km of the field in the "
            f"USDA crop map ({yr}), plus a cover crop. The map cannot tell winter from spring peas or canola, "
            "so both are offered where the map shows the crop.")
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
    """Plain-words differences, per year and as one short phrase."""
    details, phrases = [], []
    for i, (e, c) in enumerate(zip(existing, candidate), start=1):
        if e.id == c.id:
            continue
        details.append(f"Year {i}: {c.name.lower()} instead of {e.name.lower()}")
        phrases.append(f"{c.name.lower()} instead of {e.name.lower()}")
    if not phrases:
        return details, "Same as your current rotation"
    if len(phrases) <= 2:
        summary = " and ".join(phrases)
    else:
        rest = len(phrases) - 2
        summary = f"{phrases[0]}, {phrases[1]} and {rest} more change{'s' if rest > 1 else ''}"
    return details, summary[:1].upper() + summary[1:]


@dataclass
class Candidate:
    strategy: Strategy
    crops: list[Crop]  # aligned to the current rotation
    prevalence: float  # how common its crops are nearby (tie-break before nearby use exists)


@dataclass
class Enumeration:
    candidates: list[Candidate]
    stats: dict


def check_rules(strategy: Strategy, rules: list[Rule], content: Content) -> None:
    strategy.rule_results = [r.check(strategy, content) for r in rules]


def enumerate_candidates(existing_crops: list[Crop], pool: CropPool, content: Content, rules: list[Rule],
                         first_harvest_year: int, exclude: set[str] | None = None,
                         keep: set[str] | None = None) -> Enumeration:
    s = content.settings
    weights = dict(s["generation.distance_weights"])
    default_window = SeasonWindow.parse(s["generation.default_step_window"], "settings generation.default_step_window")
    max_candidates = int(s["generation.max_candidates"])
    n = len(existing_crops)
    exclude = set(exclude or ())
    keep = {k for k in (keep or ()) if content.has_crop(k)}

    crops = [c for c in pool.crops if c.id not in exclude]
    for k in keep:  # a crop the farmer wants kept is offered even if the map does not show it nearby
        kc = content.crop(k)
        if kc.generate and kc not in crops and kc.id not in exclude:
            crops.append(kc)
    gen_roles = {r.id for r in content.roles if r.generate}
    by_role: dict[str, list[Crop]] = defaultdict(list)
    for c in crops:
        if c.role in gen_roles:
            by_role[c.role].append(c)
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
    out: list[Candidate] = []
    fail_reasons: Counter = Counter()
    skipped_keep = 0
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
                if keep and not keep <= set(ids):
                    skipped_keep += 1
                    continue
                used += 1
                generated += 1
                aligned, d = best_alignment(existing_crops, list(combo), weights)
                if d <= 0:
                    continue
                cand = Strategy(f"c{generated}", "generated", make_steps(aligned, first_harvest_year, default_window),
                                distance=d)
                check_rules(cand, rules, content)
                if not cand.passed:
                    for r in cand.rule_results:
                        if not r.passed:
                            fail_reasons[r.code or r.label] += 1
                    continue
                prevalence = sum(math.log(max(pool.shares.get(c.id, 0.0), 1e-3)) for c in aligned) / n
                out.append(Candidate(cand, aligned, prevalence))
            if used >= budget:
                break

    stats = {
        "plan_length": n,
        "roles_used": role_ids,
        "crops_used": [c.id for c in crops],
        "candidates_generated": generated,
        "candidates_passed": len(out),
        "candidates_failed": generated - len(out),
        "failures_by_rule": dict(fail_reasons),
        "truncated": truncated,
        "max_candidates": max_candidates,
        "excluded": sorted(exclude),
        "kept": sorted(keep),
    }
    return Enumeration(out, stats)
