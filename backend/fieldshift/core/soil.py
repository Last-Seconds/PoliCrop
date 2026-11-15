"""Soil facts for a field: water storage, main soil, drainage, slope class.

Input is the SoilProvider payload (untrusted); output is what the water budget,
soil protection and warnings need, plus what the evidence section shows. If the
soil source failed, `field_soil(None, ...)` gives the stated default storage and
marks everything else unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import units
from .content import Settings

AWS_RANGE_MM = (0.0, 1000.0)


@dataclass
class FieldSoil:
    capacity_mm: dict[str, float]  # "0_100cm" / "0_150cm" -> plant-available storage, mm
    capacity_default: bool  # True when the soil source failed and defaults are used
    main_name: str | None = None
    main_component: str | None = None
    main_share: float | None = None
    drainage: str | None = None
    slope_low: float | None = None
    slope_rep: float | None = None
    slope_high: float | None = None
    kw: float | None = None
    hydgrp: str | None = None
    soils: list[dict] = field(default_factory=list)
    source: str | None = None
    attributes_missing: bool = False
    error: str | None = None

    def sensitivity(self, settings: Settings) -> str | None:
        """low / moderate / high from the representative slope (brief 6.3); None if unknown."""
        if self.slope_rep is None:
            return None
        lo = float(settings["residue.slope_low_below_pct"])
        hi = float(settings["residue.slope_high_above_pct"])
        if self.slope_rep < lo:
            return "low"
        if self.slope_rep > hi:
            return "high"
        return "moderate"

    def to_dict(self, settings: Settings) -> dict:
        return {
            "capacity_in": {k: round(units.mm_to_in(v), 1) for k, v in self.capacity_mm.items()},
            "capacity_default": self.capacity_default,
            "main_name": self.main_name,
            "main_component": self.main_component,
            "main_share": self.main_share,
            "drainage": self.drainage,
            "slope_pct": {"low": self.slope_low, "rep": self.slope_rep, "high": self.slope_high},
            "erodibility_kw": self.kw,
            "hydrologic_group": self.hydgrp,
            "sensitivity": self.sensitivity(settings),
            "soils": self.soils,
            "source": self.source,
            "attributes_missing": self.attributes_missing,
            "error": self.error,
        }


def _f(v, lo=None, hi=None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or (lo is not None and x < lo) or (hi is not None and x > hi):
        return None
    return x


def default_soil(settings: Settings, error: str | None = None) -> FieldSoil:
    return FieldSoil(
        capacity_mm={"0_100cm": units.in_to_mm(float(settings["water.default_capacity_0_100cm_in"])),
                     "0_150cm": units.in_to_mm(float(settings["water.default_capacity_0_150cm_in"]))},
        capacity_default=True, attributes_missing=True, error=error)


def field_soil(raw: dict | None, settings: Settings, error: str | None = None) -> FieldSoil:
    if not raw:
        return default_soil(settings, error)
    units_raw = [u for u in (raw.get("map_units") or []) if isinstance(u, dict)]
    clean = []
    for u in units_raw:
        share = _f(u.get("area_share"), 0, 1)
        if not share:
            continue
        clean.append({**u, "area_share": share,
                      "aws0_100_mm": _f(u.get("aws0_100_mm"), *AWS_RANGE_MM),
                      "aws0_150_mm": _f(u.get("aws0_150_mm"), *AWS_RANGE_MM)})
    if not clean:
        return default_soil(settings, "The soil source returned no usable soil map units.")

    def weighted(key: str) -> float | None:
        pairs = [(u[key], u["area_share"]) for u in clean if u[key] is not None]
        w = sum(s for _, s in pairs)
        # Require the values to cover most of the field before trusting the average.
        return sum(v * s for v, s in pairs) / w if pairs and w >= 0.5 else None

    c100, c150 = weighted("aws0_100_mm"), weighted("aws0_150_mm")
    capacity_default = c100 is None or c150 is None
    d = default_soil(settings)
    capacity = {"0_100cm": c100 if c100 is not None else d.capacity_mm["0_100cm"],
                "0_150cm": c150 if c150 is not None else d.capacity_mm["0_150cm"]}

    main = max(clean, key=lambda u: u["area_share"])
    comps = [c for c in (main.get("components") or []) if isinstance(c, dict)]
    comp = max(comps, key=lambda c: _f(c.get("pct"), 0, 100) or 0) if comps else None
    soils = []
    for u in sorted((u for u in clean if u["area_share"] >= 0.01), key=lambda u: -u["area_share"]):
        cs = [c for c in (u.get("components") or []) if isinstance(c, dict)]
        top = max(cs, key=lambda c: _f(c.get("pct"), 0, 100) or 0) if cs else {}
        soils.append({
            "name": u.get("name") or f"Soil map unit {u.get('mukey')}",
            "share": round(u["area_share"], 3),
            "drainage": top.get("drainage"),
            "slope_pct": [_f(top.get("slope_low"), 0, 100), _f(top.get("slope_rep"), 0, 100),
                          _f(top.get("slope_high"), 0, 100)] if top else None,
            "storage_in": {"0_100cm": round(units.mm_to_in(u["aws0_100_mm"]), 1) if u["aws0_100_mm"] is not None else None,
                           "0_150cm": round(units.mm_to_in(u["aws0_150_mm"]), 1) if u["aws0_150_mm"] is not None else None},
        })
    return FieldSoil(
        capacity_mm=capacity,
        capacity_default=capacity_default,
        main_name=main.get("name"),
        main_component=comp.get("name") if comp else None,
        main_share=round(main["area_share"], 3),
        drainage=(comp or {}).get("drainage"),
        slope_low=_f((comp or {}).get("slope_low"), 0, 100),
        slope_rep=_f((comp or {}).get("slope_rep"), 0, 100),
        slope_high=_f((comp or {}).get("slope_high"), 0, 100),
        kw=_f((comp or {}).get("kw"), 0, 1),
        hydgrp=(comp or {}).get("hydgrp"),
        soils=soils,
        source=raw.get("source"),
        attributes_missing=comp is None,
        error=raw.get("attributes_error") or error,
    )
