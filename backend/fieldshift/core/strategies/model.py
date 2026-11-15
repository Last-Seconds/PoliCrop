"""Strategy data model: a sequence of seasonal steps, each a crop filling a role."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..content import Content, Crop, SeasonWindow


@dataclass(frozen=True)
class Step:
    position: int  # 1-based year of the plan
    crop_id: str
    role: str
    start: dt.date
    end: dt.date
    window_provisional: bool  # True when the dates come from the default step window

    def to_dict(self, content: Content) -> dict:
        crop = content.crop(self.crop_id) if content.has_crop(self.crop_id) else None
        role = content.role(self.role) if content.has_role(self.role) else None
        return {
            "position": self.position,
            "crop_id": self.crop_id,
            "crop": crop.name if crop else self.crop_id,
            "role": self.role,
            "role_label": role.label if role else self.role,
            "role_color": role.color if role else "#999999",
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "window_provisional": self.window_provisional,
        }


@dataclass
class RuleResult:
    rule_id: str
    label: str
    passed: bool
    reason: str
    provisional: bool = True

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "label": self.label, "passed": self.passed,
                "reason": self.reason, "provisional": self.provisional}


@dataclass
class Strategy:
    id: str
    kind: str  # "existing" or "generated"
    steps: list[Step]
    distance: float = 0.0
    rule_results: list[RuleResult] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    summary: str = ""
    label: str = ""
    scores: dict = field(default_factory=dict)
    not_assessed: list[str] = field(default_factory=list)

    @property
    def crop_ids(self) -> tuple[str, ...]:
        return tuple(s.crop_id for s in self.steps)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(s.role for s in self.steps)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.rule_results)

    def to_dict(self, content: Content) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "summary": self.summary,
            "steps": [s.to_dict(content) for s in self.steps],
            "distance": round(self.distance, 2),
            "max_distance": float(len(self.steps)),
            "differences": self.differences,
            "rules": [r.to_dict() for r in self.rule_results],
            "passed_all_rules": self.passed,
            "scores": self.scores,
            "not_assessed": self.not_assessed,
        }


def _mmdd(year: int, mmdd: str) -> dt.date:
    month, day = int(mmdd[:2]), int(mmdd[3:])
    if month == 2 and day == 29:
        day = 28  # keep it valid in non-leap years
    return dt.date(year, month, day)


def step_dates(window: SeasonWindow, harvest_year: int) -> tuple[dt.date, dt.date]:
    start_year = harvest_year - 1 if window.spans_winter else harvest_year
    return _mmdd(start_year, window.start), _mmdd(harvest_year, window.end)


def make_steps(crops: list[Crop], first_harvest_year: int, default_window: SeasonWindow) -> list[Step]:
    steps = []
    for i, crop in enumerate(crops):
        window = crop.season_window or default_window
        start, end = step_dates(window, first_harvest_year + i)
        steps.append(Step(i + 1, crop.id, crop.role, start, end, crop.season_window is None))
    return steps
