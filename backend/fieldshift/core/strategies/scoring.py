"""Scorer registry.

A scorer takes a rotation (its crops, one per crop year) and the field model,
and returns a Quantity: low / central / high, its unit, which direction is
better, the assumed values that fed it, and the pieces of its explanation.
Register one with @register_scorer("<measure id>") and list the id in
settings `comparison.measures`. The four measures of the brief are registered
in measures.py.
"""
from __future__ import annotations

from typing import Callable

SCORER_REGISTRY: dict[str, Callable] = {}


def register_scorer(name: str):
    def deco(fn):
        SCORER_REGISTRY[name] = fn
        return fn
    return deco


def build_scorers(measure_ids: list[str]) -> dict[str, Callable]:
    from . import measures  # noqa: F401  (registers the built-in scorers)
    missing = [m for m in measure_ids if m not in SCORER_REGISTRY]
    if missing:
        raise ValueError(f"settings comparison.measures lists {missing} with no scorer; known: {sorted(SCORER_REGISTRY)}")
    return {m: SCORER_REGISTRY[m] for m in measure_ids}
