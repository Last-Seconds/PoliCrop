"""Hard rules: a rule takes a strategy and says pass/fail with a readable reason.

To add a rule: write a class with `id`, `label` and `check()`, decorate it with
@register_rule, and enable it in data/rules.yaml (with any params).
Rules H1–H5 are the brief's section 6.1. A rotation repeats, so every rule
looks across the end of the plan into the next cycle ("cyclic").
"""
from __future__ import annotations

from typing import Callable, Protocol

from ..content import Content, RuleConfig
from .model import NON_HARVEST_ROLES, RuleResult, Strategy, Step


class Rule(Protocol):
    id: str
    label: str
    provisional: bool
    code: str

    def check(self, strategy: Strategy, content: Content) -> RuleResult: ...


RULE_REGISTRY: dict[str, Callable[..., Rule]] = {}


def register_rule(cls):
    RULE_REGISTRY[cls.id] = cls
    return cls


def build_rules(configs: list[RuleConfig]) -> list[Rule]:
    rules = []
    for cfg in configs:
        if not cfg.enabled:
            continue
        factory = RULE_REGISTRY.get(cfg.id)
        if factory is None:
            raise ValueError(f"rules.yaml enables unknown rule {cfg.id!r}; known: {sorted(RULE_REGISTRY)}")
        rule = factory(**cfg.params)
        rule.provisional = cfg.provisional
        rule.code = cfg.code
        rule.basis = cfg.basis
        rule.source = cfg.source
        rules.append(rule)
    return rules


def _name(content: Content, crop_id: str) -> str:
    return content.crop(crop_id).name if content.has_crop(crop_id) else crop_id


def _pairs(steps: list[Step], cyclic: bool) -> list[tuple[Step, Step, bool]]:
    """Consecutive (previous, next, wraps) pairs; `wraps` marks last -> first of the next cycle."""
    pairs = [(a, b, False) for a, b in zip(steps, steps[1:])]
    if cyclic and len(steps) > 1:
        pairs.append((steps[-1], steps[0], True))
    return pairs


def _where(a: Step, b: Step, wraps: bool) -> str:
    return "the last year and the first year of the next cycle" if wraps else f"years {a.position} and {b.position}"


class _Base:
    id = ""
    label = ""
    provisional = True
    code = ""

    def result(self, passed: bool, reason: str) -> RuleResult:
        return RuleResult(self.id, self.label, passed, reason, self.provisional, self.code)


@register_rule
class NoIdenticalConsecutiveCrop(_Base):
    id = "no_identical_consecutive_crop"
    label = "No crop directly after itself"

    def __init__(self, cyclic: bool = True):
        self.cyclic = cyclic

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        for a, b, wraps in _pairs(strategy.steps, self.cyclic):
            if a.crop_id == b.crop_id:
                return self.result(False, f"{_name(content, a.crop_id)} follows itself ({_where(a, b, wraps)}).")
        return self.result(True, "No crop directly follows itself.")


@register_rule
class NoOverlappingDates(_Base):
    """H2: a crop's latest usual sowing date must not fall before the previous crop's usual harvest end."""
    id = "no_overlapping_dates"
    label = "Each crop can be sown after the one before is harvested"

    def __init__(self, cyclic: bool = True):
        self.cyclic = cyclic

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        n = len(strategy.steps)
        for a, b, wraps in _pairs(strategy.steps, self.cyclic):
            if a.harvest_window is None or b.sow_window is None:
                continue  # fallow, cover crop or a class with no season adapts to its neighbours
            harvest_end = a.harvest_window[1]
            latest_sow = b.sow_window[1]
            if wraps:
                latest_sow = latest_sow.replace(year=latest_sow.year + n)
            if latest_sow < harvest_end:
                return self.result(
                    False,
                    f"{_name(content, b.crop_id)} is usually sown by {latest_sow:%d %b}, before "
                    f"{_name(content, a.crop_id)} is usually harvested (by {harvest_end:%d %b}).")
        return self.result(True, "Each crop can be sown after the previous one is harvested.")


@register_rule
class LegumeSpacing(_Base):
    """H3: any two legume crops at least `window_years` crop years apart, counted cyclically.

    Brief 3 (S1): pulse crops share diseases, so a different legume counts the same
    as the same legume returning [S16]. A three-year plan then holds one legume at most.
    """
    id = "legume_spacing"
    label = "Legumes at least 3 years apart"

    def __init__(self, window_years: int = 3, cyclic: bool = True):
        self.window = int(window_years)
        self.cyclic = cyclic
        self.label = f"Legumes at least {self.window} years apart"

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        steps = strategy.steps
        n = len(steps)
        # Unroll the rotation so gaps that cross into the next cycle are checked too
        # (a single legume in a plan shorter than the window meets itself).
        ext = [steps[k % n] for k in range(n + self.window - 1)] if self.cyclic else list(steps)
        for i, s in enumerate(steps):
            if s.role != "legume":
                continue
            for gap in range(1, self.window):
                j = i + gap
                if j < len(ext) and ext[j].role == "legume":
                    a, b = _name(content, s.crop_id), _name(content, ext[j].crop_id)
                    what = f"{a} returns" if ext[j].crop_id == s.crop_id else f"{b} follows {a.lower()}"
                    return self.result(False, f"{what} after {gap} year{'s' if gap > 1 else ''}; legumes should be "
                                              f"at least {self.window} years apart.")
        return self.result(True, f"Legumes are at least {self.window} years apart.")


@register_rule
class WinterCanolaAfterFallow(_Base):
    """H4: winter canola only directly after fallow."""
    id = "winter_canola_after_fallow"
    label = "Winter canola only after fallow"

    def __init__(self, crop: str = "winter_canola", after_roles: list[str] | None = None):
        self.crop = crop
        self.after = tuple(after_roles or ["fallow"])

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        steps = strategy.steps
        for i, s in enumerate(steps):
            if s.crop_id != self.crop:
                continue
            prev = steps[i - 1]  # cyclic
            if prev.role not in self.after:
                return self.result(False, f"{_name(content, self.crop)} follows {_name(content, prev.crop_id)}; after "
                                          "a harvested crop the soil is too dry for it to establish before winter.")
        return self.result(True, "Winter canola, if present, follows fallow.")


@register_rule
class NoTwoYearsWithoutHarvest(_Base):
    """H5: no two consecutive years without a harvest (fallow or cover crop)."""
    id = "no_two_years_without_harvest"
    label = "No two years running without a harvest"

    def __init__(self, cyclic: bool = True):
        self.cyclic = cyclic

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        if all(s.role in NON_HARVEST_ROLES for s in strategy.steps):
            return self.result(False, "No year has a harvest.")
        for a, b, wraps in _pairs(strategy.steps, self.cyclic):
            if a.role in NON_HARVEST_ROLES and b.role in NON_HARVEST_ROLES:
                return self.result(False, f"Two years running without a harvest ({_where(a, b, wraps)}).")
        return self.result(True, "Every year without a harvest is followed by a harvested crop.")
