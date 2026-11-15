"""Comparing, filtering, ordering and choosing options (brief section 6.6).

- A verdict on one measure (better / about the same / worse) uses central values
  and the measure's margin.
- Assumed values never decide alone: if either quantity rests on an assumed
  value and the verdict does not survive taking both ranges at the ends least
  favourable to it, the verdict is "about the same", flagged as depending on an
  assumed figure.
- A dominates B when A is no worse on all four measures, better on at least one,
  and has at least as many harvest years. Dominated options are dropped.
- Ordering follows the farmer's priority order of measures; selection shows the
  top option in each of three bands of change.

No total score is ever formed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .measures import MEASURES, Quantity

BETTER, SAME, WORSE = 1, 0, -1
WORDS = {BETTER: "better", SAME: "about the same", WORSE: "worse"}


@dataclass
class Verdict:
    value: int | None  # 1 better, 0 about the same, -1 worse, None not assessed
    held_by_assumed: bool = False  # the central verdict was reduced to "about the same" by the assumed-value rule
    central_value: int | None = None
    probably: bool = False  # addendum 2, A2: "worse" that rests on an assumed figure: shown "probably worse"

    @property
    def word(self) -> str:
        if self.value is None:
            return "not assessed"
        return "probably worse" if self.probably else WORDS[self.value]

    def to_dict(self) -> dict:
        return {"value": self.value, "word": self.word, "held_by_assumed": self.held_by_assumed,
                "central_value": self.central_value, "probably": self.probably}


def _sign(d: float, margin: float) -> int:
    if d > margin + 1e-12:
        return BETTER
    if d < -margin - 1e-12:
        return WORSE
    return SAME


def verdict(a: Quantity, b: Quantity, margin: float) -> Verdict:
    """How A compares with B on one measure."""
    if not a.assessed or not b.assessed:
        return Verdict(None)
    s = 1.0 if a.higher_is_better else -1.0
    v = _sign(s * (a.central - b.central), margin)
    if v == SAME or not (a.assumed or b.assumed):
        return Verdict(v, False, v)
    # Take both ranges at the ends least favourable to this verdict.
    if v == BETTER:
        d2 = s * (a.unfavourable() - b.favourable())
        if _sign(d2, margin) != v:
            return Verdict(SAME, True, v)
        return Verdict(v, False, v)
    # Addendum 2, A2: the rule works one way only. "Worse" stays worse; if it does not survive the ranges,
    # it is "probably worse", still counted as worse for ordering and dominance.
    d2 = s * (a.favourable() - b.unfavourable())
    return Verdict(v, False, v, probably=_sign(d2, margin) != v)


# ------------------------------------------------------------------------------------------- vectorised form

@dataclass
class Table:
    """Quantities of many options as arrays, one row per option, for fast pairwise verdicts."""
    central: dict[str, np.ndarray]
    fav: dict[str, np.ndarray]
    unfav: dict[str, np.ndarray]
    assumed: dict[str, np.ndarray]
    assessed: dict[str, np.ndarray]
    sign: dict[str, float]
    margin: dict[str, float]
    harvests: np.ndarray

    @staticmethod
    def build(scores: list[dict[str, Quantity]], harvests: list[int], margins: dict[str, float]) -> "Table":
        def arr(f):
            return {m: np.array([f(s[m]) for s in scores], dtype=float) for m in MEASURES}
        sign = {m: (1.0 if scores[0][m].higher_is_better else -1.0) for m in MEASURES} if scores else \
            {m: 1.0 for m in MEASURES}
        return Table(
            central=arr(lambda q: q.central), fav=arr(lambda q: q.favourable()),
            unfav=arr(lambda q: q.unfavourable()),
            assumed={m: np.array([bool(s[m].assumed) for s in scores]) for m in MEASURES},
            assessed={m: np.array([s[m].assessed for s in scores]) for m in MEASURES},
            sign=sign, margin=dict(margins), harvests=np.array(harvests, dtype=int))

    def verdicts_vs(self, j: int, m: str, rows: np.ndarray | None = None) -> np.ndarray:
        """Verdict of every row (or the given rows) against row j on measure m (0 where not assessed)."""
        sl = slice(None) if rows is None else rows
        s, mg = self.sign[m], self.margin[m]
        c = self.central[m][sl]
        d = s * (c - self.central[m][j])
        v = np.where(d > mg + 1e-12, BETTER, np.where(d < -mg - 1e-12, WORSE, SAME))
        risky = (v != SAME) & (self.assumed[m][sl] | self.assumed[m][j])
        if risky.any():
            d_better = s * (self.unfav[m][sl] - self.fav[m][j])
            d_worse = s * (self.fav[m][sl] - self.unfav[m][j])
            keep_b = (v == BETTER) & (d_better > mg + 1e-12)
            del d_worse  # addendum 2, A2: "worse" is never softened to "about the same"
            v = np.where(risky & (v == BETTER) & ~keep_b, SAME, v)
        ok = self.assessed[m][sl] & self.assessed[m][j]
        return np.where(ok, v, SAME)

    def dominators(self, j: int, rows: np.ndarray | None = None) -> np.ndarray:
        """Indices of rows (all, or among `rows`) that dominate row j."""
        idx = np.arange(len(self.harvests)) if rows is None else np.asarray(rows, dtype=int)
        if idx.size == 0:
            return idx
        no_worse = np.ones(idx.size, dtype=bool)
        better = np.zeros(idx.size, dtype=bool)
        for m in MEASURES:
            v = self.verdicts_vs(j, m, None if rows is None else idx)
            no_worse &= v >= SAME
            better |= v == BETTER
        dom = no_worse & better & (self.harvests[idx] >= self.harvests[j]) & (idx != j)
        return idx[dom]

    def dominated(self, j: int, elite: list[int] | None = None) -> bool:
        """Is row j dominated by any other row?

        `elite` (optional, updated in place) holds rows known to dominate others; they
        are tried first, so the full scan runs only for rows they do not dominate.
        """
        if elite:
            if self.dominators(j, np.array(elite)).size:
                return True
        found = self.dominators(j)
        if found.size and elite is not None:
            elite.append(int(found[0]))
            if len(elite) > 64:
                del elite[0]
        return bool(found.size)


# ------------------------------------------------------------------------------------------- ordering and selection

def order_key(verdicts: dict[str, Verdict], q: dict[str, Quantity], priorities: list[str], harvests: int,
              nearby: float, dry_mode: bool, seen_nearby: bool = True, serious: bool = False) -> tuple:
    """Sort key (ascending = first): options without a serious caution first (addendum 2, A1), then verdicts in
    priority order, then options seen nearby before those not (brief 3, S1), then quantities, then nearby use."""
    key: list = [1 if serious else 0]
    for m in priorities:
        v = verdicts[m].value
        key.append(-(v if v is not None else 0))
    key.append(0 if seen_nearby else 1)
    if dry_mode:
        key.append(-harvests)
    top = q[priorities[0]]
    top_val = top.central if top.assessed else 0.0
    key.append(-(top_val if top.higher_is_better else -top_val))
    key.append(-nearby)
    return tuple(key)


def band_of(distance: float, n: int, small_max: float, moderate_max: float) -> int:
    share = distance / max(n, 1)
    if share <= small_max + 1e-9:
        return 0
    if share <= moderate_max + 1e-9:
        return 1
    return 2


BAND_LABELS = ("small change", "moderate change", "large change")


@dataclass
class Selection:
    shown: list[int]  # indices into the candidate list, in band order
    shown_bands: list[int]
    more: list[int]
    surviving: int
    dominated_checked: int
    band_counts: list[int] = field(default_factory=list)
    filled_from_other_band: list[int] = field(default_factory=list)


def select(order: list[int], bands: list[int], table: Table, current_row: int, k: int, k_more: int) -> Selection:
    """Walk options in order; drop dominated ones; take the first of each band, then fill and extend.

    `table` holds every candidate plus the current rotation at `current_row`: an
    option no better than the current rotation on anything, and worse somewhere,
    is dominated by it and dropped too.
    """
    chosen: dict[int, int] = {}
    extras: list[int] = []
    elite: list[int] = []
    checked = 0
    survivors_seen = 0
    band_counts = [0, 0, 0]
    for i in order:
        checked += 1
        if table.dominated(i, elite):
            continue
        survivors_seen += 1
        b = bands[i]
        band_counts[b] += 1
        if b not in chosen and len(chosen) < 3:
            chosen[b] = i
        else:
            extras.append(i)
        if len(chosen) == min(3, k) and len(extras) >= k + k_more:
            break
    shown = [chosen[b] for b in sorted(chosen)]
    filled = []
    while len(shown) < k and extras:  # an empty band: take the next best overall
        i = extras.pop(0)
        shown.append(i)
        filled.append(i)
    return Selection(shown=shown, shown_bands=[bands[i] for i in shown], more=extras[:k_more],
                     surviving=survivors_seen, dominated_checked=checked, band_counts=band_counts,
                     filled_from_other_band=filled)
