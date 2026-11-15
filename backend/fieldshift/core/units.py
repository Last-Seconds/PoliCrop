"""Unit conventions and conversions.

Internal units (everything inside the core, every provider payload):
    water depth      mm
    temperature      °C
    mass per area    kg/ha
    area             ha
    length           m

Content files may state a value in US units; the field name then carries the
unit (``need_in``, ``residue_lb_ac``, ``limit_f``) and the loader converts it to
internal units. US units appear only at the display edge (core.present and the
front end): inches, °F, acres, pounds per acre, bushels per acre.
"""
from __future__ import annotations

MM_PER_IN = 25.4
HA_PER_ACRE = 0.40468564224
LB_PER_KG = 2.2046226218
# 1 lb/ac = 0.45359237 kg / 0.40468564224 ha
KG_HA_PER_LB_AC = 0.45359237 / HA_PER_ACRE  # 1.12085...
WHEAT_LB_PER_BU = 60.0  # the standard bushel weight for wheat


def in_to_mm(x: float) -> float:
    return x * MM_PER_IN


def mm_to_in(x: float) -> float:
    return x / MM_PER_IN


def cm_to_mm(x: float) -> float:
    return x * 10.0


def f_to_c(x: float) -> float:
    return (x - 32.0) * 5.0 / 9.0


def c_to_f(x: float) -> float:
    return x * 9.0 / 5.0 + 32.0


def delta_f_to_c(x: float) -> float:
    """A temperature *difference* in °F as a difference in °C."""
    return x * 5.0 / 9.0


def delta_c_to_f(x: float) -> float:
    return x * 9.0 / 5.0


def ha_to_acres(x: float) -> float:
    return x / HA_PER_ACRE


def acres_to_ha(x: float) -> float:
    return x * HA_PER_ACRE


def lb_ac_to_kg_ha(x: float) -> float:
    return x * KG_HA_PER_LB_AC


def kg_ha_to_lb_ac(x: float) -> float:
    return x / KG_HA_PER_LB_AC


def bu_to_lb(bu: float, lb_per_bu: float = WHEAT_LB_PER_BU) -> float:
    return bu * lb_per_bu


def lb_to_bu(lb: float, lb_per_bu: float = WHEAT_LB_PER_BU) -> float:
    return lb / lb_per_bu


# Field-name suffix -> converter to internal units (used by the content loader).
SUFFIX_TO_INTERNAL = {
    "_in": in_to_mm,
    "_mm": lambda x: x,
    "_cm": cm_to_mm,
    "_lb_ac": lb_ac_to_kg_ha,
    "_kg_ha": lambda x: x,
    "_f": f_to_c,
    "_c": lambda x: x,
}
