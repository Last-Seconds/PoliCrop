"""Crop history: dominant crop class per year inside the field, and the existing rotation."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from .content import Content, Settings


@dataclass
class CropYear:
    year: int
    code: int | None  # classification code (None when there is no data)
    name: str
    color: str
    share: float | None  # share of classified field pixels in the dominant class
    pixels: int
    crop_id: str | None  # crop-table id, None if the class is not in the crop table
    role: str | None
    uncertain: bool
    corrected: bool = False
    detected_code: int | None = None
    detected_name: str | None = None
    source: str | None = None
    runner_up: str | None = None  # second most common class, as context for uncertain years
    runner_up_share: float | None = None

    @property
    def has_data(self) -> bool:
        return self.code is not None or self.crop_id is not None

    def to_dict(self) -> dict:
        return asdict(self)


def validate_counts(raw: dict) -> dict[int, int]:
    """Untrusted provider output -> {code: count} with non-negative integer counts."""
    counts: dict[int, int] = {}
    for k, v in ((raw or {}).get("counts") or {}).items():
        try:
            code, n = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if 0 < code < 256 and n > 0:  # 0 is "no data" in the CDL
            counts[code] = counts.get(code, 0) + n
    return counts


def summarize_year(year: int, counts: dict[int, int], content: Content, classification: str,
                   legend: dict[int, dict], source: str | None) -> CropYear:
    settings = content.settings
    total = sum(counts.values())
    if total < int(settings["crop_history.min_pixels"]):
        return CropYear(year, None, "No data", "#DDDDDD", None, total, None, None, True, source=source)
    ranked = Counter(counts).most_common()
    code, n = ranked[0]
    share = n / total
    crop = content.crop_for_code(classification, code)
    entry = legend.get(code, {})
    name = crop.name if crop else entry.get("name", f"Class {code}")
    color = entry.get("color", "#999999")
    runner = ranked[1] if len(ranked) > 1 else None
    runner_name = None
    if runner:
        rc = content.crop_for_code(classification, runner[0])
        runner_name = rc.name if rc else legend.get(runner[0], {}).get("name", f"Class {runner[0]}")
    return CropYear(
        year=year,
        code=code,
        name=name,
        color=color,
        share=round(share, 3),
        pixels=total,
        crop_id=crop.id if crop else None,
        role=crop.role if crop else None,
        uncertain=share < float(settings["crop_history.min_share_confident"]),
        detected_code=code,
        detected_name=name,
        source=source,
        runner_up=runner_name,
        runner_up_share=round(runner[1] / total, 3) if runner else None,
    )


def apply_corrections(history: list[CropYear], corrections: dict, content: Content,
                      classification: str, legend: dict[int, dict]) -> list[CropYear]:
    """Apply farmer corrections: {year: crop_id} or {year: "class:<code>"}.

    Unknown years or values are ignored rather than failing the page.
    """
    by_year = {str(k): v for k, v in (corrections or {}).items()}
    out = []
    for cy in history:
        value = by_year.get(str(cy.year))
        if value in (None, ""):
            out.append(cy)
            continue
        value = str(value)
        if content.has_crop(value):
            crop = content.crop(value)
            codes = crop.codes(classification)
            code = codes[0] if codes else None
            color = legend.get(code, {}).get("color") if code else None
            new = CropYear(
                year=cy.year, code=code, name=crop.name, color=color or content.role(crop.role).color,
                share=None, pixels=cy.pixels, crop_id=crop.id, role=crop.role, uncertain=False,
                corrected=True, detected_code=cy.detected_code, detected_name=cy.detected_name, source="farmer",
            )
        elif value.startswith("class:") and value[6:].isdigit():
            code = int(value[6:])
            crop = content.crop_for_code(classification, code)
            entry = legend.get(code, {})
            new = CropYear(
                year=cy.year, code=code, name=crop.name if crop else entry.get("name", f"Class {code}"),
                color=entry.get("color", "#999999"), share=None, pixels=cy.pixels,
                crop_id=crop.id if crop else None, role=crop.role if crop else None, uncertain=False,
                corrected=True, detected_code=cy.detected_code, detected_name=cy.detected_name, source="farmer",
            )
        else:
            out.append(cy)
            continue
        out.append(new)
    return out


@dataclass
class RotationDetection:
    period: int
    found: bool
    match_score: float | None
    years_used: list[int]
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_rotation(history: list[CropYear], settings: Settings) -> RotationDetection:
    """Find the shortest period after which the crop roles repeat in recent years.

    Compares roles (cereal, legume, ...) rather than exact crops, so that a
    wheat-legume rotation that alternates peas and lentils is still found.
    """
    window = int(settings["rotation.history_window_years"])
    pmin, pmax = int(settings["rotation.min_period"]), int(settings["rotation.max_period"])
    threshold = float(settings["rotation.period_match_threshold"])
    default = int(settings["rotation.default_plan_length"])

    recent = [cy for cy in history if cy.has_data][-window:]
    labels = [cy.role or f"class:{cy.code}" for cy in recent]
    years = [cy.year for cy in recent]
    best: tuple[int, float] | None = None
    for p in range(pmin, pmax + 1):
        pairs = [(labels[i], labels[i + p]) for i in range(len(labels) - p)]
        if len(pairs) < max(p, 3):  # need at least one full repeat and a few comparisons
            continue
        score = sum(a == b for a, b in pairs) / len(pairs)
        if score >= threshold:
            best = (p, score)
            break
    if best:
        p, score = best
        return RotationDetection(
            p, True, round(score, 2), years,
            f"In {len(recent)} recent years the crop types repeat every {p} years "
            f"({score:.0%} of years match).",
        )
    return RotationDetection(
        default, False, None, years,
        f"No regular repeating pattern was found in {len(recent)} recent years; "
        f"using the default plan length of {default} years (provisional).",
    )


def existing_rotation(history: list[CropYear], period: int) -> list[CropYear]:
    """The last `period` years with data, oldest first."""
    with_data = [cy for cy in history if cy.has_data]
    return with_data[-period:]
