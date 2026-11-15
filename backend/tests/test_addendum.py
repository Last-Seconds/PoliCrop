"""BUILD_BRIEF_3_ADDENDUM.md: corrected crop values and the rotations farmers use."""
from __future__ import annotations

import pytest

from fieldshift.core import units
from fieldshift.core.content import SeasonWindow, load_content
from fieldshift.core.soil import field_soil
from fieldshift.core.strategies import warnings as W
from fieldshift.core.strategies.generate import build_pool, canonical, enumerate_candidates
from fieldshift.core.strategies.inputs import FarmerInputs
from fieldshift.core.strategies.model import Strategy, make_steps
from fieldshift.core.strategies.plan import build_field_model
from fieldshift.core.strategies.rules import build_rules
from fieldshift.core.weather import DailySeries

from .fakes import DATA_DIR, FakeSoil, FakeWeather

# Item 6: [S27] Table 5-2, written with the crops this tool knows ("pea" is spring peas, "legume" each pulse).
LEGUMES = ["spring_peas", "lentils", "chickpeas"]
ANNUAL = ([["winter_wheat", "spring_wheat", x] for x in LEGUMES]
          + [["winter_wheat", "spring_barley", x] for x in LEGUMES]
          + [["winter_wheat", "spring_wheat", "winter_wheat", x] for x in LEGUMES]
          + [["winter_wheat", "spring_wheat", "spring_canola"], ["winter_wheat", "spring_wheat", "winter_peas"]]
          + [["winter_wheat", "spring_canola", x] for x in LEGUMES])
TRANSITION = [["winter_wheat", "spring_wheat", "fallow"], ["winter_wheat", "fallow"],
              ["winter_wheat", "fallow", "winter_canola"], ["winter_wheat", "fallow", "spring_canola"],
              ["winter_wheat", "spring_barley", "fallow"]]
GRAIN_FALLOW = [["winter_wheat", "fallow"], ["winter_wheat", "fallow", "winter_peas"],
                ["winter_wheat", "fallow", "winter_canola"]]
TRADITIONAL = {"annual_crop": ["winter_wheat", "spring_wheat", "chickpeas"],
               "transition": ["winter_wheat", "spring_wheat", "fallow"],
               "grain_fallow": ["winter_wheat", "fallow"]}


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture(scope="module")
def rules(content):
    return build_rules(content.rules)


def model(content, scale=1.0, **inputs):
    series = DailySeries.from_raw(FakeWeather(short=False, scale=scale).daily(0, 0))
    soil = field_soil(FakeSoil().soil({}), content.settings)
    ref = [content.crop("fallow"), content.crop("winter_wheat")]
    return build_field_model(content, series, soil, ref, FarmerInputs.parse(inputs, content))


@pytest.mark.parametrize("seq", ANNUAL + TRANSITION + GRAIN_FALLOW, ids=lambda s: "-".join(s))
def test_rotations_in_real_use_pass_the_hard_rules(content, rules, seq):
    dw = SeasonWindow.parse(content.settings["generation.default_step_window"], "t")
    st = Strategy("t", "generated", make_steps([content.crop(c) for c in seq], 2027, dw))
    failed = {r.code: r.check(st, content).reason for r in rules if not r.check(st, content).passed}
    assert not failed, failed


@pytest.mark.parametrize("zone", sorted(TRADITIONAL))
def test_traditional_sequence_is_a_candidate_when_grown_nearby(content, rules, zone):
    trad = TRADITIONAL[zone]
    # A pool with every crop of the traditional sequence grown nearby, starting from a different rotation.
    codes = {24: 5000, 23: 3000, 21: 1000, 51: 800, 61: 2000, 53: 500, 52: 500, 31: 300}
    pool = build_pool(codes, content, "us_cdl", [2023, 2024, 2025], 10)
    existing = [content.crop(c) for c in (["spring_wheat", "winter_wheat", "spring_barley"][:len(trad)])]
    enum = enumerate_candidates(existing, pool, content, rules, 2027)
    have = {canonical(c.strategy.crop_ids) for c in enum.candidates}
    assert canonical(tuple(trad)) in have


def test_zone_yields(content):
    wet, mid, dry = model(content, 1.0), model(content, 0.65), model(content, 0.5)
    for fm, z in ((wet, "annual_crop"), (mid, "transition"), (dry, "grain_fallow")):
        assert fm.zone == z, (units.mm_to_in(fm.mean_precip_mm), z)
    lb = lambda fm, c: round(units.kg_ha_to_lb_ac(fm.expected_yield(content.crop(c)).kg_ha))
    assert lb(wet, "winter_wheat") == 4800
    assert lb(mid, "winter_wheat") == 78 * 60  # after fallow in the reference rotation
    assert lb(dry, "winter_wheat") == 45 * 60 and lb(dry, "spring_canola") == 500
    assert lb(mid, "lentils") == 1200 and dry.expected_yield(content.crop("lentils")).tag == "regional_wetter"
    assert lb(dry, "lentils") == 1200  # nearest wetter zone
    assert mid.expected_yield(content.crop("chickpeas")).tag == "regional_wetter"
    after_crop = build_field_model(content, DailySeries.from_raw(FakeWeather(short=False, scale=0.65).daily(0, 0)),
                                   field_soil(FakeSoil().soil({}), content.settings),
                                   [content.crop("spring_wheat"), content.crop("winter_wheat")], FarmerInputs())
    y = after_crop.expected_yield(content.crop("winter_wheat"))
    assert round(units.kg_ha_to_lb_ac(y.kg_ha)) == 35 * 60 and y.assumed  # unlabelled figure, assumed
    farmer = model(content, 0.65, yields={"winter_wheat": 60})
    assert farmer.expected_yield(content.crop("winter_wheat")).tag == "farmer"


def test_canola_water_use_from_yield(content):
    fm = model(content, 1.6)
    t = fm.too_dry(content.crop("spring_canola"))
    assert units.mm_to_in(t["use_mm"]) == pytest.approx(1500 / 105)
    assert units.mm_to_in(t["use_range_mm"][1]) == pytest.approx(1500 / 65)
    farmer = model(content, 1.6, yields={"spring_canola": 2100})
    assert units.mm_to_in(farmer.too_dry(content.crop("spring_canola"))["use_mm"]) == pytest.approx(20)


def test_winter_pea_cold_limit_is_zero_f(content):
    cfg = next(w for w in content.warnings if w.id == "winter_pea_cold")
    assert cfg.params["limit_f"] == 0
    fm = model(content)
    ws = {w.code: w for w in W.evaluate([content.crop("winter_peas"), content.crop("winter_wheat")], fm,
                                        content.warnings)}
    if "W6" in ws:
        assert "Lynx" in ws["W6"].text and "+10" in ws["W6"].text
