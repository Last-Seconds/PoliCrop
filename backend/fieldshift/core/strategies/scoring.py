"""Scoring interface. v0 ships NO scorers: strategies are shown unranked.

A scorer returns named criteria for a strategy, for example
{"Water use": {"value": ..., "unit": ..., "explanation": ..., "caveats": [...]}}.
Register it with @register_scorer. Criteria listed in settings
(assessment.criteria) that no scorer provides are reported per strategy as
"not yet assessed", so the gaps stay explicit.
"""
from __future__ import annotations

from typing import Callable, Protocol

from ..content import Content
from .model import Strategy


class Scorer(Protocol):
    criteria: tuple[str, ...]

    def score(self, strategy: Strategy, context: dict, content: Content) -> dict[str, dict]: ...


SCORER_REGISTRY: dict[str, Callable[[], Scorer]] = {}


def register_scorer(name: str):
    def deco(cls):
        SCORER_REGISTRY[name] = cls
        return cls
    return deco


def assess(strategy: Strategy, context: dict, content: Content, scorers: list[Scorer]) -> None:
    scores: dict[str, dict] = {}
    for scorer in scorers:
        for name, result in scorer.score(strategy, context, content).items():
            scores[name] = result
    strategy.scores = scores
    wanted = list(content.settings.get("assessment.criteria", []) or [])
    strategy.not_assessed = [c for c in wanted if c not in scores]
