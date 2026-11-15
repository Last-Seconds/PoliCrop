"""Farmer inputs (brief section 7): all optional, each with a visible default.

The field alone gives a complete result. Requests carry the inputs as one JSON
object; anything malformed is dropped with a note rather than failing the page.
Results say which values came from the farmer and which are defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import units
from ..content import Content

TILLAGE = ("no_till", "reduced", "conventional")


@dataclass
class FarmerInputs:
    corrections: dict[str, str] = field(default_factory=dict)
    priorities: list[str] | None = None
    dry_mode: bool = False
    exclude: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)
    plan_length: int | None = None
    ph: float | None = None
    tillage: str | None = None
    yields: dict[str, float] = field(default_factory=dict)  # crop id -> amount in the crop's yield unit
    rain_pct: float = 0.0
    temp_f: float = 0.0
    ignored: list[str] = field(default_factory=list)  # what was dropped as malformed

    @staticmethod
    def parse(raw: dict | None, content: Content) -> "FarmerInputs":
        raw = raw if isinstance(raw, dict) else {}
        s = content.settings
        out = FarmerInputs()
        measures = list(s["comparison.measures"])

        corr = raw.get("corrections") or {}
        if isinstance(corr, dict):
            out.corrections = {str(k): str(v) for k, v in corr.items() if str(k).isdigit()}

        pr = raw.get("priorities")
        if isinstance(pr, list):
            pr = [str(m) for m in pr if str(m) in measures]
            if pr:
                out.priorities = list(dict.fromkeys(pr + [m for m in measures if m not in pr]))
            else:
                out.ignored.append("priorities")

        out.dry_mode = bool(raw.get("dry_mode", False))
        offered = {c.id for c in content.offered_crops()}
        for key in ("exclude", "keep"):
            v = raw.get(key) or []
            if isinstance(v, list):
                ids = []
                for x in v:
                    if content.has_crop(str(x)) and content.crop(str(x)).id in offered:
                        ids.append(content.crop(str(x)).id)
                    else:
                        out.ignored.append(f"{key}:{x}")
                setattr(out, key, sorted(set(ids)))
        out.keep = [k for k in out.keep if k not in out.exclude]

        pl = raw.get("plan_length")
        if pl not in (None, ""):
            try:
                pl = int(pl)
                lo, hi = int(s["rotation.min_period"]), max(int(s["rotation.max_period"]), 2)
                out.plan_length = min(max(pl, lo), hi)
            except (TypeError, ValueError):
                out.ignored.append("plan_length")

        ph = raw.get("ph")
        if ph not in (None, ""):
            try:
                ph = float(ph)
                if 3.0 <= ph <= 10.0:
                    out.ph = round(ph, 2)
                else:
                    out.ignored.append("ph")
            except (TypeError, ValueError):
                out.ignored.append("ph")

        t = raw.get("tillage")
        if t in TILLAGE:
            out.tillage = t
        elif t not in (None, ""):
            out.ignored.append("tillage")

        ys = raw.get("yields") or {}
        if isinstance(ys, dict):
            for k, v in ys.items():
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    out.ignored.append(f"yield:{k}")
                    continue
                if content.has_crop(str(k)) and v > 0 and content.crop(str(k)).yield_unit:
                    out.yields[content.crop(str(k)).id] = v
                else:
                    out.ignored.append(f"yield:{k}")

        rlo, rhi = s["scenario.rain_pct_range"]["low"], s["scenario.rain_pct_range"]["high"]
        tlo, thi = s["scenario.temp_f_range"]["low"], s["scenario.temp_f_range"]["high"]
        try:
            out.rain_pct = min(max(float(raw.get("rain_pct") or 0), rlo), rhi)
        except (TypeError, ValueError):
            out.ignored.append("rain_pct")
        try:
            out.temp_f = min(max(float(raw.get("temp_f") or 0), tlo), thi)
        except (TypeError, ValueError):
            out.ignored.append("temp_f")
        return out

    # ---- effective values
    def effective_priorities(self, content: Content) -> list[str]:
        p = list(self.priorities or content.settings["comparison.measures"])
        if self.dry_mode:  # dry region mode puts water first
            p = ["water"] + [m for m in p if m != "water"]
        return p

    def effective_tillage(self, content: Content) -> str:
        return self.tillage or str(content.settings["residue.default_tillage"])

    def yields_kg_ha(self, content: Content) -> dict[str, float]:
        out = {}
        for cid, v in self.yields.items():
            yu = content.crop(cid).yield_unit
            out[cid] = units.lb_ac_to_kg_ha(v * yu["lb_per_unit"])
        return out

    @property
    def has_scenario(self) -> bool:
        return bool(self.rain_pct) or bool(self.temp_f)

    def to_dict(self, content: Content) -> dict:
        """Each input with its value and whether it came from the farmer or is the default."""
        default_pr = list(content.settings["comparison.measures"])

        def item(value, given, default_text):
            return {"value": value, "source": "farmer" if given else "default", "default": default_text}

        return {
            "corrections": item(self.corrections, bool(self.corrections), "the crop map, spring assumed"),
            "priorities": item(self.effective_priorities(content), self.priorities is not None or self.dry_mode,
                               default_pr),
            "dry_mode": item(self.dry_mode, self.dry_mode, False),
            "exclude": item(self.exclude, bool(self.exclude), []),
            "keep": item(self.keep, bool(self.keep), []),
            "plan_length": item(self.plan_length, self.plan_length is not None, "length of the current rotation"),
            "ph": item(self.ph, self.ph is not None, None),
            "tillage": item(self.effective_tillage(content), self.tillage is not None,
                            str(content.settings["residue.default_tillage"])),
            "yields": item(self.yields, bool(self.yields), {}),
            "rain_pct": item(self.rain_pct, bool(self.rain_pct), 0),
            "temp_f": item(self.temp_f, bool(self.temp_f), 0),
            "ignored": self.ignored,
        }
