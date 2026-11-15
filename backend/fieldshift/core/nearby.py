"""Nearby use (brief 6.6, 6.7): how much cropland around a field follows a strategy's role pattern.

Built from a role-sequence histogram (one entry per distinct per-pixel sequence of crop roles
over recent crop-map years; see providers/us/cdl_sequences.py for how it is made). A pixel
follows a pattern when its sequence equals the pattern repeated cyclically, starting at any
phase, with at most `max_mismatch` years different (the crop map has errors), and with every
year of the pattern seen at least once (so the tolerance never erases a whole pattern slot).

This is evidence that a pattern is workable locally, never proof that it is good. It is the
last tie-break when ordering options, so `share()` is called thousands of times per request:
results are cached by canonical role pattern (rotation- and repetition-free), and the
sequences are held as one small integer matrix.

Choices:
- A pattern containing a role the crop map cannot show (no class code, e.g. cover crop)
  has share 0.0: the map can never confirm it.
- An "unknown" year in a sequence (a class the tool does not model) never equals any role,
  so it counts as a mismatch.
- Shares of different patterns can overlap (a pixel may be within `max_mismatch` of two).
"""
from __future__ import annotations

from itertools import product
from typing import Any, Iterable, Sequence

import numpy as np

SEP = "|"


def code_roles(content: Any, system: str = "us_cdl") -> dict[int, str]:
    """Crop-map class code -> role id, from the crop table (first crop listing a code wins)."""
    out: dict[int, str] = {}
    for c in content.crops:
        for code in c.codes(system):
            out.setdefault(int(code), c.role)
    return out


def canonical(pattern: Sequence[str]) -> tuple[str, ...]:
    """The same cyclic pattern written one way: shortest repeating unit, smallest rotation."""
    p = tuple(pattern)
    n = len(p)
    for d in range(1, n + 1):
        if n % d == 0 and p == p[:d] * (n // d):
            p = p[:d]
            break
    return min(p[i:] + p[:i] for i in range(len(p))) if p else p


class NearbyUse:
    def __init__(self, payload: dict, max_mismatch: int = 1):
        years = [int(y) for y in payload.get("years") or []]
        seqs = payload.get("sequences")
        if not years or not isinstance(seqs, dict):
            raise ValueError("nearby: payload needs 'years' and 'sequences'")
        if max_mismatch < 0:
            raise ValueError("nearby: max_mismatch must be >= 0")
        self.years = years
        self.max_mismatch = int(max_mismatch)
        self.pixel_size_m = float(payload.get("pixel_size_m") or 30.0)
        self.radius_km = payload.get("radius_km")
        self.source = str(payload.get("source") or "")
        unknown = str(payload.get("unknown_token") or "?")

        n = len(years)
        vocab: dict[str, int] = {}
        rows, counts = [], []
        for key, cnt in seqs.items():
            parts = str(key).split(SEP)
            cnt = int(cnt)
            if len(parts) != n or cnt <= 0:
                raise ValueError(f"nearby: bad sequence entry {key!r}: {cnt!r}")
            rows.append([-1 if t == unknown else vocab.setdefault(t, len(vocab)) for t in parts])
            counts.append(cnt)
        self._vocab = vocab
        mapped = payload.get("roles_mapped")
        self._mapped = set(mapped) if mapped is not None else set(vocab)
        self._seq = np.array(rows, dtype=np.int16).reshape(len(rows), n)
        self._counts = np.array(counts, dtype=np.int64)
        self.cropland_pixels = int(self._counts.sum())
        self._cache: dict[tuple[str, ...], float] = {}  # canonical pattern -> share
        self._raw: dict[tuple[str, ...], float] = {}  # pattern as given -> share (skips canonicalising)

    @classmethod
    def from_settings(cls, payload: dict, settings: Any) -> "NearbyUse":
        return cls(payload, int(settings["nearby.max_mismatch"]))

    @property
    def cropland_ha(self) -> float:
        return self.cropland_pixels * self.pixel_size_m ** 2 / 10_000.0

    # ---- shares
    def share(self, crops: Iterable[Any]) -> float:
        """Share (0..1) of nearby cropland whose sequence follows these crops' role pattern cyclically."""
        return self.share_roles([c.role for c in crops])

    def share_roles(self, roles: Sequence[str]) -> float:
        raw = tuple(roles)
        hit = self._raw.get(raw)
        if hit is not None:
            return hit
        key = canonical(raw)
        val = self._cache.get(key)
        if val is None:
            val = self._compute(key)
            self._cache[key] = val
        self._raw[raw] = val
        return val

    def _compute(self, pattern: tuple[str, ...]) -> float:
        if not pattern or not self.cropland_pixels or any(r not in self._mapped for r in pattern):
            return 0.0
        # A mapped role no pixel shows gets -2, which equals nothing (unknown years are -1).
        ids = [self._vocab.get(r, -2) for r in pattern]
        n, L = len(self.years), len(pattern)
        t = np.arange(n)
        matched = np.zeros(len(self._counts), dtype=bool)
        for ph in range(L):
            slot = (t + ph) % L
            eq = self._seq == np.array(ids, dtype=np.int16)[slot]  # K x n
            ok = (n - eq.sum(axis=1)) <= self.max_mismatch
            # Every year of the pattern must be seen at least once: otherwise the tolerance could
            # erase a slot that falls in only one year of the window (a 4-year pattern over 6 years).
            for j in range(L):
                cols = slot == j
                if cols.any():
                    ok &= eq[:, cols].any(axis=1)
            matched |= ok
        return float(self._counts[matched].sum()) / self.cropland_pixels

    # ---- evidence
    def top_patterns(self, k: int = 5, min_len: int = 1, max_len: int = 4) -> list[dict]:
        """The most followed cyclic role patterns nearby: [{"roles": [...], "share": float}, ...].

        Patterns are written in their shortest repeating unit, so continuous cereal is ["cereal"]
        (length 1); set min_len=2 to leave single-role patterns out.
        """
        roles = sorted(r for r in self._vocab if r in self._mapped)
        seen: set[tuple[str, ...]] = set()
        scored = []
        for L in range(1, max_len + 1):
            for p in product(roles, repeat=L):
                c = canonical(p)
                if c in seen or len(c) != L or L < min_len:
                    continue
                seen.add(c)
                s = self.share_roles(c)
                if s > 0:
                    scored.append((s, L, c))
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        return [{"roles": list(c), "share": round(s, 4)} for s, _, c in scored[:k]]

    def describe(self, k: int = 5) -> dict:
        """Evidence summary for the interface."""
        return {
            "years": list(self.years),
            "radius_km": self.radius_km,
            "cropland_pixels": self.cropland_pixels,
            "cropland_ha": round(self.cropland_ha, 1),
            "max_mismatch": self.max_mismatch,
            "top_patterns": self.top_patterns(k),
            "source": self.source,
        }
