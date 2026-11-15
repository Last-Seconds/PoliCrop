"""Filter rules: a rule takes a candidate and says pass/fail with a readable reason.

To add a rule: write a class with `id`, `label` and `check()`, decorate it with
@register_rule, and enable it in data/rules.yaml (with any params).
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Protocol

from ..content import Content, RuleConfig
from .model import RuleResult, Strategy


class Rule(Protocol):
    id: str
    label: str
    provisional: bool

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
        rules.append(rule)
    return rules


def _name(content: Content, crop_id: str) -> str:
    return content.crop(crop_id).name if content.has_crop(crop_id) else crop_id


@register_rule
class NoIdenticalConsecutiveCrop:
    id = "no_identical_consecutive_crop"
    label = "No identical crop in consecutive steps"

    def __init__(self, cyclic: bool = True):
        self.cyclic = cyclic
        self.provisional = True

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        steps = strategy.steps
        pairs = list(zip(steps, steps[1:]))
        if self.cyclic and len(steps) > 1:
            pairs.append((steps[-1], steps[0]))
        for a, b in pairs:
            if a.crop_id == b.crop_id:
                where = (f"year {a.position} and year {b.position}" if b.position > a.position
                         else f"the last year and the first year of the next cycle")
                return RuleResult(self.id, self.label, False,
                                  f"{_name(content, a.crop_id)} follows itself ({where}).", self.provisional)
        return RuleResult(self.id, self.label, True, "No crop directly follows itself.", self.provisional)


@register_rule
class NoOverlappingDates:
    id = "no_overlapping_dates"
    label = "No overlapping step dates"

    def __init__(self, cyclic: bool = True):
        self.cyclic = cyclic
        self.provisional = True

    def check(self, strategy: Strategy, content: Content) -> RuleResult:
        steps = sorted(strategy.steps, key=lambda s: s.start)
        pairs = list(zip(steps, steps[1:]))
        if self.cyclic and len(steps) > 1:
            n = len({s.position for s in steps})
            first = steps[0]
            try:
                shifted = first.start.replace(year=first.start.year + n)
            except ValueError:  # 29 Feb
                shifted = first.start.replace(year=first.start.year + n, day=28)
            pairs.append((steps[-1], _Shifted(first.crop_id, first.position, shifted)))
        for a, b in pairs:
            if b.start <= a.end:
                return RuleResult(
                    self.id, self.label, False,
                    f"{_name(content, b.crop_id)} (year {b.position}) would start on {b.start:%d %b %Y}, "
                    f"before {_name(content, a.crop_id)} (year {a.position}) ends on {a.end:%d %b %Y}.",
                    self.provisional)
        return RuleResult(self.id, self.label, True, "Each step ends before the next one starts.", self.provisional)


class _Shifted:
    def __init__(self, crop_id: str, position: int, start: dt.date):
        self.crop_id, self.position, self.start = crop_id, position, start
