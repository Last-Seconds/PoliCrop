"""Field report service: asks providers for data, runs the core analyses, attaches caveats.

Framework-independent: the web layer calls these methods, tests call them with
fake providers. Each report section is built independently so a failing data
source degrades one section instead of breaking the page.
"""
from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape

from . import climate as climate_mod
from . import history as history_mod
from . import vegetation as vegetation_mod
from .content import Content
from .geometry import FieldError, FieldGeometry, buffer_geojson, check_field, field_from_spec
from .ports import CropHistoryProvider, RegionProvider, VegetationProvider, WeatherProvider
from .strategies.generate import build_pool, generate, pseudo_crop
from .strategies.rules import build_rules
from .strategies.scoring import SCORER_REGISTRY

log = logging.getLogger(__name__)


def caveat(cid: str, text: str, applies_to: list[str] | str) -> dict:
    return {"id": cid, "text": text, "applies_to": [applies_to] if isinstance(applies_to, str) else applies_to}


@dataclass
class Providers:
    region: RegionProvider
    crops: CropHistoryProvider
    weather: WeatherProvider
    vegetation: VegetationProvider
    overlay: Any = None  # optional MapOverlayProvider


@dataclass
class FieldService:
    content: Content
    providers: Providers
    today: dt.date = field(default_factory=dt.date.today)
    max_workers: int = 6

    def __post_init__(self) -> None:
        self.rules = build_rules(self.content.rules)
        self.scorers = [factory() for factory in SCORER_REGISTRY.values()]
        self._region_cache: dict | None = None

    # ---- region and field -------------------------------------------------
    def region(self) -> dict:
        if self._region_cache is None:
            raw = self.providers.region.region()
            geom = shape(raw["geometry"])
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            self._region_cache = {**raw, "_shape": geom}
        return self._region_cache

    def make_field(self, spec: dict) -> FieldGeometry:
        f = field_from_spec(spec)
        r = self.region()
        s = self.content.settings
        check_field(f, r["_shape"], r["name"], float(s["field.min_area_ha"]), float(s["field.max_area_ha"]))
        return f

    def field_summary(self, f: FieldGeometry) -> dict:
        lon, lat = f.centroid()
        return {"field_id": f.key(), "area_ha": round(f.area_ha(), 1), "centroid": [round(lon, 5), round(lat, 5)],
                "geometry": f.geojson(), "type": f.kind}

    # ---- crop history ------------------------------------------------------
    def _raw_history(self, f: FieldGeometry) -> tuple[list[history_mod.CropYear], list[dict]]:
        prov = self.providers.crops
        legend = self._legend()
        years = prov.available_years()
        geom = f.geojson()

        def one(year: int):
            try:
                raw = prov.class_counts(geom, year)
                return year, history_mod.validate_counts(raw), raw.get("source"), None
            except Exception as exc:  # one failed year must not break the page
                log.warning("crop history %s failed: %s", year, exc)
                return year, {}, None, str(exc)

        with ThreadPoolExecutor(self.max_workers) as ex:
            results = list(ex.map(one, years))
        out, failures = [], []
        for year, counts, source, err in results:
            cy = history_mod.summarize_year(year, counts, self.content, prov.classification, legend, source)
            if err:
                cy.name = "Data unavailable"
                failures.append({"year": year, "error": err})
            out.append(cy)
        return out, failures

    def _legend(self) -> dict[int, dict]:
        legend = dict(self.content.legend(self.providers.crops.classification))
        try:
            for k, v in (self.providers.crops.legend() or {}).items():
                legend.setdefault(int(k), v)
        except Exception:
            pass
        return legend

    def history(self, f: FieldGeometry, corrections: dict | None = None) -> dict:
        s = self.content.settings
        hist, failures = self._raw_history(f)
        prov = self.providers.crops
        hist = history_mod.apply_corrections(hist, corrections or {}, self.content, prov.classification, self._legend())
        detection = history_mod.detect_rotation(hist, s)
        rotation = history_mod.existing_rotation(hist, detection.period)
        years_with_data = [cy.year for cy in hist if cy.has_data]
        thr = float(s["crop_history.min_share_confident"])
        caveats = [
            caveat("cdl_classification",
                   "The crop for each year comes from a satellite-based classification (USDA Cropland Data Layer), "
                   "which has errors, especially for similar crops such as wheat types or peas and lentils. "
                   "That is why you can correct it.", "history"),
            caveat("cdl_label_year",
                   "Each year is labelled by the harvest year: winter wheat sown in autumn 2023 and harvested "
                   "in 2024 is shown as 2024.", "history"),
            caveat("cdl_resolution",
                   "The map has 30 m pixels; along field edges pixels can mix with neighbouring fields or roads, "
                   "so small or narrow fields are less reliable.", "history"),
        ]
        uncertain = [cy.year for cy in hist if cy.has_data and cy.uncertain and not cy.corrected]
        if uncertain:
            caveats.append(caveat(
                "uncertain_years",
                f"In {', '.join(map(str, uncertain))} the main crop covers less than {thr:.0%} of the field "
                "(provisional threshold), so the label is uncertain: the field may have been split, or the "
                "classification mixed.", [f"history:{y}" for y in uncertain]))
        if any(cy.code == 42 for cy in hist) and prov.classification == "us_cdl":
            caveats.append(caveat(
                "dry_beans", "\"Dry beans\" in older years may be chickpeas: the crop map shows chickpeas "
                "separately only in later years.", [f"history:{cy.year}" for cy in hist if cy.code == 42]))
        if failures:
            caveats.append(caveat("history_failures",
                                  f"Crop data could not be loaded for {', '.join(str(x['year']) for x in failures)}.",
                                  [f"history:{x['year']}" for x in failures]))
        return {
            "status": "partial" if failures else "ok",
            "years": [cy.to_dict() for cy in hist],
            "years_with_data": years_with_data,
            "rotation": {**detection.to_dict(), "years": [cy.year for cy in rotation],
                         "crops": [cy.name for cy in rotation]},
            "correction_options": self._correction_options(),
            "caveats": caveats,
            "provisional": ["crop_history.min_share_confident", "rotation.period_match_threshold",
                            "rotation.default_plan_length"],
            "failures": failures,
        }

    def _correction_options(self) -> list[dict]:
        cls = self.providers.crops.classification
        legend = self._legend()
        opts = []
        for c in self.content.crops:
            codes = c.codes(cls)
            color = legend.get(codes[0], {}).get("color") if codes else None
            opts.append({"value": c.id, "label": c.name, "role": c.role,
                         "color": color or self.content.role(c.role).color})
        table_codes = {code for c in self.content.crops for code in c.codes(cls)}
        for code in (176, 152, 37, 121, 122, 141, 142, 111, 195, 190):  # common non-crop classes here
            if code in legend and code not in table_codes:
                opts.append({"value": f"class:{code}", "label": legend[code]["name"], "role": None,
                             "color": legend[code]["color"]})
        return opts

    # ---- climate -----------------------------------------------------------
    def climate(self, f: FieldGeometry) -> dict:
        lon, lat = f.centroid()
        raw = self.providers.weather.daily(lon, lat)
        summary = climate_mod.climate_summary(raw, self.content.settings)
        res = raw.get("spatial_resolution", "a coarse regional grid")
        regional = caveat(
            "regional_weather",
            f"Regional value: NASA POWER weather is an average over a grid cell of {res}, not a measurement "
            "on your field. Rain and frost on your slopes can differ.",
            ["rainfall_monthly", "rainfall_yearly", "temperature_monthly", "frost_days"])
        return {
            "status": "ok",
            **summary,
            "source": raw.get("source"),
            "grid_cell": raw.get("grid_cell"),
            "caveats": [
                regional,
                caveat("historical_only", "Historical record only: no trend line and no forecast.",
                       ["rainfall_yearly", "frost_days"]),
                caveat("incomplete_years",
                       "Years with missing days (including the current, unfinished year) are left out of totals "
                       "rather than estimated.", ["rainfall_yearly", "frost_days"]),
            ],
            "provisional": ["climate.crop_year_start_month"],
        }

    # ---- vegetation ----------------------------------------------------------
    def vegetation_years(self) -> list[int]:
        n = int(self.content.settings["vegetation.years"])
        years = [y for y in self.providers.vegetation.available_years() if y <= self.today.year]
        return years[-n:]

    def vegetation_year(self, f: FieldGeometry, year: int) -> dict:
        raw = self.providers.vegetation.ndvi_year(f.geojson(), year)
        obs = raw.get("observations") or []
        return {"year": year, "images": len(obs), "scenes_failed": raw.get("scenes_failed", 0)}

    def vegetation(self, f: FieldGeometry) -> dict:
        s = self.content.settings
        years = self.vegetation_years()
        raws, failures = [], []
        for y in years:
            try:
                raws.append(self.providers.vegetation.ndvi_year(f.geojson(), y))
            except Exception as exc:
                log.warning("vegetation %s failed: %s", y, exc)
                failures.append({"year": y, "error": str(exc)})
        start = dt.date(years[0], 1, 1) if years else self.today
        end = min(self.today, dt.date(years[-1], 12, 31)) if years else self.today
        summary = vegetation_mod.vegetation_summary(raws, s, start, end)
        caveats = [
            caveat("ndvi_meaning",
                   "NDVI measures how green the field looks from space (0 = bare soil, about 0.8 = dense green "
                   "crop). It cannot tell crops from weeds or stubble regrowth.", "vegetation"),
            caveat("bare_threshold",
                   f"'Bare' means NDVI below {float(s['vegetation.bare_ndvi_threshold'])} "
                   f"(provisional threshold) in at least {int(s['vegetation.min_bare_observations'])} images in a row. "
                   "Mature, dry crops before harvest can also look bare.", "vegetation:bare"),
            caveat("ndvi_gaps",
                   "Gaps are periods without a usable cloud- and snow-free image (common in Palouse winters). "
                   "They are left empty, not filled in.", "vegetation:gaps"),
        ]
        if failures:
            caveats.append(caveat("ndvi_failures",
                                  f"Imagery could not be loaded for {', '.join(str(x['year']) for x in failures)}.",
                                  "vegetation"))
        failed_scenes = sum(int(r.get("scenes_failed") or 0) for r in raws)
        if failed_scenes:
            caveats.append(caveat("ndvi_scene_failures",
                                  f"{failed_scenes} images could not be read and are missing from the series.",
                                  "vegetation"))
        return {
            "status": "partial" if failures else "ok",
            **summary,
            "years": years,
            "threshold": float(s["vegetation.bare_ndvi_threshold"]),
            "caveats": caveats,
            "provisional": ["vegetation.bare_ndvi_threshold", "vegetation.min_bare_observations",
                            "vegetation.max_gap_days", "vegetation.min_valid_fraction"],
            "failures": failures,
        }

    # ---- strategies ------------------------------------------------------------
    def crop_pool(self, f: FieldGeometry):
        s = self.content.settings
        prov = self.providers.crops
        radius_km = float(s["crop_pool.radius_km"])
        n_years = int(s["crop_pool.years"])
        years = prov.available_years()[-n_years:]
        area = buffer_geojson(f, radius_km * 1000)
        totals: dict[int, int] = {}
        used = []
        for y in years:
            try:
                counts = history_mod.validate_counts(prov.class_counts(area, y))
            except Exception as exc:
                log.warning("crop pool %s failed: %s", y, exc)
                continue
            used.append(y)
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
        if not used:
            raise RuntimeError("The crop-type map for the surrounding area could not be loaded.")
        return build_pool(totals, self.content, prov.classification, used, radius_km)

    def strategies(self, f: FieldGeometry, corrections: dict | None = None, plan_length: int | None = None,
                   alternatives: int | None = None, history: dict | None = None) -> dict:
        s = self.content.settings
        hist_section = history or self.history(f, corrections)
        hist = [history_mod.CropYear(**y) for y in hist_section["years"]]
        detection = hist_section["rotation"]
        period = int(detection["period"])
        pmin, pmax = 2, max(int(s["rotation.max_period"]), period)
        n = period if plan_length is None else max(pmin, min(int(plan_length), pmax))
        rotation = history_mod.existing_rotation(hist, period)
        if len(rotation) < 2:
            raise RuntimeError("Not enough crop history on this field to describe a rotation.")
        rot_crops = [self.content.crop(cy.crop_id) if cy.crop_id and self.content.has_crop(cy.crop_id)
                     else pseudo_crop(cy.code, cy.name) for cy in rotation]
        # The plan starts with the first crop year that has not begun yet; the
        # existing rotation is assumed to continue through years the crop map
        # does not cover yet, so its phase is carried forward.
        last_year = max(cy.year for cy in rotation)
        start_month = int(s["climate.crop_year_start_month"])
        first_year = max(last_year + 1, climate_mod.crop_year_of(self.today, start_month) + 1)
        shift = (first_year - rotation[0].year) % len(rot_crops)
        phased = rot_crops[shift:] + rot_crops[:shift]
        existing = [phased[i % len(phased)] for i in range(n)]
        pool = self.crop_pool(f)
        assumed_years = list(range(last_year + 1, first_year))
        result = generate(existing, pool, self.content, self.rules, self.scorers, first_year,
                          alternatives, context={"field": f})
        unknown = [c.name for c in existing if c.role == "unknown"]
        caveats = [
            caveat("not_ranked", "Strategies are not ranked and none is labelled best: no scoring exists yet. "
                   "The distance value only says how much would change.", "strategies"),
            caveat("provisional_content", "The crop table, crop roles and the two filter rules are provisional "
                   "placeholders, so alternatives may include combinations an agronomist would rule out.",
                   "strategies"),
            caveat("default_dates", "Crop season dates are not filled in yet, so each step is shown as one "
                   "crop year (1 Sep – 31 Aug, provisional).", "strategies:dates"),
            caveat("crop_pool", f"Only crops seen within {float(s['crop_pool.radius_km']):g} km in the crop-type map "
                   "(plus a generic cover crop) are offered.", "strategies:pool"),
        ]
        if unknown:
            caveats.append(caveat("unknown_classes", f"Your detected rotation includes {', '.join(sorted(set(unknown)))}, "
                                  "which is not in the crop table. Correct the crop history if this is wrong.",
                                  "strategies:existing"))
        if assumed_years:
            caveats.append(caveat("assumed_years", f"The crop map does not cover {', '.join(map(str, assumed_years))} yet; "
                                  "the plan assumes your rotation continued unchanged through those years and starts "
                                  f"with the crop year harvested in {first_year}.", "strategies:existing"))
        if n != period:
            caveats.append(caveat("plan_length", f"Plan length is {n} years but the detected rotation is {period} "
                                  "years; the existing rotation is repeated to fill the plan.", "strategies:existing"))
        return {
            "status": "ok",
            "plan_length": n,
            "detected_period": period,
            "first_harvest_year": first_year,
            "based_on_years": [cy.year for cy in rotation],
            "assumed_years": assumed_years,
            "existing": result.existing.to_dict(self.content),
            "alternatives": [a.to_dict(self.content) for a in result.alternatives],
            "generation": result.stats,
            "pool": {
                "description": pool.description,
                "crops": [{"id": c.id, "name": c.name, "role": c.role, "share": pool.shares.get(c.id)}
                          for c in pool.crops],
                "years": pool.years,
            },
            "check_locally": s["assessment.check_locally"],
            "caveats": caveats,
            "provisional": ["generation.default_step_window", "generation.distance_weights",
                            "crop_pool.radius_km", "crop_pool.min_share", "assessment.criteria"],
        }

    # ---- configuration for the UI -------------------------------------------------
    def config(self) -> dict:
        r = self.region()
        return {
            "region": {"id": r.get("id"), "name": r.get("name"), "geometry": r.get("geometry"),
                       "source": r.get("source")},
            "roles": [x.to_dict() for x in self.content.roles],
            "roles_provisional": self.content.roles_provisional,
            "crops": [c.to_dict() for c in self.content.crops],
            "crops_provisional": self.content.crops_provisional,
            "rules": [{"id": x.id, "label": x.label, "provisional": x.provisional} for x in self.rules],
            "settings": [p.to_dict() for p in self.content.settings.params()],
            "attributions": self.content.attributions,
        }


__all__ = ["FieldService", "Providers", "FieldError", "caveat"]
