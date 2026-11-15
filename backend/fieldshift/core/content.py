"""Load and validate the content files (crop table, roles, rules, settings, attributions).

Content is data, not code: everything the team may want to change without a
code change lives in the data directory. This module turns those files into
typed objects and fails loudly (at start-up) when a file is malformed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

AGRONOMIC_ATTRIBUTES = ("water_need_mm", "temperature_limits_c", "nitrogen_effect", "ground_cover")
_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


class ContentError(ValueError):
    """A content file is malformed."""


@dataclass(frozen=True)
class SeasonWindow:
    start: str  # "MM-DD"
    end: str  # "MM-DD"
    spans_winter: bool

    @staticmethod
    def parse(raw: Any, where: str) -> "SeasonWindow | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ContentError(f"{where}: season window must be a mapping or null")
        start, end = str(raw.get("start", "")), str(raw.get("end", ""))
        if not _MMDD.match(start) or not _MMDD.match(end):
            raise ContentError(f"{where}: season window start/end must be 'MM-DD', got {start!r}/{end!r}")
        return SeasonWindow(start, end, bool(raw.get("spans_winter", False)))

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "spans_winter": self.spans_winter}


@dataclass(frozen=True)
class Crop:
    id: str
    name: str
    role: str
    class_codes: dict[str, tuple[int, ...]]
    pool: str = "if_grown_nearby"
    season_window: SeasonWindow | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def codes(self, system: str) -> tuple[int, ...]:
        return self.class_codes.get(system, ())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "class_codes": {k: list(v) for k, v in self.class_codes.items()},
            "pool": self.pool,
            "season_window": self.season_window.to_dict() if self.season_window else None,
            **self.attributes,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    color: str
    generate: bool = True
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
            "description": self.description,
        }


@dataclass(frozen=True)
class Param:
    key: str
    value: Any
    unit: str | None
    provisional: bool
    description: str | None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
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
                self._params[key] = Param(
                    key=key,
                    value=spec["value"],
                    unit=spec.get("unit"),
                    provisional=bool(spec.get("provisional", True)),
                    description=spec.get("description"),
                )

    def __getitem__(self, key: str) -> Any:
        try:
            return self._params[key].value
        except KeyError:
            raise KeyError(f"missing setting {key!r} in settings.yaml") from None

    def get(self, key: str, default: Any = None) -> Any:
        p = self._params.get(key)
        return default if p is None else p.value

    def param(self, key: str) -> Param:
        return self._params[key]

    def params(self) -> list[Param]:
        return list(self._params.values())

    def with_overrides(self, overrides: dict[str, Any]) -> "Settings":
        clone = Settings({})
        clone._params = dict(self._params)
        for key, value in overrides.items():
            old = clone._params.get(key)
            clone._params[key] = Param(key, value, old.unit if old else None, True, old.description if old else None)
        return clone


@dataclass(frozen=True)
class RuleConfig:
    id: str
    enabled: bool
    provisional: bool
    params: dict[str, Any]


@dataclass
class Content:
    crops: list[Crop]
    roles: list[Role]
    settings: Settings
    rules: list[RuleConfig]
    attributions: list[dict]
    region: dict
    crops_provisional: bool = True
    roles_provisional: bool = True
    legends: dict[str, dict[int, dict]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._crop_by_id = {c.id: c for c in self.crops}
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


def parse_crops(raw: dict, role_ids: set[str]) -> list[Crop]:
    crops: list[Crop] = []
    seen_codes: dict[tuple[str, int], str] = {}
    for i, c in enumerate((raw or {}).get("crops") or []):
        where = f"crops[{i}] ({c.get('id', '?')})"
        if not c.get("id") or not c.get("name") or not c.get("role"):
            raise ContentError(f"{where}: id, name and role are required")
        if c["role"] not in role_ids:
            raise ContentError(f"{where}: unknown role {c['role']!r}")
        codes_raw = c.get("class_codes") or {}
        if not isinstance(codes_raw, dict):
            raise ContentError(f"{where}: class_codes must be a mapping of system -> list of codes")
        codes: dict[str, tuple[int, ...]] = {}
        for system, lst in codes_raw.items():
            try:
                codes[system] = tuple(int(x) for x in (lst or []))
            except (TypeError, ValueError):
                raise ContentError(f"{where}: class codes for {system!r} must be integers") from None
            for code in codes[system]:
                if (system, code) in seen_codes:
                    raise ContentError(f"{where}: {system} code {code} already used by {seen_codes[(system, code)]}")
                seen_codes[(system, code)] = c["id"]
        pool = c.get("pool", "if_grown_nearby")
        if pool not in ("if_grown_nearby", "always"):
            raise ContentError(f"{where}: pool must be 'if_grown_nearby' or 'always'")
        crops.append(
            Crop(
                id=str(c["id"]),
                name=str(c["name"]),
                role=str(c["role"]),
                class_codes=codes,
                pool=pool,
                season_window=SeasonWindow.parse(c.get("season_window"), where),
                attributes={a: c.get(a) for a in AGRONOMIC_ATTRIBUTES},
                notes=c.get("notes"),
            )
        )
    ids = [c.id for c in crops]
    if len(set(ids)) != len(ids):
        raise ContentError("crops: duplicate crop id")
    return crops


def parse_rules(raw: dict) -> list[RuleConfig]:
    out = []
    for i, r in enumerate((raw or {}).get("rules") or []):
        if not r.get("id"):
            raise ContentError(f"rules[{i}]: id is required")
        out.append(
            RuleConfig(
                id=str(r["id"]),
                enabled=bool(r.get("enabled", True)),
                provisional=bool(r.get("provisional", True)),
                params=dict(r.get("params") or {}),
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
    crops_raw = _read_yaml(d / "crops.yaml")
    crops = parse_crops(crops_raw, {r.id for r in roles})
    settings = Settings(_read_yaml(d / "settings.yaml"))
    rules = parse_rules(_read_yaml(d / "rules.yaml"))
    attributions = (_read_yaml(d / "attributions.yaml") or {}).get("sources") or []
    region = _read_yaml(d / "region.yaml") or {}
    legends = {}
    if (d / "us" / "cdl_legend.json").exists():
        legends["us_cdl"] = load_legend(d / "us" / "cdl_legend.json")
    return Content(
        crops=crops,
        roles=roles,
        settings=settings,
        rules=rules,
        attributions=attributions,
        region=region,
        crops_provisional=bool((crops_raw or {}).get("provisional", True)),
        roles_provisional=bool((roles_raw or {}).get("provisional", True)),
        legends=legends,
    )
