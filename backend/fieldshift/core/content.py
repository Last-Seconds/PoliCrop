"""Load and validate the content files (crop table, roles, rules, settings, sources).

Content is data, not code: everything the team may want to change without a
code change lives in the data directory. This module turns those files into
typed objects and fails loudly (at start-up) when a file is malformed.

Every agronomic value carries a basis (sourced / derived / assumed) and, unless
assumed, a source. Values given in US units in the files (field names ending in
_in, _lb_ac, _f) are converted to internal units here (see core.units).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import units

BASES = ("sourced", "derived", "assumed")
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class ContentError(ValueError):
    """A content file is malformed."""


def _check_basis(raw: dict, where: str) -> tuple[str, str | None]:
    basis = raw.get("basis")
    if basis not in BASES:
        raise ContentError(f"{where}: basis must be one of {BASES}, got {basis!r}")
    source = raw.get("source")
    if basis != "assumed" and not source:
        raise ContentError(f"{where}: a {basis} value needs a source")
    return basis, (str(source) if source is not None else None)


@dataclass(frozen=True)
class Basis:
    """Where a value comes from."""
    basis: str
    source: str | None = None
    note: str | None = None

    @property
    def assumed(self) -> bool:
        return self.basis == "assumed"

    def to_dict(self) -> dict:
        return {"basis": self.basis, "source": self.source, "note": self.note}

    @staticmethod
    def parse(raw: dict, where: str) -> "Basis":
        basis, source = _check_basis(raw, where)
        return Basis(basis, source, raw.get("note"))


@dataclass(frozen=True)
class SeasonWindow:
    """A usual date range, as MM-DD strings (no year)."""
    start: str
    end: str
    spans_winter: bool = False  # only for the default whole-crop-year window
    basis: Basis | None = None

    @staticmethod
    def parse(raw: Any, where: str, need_basis: bool = False) -> "SeasonWindow | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ContentError(f"{where}: date window must be a mapping or null")
        start, end = str(raw.get("start", "")), str(raw.get("end", ""))
        if not _MMDD.match(start) or not _MMDD.match(end):
            raise ContentError(f"{where}: window start/end must be 'MM-DD', got {start!r}/{end!r}")
        b = Basis.parse(raw, where) if need_basis else None
        return SeasonWindow(start, end, bool(raw.get("spans_winter", False)), b)

    def to_dict(self) -> dict:
        d = {"start": self.start, "end": self.end}
        if self.basis:
            d.update(self.basis.to_dict())
        return d


@dataclass(frozen=True)
class Crop:
    id: str
    name: str
    role: str
    class_codes: dict[str, tuple[int, ...]]
    pool: str = "if_grown_nearby"
    pool_codes: dict[str, tuple[int, ...]] | None = None
    generate: bool = True
    plant_type: str = "none"  # grass | broadleaf | none
    sown: str = "none"  # autumn | spring | none
    sowing_window: SeasonWindow | None = None
    harvest_window: SeasonWindow | None = None
    # Agronomic blocks, kept as validated dicts in internal units plus a Basis.
    water_need: dict | None = None
    water_use: dict | None = None  # sourced seasonal use (brief 3, S1): drives the "may be too dry" caution
    root_zone: dict | None = None
    growing_season: dict | None = None
    regional_yield: dict | None = None
    yield_unit: dict | None = None
    residue: dict | None = None
    nitrogen_credit: dict | None = None
    critical_ph: dict | None = None
    income: dict | None = None
    limits: tuple[dict, ...] = ()
    aliases: tuple[str, ...] = ()
    notes: str | None = None

    def codes(self, system: str) -> tuple[int, ...]:
        return self.class_codes.get(system, ())

    def presence_codes(self, system: str) -> tuple[int, ...]:
        if self.pool_codes is not None:
            return self.pool_codes.get(system, ())
        return self.codes(system)

    @property
    def is_crop_year_with_harvest(self) -> bool:
        return self.role not in ("fallow", "cover_crop")

    def to_dict(self) -> dict:
        def b(block):
            if block is None:
                return None
            return {k: (v.to_dict() if isinstance(v, Basis) else v) for k, v in block.items()}
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "class_codes": {k: list(v) for k, v in self.class_codes.items()},
            "pool": self.pool,
            "generate": self.generate,
            "plant_type": self.plant_type,
            "sown": self.sown,
            "sowing_window": self.sowing_window.to_dict() if self.sowing_window else None,
            "harvest_window": self.harvest_window.to_dict() if self.harvest_window else None,
            "water_need": b(self.water_need),
            "water_use": b(self.water_use),
            "root_zone": b(self.root_zone),
            "growing_season": b(self.growing_season),
            "regional_yield": b(self.regional_yield),
            "yield_unit": self.yield_unit,
            "residue": b(self.residue),
            "nitrogen_credit": b(self.nitrogen_credit),
            "critical_ph": b(self.critical_ph),
            "income": b(self.income),
            "limits": list(self.limits),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    color: str
    generate: bool = True
    harvest: bool = True
    short: str | None = None
    description: str | None = None

    @property
    def short_label(self) -> str:
        return self.short or self.label.lower()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "short": self.short_label,
            "color": self.color,
            "generate": self.generate,
            "harvest": self.harvest,
            "description": self.description,
        }


@dataclass(frozen=True)
class Param:
    key: str
    value: Any
    unit: str | None
    basis: str
    source: str | None
    description: str | None

    @property
    def provisional(self) -> bool:
        return self.basis == "assumed"

    @property
    def is_range(self) -> bool:
        return isinstance(self.value, dict) and "central" in self.value

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "basis": self.basis,
            "source": self.source,
            "provisional": self.provisional,
            "description": self.description,
        }


class Settings:
    """Named parameters from settings.yaml, addressed as 'section.name'."""

    def __init__(self, raw: dict):
        self._params: dict[str, Param] = {}
        for section, entries in (raw or {}).items():
            if not isinstance(entries, dict):
                raise ContentError(f"settings: section {section!r} must be a mapping")
            for name, spec in entries.items():
                key = f"{section}.{name}"
                if not isinstance(spec, dict) or "value" not in spec:
                    raise ContentError(f"settings: {key} must be a mapping with a 'value'")
                if "basis" not in spec and "provisional" in spec:  # older files
                    spec = {**spec, "basis": "assumed" if spec["provisional"] else "sourced",
                            "source": spec.get("source", "unspecified")}
                basis, source = _check_basis(spec, f"settings: {key}")
                v = spec["value"]
                if isinstance(v, dict) and "central" in v:
                    lo, c, hi = v.get("low"), v.get("central"), v.get("high")
                    if not all(isinstance(x, (int, float)) for x in (lo, c, hi)) or not lo <= c <= hi:
                        raise ContentError(f"settings: {key}: a range needs numeric low <= central <= high")
                self._params[key] = Param(key, v, spec.get("unit"), basis, source, spec.get("description"))

    def __getitem__(self, key: str) -> Any:
        try:
            return self._params[key].value
        except KeyError:
            raise KeyError(f"missing setting {key!r} in settings.yaml") from None

    def get(self, key: str, default: Any = None) -> Any:
        p = self._params.get(key)
        return default if p is None else p.value

    def has(self, key: str) -> bool:
        return key in self._params

    def param(self, key: str) -> Param:
        return self._params[key]

    def params(self) -> list[Param]:
        return list(self._params.values())

    def central(self, key: str) -> float:
        v = self[key]
        return float(v["central"]) if isinstance(v, dict) and "central" in v else float(v)

    def range(self, key: str) -> tuple[float, float, float]:
        """(low, central, high); a single value gives (v, v, v)."""
        v = self[key]
        if isinstance(v, dict) and "central" in v:
            return float(v["low"]), float(v["central"]), float(v["high"])
        return float(v), float(v), float(v)

    def assumed(self, key: str) -> bool:
        return self._params[key].basis == "assumed"

    def with_overrides(self, overrides: dict[str, Any]) -> "Settings":
        clone = Settings({})
        clone._params = dict(self._params)
        for key, value in overrides.items():
            old = clone._params.get(key)
            clone._params[key] = Param(key, value, old.unit if old else None, "assumed", None,
                                       old.description if old else None)
        return clone


@dataclass(frozen=True)
class RuleConfig:
    id: str
    enabled: bool
    code: str
    basis: str
    source: str | None
    params: dict[str, Any]
    kind: str = "rule"  # rule | warning

    @property
    def provisional(self) -> bool:
        return self.basis == "assumed"


@dataclass
class Content:
    crops: list[Crop]
    roles: list[Role]
    settings: Settings
    rules: list[RuleConfig]
    attributions: list[dict]
    region: dict
    warnings: list[RuleConfig] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)
    crops_provisional: bool = True
    roles_provisional: bool = True
    legends: dict[str, dict[int, dict]] = field(default_factory=dict)
    data_dir: Path | None = None

    def __post_init__(self) -> None:
        self._crop_by_id = {c.id: c for c in self.crops}
        for c in self.crops:
            for a in c.aliases:
                self._crop_by_id.setdefault(a, c)
        self._role_by_id = {r.id: r for r in self.roles}

    def crop(self, crop_id: str) -> Crop:
        return self._crop_by_id[crop_id]

    def has_crop(self, crop_id: str) -> bool:
        return crop_id in self._crop_by_id

    def role(self, role_id: str) -> Role:
        return self._role_by_id[role_id]

    def has_role(self, role_id: str) -> bool:
        return role_id in self._role_by_id

    def crop_for_code(self, system: str, code: int) -> Crop | None:
        for c in self.crops:
            if code in c.codes(system):
                return c
        return None

    def legend(self, system: str) -> dict[int, dict]:
        return self.legends.get(system, {})

    def offered_crops(self) -> list[Crop]:
        return [c for c in self.crops if c.generate and self.role(c.role).generate]


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ContentError(f"missing content file {path}") from None
    except yaml.YAMLError as exc:
        raise ContentError(f"{path}: invalid YAML: {exc}") from None


def parse_roles(raw: dict) -> list[Role]:
    roles = []
    for i, r in enumerate((raw or {}).get("roles") or []):
        if not r.get("id") or not r.get("label"):
            raise ContentError(f"roles[{i}]: id and label are required")
        roles.append(
            Role(
                id=str(r["id"]),
                label=str(r["label"]),
                color=str(r.get("color", "#888888")),
                generate=bool(r.get("generate", True)),
                harvest=bool(r.get("harvest", True)),
                short=r.get("short"),
                description=r.get("description"),
            )
        )
    ids = [r.id for r in roles]
    if len(set(ids)) != len(ids):
        raise ContentError("roles: duplicate role id")
    if not roles:
        raise ContentError("roles: no roles defined")
    return roles


def _codes(raw: Any, where: str) -> dict[str, tuple[int, ...]]:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ContentError(f"{where}: class codes must be a mapping of system -> list of codes")
    out = {}
    for system, lst in raw.items():
        try:
            out[system] = tuple(int(x) for x in (lst or []))
        except (TypeError, ValueError):
            raise ContentError(f"{where}: class codes for {system!r} must be integers") from None
    return out


def _num(raw: dict, key: str, where: str, lo: float | None = None, hi: float | None = None) -> float:
    v = raw.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ContentError(f"{where}: {key} must be a number, got {v!r}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ContentError(f"{where}: {key}={v} outside the plausible range [{lo}, {hi}]")
    return float(v)


def _water_need(raw: Any, where: str) -> dict | None:
    if raw is None:
        return None
    b = Basis.parse(raw, where)
    m = raw.get("method")
    if m == "self_calibrated":
        return {"method": m, "basis": b}
    if m in ("fixed", "relative_to"):
        raise ContentError(f"{where}: water_need method {m!r} was retired in brief 3 (S1); every crop's need is "
                           "self_calibrated. Put a sourced figure in water_use instead.")
    raise ContentError(f"{where}: unknown water_need method {m!r}")


def _water_use(raw: Any, where: str) -> dict | None:
    if raw is None:
        return None
    if raw.get("method") == "from_yield":  # addendum item 4: seasonal use = expected yield / seed per inch
        r = raw.get("seed_lb_ac_per_in") or {}
        lo, hi = _num(r, "low", where, 1, 1000), _num(r, "high", where, 1, 1000)
        return {"method": "from_yield", "lb_per_in_low": lo, "lb_per_in_high": hi, "basis": Basis.parse(raw, where)}
    return {"method": "fixed", "use_mm": units.in_to_mm(_num(raw, "use_in", where, 0, 40)),
            "basis": Basis.parse(raw, where)}


def _residue(raw: Any, where: str) -> dict | None:
    if raw is None:
        return None
    m = raw.get("method")
    if m == "none":
        return {"method": m}
    b = Basis.parse(raw, where)
    if m == "linear_kg_ha":
        return {"method": m, "slope": _num(raw, "slope", where, 0, 10),
                "intercept_kg_ha": _num(raw, "intercept_kg_ha", where, -5000, 20000), "basis": b}
    if m == "range_lb_ac":
        lo = units.lb_ac_to_kg_ha(_num(raw, "low_lb_ac", where, 0, 30000))
        hi = units.lb_ac_to_kg_ha(_num(raw, "high_lb_ac", where, 0, 30000))
        if lo > hi:
            raise ContentError(f"{where}: low_lb_ac > high_lb_ac")
        return {"method": m, "low_kg_ha": lo, "high_kg_ha": hi, "basis": b}
    if m == "harvest_index":
        lo, hi = _num(raw, "h_low", where, 0.01, 0.99), _num(raw, "h_high", where, 0.01, 0.99)
        if lo > hi:
            raise ContentError(f"{where}: h_low > h_high")
        return {"method": m, "h_low": lo, "h_high": hi, "basis": b}
    raise ContentError(f"{where}: unknown residue method {m!r}")


def _nitrogen(raw: Any, where: str) -> dict | None:
    if raw is None:
        return None
    b = Basis.parse(raw, where)
    m = raw.get("method")
    if m == "fixed":
        return {"method": m, "credit_kg_ha": units.lb_ac_to_kg_ha(_num(raw, "credit_lb_ac", where, 0, 300)), "basis": b}
    if m == "range":
        return {"method": m, "low_kg_ha": units.lb_ac_to_kg_ha(_num(raw, "low_lb_ac", where, 0, 300)),
                "high_kg_ha": units.lb_ac_to_kg_ha(_num(raw, "high_lb_ac", where, 0, 300)), "basis": b}
    if m == "tiers_by_yield":
        tiers = []
        for j, t in enumerate(raw.get("tiers") or []):
            credit = units.lb_ac_to_kg_ha(_num(t, "credit_lb_ac", f"{where} tier {j}", 0, 300))
            below = t.get("below_lb_ac")
            tiers.append({"below_kg_ha": None if below is None else units.lb_ac_to_kg_ha(float(below)),
                          "credit_kg_ha": credit})
        if not tiers or tiers[-1]["below_kg_ha"] is not None:
            raise ContentError(f"{where}: the last nitrogen tier must have no upper bound")
        return {"method": m, "tiers": tiers, "basis": b}
    raise ContentError(f"{where}: unknown nitrogen_credit method {m!r}")


def parse_crops(raw: dict, role_ids: set[str], season_ids: set[str] | None = None) -> list[Crop]:
    crops: list[Crop] = []
    seen_codes: dict[tuple[str, int], str] = {}
    for i, c in enumerate((raw or {}).get("crops") or []):
        where = f"crops[{i}] ({c.get('id', '?')})"
        if not c.get("id") or not c.get("name") or not c.get("role"):
            raise ContentError(f"{where}: id, name and role are required")
        if c["role"] not in role_ids:
            raise ContentError(f"{where}: unknown role {c['role']!r}")
        codes = _codes(c.get("class_codes"), where)
        for system, lst in codes.items():
            for code in lst:
                if (system, code) in seen_codes:
                    raise ContentError(f"{where}: {system} code {code} already used by {seen_codes[(system, code)]}")
                seen_codes[(system, code)] = c["id"]
        pool = c.get("pool", "if_grown_nearby")
        if pool not in ("if_grown_nearby", "always"):
            raise ContentError(f"{where}: pool must be 'if_grown_nearby' or 'always'")
        plant_type = c.get("plant_type", "none")
        if plant_type not in ("grass", "broadleaf", "none"):
            raise ContentError(f"{where}: plant_type must be grass, broadleaf or none")
        sown = c.get("sown", "none")
        if sown not in ("autumn", "spring", "none"):
            raise ContentError(f"{where}: sown must be autumn, spring or none")
        generate = bool(c.get("generate", True))
        sow = SeasonWindow.parse(c.get("sowing_window"), f"{where} sowing_window", need_basis=True)
        harv = SeasonWindow.parse(c.get("harvest_window"), f"{where} harvest_window", need_basis=True)
        if generate and sown != "none" and (sow is None or harv is None):
            raise ContentError(f"{where}: an offered crop needs sowing and harvest windows")

        root = c.get("root_zone")
        if root is not None:
            if root.get("value") not in ("0_100cm", "0_150cm"):
                raise ContentError(f"{where}: root_zone value must be 0_100cm or 0_150cm")
            root = {"value": root["value"], "basis": Basis.parse(root, f"{where} root_zone")}
        gs = c.get("growing_season")
        if gs is not None:
            if season_ids is not None and gs.get("value") not in season_ids:
                raise ContentError(f"{where}: growing_season {gs.get('value')!r} not in settings water.growing_seasons")
            gs = {"value": gs["value"], "basis": Basis.parse(gs, f"{where} growing_season")}
        ry = c.get("regional_yield")
        if ry is not None:
            ry = {"kg_ha": units.lb_ac_to_kg_ha(_num(ry, "value_lb_ac", where, 0, 20000)),
                  "basis": Basis.parse(ry, f"{where} regional_yield"), "zones": {}}
            zy = c.get("zone_yields")
            if zy is not None:  # addendum item 1: typical yields in the Transition and Grain-Fallow zones [S27]
                ry["zone_basis"] = Basis.parse(zy, f"{where} zone_yields")
                for z in ("transition", "grain_fallow"):
                    if zy.get(f"{z}_lb_ac") is not None:
                        ry["zones"][z] = units.lb_ac_to_kg_ha(_num(zy, f"{z}_lb_ac", where, 0, 20000))
                ac = zy.get("transition_after_crop")
                if ac is not None:
                    ry["after_crop_kg_ha"] = units.lb_ac_to_kg_ha(_num(ac, "value_lb_ac", where, 0, 20000))
                    ry["after_crop_basis"] = Basis.parse(ac, f"{where} zone_yields.transition_after_crop")
        yu = c.get("yield_unit")
        if yu is not None:
            yu = {"name": str(yu.get("name", "lb")), "lb_per_unit": _num(yu, "lb_per_unit", where, 0.001, 10000)}
        ph = c.get("critical_ph")
        if ph is not None:
            lo, hi = _num(ph, "low", where, 3, 9), _num(ph, "high", where, 3, 9)
            ph = {"low": lo, "high": hi, "basis": Basis.parse(ph, f"{where} critical_ph")}
        inc = c.get("income")
        if inc is not None:
            inc = {"return_usd_ac": _num(inc, "return_usd_ac", where, -2000, 2000),
                   "label": str(inc.get("label", c["name"])), "basis": Basis.parse(inc, f"{where} income")}
        crops.append(
            Crop(
                id=str(c["id"]),
                name=str(c["name"]),
                role=str(c["role"]),
                class_codes=codes,
                pool=pool,
                pool_codes=_codes(c["pool_codes"], where) if "pool_codes" in c else None,
                generate=generate,
                plant_type=plant_type,
                sown=sown,
                sowing_window=sow,
                harvest_window=harv,
                water_need=_water_need(c.get("water_need"), f"{where} water_need"),
                water_use=_water_use(c.get("water_use"), f"{where} water_use"),
                root_zone=root,
                growing_season=gs,
                regional_yield=ry,
                yield_unit=yu,
                residue=_residue(c.get("residue"), f"{where} residue"),
                nitrogen_credit=_nitrogen(c.get("nitrogen_credit"), f"{where} nitrogen_credit"),
                critical_ph=ph,
                income=inc,
                limits=tuple(c.get("limits") or ()),
                aliases=tuple(str(a) for a in (c.get("aliases") or ())),
                notes=c.get("note") or c.get("notes"),
            )
        )
    ids = [c.id for c in crops]
    if len(set(ids)) != len(ids):
        raise ContentError("crops: duplicate crop id")
    for c in crops:
        if c.generate and c.role not in ("fallow", "cover_crop") and c.sown != "none":
            missing = [k for k in ("water_need", "root_zone", "growing_season") if getattr(c, k) is None]
            if missing:
                raise ContentError(f"crop {c.id}: an offered crop needs {', '.join(missing)}")
    return crops


def parse_rules(raw: dict, section: str = "rules", kind: str = "rule") -> list[RuleConfig]:
    out = []
    for i, r in enumerate((raw or {}).get(section) or []):
        if not r.get("id"):
            raise ContentError(f"{section}[{i}]: id is required")
        if "basis" in r:
            basis, source = _check_basis(r, f"{section}[{i}] ({r['id']})")
        else:  # older files
            basis, source = ("assumed" if r.get("provisional", True) else "sourced"), r.get("source")
        out.append(
            RuleConfig(
                id=str(r["id"]),
                enabled=bool(r.get("enabled", True)),
                code=str(r.get("code", r["id"])),
                basis=basis,
                source=source,
                params=dict(r.get("params") or {}),
                kind=kind,
            )
        )
    return out


def load_legend(path: Path) -> dict[int, dict]:
    raw = json.loads(path.read_text())
    return {int(k): {"name": v["name"], "color": v["color"]} for k, v in raw["classes"].items()}


def load_content(data_dir: str | Path) -> Content:
    d = Path(data_dir)
    roles_raw = _read_yaml(d / "roles.yaml")
    roles = parse_roles(roles_raw)
    settings = Settings(_read_yaml(d / "settings.yaml"))
    seasons = set((settings.get("water.growing_seasons") or {}).keys()) or None
    crops_raw = _read_yaml(d / "crops.yaml")
    crops = parse_crops(crops_raw, {r.id for r in roles}, seasons)
    rules_raw = _read_yaml(d / "rules.yaml")
    rules = parse_rules(rules_raw, "rules", "rule")
    warnings = parse_rules(rules_raw, "warnings", "warning")
    attributions = (_read_yaml(d / "attributions.yaml") or {}).get("sources") or []
    sources = {}
    if (d / "sources.yaml").exists():
        sources = {str(s["id"]): s for s in (_read_yaml(d / "sources.yaml") or {}).get("sources") or []}
    region = _read_yaml(d / "region.yaml") or {}
    legends = {}
    if (d / "us" / "cdl_legend.json").exists():
        legends["us_cdl"] = load_legend(d / "us" / "cdl_legend.json")
    return Content(
        crops=crops,
        roles=roles,
        settings=settings,
        rules=rules,
        warnings=warnings,
        attributions=attributions,
        sources=sources,
        region=region,
        crops_provisional=bool((crops_raw or {}).get("provisional", True)),
        roles_provisional=bool((roles_raw or {}).get("provisional", True)),
        legends=legends,
        data_dir=d,
    )
