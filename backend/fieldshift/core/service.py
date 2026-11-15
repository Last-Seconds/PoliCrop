"""Field report service: asks providers for data, runs the core analyses, attaches caveats.

Framework-independent: the web layer calls these methods, tests call them with
fake providers. Each report section is built independently so a failing data
source degrades one section instead of breaking the page.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape

from . import climate as climate_mod
from . import soil as soil_mod
from . import drought as drought_mod
from .nearby import NearbyUse, code_roles
from .station import station_check
from . import terrain as terrain_mod
from . import greenness as greenness_mod
from . import soil_moisture as sm_mod
from . import history as history_mod
from . import vegetation as vegetation_mod
from .content import Content
from .geometry import FieldError, FieldGeometry, buffer_geojson, check_field, field_from_spec
from .ports import CropHistoryProvider, RegionProvider, SoilProvider, VegetationProvider, WeatherProvider
from .strategies.generate import build_pool, pseudo_crop
from .strategies.inputs import FarmerInputs
from .strategies.plan import run_plan
from .strategies.rules import build_rules
from .strategies.warnings import check_configs
from .present import QUESTIONS, present
from .strategies.measures import MEASURE_LABELS, TILLAGE_LABELS
from .weather import DailySeries
from . import units


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
    soil: SoilProvider | None = None
    drought: Any = None  # optional: weekly county drought statistics
    stations: Any = None  # optional: weather station records
    long_vegetation: Any = None  # optional: long vegetation-index history (MODIS)
    terrain: Any = None  # optional: elevation for slope
    sequences: Any = None  # optional: crop-map sequence histogram around a field
    boundaries: Any = None  # optional FieldBoundaryProvider: tap a field to pick it
    soil_moisture: Any = None  # optional: weekly satellite topsoil moisture grids


@dataclass
class FieldService:
    content: Content
    providers: Providers
    today: dt.date = field(default_factory=dt.date.today)
    max_workers: int = 6

    def __post_init__(self) -> None:
        self.rules = build_rules(self.content.rules)
        check_configs(self.content.warnings)

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

    def pick_field(self, lon: float, lat: float) -> dict:
        """The field outline at a tapped point, for the farmer to confirm (stage 5)."""
        if self.providers.boundaries is None:
            raise FieldError("Picking a field by tapping is not available here; please draw it.")
        try:
            lon, lat = float(lon), float(lat)
        except (TypeError, ValueError):
            raise FieldError("Bad map position.") from None
        r = self.region()
        if not r["_shape"].contains(shape({"type": "Point", "coordinates": [lon, lat]})):
            raise FieldError(f"That spot is outside {r['name']}.")
        st = self.content.settings
        try:
            feat = self.providers.boundaries.pick(
                lon, lat, years=int(st["field_pick.years"]), max_mismatch=int(st["field_pick.max_mismatch"]),
                inset_m=float(st["field_pick.inset_m"]), simplify_m=float(st["field_pick.simplify_m"]),
                max_window_px=int(st["field_pick.max_window_px"]))
        except ValueError as exc:
            raise FieldError(str(exc)) from None
        f = self.make_field({"type": "polygon", "geometry": feat["geometry"]})  # validates size and region
        legend = self._legend()
        props = feat.get("properties") or {}
        seq = [{"year": y, "name": (self.content.crop_for_code(self.providers.crops.classification, c).name
                                    if self.content.crop_for_code(self.providers.crops.classification, c)
                                    else legend.get(c, {}).get("name", f"Class {c}"))}
               for y, c in zip(props.get("years", []), props.get("sequence", []))]
        return {"geometry": f.geojson(), "acres": round(units.ha_to_acres(f.area_ha())), "sequence": seq,
                "note": "Traced from the USDA crop map: the connected area whose crops matched this spot's, year "
                        "by year. Check it follows your field's edges; if not, draw the field instead.",
                "touches_window_edge": props.get("touches_window_edge", False)}

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
        """Rain and heat evidence, in US units (the display edge)."""
        lon, lat = f.centroid()
        raw = self.providers.weather.daily(lon, lat)
        sm = climate_mod.climate_summary(raw, self.content.settings)
        st = self.content.settings
        mm = lambda v: None if v is None else round(units.mm_to_in(v), 2)
        degf = lambda v: None if v is None else round(units.c_to_f(v), 1)
        months = [{"month": m["month"], "mean_in": mm(m["mean_mm"]), "min_in": mm(m["min_mm"]),
                   "max_in": mm(m["max_mm"]), "min_year": m.get("min_year"), "max_year": m.get("max_year"),
                   "years": m["years"]} for m in sm["rainfall_monthly"]["months"]]
        yearly = [{"year": y["year"], "label": y["label"], "total_in": mm(y["total_mm"])}
                  for y in sm["rainfall_yearly"]["years"] if y["complete"]]
        temps = [{"month": m["month"], "high_f": degf(m["mean_tmax_c"]), "low_f": degf(m["mean_tmin_c"])}
                 for m in sm["temperature_monthly"]["months"]]
        gs = sm["growing_season"]
        periods = [{"first": p["first"], "last": p["last"], "apr_jul_in": mm(p["apr_jul_mm"]),
                    "hot_days": p["hot_days"], "crop_year_in": mm(p["crop_year_mm"]),
                    "years": p["rain_years"]} for p in gs["periods"]]
        per_year = [{"year": r["year"], "apr_jul_in": mm(r["apr_jul_mm"]), "hot_days": r["hot_days"]}
                    for r in gs["per_year"]]
        totals = [y["total_in"] for y in yearly if y["year"] >= int(st["water.replay_first_year"])]
        res = raw.get("spatial_resolution", "a grid")
        return {
            "status": "ok",
            "record": sm["record"],
            "monthly": months,
            "monthly_years": [sm["rainfall_monthly"]["first_year"], sm["rainfall_monthly"]["last_year"]],
            "yearly": yearly,
            "mean_crop_year_in": round(sum(totals) / len(totals), 1) if totals else None,
            "temperature": temps,
            "frost_days": [{"year": y["year"], "label": y["label"], "days": y["frost_days"]}
                           for y in sm["frost_days"]["years"] if y["complete"]],
            "periods": periods,
            "per_year": per_year,
            "hot_threshold_f": float(st["climate.hot_day_threshold_f"]),
            "highlight_year": int(st["water.highlight_year"]),
            "source": raw.get("source"),
            "grid_cell": raw.get("grid_cell"),
            "caveats": [
                caveat("regional_weather",
                       f"Weather is a {res} grid estimate (Daymet), built from nearby weather stations, not a "
                       "measurement on your field. Rain and frost on your slopes can differ.", "climate"),
                caveat("incomplete_years", "Daymet is released once a year, so the current, unfinished year is "
                       "left out.", "climate"),
            ],
        }

    # ---- soil ----------------------------------------------------------------
    def field_soil(self, f: FieldGeometry) -> soil_mod.FieldSoil:
        """Soil facts for the field; the stated default storage if the soil source fails."""
        if self.providers.soil is None:
            return soil_mod.default_soil(self.content.settings, "No soil source is configured for this region.")
        try:
            raw = self.providers.soil.soil(f.geojson())
        except Exception as exc:
            log.warning("soil failed: %s", exc)
            return soil_mod.default_soil(self.content.settings, f"The soil database could not be reached ({exc}).")
        return soil_mod.field_soil(raw, self.content.settings)

    def soil(self, f: FieldGeometry) -> dict:
        fs = self.field_soil(f)
        return {"status": "partial" if fs.capacity_default or fs.attributes_missing else "ok",
                **fs.to_dict(self.content.settings)}

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

    def weather_series(self, f: FieldGeometry) -> DailySeries:
        lon, lat = f.centroid()
        return DailySeries.from_raw(self.providers.weather.daily(lon, lat))

    def strategies(self, f: FieldGeometry, inputs: dict | FarmerInputs | None = None,
                   history: dict | None = None) -> dict:
        """The farmer's screen: the current rotation beside the chosen options (brief 6.6, 9)."""
        s = self.content.settings
        inp = inputs if isinstance(inputs, FarmerInputs) else FarmerInputs.parse(inputs, self.content)
        hist_section = history or self.history(f, inp.corrections)
        hist = [history_mod.CropYear(**y) for y in hist_section["years"]]
        detection = hist_section["rotation"]
        period = int(detection["period"])
        n = period if inp.plan_length is None else inp.plan_length
        rotation = history_mod.existing_rotation(hist, period)
        if len(rotation) < 2:
            raise RuntimeError("Not enough crop history on this field to describe a rotation.")
        rot_crops = [self.content.crop(cy.crop_id) if cy.crop_id and self.content.has_crop(cy.crop_id)
                     else pseudo_crop(cy.code, cy.name) for cy in rotation]
        # The plan starts with the first crop year that has not begun yet; the
        # current rotation is assumed to continue through years the crop map
        # does not cover yet, so its phase is carried forward.
        last_year = max(cy.year for cy in rotation)
        start_month = int(s["climate.crop_year_start_month"])
        first_year = max(last_year + 1, climate_mod.crop_year_of(self.today, start_month) + 1)
        shift = (first_year - rotation[0].year) % len(rot_crops)
        phased = rot_crops[shift:] + rot_crops[:shift]
        existing = [phased[i % len(phased)] for i in range(n)]
        pool = self.crop_pool(f)
        series = self.weather_series(f)
        soil = self.field_soil(f)
        nearby = self.nearby_use(f)
        result = run_plan(self.content, existing, phased, pool, self.rules, series, soil, inp, first_year, nearby)
        assumed_years = list(range(last_year + 1, first_year))
        caveats = []
        unknown = [c.name for c in existing if c.role == "unknown"]
        if unknown:
            caveats.append(caveat("unknown_classes", f"Your rotation as mapped includes {', '.join(sorted(set(unknown)))}, "
                                  "which this tool has no figures for. Correct the crop history if this is wrong.",
                                  "strategies:existing"))
        if assumed_years:
            caveats.append(caveat("assumed_years", f"The crop map does not cover {', '.join(map(str, assumed_years))} "
                                  "yet; the plan assumes your rotation continued unchanged and starts with the crop "
                                  f"year harvested in {first_year}.", "strategies:existing"))
        if n != period:
            caveats.append(caveat("plan_length", f"Plan length is {n} years but your rotation repeats every {period} "
                                  "years; your rotation is repeated to fill the plan.", "strategies:existing"))
        if any(cy.crop_id in ("spring_peas", "spring_canola") and not cy.corrected for cy in rotation):
            caveats.append(caveat("spring_assumed", "The crop map cannot tell winter from spring peas or canola; "
                                  "spring is assumed. Correct the crop history if yours was a winter crop.",
                                  "strategies:existing"))
        extra = {
            "field": {"acres": round(units.ha_to_acres(f.area_ha())), "rotation_years": [cy.year for cy in rotation],
                      "rotation_found": bool(detection.get("found")), "rotation_source":
                      "from the USDA crop map; fix it if wrong"},
            "plan_length": n,
            "detected_period": period,
            "first_harvest_year": first_year,
            "based_on_years": [cy.year for cy in rotation],
            "assumed_years": assumed_years,
            "pool": {
                "description": pool.description,
                "crops": [{"id": c.id, "name": c.name, "role": c.role, "share": pool.shares.get(c.id)}
                          for c in pool.crops],
                "years": pool.years,
            },
            "soil": soil.to_dict(s),
            "nearby": nearby.describe() if nearby is not None else None,
            "caveats": caveats,
        }
        return present(result, self.content, extra)

    # ---- weather station check -----------------------------------------------------
    def station(self, f: FieldGeometry) -> dict:
        """The field's grid weather against the nearest long-record weather station (evidence only)."""
        if self.providers.stations is None:
            raise RuntimeError("No weather-station source is configured for this region.")
        s = self.content.settings
        lon, lat = f.centroid()
        stations = (self.providers.stations.stations(str(self.content.region.get("fips"))) or {}).get("stations") or []
        grid = self.providers.weather.daily(lon, lat)
        out = station_check(
            stations, lambda sid, a, b: self.providers.stations.daily(sid, a, b), grid, lon, lat,
            crop_year_start_month=int(s["climate.crop_year_start_month"]),
            min_years=int(s["station_check.min_years"]), max_distance_km=float(s["station_check.max_distance_km"]),
            min_complete_fraction=float(s["station_check.min_complete_fraction"]),
            max_candidates=int(s["station_check.max_candidates"]),
            agreement_tolerance_pct=float(s["station_check.agreement_tolerance_pct"]))
        return out

    # ---- long greenness history (MODIS) ---------------------------------------------------
    def greenness_history(self, f: FieldGeometry) -> dict:
        """Peak and late-spring greenness per year since 2000, labelled with the crop map's crop (evidence only)."""
        prov = self.providers.long_vegetation
        if prov is None:
            raise RuntimeError("No long greenness record is configured for this region.")
        st = self.content.settings
        last_full = climate_mod.crop_year_of(self.today, 1) - 1  # past calendar years only
        years = [y for y in prov.available_years() if y <= last_full]
        geom = f.geojson()

        def one(y):
            try:
                return prov.ndvi_year(geom, y)
            except Exception as exc:
                log.warning("MODIS %s failed: %s", y, exc)
                return None
        with ThreadPoolExecutor(4) as ex:
            raws = [r for r in ex.map(one, years) if r]
        mmdd = lambda v: (int(v[:2]), int(v[3:]))
        out = greenness_mod.peak_greenness(
            raws, min_good_fraction=float(st["modis.min_good_fraction"]), min_whole_pixels=int(st["modis.min_whole_pixels"]),
            season_start=mmdd(st["modis.season"]["start"]), season_end=mmdd(st["modis.season"]["end"]),
            smooth=int(st["modis.smooth"]), pair_max_days=int(st["modis.pair_max_days"]),
            min_good_composites=int(st["modis.min_good_composites"]), max_gap_days=int(st["modis.max_gap_days"]),
            window_start=mmdd(st["modis.window"]["start"]), window_end=mmdd(st["modis.window"]["end"]),
            min_window_composites=int(st["modis.min_window_composites"]))
        return {**out, "years_requested": years, "years_failed": len(years) - len(raws)}

    # ---- slope ----------------------------------------------------------------------
    def _slope(self, f: FieldGeometry):
        if self.providers.terrain is None:
            raise RuntimeError("No elevation source is configured for this region.")
        st = self.content.settings
        raw = self.providers.terrain.elevation(f.geojson(), float(st["terrain.buffer_m"]))
        fs = terrain_mod.field_slope(raw, float(st["residue.slope_low_below_pct"]), float(st["residue.slope_high_above_pct"]),
                                     tuple(st["terrain.share_thresholds_pct"]))
        return fs

    def slope(self, f: FieldGeometry) -> dict:
        """Slope across the field from the elevation map, compared with the soil survey (evidence only)."""
        fs = self._slope(f)
        cmp = terrain_mod.compare_with_soil(fs, self.field_soil(f), float(self.content.settings["terrain.agree_within_pct"]))
        return {"status": "ok" if not fs.to_dict().get("error") else "partial", **fs.to_dict(), "comparison": cmp,
                "overlay": f"/api/field/{f.key()}/slope.png"}

    def slope_png(self, f: FieldGeometry) -> tuple[bytes, dict]:
        out = terrain_mod.slope_overlay(self._slope(f), f.geojson(), float(self.content.settings["terrain.display_pixel_m"]))
        if out is None:
            raise RuntimeError("No slope map could be made for this field.")
        return out

    # ---- nearby use ----------------------------------------------------------------
    def nearby_use(self, f: FieldGeometry) -> NearbyUse | None:
        """How common each role pattern is on cropland around the field (a note and a tie-break, never scored)."""
        if self.providers.sequences is None:
            return None
        s = self.content.settings
        try:
            years = self.providers.crops.available_years()[-int(s["nearby.years"]):]
            cr = sorted([k, v] for k, v in code_roles(self.content, self.providers.crops.classification).items())
            raw = self.providers.sequences.histogram(f.geojson(), years, cr, float(s["nearby.radius_km"]),
                                                     int(s["nearby.max_unknown_years"]))
            return NearbyUse.from_settings(raw, s)
        except Exception as exc:  # a note, not a requirement: degrade quietly
            log.warning("nearby use failed: %s", exc)
            return None

    # ---- regional context ------------------------------------------------------------
    def drought(self) -> dict:
        """County drought history from the US Drought Monitor (regional context, never scored)."""
        if self.providers.drought is None:
            raise RuntimeError("No drought source is configured for this region.")
        fips = str(self.content.region.get("fips"))
        # Cache key is per day: the Drought Monitor adds a week at a time.
        raw = self.providers.drought.county_weeks(fips, "2000-01-01", self.today.isoformat())
        s = self.content.settings
        out = drought_mod.summarise(raw, int(s["climate.crop_year_start_month"]), float(s["drought.min_share_pct"]),
                                    int(s["water.highlight_year"]))
        return {"status": "ok", **out, "source": raw.get("source"),
                "note": "County-wide weekly maps, not your field. Drought classes: D0 abnormally dry, D1 moderate, "
                        "D2 severe, D3 extreme, D4 exceptional."}

    def soil_moisture(self) -> dict:
        """County topsoil moisture, May to July of each year, from SMAP via Crop-CASMA (regional context)."""
        prov = self.providers.soil_moisture
        if prov is None:
            raise RuntimeError("No soil moisture source is configured for this region.")
        st = self.content.settings
        reg = self.region()["_shape"]
        m0, m1 = (int(x) for x in st["soil_moisture.months"])
        years = range(int(st["soil_moisture.first_year"]), self.today.year + (1 if self.today.month > m1 else 0))
        jobs = []
        for y in years:
            try:
                for w in prov.weeks(y)["weeks"]:
                    if m0 <= int(w["start"][5:7]) <= m1:
                        jobs.append((y, w))
            except Exception as exc:
                log.warning("soil moisture weeks %s failed: %s", y, exc)

        def one(job):
            y, w = job
            try:
                return y, w["start"], sm_mod.week_mean(prov.week_grid(y, w["id"], list(reg.bounds)), reg)
            except Exception as exc:
                log.warning("soil moisture %s failed: %s", w["id"], exc)
                return y, w["start"], None
        weekly: dict[int, list] = {}
        with ThreadPoolExecutor(6) as ex:
            for y, d, v in ex.map(one, jobs):
                weekly.setdefault(y, []).append((d, v))
        out = sm_mod.seasonal(weekly, (m0, m1), int(st["water.highlight_year"]), int(st["soil_moisture.min_weeks"]))
        return {"status": "ok", **out, "months": [m0, m1], "source": "NASA SMAP satellite, 9 km weekly topsoil "
                "moisture (top 2 in), via USDA Crop-CASMA",
                "note": "County average of the top 2 inches only; deeper storage, which crops here rely on, is not "
                        "seen by the satellite."}

    def outlook(self) -> dict:
        """The 2050 outlook panel, from the file written offline by tools/build_outlook.py. Never scored."""
        import json as _json
        path = (self.content.data_dir or Path(".")) / "outlook_2050.json"
        if not path.exists():
            raise FileNotFoundError("The 2050 outlook has not been prepared (run backend/tools/build_outlook.py).")
        o = _json.loads(path.read_text())
        sc = o.get("scenarios") or {}
        names = {"ssp245": "Middle emissions (SSP2-4.5)", "ssp585": "High emissions (SSP5-8.5)"}

        def rng(d, fmt, unit=""):
            if not d or d.get("median") is None:
                return "–"
            return f"{fmt(d['median'])}{unit} (models: {fmt(d['min'])} to {fmt(d['max'])})"
        sign = lambda v: f"{'+' if v >= 0 else '−'}{abs(v):.0f}"
        sign1 = lambda v: f"{'+' if v >= 0 else '−'}{abs(v):.1f}"
        rows = [[names.get(k, k), rng(v.get("apr_jul_precip_change_pct"), sign, "%"),
                 rng(v.get("hot_days_change"), sign, " days"), rng(v.get("mean_temp_change_f"), sign1, " °F")]
                for k, v in sc.items()]
        h, m = o.get("historical", ["?", "?"]), o.get("mid_century", ["?", "?"])
        models = o.get("models") or []
        return {
            "status": "ok",
            "intro": (f"How climate models project Whitman County's weather to change, from {h[0]}–{h[1]} to "
                      f"{m[0]}–{m[1]}, under two emissions scenarios. The middle value across {len(models)} models is "
                      "shown, with the range across them in brackets. The models disagree, especially about rain."),
            "columns": ["Scenario", "April–July rain and snow", f"June–July days at or above 90 °F", "Mean temperature"],
            "rows": rows,
            "notes": [f"Models used ({len(models)}): {', '.join(models)}.",
                      f"Source: {o.get('source', 'NASA NEX-GDDP-CMIP6')}, prepared {o.get('generated', '?')}.",
                      "This outlook is shown for context only. It never changes how options are judged: they are "
                      "judged on the weather that actually happened.", *o.get("notes", [])],
            "studies_text": ("What this means for fallow is unsettled: two published studies of this region drew "
                             "opposite conclusions. One projected that more fallow would be needed; the other, that "
                             "yields would rise and fallow would decrease."),
            "studies_url": "https://csanr.wsu.edu/climate-change-and-fallow/",
            "raw": o,
        }

    def region_context(self) -> dict:
        out: dict = {"status": "ok"}
        try:
            out["soil_moisture"] = self.soil_moisture()
        except Exception as exc:
            log.warning("soil moisture context failed: %s", exc)
            out["soil_moisture_error"] = str(exc)
        try:
            out["drought"] = self.drought()
        except Exception as exc:
            log.warning("drought context failed: %s", exc)
            out["drought_error"] = str(exc)
        return out

    # ---- configuration for the UI -------------------------------------------------
    def config(self) -> dict:
        r = self.region()
        c = self.content
        return {
            "region": {"id": r.get("id"), "name": r.get("name"), "geometry": r.get("geometry"),
                       "source": r.get("source")},
            "roles": [x.to_dict() for x in c.roles],
            "crops": [x.to_dict() for x in c.crops],
            "offered_crops": [x.id for x in c.offered_crops()],
            "rules": [{"id": x.id, "code": x.code, "label": x.label, "basis": x.basis, "source": x.source}
                      for x in self.rules],
            "warnings": [{"id": w.id, "code": w.code, "basis": w.basis, "source": w.source, "params": w.params}
                         for w in c.warnings if w.enabled],
            "settings": [p.to_dict() for p in c.settings.params()],
            "sources": list(c.sources.values()),
            "attributions": c.attributions,
            "measures": [{"id": m, "label": MEASURE_LABELS[m], "question": QUESTIONS[m]}
                         for m in c.settings["comparison.measures"]],
            "scenario": {"rain_pct": c.settings["scenario.rain_pct_range"],
                         "temp_f": c.settings["scenario.temp_f_range"]},
            "tillage": {"options": [{"id": k, "label": v} for k, v in TILLAGE_LABELS.items()],
                        "default": c.settings["residue.default_tillage"]},
        }


__all__ = ["FieldService", "Providers", "FieldError", "caveat"]
