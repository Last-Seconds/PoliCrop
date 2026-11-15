"""Stage 1 tests: units, season windows, hard rules H1–H5, Daymet parsing, soil summary."""
from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest

from fieldshift.core import soil as soil_mod
from fieldshift.core import units
from fieldshift.core.content import SeasonWindow, load_content
from fieldshift.core.strategies.model import Strategy, make_steps
from fieldshift.core.strategies.rules import build_rules
from fieldshift.core.weather import DailySeries
from fieldshift.providers.us.daymet import parse_daymet_csv

from .fakes import DATA_DIR, FakeSoil, FakeWeather


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture(scope="module")
def rules(content):
    return {r.code: r for r in build_rules(content.rules)}


def strat(content, *ids, year=2027):
    dw = SeasonWindow.parse(content.settings["generation.default_step_window"], "t")
    return Strategy("t", "generated", make_steps([content.crop(i) for i in ids], year, dw))


def check(rules, content, s):
    return {code: r.check(s, content) for code, r in rules.items()}


# ---- units ------------------------------------------------------------------------------

def test_unit_conversions_round_trip_and_known_values():
    assert units.in_to_mm(1) == 25.4
    assert units.mm_to_in(254) == pytest.approx(10)
    assert units.c_to_f(0) == 32 and units.c_to_f(100) == 212
    assert units.f_to_c(98) == pytest.approx(36.667, abs=1e-3)
    assert units.f_to_c(-6) == pytest.approx(-21.11, abs=1e-2)  # the winter pea limit, [S4] gives −21 °C
    assert units.delta_f_to_c(9) == pytest.approx(5)
    assert units.ha_to_acres(1) == pytest.approx(2.4710538, abs=1e-6)
    assert units.lb_ac_to_kg_ha(1) == pytest.approx(1.12085, abs=1e-5)
    assert units.kg_ha_to_lb_ac(units.lb_ac_to_kg_ha(4800)) == pytest.approx(4800)
    assert units.bu_to_lb(80) == 4800  # 80 bu of wheat = 4,800 lb (Appendix A)
    assert units.cm_to_mm(20) == 200  # SDA storage (cm) vs gNATSGO raster (mm)
    for x in (0.0, 3.3, 17.7, -40.0):
        assert units.mm_to_in(units.in_to_mm(x)) == pytest.approx(x)
        assert units.c_to_f(units.f_to_c(x)) == pytest.approx(x)
        assert units.acres_to_ha(units.ha_to_acres(x)) == pytest.approx(x)


def test_content_converts_us_units_on_load(content):
    peas = content.crop("spring_peas")
    assert peas.water_use["use_mm"] == pytest.approx(9.3 * 25.4)
    assert peas.residue["low_kg_ha"] == pytest.approx(units.lb_ac_to_kg_ha(1500))
    assert content.crop("winter_wheat").regional_yield["kg_ha"] == pytest.approx(units.lb_ac_to_kg_ha(4800))


# ---- season windows -----------------------------------------------------------------------

def test_steps_carry_real_dates_and_fallow_fills_the_gap(content):
    s = strat(content, "winter_wheat", "fallow", "winter_wheat", year=2027)
    ww, fal, ww2 = s.steps
    assert ww.sow_window == (dt.date(2026, 9, 1), dt.date(2026, 10, 10))  # autumn sown the year before
    assert ww.harvest_window == (dt.date(2027, 7, 25), dt.date(2027, 8, 20))
    assert fal.start == dt.date(2027, 8, 21) and fal.end == dt.date(2028, 8, 31)  # harvest -> next sowing
    assert not fal.harvested and ww.harvested
    sp = strat(content, "spring_wheat", "lentils").steps
    assert sp[1].sow_window[0] == dt.date(2028, 4, 10) and sp[1].dates_assumed  # lentil sowing is assumed


# ---- hard rules ----------------------------------------------------------------------------

def test_brief_examples(content, rules):
    ok = check(rules, content, strat(content, "winter_wheat", "spring_wheat", "chickpeas"))
    assert all(r.passed for r in ok.values()), {k: r.reason for k, r in ok.items() if not r.passed}
    alt = check(rules, content, strat(content, "winter_wheat", "spring_peas"))
    assert not alt["H3"].passed and "returns after 2 years" in alt["H3"].reason
    wc = check(rules, content, strat(content, "spring_wheat", "winter_canola", "winter_wheat"))
    assert not wc["H4"].passed
    assert check(rules, content, strat(content, "fallow", "winter_canola", "winter_wheat"))["H4"].passed


def test_h1_identical_consecutive_including_wrap(content, rules):
    r = check(rules, content, strat(content, "winter_wheat", "spring_peas", "winter_wheat"))["H1"]
    assert not r.passed and "next cycle" in r.reason


def test_h2_uses_real_windows(content, rules):
    assert check(rules, content, strat(content, "spring_wheat", "winter_peas", "winter_wheat"))["H2"].passed
    late = replace(content.crop("spring_wheat"), id="late_wheat",
                   harvest_window=SeasonWindow("09-20", "10-30", basis=None))
    dw = SeasonWindow.parse(content.settings["generation.default_step_window"], "t")
    s = Strategy("t", "generated", make_steps([late, content.crop("winter_wheat")], 2027, dw))
    r = rules["H2"].check(s, content)
    assert not r.passed and "before" in r.reason


def test_h3_any_two_legumes_three_years_apart_cyclic(content, rules):
    # Lentils in years 1 and 4 of a 4-year rotation return after 3 years: allowed.
    assert check(rules, content, strat(content, "lentils", "winter_wheat", "spring_wheat", "fallow"))["H3"].passed
    # In a 2-year rotation the same legume comes back every other year.
    assert not check(rules, content, strat(content, "chickpeas", "winter_wheat"))["H3"].passed
    # Brief 3, S1: different legumes close together now fail too (W2 is gone).
    r = check(rules, content, strat(content, "lentils", "winter_wheat", "spring_peas", "spring_wheat"))["H3"]
    assert not r.passed and "spring peas follows lentils after 2 years" in r.reason.lower()
    assert not check(rules, content, strat(content, "spring_peas", "lentils", "chickpeas"))["H3"].passed
    # Across the wrap: chickpeas in year 3, winter peas in year 1 of the next cycle.
    assert not check(rules, content, strat(content, "winter_peas", "winter_wheat", "chickpeas"))["H3"].passed
    # A three-year plan holds one legume at most, and one is allowed.
    assert check(rules, content, strat(content, "winter_wheat", "spring_wheat", "chickpeas"))["H3"].passed
    # Six years, two legumes three years apart each way: allowed.
    assert check(rules, content, strat(content, "lentils", "winter_wheat", "spring_wheat", "chickpeas",
                                       "winter_wheat", "spring_barley"))["H3"].passed


def test_h5_no_two_years_without_harvest(content, rules):
    r = check(rules, content, strat(content, "fallow", "cover_crop", "winter_wheat"))["H5"]
    assert not r.passed
    r = check(rules, content, strat(content, "cover_crop", "winter_wheat", "fallow"))["H5"]
    assert not r.passed and "next cycle" in r.reason  # fallow wraps onto the cover crop
    assert check(rules, content, strat(content, "fallow", "winter_wheat", "spring_wheat"))["H5"].passed


# ---- Daymet ----------------------------------------------------------------------------------

DAYMET_SAMPLE = """Latitude: 46.73  Longitude: -117.18
X & Y on Lambert Conformal Conic: -1245399.01 577087.15
Tile: 12272
Elevation: 731 meters
All years; all variables; Daymet Software Version 4.0
How to cite: Thornton et al.
year,yday,prcp (mm/day),tmax (deg c),tmin (deg c)
2024,365,1.48,5.05,-0.26
2025,1,0.80,0.79,-1.79
2025,2,nan,2.78,-0.95
"""


def test_daymet_csv_parsing():
    p = parse_daymet_csv(DAYMET_SAMPLE)
    assert p["elevation_m"] == 731 and p["tile"] == "12272"
    # 2024 is a leap year: yday 365 is 30 December (Daymet drops 31 December).
    assert p["days"][0] == {"date": "2024-12-30", "precip_mm": 1.48, "tmax_c": 5.05, "tmin_c": -0.26}
    assert p["days"][1]["date"] == "2025-01-01" and p["days"][2]["precip_mm"] is None
    with pytest.raises(ValueError):
        parse_daymet_csv("<html>error</html>")


def test_daily_series_window_sums_and_365_day_calendar():
    s = DailySeries.from_raw(FakeWeather(short=False).daily(0, 0))
    total, missing = s.precip_sum(dt.date(2020, 9, 1), dt.date(2021, 3, 31))
    assert missing == 0  # 31 Dec 2020 is absent by design, not missing
    assert total > 0
    assert s.absent[s.idx(dt.date(2020, 12, 31))]
    wetter = s.adjusted(rain_factor=1.1, rain_months=(4, 5, 6, 7))
    a, _ = s.precip_sum(dt.date(2021, 4, 1), dt.date(2021, 7, 31))
    b, _ = wetter.precip_sum(dt.date(2021, 4, 1), dt.date(2021, 7, 31))
    assert b == pytest.approx(a * 1.1)
    assert wetter.precip_sum(dt.date(2021, 1, 1), dt.date(2021, 1, 31))[0] == \
        pytest.approx(s.precip_sum(dt.date(2021, 1, 1), dt.date(2021, 1, 31))[0])


# ---- soil -------------------------------------------------------------------------------------

def test_soil_summary_area_weighted(content):
    fs = soil_mod.field_soil(FakeSoil().soil({}), content.settings)
    assert fs.capacity_mm["0_150cm"] == pytest.approx(0.7 * 300 + 0.3 * 260)
    assert fs.capacity_mm["0_100cm"] == pytest.approx(0.7 * 200 + 0.3 * 180)
    assert fs.main_component == "Palouse" and fs.drainage == "Well drained"
    assert fs.sensitivity(content.settings) == "high" and not fs.capacity_default
    assert soil_mod.field_soil(FakeSoil(slope=2).soil({}), content.settings).sensitivity(content.settings) == "low"


def test_soil_falls_back_to_stated_default(content):
    fs = soil_mod.field_soil(None, content.settings, "down")
    assert fs.capacity_default and fs.attributes_missing
    assert units.mm_to_in(fs.capacity_mm["0_150cm"]) == pytest.approx(9.9)
    assert fs.sensitivity(content.settings) is None
    garbage = soil_mod.field_soil({"map_units": [{"mukey": "1", "area_share": 7, "aws0_150_mm": -5}]},
                                  content.settings)
    assert garbage.capacity_default
