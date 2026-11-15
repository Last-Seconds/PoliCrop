"""Offline tests for the core logic (no network)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from fieldshift.cache import CachedProvider, FileCache
from fieldshift.core import climate, history, vegetation
from fieldshift.core.content import AGRONOMIC_ATTRIBUTES, ContentError, load_content, parse_crops
from fieldshift.core.geometry import FieldError, PolygonField, field_from_spec
from fieldshift.core.service import FieldService, Providers
from fieldshift.core.strategies.generate import (best_alignment, build_pool, canonical, describe_differences,
                                                 distance, generate)
from fieldshift.core.strategies.model import Strategy, make_steps
from fieldshift.core.strategies.rules import RULE_REGISTRY, build_rules

from .fakes import DATA_DIR, FIELD, OUTSIDE, FakeCrops, FakeRegion, FakeVegetation, FakeWeather


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture
def service(content):
    return FieldService(content, Providers(FakeRegion(), FakeCrops(), FakeWeather(), FakeVegetation()),
                        today=dt.date(2026, 11, 14))


# ---- content ---------------------------------------------------------------------------

def test_content_files_load_and_reference_valid_roles(content):
    role_ids = {r.id for r in content.roles}
    assert {c.role for c in content.crops} <= role_ids
    names = {c.name for c in content.crops}
    for expected in ("Winter wheat", "Spring wheat", "Barley", "Peas", "Lentils", "Chickpeas", "Canola", "Fallow"):
        assert expected in names
    assert content.crop_for_code("us_cdl", 24).id == "winter_wheat"
    assert content.crop_for_code("us_cdl", 61).role == "fallow"
    assert any(c.pool == "always" and c.role == "cover_crop" for c in content.crops)


def test_crop_table_schema_has_every_attribute(content):
    for c in content.crops:
        assert set(AGRONOMIC_ATTRIBUTES) <= set(c.attributes)


def test_bad_content_is_rejected():
    with pytest.raises(ContentError):
        parse_crops({"crops": [{"id": "x", "name": "X", "role": "nope"}]}, {"cereal"})
    with pytest.raises(ContentError):
        parse_crops({"crops": [{"id": "a", "name": "A", "role": "cereal", "class_codes": {"us_cdl": [1]}},
                               {"id": "b", "name": "B", "role": "cereal", "class_codes": {"us_cdl": [1]}}]},
                    {"cereal"})
    with pytest.raises(ContentError):
        parse_crops({"crops": [{"id": "a", "name": "A", "role": "cereal",
                                "season_window": {"start": "13-01", "end": "08-01"}}]}, {"cereal"})


def test_thresholds_come_from_settings_file(tmp_path, content):
    # Changing a threshold in the data file changes behaviour with no code change.
    import shutil
    d = tmp_path / "data"
    shutil.copytree(DATA_DIR, d)
    text = (d / "settings.yaml").read_text().replace("value: 0.25\n", "value: 0.9\n")
    (d / "settings.yaml").write_text(text)
    c2 = load_content(d)
    assert c2.settings["vegetation.bare_ndvi_threshold"] == 0.9
    assert content.settings.param("vegetation.bare_ndvi_threshold").provisional


# ---- geometry ------------------------------------------------------------------------------

def test_field_geometry_and_region_check(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    assert 30 < f.area_ha() < 60
    assert f.key() == PolygonField(json.loads(json.dumps(FIELD))).key()
    with pytest.raises(FieldError, match="outside Test County"):
        service.make_field({"type": "polygon", "geometry": OUTSIDE})
    with pytest.raises(FieldError):
        field_from_spec({"type": "parcel", "id": "123"})
    with pytest.raises(FieldError):
        field_from_spec({"type": "polygon", "geometry": {"type": "Point", "coordinates": [0, 0]}})


# ---- crop history ----------------------------------------------------------------------------

def test_history_dominant_class_share_and_uncertainty(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    h = service.history(f)
    years = {y["year"]: y for y in h["years"]}
    assert years[2025]["name"] == "Lentils" and years[2025]["role"] == "legume"
    assert years[2024]["name"] == "Spring wheat" and years[2023]["name"] == "Winter wheat"
    assert years[2024]["share"] == pytest.approx(180 / 190, abs=1e-3)
    assert years[2015]["uncertain"] is True  # 90/180 < 0.6
    assert years[2014]["uncertain"] is False
    assert h["rotation"]["found"] and h["rotation"]["period"] == 3
    assert any("2015" in c["text"] for c in h["caveats"] if c["id"] == "uncertain_years")


def test_history_corrections(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    h = service.history(f, {"2025": "barley", "2024": "class:176", "1990": "peas", "2023": "nonsense"})
    years = {y["year"]: y for y in h["years"]}
    assert years[2025]["name"] == "Barley" and years[2025]["corrected"] and years[2025]["detected_name"] == "Lentils"
    assert years[2024]["name"] == "Grass/Pasture" and years[2024]["role"] is None
    assert not years[2023]["corrected"]


def test_history_survives_failed_years(content):
    svc = FieldService(content, Providers(FakeRegion(), FakeCrops(fail_years={2012}), FakeWeather(),
                                          FakeVegetation()))
    h = svc.history(svc.make_field({"type": "polygon", "geometry": FIELD}))
    assert h["status"] == "partial"
    assert any(y["year"] == 2012 and y["code"] is None for y in h["years"])


def test_rotation_detection_falls_back_to_default(content):
    hist = [history.CropYear(2000 + i, c, "x", "#000", 1.0, 100, None, r, False)
            for i, (c, r) in enumerate([(24, "cereal"), (61, "fallow"), (52, "legume"), (24, "cereal"),
                                        (31, "oilseed"), (23, "cereal"), (61, "fallow")])]
    det = history.detect_rotation(hist, content.settings)
    assert not det.found and det.period == content.settings["rotation.default_plan_length"]


def test_validate_counts_rejects_garbage():
    assert history.validate_counts({"counts": {"24": 10, "0": 99, "x": 3, "300": 4, "23": -1}}) == {24: 10}


# ---- climate ----------------------------------------------------------------------------------

def test_climate_wet_winter_dry_summer_and_missing_values(service, content):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    c = service.climate(f)
    months = {m["month"]: m for m in c["rainfall_monthly"]["months"]}
    assert months[12]["mean_mm"] > months[7]["mean_mm"] * 5
    # Feb 2001 has a missing day -> that month is excluded, not estimated
    assert months[2]["years"] == 5
    yearly = {y["year"]: y for y in c["rainfall_yearly"]["years"]}
    assert yearly[2000]["total_mm"] is None  # crop year 1999-2000 starts before the record
    assert yearly[2001]["total_mm"] is None  # contains the missing day
    assert yearly[2003]["complete"] and yearly[2003]["total_mm"] > 0
    frost = {y["year"]: y for y in c["frost_days"]["years"]}
    assert frost[2003]["frost_days"] > 0
    assert any(cv["id"] == "regional_weather" and "rainfall_monthly" in cv["applies_to"] for cv in c["caveats"])


def test_climate_value_validation():
    days = climate.validate_days({"days": [
        {"date": "2020-01-01", "precip_mm": -999, "tmax_c": 5, "tmin_c": -2},
        {"date": "2020-01-02", "precip_mm": 9999, "tmax_c": 99, "tmin_c": -2},
        {"date": "nope", "precip_mm": 1},
        {"date": "2020-01-03", "precip_mm": "2.5", "tmax_c": 1, "tmin_c": 8},
    ]})
    assert [d.precip_mm for d in days] == [None, None, 2.5]
    assert days[1].tmax_c is None and days[2].tmax_c is None  # out of range / tmin > tmax


def test_crop_year_convention():
    assert climate.crop_year_of(dt.date(2023, 9, 1), 9) == 2024
    assert climate.crop_year_of(dt.date(2024, 8, 31), 9) == 2024
    assert climate.crop_year_label(2024, 9) == "2023–24"


# ---- vegetation ---------------------------------------------------------------------------------

def test_vegetation_bare_periods_and_gaps(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    v = service.vegetation(f)
    assert v["counts"]["images_used"] < v["counts"]["images_read"]  # the cloudy image is dropped
    assert len(v["bare_periods"]) >= 3
    assert all(p["mean_ndvi"] < v["threshold"] for p in v["bare_periods"])
    # winter has no images: shown as gaps, and no bare period spans a winter
    assert any(g["start"].startswith("2023-11") or g["start"].startswith("2023-12") for g in v["gaps"])
    for p in v["bare_periods"]:
        assert p["start"][:4] == p["end"][:4]
    assert len(v["segments"]) >= 2


def test_bare_period_not_carried_across_gap(content):
    obs = [vegetation.Obs(dt.date(2024, 1, 1) + dt.timedelta(days=d), 0.1, 1.0, "") for d in (0, 10, 80, 90)]
    periods = vegetation.bare_periods(obs, content.settings)
    assert len(periods) == 2


# ---- strategies -----------------------------------------------------------------------------------

def test_strategies_end_to_end(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    st = service.strategies(f)
    assert st["plan_length"] == 3
    # history ends 2025 (W, S, L for 2023-25); today is Nov 2026, so the plan starts with harvest 2028
    # and the rotation's phase is carried forward: 2026 W, 2027 S, 2028 L, 2029 W, 2030 S
    assert st["first_harvest_year"] == 2028 and st["assumed_years"] == [2026, 2027]
    assert [s["crop"] for s in st["existing"]["steps"]] == ["Lentils", "Winter wheat", "Spring wheat"]
    assert st["existing"]["steps"][0]["start"] == "2027-09-01"
    assert any(c["id"] == "assumed_years" for c in st["caveats"])
    assert len(st["alternatives"]) >= 3
    distances = [a["distance"] for a in st["alternatives"]]
    assert all(d > 0 for d in distances) and len(set(distances)) >= 2
    for s in [st["existing"], *st["alternatives"]]:
        assert s["scores"] == {}  # no scoring in v0
        assert s["not_assessed"] == ["Water use", "Nitrogen", "Erosion", "Income"]
        assert {r["rule_id"] for r in s["rules"]} == {"no_identical_consecutive_crop", "no_overlapping_dates"}
        assert s["steps"][0]["start"] < s["steps"][0]["end"]
        assert "best" not in json.dumps(s).lower()
    for a in st["alternatives"]:
        assert a["passed_all_rules"] and a["differences"] and a["summary"]
    pool_names = {c["name"] for c in st["pool"]["crops"]}
    assert "Alfalfa" not in pool_names  # below the minimum share nearby
    assert "Cover crop (species not chosen)" in pool_names


def test_strategies_respect_plan_length_and_corrections(service):
    f = service.make_field({"type": "polygon", "geometry": FIELD})
    st = service.strategies(f, plan_length=4)
    assert st["plan_length"] == 4 and len(st["existing"]["steps"]) == 4
    st2 = service.strategies(f, corrections={"2025": "peas"})
    assert "Peas" in [s["crop"] for s in st2["existing"]["steps"]]


def test_rules(content):
    rules = build_rules(content.rules)
    assert {r.id for r in rules} == set(RULE_REGISTRY) & {"no_identical_consecutive_crop", "no_overlapping_dates"}
    ww = content.crop("winter_wheat")
    window = content.settings["generation.default_step_window"]
    from fieldshift.core.content import SeasonWindow
    dw = SeasonWindow.parse(window, "t")
    bad = Strategy("x", "generated", make_steps([ww, content.crop("peas"), ww], 2026, dw))
    res = {r.rule_id: r for r in (rule.check(bad, content) for rule in rules)}
    assert not res["no_identical_consecutive_crop"].passed  # last -> first (cyclic)
    assert "next cycle" in res["no_identical_consecutive_crop"].reason
    assert res["no_overlapping_dates"].passed
    # Overlap: a crop sown in spring before an autumn-to-summer crop ends
    early = SeasonWindow("07-01", "07-15", True)  # sown 1 Jul before harvest year
    late = SeasonWindow("09-15", "08-10", True)
    from dataclasses import replace
    a = replace(ww, id="a", season_window=late)
    b = replace(ww, id="b", season_window=early)
    s = Strategy("y", "generated", make_steps([a, b], 2026, dw))
    assert not rules[1].check(s, content).passed


def test_distance_alignment_and_canonical(content):
    w = {"same_crop": 0, "same_role_other_crop": 0.5, "other_role": 1}
    ww, sw, le, pe, ca = (content.crop(x) for x in ("winter_wheat", "spring_wheat", "lentils", "peas", "canola"))
    assert distance([ww, sw, le], [ww, sw, pe], w) == 0.5
    aligned, d = best_alignment([ww, sw, le], [le, ww, sw], w)
    assert d == 0 and [c.id for c in aligned] == ["winter_wheat", "spring_wheat", "lentils"]
    assert canonical(("b", "c", "a")) == canonical(("a", "b", "c"))
    details, summary = describe_differences([ww, sw, le], [ww, ca, le], content)
    assert "adds an oilseed in year 2" in summary.lower()
    assert details == ["Year 2: Canola (oilseed) instead of Spring wheat (cereal)"]


def test_generation_never_returns_existing_or_rule_breakers(content):
    pool = build_pool({24: 100, 23: 100, 52: 100, 31: 100, 61: 100}, content, "us_cdl", [2025], 10)
    rules = build_rules(content.rules)
    ex = [content.crop(x) for x in ("winter_wheat", "spring_wheat", "lentils")]
    res = generate(ex, pool, content, rules, [], 2026, alternatives_wanted=5)
    assert res.stats["candidates_generated"] > 0 and res.stats["candidates_failed"] > 0
    seen = {canonical(tuple(c.id for c in ex))}
    for a in res.alternatives:
        assert canonical(a.crop_ids) not in seen
        seen.add(canonical(a.crop_ids))
        assert a.passed


# ---- cache ------------------------------------------------------------------------------------------

def test_cache_layer_caches_and_serves_stale_on_failure(tmp_path):
    cache = FileCache(tmp_path)
    inner = FakeCrops()
    wrapped = CachedProvider(inner, cache, "t", ["class_counts"], lambda m, a, r: 0.0)  # always stale
    first = wrapped.class_counts(FIELD, 2020)
    inner.fail_years = {2020}
    assert wrapped.class_counts(FIELD, 2020) == first  # refresh failed -> stale value served
    assert inner.calls == 2
    forever = CachedProvider(FakeCrops(), cache, "u", ["class_counts"])
    forever.class_counts(FIELD, 2021)
    forever.class_counts(FIELD, 2021)
    assert forever._inner.calls == 1
    assert forever.classification == "us_cdl"  # attributes pass through


def test_core_is_independent_of_data_sources_and_web_framework():
    from pathlib import Path
    core = Path(__file__).resolve().parents[1] / "fieldshift" / "core"
    forbidden = ("httpx", "rasterio", "pystac", "planetary_computer", "fastapi", "uvicorn", "fieldshift.providers",
                 "..providers", "..cache")
    for py in core.rglob("*.py"):
        text = py.read_text()
        for name in forbidden:
            assert f"import {name}" not in text and f"from {name}" not in text, f"{py.name} imports {name}"
