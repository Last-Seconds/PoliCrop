"""Strategy data model: one slot per crop year, each slot a crop filling a role.

A crop year y runs from 1 September of y−1 to 31 August of y and is labelled by
its harvest year. Inside its slot each crop carries its real usual sowing and
harvest dates, so periods with nothing growing are visible. Fallow and cover
crop slots run from the previous crop's harvest to the next crop's sowing.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from ..content import Content, Crop, SeasonWindow

NON_HARVEST_ROLES = ("fallow", "cover_crop")


@dataclass(frozen=True)
class Step:
    position: int  # 1-based year of the plan
    crop_id: str
    role: str
    harvest_year: int
    start: dt.date  # sowing (start of usual window); for fallow: day after the previous harvest
    end: dt.date  # harvest (end of usual window); for fallow: day before the next sowing
    sow_window: tuple[dt.date, dt.date] | None = None
    harvest_window: tuple[dt.date, dt.date] | None = None
    dates_assumed: bool = False  # any date in this step rests on an assumed value
    window_default: bool = False  # True when the dates are the default whole crop year

    @property
    def harvested(self) -> bool:
        return self.role not in NON_HARVEST_ROLES

    def to_dict(self, content: Content) -> dict:
        crop = content.crop(self.crop_id) if content.has_crop(self.crop_id) else None
        role = content.role(self.role) if content.has_role(self.role) else None
        return {
            "position": self.position,
            "crop_id": self.crop_id,
            "crop": crop.name if crop else self.crop_id,
            "role": self.role,
            "role_label": role.label if role else "Other",
            "role_color": role.color if role else "#999999",
            "harvest_year": self.harvest_year,
            "slot_start": dt.date(self.harvest_year - 1, 9, 1).isoformat(),
            "slot_end": dt.date(self.harvest_year, 8, 31).isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "sow_window": [d.isoformat() for d in self.sow_window] if self.sow_window else None,
            "harvest_window": [d.isoformat() for d in self.harvest_window] if self.harvest_window else None,
            "harvested": self.harvested,
            "dates_assumed": self.dates_assumed,
            "window_default": self.window_default,
        }


@dataclass
class RuleResult:
    rule_id: str
    label: str
    passed: bool
    reason: str
    provisional: bool = True
    code: str = ""

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "code": self.code, "label": self.label, "passed": self.passed,
                "reason": self.reason, "assumed": self.provisional}


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
    scores: dict = field(default_factory=dict)  # measure id -> Quantity
    not_assessed: list[str] = field(default_factory=list)
    warnings: list = field(default_factory=list)  # list[Warning]
    extra: dict = field(default_factory=dict)

    @property
    def crop_ids(self) -> tuple[str, ...]:
        return tuple(s.crop_id for s in self.steps)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(s.role for s in self.steps)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.rule_results)

    @property
    def harvests(self) -> int:
        return sum(1 for s in self.steps if s.harvested)

    def to_dict(self, content: Content) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "summary": self.summary,
            "steps": [s.to_dict(content) for s in self.steps],
            "distance": round(self.distance, 2),
            "max_distance": float(len(self.steps)),
            "harvests": self.harvests,
            "differences": self.differences,
            "rules": [r.to_dict() for r in self.rule_results],
            "passed_all_rules": self.passed,
        }

    def years_changed(self, other: "Strategy") -> int:
        return sum(1 for a, b in zip(self.steps, other.steps) if a.crop_id != b.crop_id)


def _mmdd(year: int, mmdd: str) -> dt.date:
    month, day = int(mmdd[:2]), int(mmdd[3:])
    if month == 2 and day == 29:
        day = 28  # keep it valid in non-leap years
    return dt.date(year, month, day)


def sow_year(crop: Crop, harvest_year: int, mmdd: str) -> int:
    """Autumn-sown crops are sown in the calendar year before their harvest."""
    return harvest_year - 1 if crop.sown == "autumn" else harvest_year


def crop_dates(crop: Crop, harvest_year: int) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]] | None:
    """(sowing window, harvest window) as real dates for a harvest year; None for no-season crops."""
    if crop.sowing_window is None or crop.harvest_window is None or crop.sown == "none":
        return None
    sw, hw = crop.sowing_window, crop.harvest_window
    sy = sow_year(crop, harvest_year, sw.start)
    sow = (_mmdd(sy, sw.start), _mmdd(sy, sw.end))
    harv = (_mmdd(harvest_year, hw.start), _mmdd(harvest_year, hw.end))
    return sow, harv


def _dates_assumed(crop: Crop) -> bool:
    return any(w is not None and w.basis is not None and w.basis.assumed
               for w in (crop.sowing_window, crop.harvest_window))


def make_steps(crops: list[Crop], first_harvest_year: int, default_window: SeasonWindow) -> list[Step]:
    n = len(crops)
    years = [first_harvest_year + i for i in range(n)]
    dates = [crop_dates(c, y) for c, y in zip(crops, years)]
    steps: list[Step] = []
    for i, (crop, y, d) in enumerate(zip(crops, years, dates)):
        if d is not None:
            (s0, s1), (h0, h1) = d
            steps.append(Step(i + 1, crop.id, crop.role, y, s0, h1, (s0, s1), (h0, h1), _dates_assumed(crop)))
            continue
        if crop.role in NON_HARVEST_ROLES:
            # From the day after the previous harvest to the day before the next sowing.
            prev_i, next_i = (i - 1) % n, (i + 1) % n
            prev = dates[prev_i]
            nxt = dates[next_i]
            if prev is not None and n > 1:
                prev_end = prev[1][1]
                if prev_i > i:  # wrapped: the previous slot belongs to the cycle before
                    prev_end = prev_end.replace(year=prev_end.year - n)
                start = prev_end + dt.timedelta(days=1)
            else:
                start = dt.date(y - 1, 9, 1)
            if nxt is not None and n > 1:
                nxt_start = nxt[0][0]
                if next_i < i:  # wrapped: the next slot belongs to the next cycle
                    nxt_start = nxt_start.replace(year=nxt_start.year + n)
                end = nxt_start - dt.timedelta(days=1)
            else:
                end = dt.date(y, 8, 31)
            steps.append(Step(i + 1, crop.id, crop.role, y, start, end))
            continue
        # History-only class with no season: the whole crop year.
        start = _mmdd(y - 1 if default_window.spans_winter else y, default_window.start)
        steps.append(Step(i + 1, crop.id, crop.role, y, start, _mmdd(y, default_window.end), window_default=True))
    return steps


def kind_of(role: str) -> str:
    """The water-budget kind of a slot: what the following crop inherits."""
    if role == "fallow":
        return "fallow"
    if role == "cover_crop":
        return "cover"
    return "harvested"
