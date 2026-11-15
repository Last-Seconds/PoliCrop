"""Stage 2 tests: water budget, the four measures, comparison, assumed-value rule, dominance, ordering,
selection, warnings W1–W9."""
from __future__ import annotations

import datetime as dt
import shutil

import numpy as np
import pytest

from fieldshift.core import present, units
from fieldshift.core.content import SeasonWindow, load_content
from fieldshift.core.replay import build_replay, supply_mm
from fieldshift.core.soil import field_soil
from fieldshift.core.strategies import warnings as W
from fieldshift.core.strategies.compare import (BETTER, SAME, WORSE, Table, band_of, order_key, select, verdict)
from fieldshift.core.strategies.inputs import FarmerInputs
from fieldshift.core.strategies.measures import (Assumed, Quantity, margins, nitrogen_measure, soil_measure,
                                                 variety_measure, water_measure)
from fieldshift.core.strategies.plan import build_field_model
from fieldshift.core.weather import DailySeries

from .fakes import DATA_DIR, FakeSoil, FakeWeather

IN = units.in_to_mm


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture(scope="module")
def series():
    return DailySeries.from_raw(FakeWeather(short=False).daily(0, 0))


def crops(content, *ids):
    return [content.crop(i) for i in ids]


def model(content, series, reference=("fallow", "winter_wheat"), soil=None, **inputs):
    soil = soil or field_soil(FakeSoil().soil({}), content.settings)
    return build_field_model(content, series, soil, crops(content, *reference), FarmerInputs.parse(inputs, content))


# ---- water budget ---------------------------------------------------------------------------------

def test_worked_example_from_the_brief(content):
    """September–March 10.0 in, April–June 3.0 in, fallow period 15.0 in, capacity 10.6 in, central constants."""
    s = content.settings
    ew, ef = s.central("water.e_winter"), s.central("water.e_fallow")
    cost = IN(s.central("water.cover_cost_in"))
    args = (IN(10.0), IN(15.0), IN(3.0), IN(10.6))
    assert units.mm_to_in(supply_mm(*args, "harvested", ew, ef, cost)) == pytest.approx(9.75)
    assert units.mm_to_in(supply_mm(*args, "fallow", ew, ef, cost)) == pytest.approx(13.6)
    assert units.mm_to_in(supply_mm(*args, "cover", ew, ef, cost)) == pytest.approx(11.25)
    # the fallow store never goes below zero after a cover crop
    assert units.mm_to_in(supply_mm(IN(10.0), IN(5.0), IN(3.0), IN(10.6), "cover", ew, ef, cost)) == pytest.approx(9.75)


def test_replay_windows_match_hand_sums(content, series):
    rp = build_replay(series, {"0_100cm": IN(7), "0_150cm": IN(10.6)}, content.settings)
    assert rp.years[0] == 1982 and rp.years[-1] == 2025 and len(rp.years) == 44
    j = int(np.where(rp.years == 2010)[0][0])
    pw = series.precip_sum(dt.date(2009, 9, 1), dt.date(2010, 3, 31))[0]
    pf = series.precip_sum(dt.date(2008, 8, 1), dt.date(2009, 8, 31))[0]
    pg = series.precip_sum(dt.date(2010, 4, 1), dt.date(2010, 6, 30))[0]
    assert rp.p_winter[j] == pytest.approx(pw) and rp.p_fallow[j] == pytest.approx(pf)
    expect = supply_mm(pw, pf, pg, IN(10.6), "fallow", 0.675, 0.30, IN(3))
    assert rp.supply_for("0_150cm", "apr_jun", "fallow")[j] == pytest.approx(expect)
    lo, hi = rp.supply_for("0_150cm", "apr_jun", "harvested", "low"), rp.supply_for("0_150cm", "apr_jun", "harvested", "high")
    assert (lo <= hi + 1e-9).all()  # the "low" end has the least water


def test_every_need_is_self_calibrated(content, series):
    """Brief 3, S1: every crop's need is its median supply here in its reference position."""
    fm = model(content, series, reference=("fallow", "winter_wheat"))
    ww = content.crop("winter_wheat")
    after_fallow = fm.base.supply_for("0_150cm", "apr_jun", "fallow")
    assert fm.reference_kinds("winter_wheat") == ["fallow"]
    assert fm.need(ww)["central"] == pytest.approx(np.median(after_fallow))
    harvested = fm.base.supply_for("0_150cm", "apr_jun", "harvested")
    assert fm.need(content.crop("winter_canola"))["central"] == pytest.approx(np.median(harvested))
    for cid in ("lentils", "chickpeas", "spring_peas"):
        assert fm.need(content.crop(cid))["central"] == pytest.approx(
            np.median(fm.base.supply_for("0_100cm", "apr_jul", "harvested")))
    sw = content.crop("spring_wheat")
    assert fm.reference_kinds("spring_wheat") == ["harvested"]
    assert fm.need(sw)["central"] == pytest.approx(np.median(harvested))
    assert fm.need(content.crop("fallow")) is None


@pytest.mark.parametrize("scale", [0.5, 1.0, 1.5])
def test_swapping_spring_crops_does_not_change_the_water_verdict(content, scale):
    s = DailySeries.from_raw(FakeWeather(short=False, scale=scale).daily(0, 0))
    fm = model(content, s, reference=("winter_wheat", "spring_wheat", "chickpeas"))
    mg = margins(content.settings)["water"]
    spring = ["spring_wheat", "spring_barley", "chickpeas", "lentils", "spring_peas", "spring_canola"]
    for a in spring:
        for b in spring:
            qa = water_measure(crops(content, "winter_wheat", "spring_wheat", a), fm)
            qb = water_measure(crops(content, "winter_wheat", "spring_wheat", b), fm)
            assert verdict(qa, qb, mg).value == SAME, (a, b, qa.central, qb.central)


def test_too_dry_uses_the_sourced_water_use(content):
    dry = model(content, DailySeries.from_raw(FakeWeather(short=False, scale=0.4).daily(0, 0)))
    wet = model(content, DailySeries.from_raw(FakeWeather(short=False, scale=1.6).daily(0, 0)))
    lent = content.crop("lentils")
    t = dry.too_dry(lent)
    assert t["use_mm"] == pytest.approx(IN(9.7)) and t["dry"]
    assert t["median_supply_mm"] == pytest.approx(dry.need(lent)["central"])
    assert not wet.too_dry(lent)["dry"]
    assert dry.too_dry(content.crop("winter_wheat")) is None  # no sourced use figure: no caution
    assert "W10" in codes(content, dry, "winter_wheat", "lentils")
    assert "W10" not in codes(content, wet, "winter_wheat", "lentils")


def test_fallow_helps_the_following_wheat(content, series):
    fm = model(content, series)
    after_fallow = water_measure(crops(content, "fallow", "winter_wheat"), fm)
    annual = water_measure(crops(content, "spring_wheat", "winter_wheat"), fm)
    assert after_fallow.central < annual.central
    assert after_fallow.details["slots"] == 1 and annual.details["slots"] == 2
    assert after_fallow.unit == "share" and not after_fallow.higher_is_better
    assert after_fallow.low <= after_fallow.central <= after_fallow.high
    assert any(a.key == "water.short_threshold_in" for a in after_fallow.assumed)
    assert after_fallow.details["highlight_year"] == 2021


def test_drier_scenario_shows_more_shortfalls_needs_unchanged(content, series):
    base = model(content, series)
    dry = model(content, series, rain_pct=-30)
    ww = content.crop("winter_wheat")
    assert dry.need(ww) == base.need(ww)  # needs stay as calibrated on the unchanged record
    rot = crops(content, "spring_peas", "winter_wheat", "spring_wheat")
    assert water_measure(rot, dry).central > water_measure(rot, base).central


def test_dry_region_mode_uses_the_five_driest_recent_years(content, series):
    fm = model(content, series, dry_mode=True)
    ys = fm.window_years
    assert len(ys) == 5 and set(ys) <= set(fm.recent_years)
    p = dict(zip(fm.replay.years, fm.replay.crop_year_precip_mm))
    others = [y for y in fm.recent_years if y not in ys]
    assert max(p[y] for y in ys) <= min(p[y] for y in others)


# ---- soil protection, nitrogen, variety ----------------------------------------------------------------------

def test_soil_protection_formula(content, series):
    fm = model(content, series, tillage="no_till", yields={"winter_wheat": 80, "spring_wheat": 58})
    q = soil_measure(crops(content, "winter_wheat", "fallow"), fm)
    y = units.lb_ac_to_kg_ha(4800)
    ww_res = 1.1274 * y + 1175
    # winter after the wheat: own residue, all of it (persist 1.0); winter after fallow: half carried over
    w = {x["after_position"]: x for x in q.details["winters"]}
    assert w[1]["central"] == pytest.approx(ww_res)
    assert w[2]["central"] == pytest.approx(0.5 * ww_res)
    assert q.central == pytest.approx(0.5 * ww_res) and q.details["weakest"] == [2]
    reduced = soil_measure(crops(content, "winter_wheat", "fallow"),
                           model(content, series, tillage="reduced", yields={"winter_wheat": 80}))
    assert reduced.central == pytest.approx(0.6 * 0.5 * ww_res)
    assert not any(a.key == "residue.default_tillage" for a in reduced.assumed)  # the farmer said so


def test_soil_protection_legume_range_and_cover_crop(content, series):
    fm = model(content, series)
    q = soil_measure(crops(content, "winter_wheat", "lentils", "spring_wheat"), fm)
    assert q.low < q.central < q.high
    lent = [w for w in q.details["winters"] if w["after_crop"] == "Lentils"][0]
    lo_res, hi_res = units.lb_ac_to_kg_ha(1500), units.lb_ac_to_kg_ha(2000)
    ww_res = fm.residue(content.crop("winter_wheat"))[0][1]
    # reduced tillage (default) × (lentil residue × persist + half the wheat residue from the year before)
    assert lent["low"] == pytest.approx(0.6 * (lo_res * 0.33 + 0.5 * ww_res))
    assert lent["high"] == pytest.approx(0.6 * (hi_res * 0.75 + 0.5 * ww_res))
    after_sw = [w for w in q.details["winters"] if w["after_crop"] == "Spring wheat"][0]
    assert after_sw["low"] == after_sw["high"]  # lentil residue does not carry into a second winter
    cov = soil_measure(crops(content, "cover_crop", "winter_wheat"), fm)
    w = {x["after_role"]: x for x in cov.details["winters"]}
    assert w["cover_crop"]["central"] == pytest.approx(units.lb_ac_to_kg_ha(3000))
    assert any(a.key == "residue.cover_crop_winter_lb_ac" for a in cov.assumed)


def test_nitrogen_tiers_ranges_and_average(content, series):
    fm = model(content, series, yields={"spring_peas": 2600})
    q = nitrogen_measure(crops(content, "winter_wheat", "spring_peas", "spring_wheat"), fm)
    assert units.kg_ha_to_lb_ac(q.central) == pytest.approx(20 / 3)  # 20 lb above 2,500 lb of peas, over 3 years
    fm2 = model(content, series, yields={"spring_peas": 1000})
    assert units.kg_ha_to_lb_ac(nitrogen_measure(crops(content, "winter_wheat", "spring_peas"), fm2).central) == pytest.approx(5)
    # Addendum item 2: chickpeas give 15 lb above 2,000 lb/ac, 10 below; winter peas 30 above 3,750 lb/ac.
    chick = nitrogen_measure(crops(content, "winter_wheat", "chickpeas"), fm)  # 1,200 lb regional yield
    assert units.kg_ha_to_lb_ac(chick.central) == pytest.approx(5)
    hi = model(content, series, yields={"chickpeas": 2400, "winter_peas": 4000})
    assert units.kg_ha_to_lb_ac(nitrogen_measure(crops(content, "winter_wheat", "chickpeas"), hi).central) == pytest.approx(7.5)
    assert units.kg_ha_to_lb_ac(nitrogen_measure(crops(content, "winter_wheat", "winter_peas"), hi).central) == pytest.approx(15)
    wp = nitrogen_measure(crops(content, "winter_peas", "winter_wheat"), fm)
    assert any(a.key == "nitrogen:winter_peas" for a in wp.assumed)  # the spring pea tiers, assumed
    assert nitrogen_measure(crops(content, "fallow", "winter_wheat"), fm).central == 0
    assert q.details["demanding_years"] == 2


def test_variety_groups_and_cyclic_grass_run(content):
    q = variety_measure(crops(content, "winter_wheat", "spring_wheat", "chickpeas"))
    assert q.details["groups"] == 3 - 1 + 1 and q.details["grass_run"] == 2
    q2 = variety_measure(crops(content, "spring_wheat", "lentils", "winter_wheat"))  # WW wraps onto SW
    assert q2.details["grass_run"] == 2
    q3 = variety_measure(crops(content, "winter_wheat", "fallow"))
    assert q3.details["groups"] == 1 and q3.details["grass_run"] == 1  # fallow belongs to no group
    q4 = variety_measure(crops(content, "winter_wheat", "winter_canola", "spring_peas", "spring_barley"))
    assert q4.details["groups"] == 4
    # more groups beats a shorter run
    assert verdict(q4, q, 0).value == BETTER


# ---- comparison --------------------------------------------------------------------------------------------------

def Q(c, lo=None, hi=None, hib=True, assumed=False):
    return Quantity("x", c if lo is None else lo, c, c if hi is None else hi, hib, "u",
                    [Assumed("k", "t")] if assumed else [])


def test_verdict_uses_central_values_and_margin():
    assert verdict(Q(10), Q(5), 2).value == BETTER
    assert verdict(Q(6), Q(5), 2).value == SAME
    assert verdict(Q(2), Q(5), 2).value == WORSE
    assert verdict(Q(0.1, hib=False), Q(0.3, hib=False), 0.07).value == BETTER  # less short is better
    na = Quantity("x", float("nan"), float("nan"), float("nan"), True, "u", assessed=False)
    assert verdict(na, Q(5), 1).value is None and verdict(na, Q(5), 1).word == "not assessed"


def test_assumed_values_never_decide_alone():
    # Better on central values; at the unfavourable ends (A low, B high) it would not be.
    v = verdict(Q(10, 4, 12, assumed=True), Q(5, 3, 9), 2)
    assert v.value == SAME and v.held_by_assumed and v.central_value == BETTER
    # Same ranges, but nothing assumed: the central verdict stands.
    assert verdict(Q(10, 4, 12), Q(5, 3, 9), 2).value == BETTER
    # Assumed, but the verdict survives the unfavourable ends.
    v2 = verdict(Q(20, 18, 22, assumed=True), Q(5, 3, 9), 2)
    assert v2.value == BETTER and not v2.held_by_assumed
    # Addendum 2, A2: the rule works one way only. Worse stays worse, shown "probably worse".
    v3 = verdict(Q(1, 0, 6), Q(5, 4, 6, assumed=True), 2)
    assert v3.value == WORSE and v3.probably and v3.word == "probably worse" and not v3.held_by_assumed
    t = Table.build([{"water": Q(1, 0, 6), "soil": Q(1), "nitrogen": Q(1), "variety": Q(1)},
                     {"water": Q(5, 4, 6, assumed=True), "soil": Q(1), "nitrogen": Q(1), "variety": Q(1)}], [1, 1],
                    {"water": 2, "soil": 0, "nitrogen": 0, "variety": 0})
    assert t.verdicts_vs(1, "water")[0] == WORSE  # counted as worse for dominance
    v4 = verdict(Q(1, 0.5, 1.5), Q(5, 4, 6, assumed=True), 2)
    assert v4.value == WORSE and not v4.probably


def test_dominance_requires_as_many_harvests(content):
    mg = {"water": 0.07, "soil": 500, "nitrogen": 2, "variety": 0}

    def scores(water, soil, n, var):
        return {"water": Q(water, hib=False), "soil": Q(soil), "nitrogen": Q(n), "variety": Q(var)}
    fallowy = scores(0.0, 2000, 0, 100)  # less short of water, nothing else worse ...
    annual = scores(0.3, 2000, 0, 100)
    t = Table.build([fallowy, annual], [1, 2], mg)  # ... but one harvest instead of two
    assert not t.dominated(1)
    t2 = Table.build([fallowy, annual], [2, 2], mg)
    assert t2.dominated(1) and not t2.dominated(0)
    same = Table.build([annual, annual], [2, 2], mg)
    assert not same.dominated(0) and not same.dominated(1)  # equal is not dominated
    held = Table.build([scores(0.0, 2000, 0, 100), {**annual, "water": Q(0.3, 0.0, 0.4, hib=False, assumed=True)}],
                       [2, 2], mg)
    assert not held.dominated(1)  # the water difference depends on an assumed figure


def test_ordering_follows_priorities_then_quantity():
    v = lambda w, s: {"water": type("V", (), {"value": w})(), "soil": type("V", (), {"value": s})(),
                      "nitrogen": type("V", (), {"value": 0})(), "variety": type("V", (), {"value": 0})()}
    q = {"water": Q(0.1, hib=False), "soil": Q(1000), "nitrogen": Q(0), "variety": Q(100)}
    a = order_key(v(BETTER, WORSE), q, ["water", "soil", "nitrogen", "variety"], 2, 0, False)
    b = order_key(v(SAME, BETTER), q, ["water", "soil", "nitrogen", "variety"], 2, 0, False)
    assert a < b
    a2 = order_key(v(BETTER, WORSE), q, ["soil", "water", "nitrogen", "variety"], 2, 0, False)
    b2 = order_key(v(SAME, BETTER), q, ["soil", "water", "nitrogen", "variety"], 2, 0, False)
    assert b2 < a2
    # dry region mode: ties go to more harvests
    assert order_key(v(SAME, SAME), q, ["water"], 3, 0, True) < order_key(v(SAME, SAME), q, ["water"], 2, 0, True)


def test_bands_and_selection_fill_empty_band():
    assert [band_of(d, 3, 0.34, 0.67) for d in (0.5, 1, 1.5, 2, 2.5, 3)] == [0, 0, 1, 1, 2, 2]
    mg = {"water": 0.07, "soil": 500, "nitrogen": 2, "variety": 0}
    s = lambda soil: {"water": Q(0.1, hib=False), "soil": Q(soil), "nitrogen": Q(0), "variety": Q(100)}
    rows = [s(3000), s(2900), s(2800), s(1000)]  # the last row is the current rotation
    t = Table.build(rows, [2, 2, 2, 2], mg)
    sel = select([0, 1, 2], [0, 0, 2], t, 3, 3, 3)  # no moderate change exists
    assert sel.shown == [0, 2, 1] and sel.shown_bands == [0, 2, 0] and sel.filled_from_other_band == [1]


def test_changing_a_constant_needs_no_code_change(tmp_path, series):
    d = tmp_path / "data"
    shutil.copytree(DATA_DIR, d)
    text = (d / "settings.yaml").read_text().replace("short_threshold_in:\n    value: 1.5", "short_threshold_in:\n    value: 0.1")
    (d / "settings.yaml").write_text(text)
    c1, c2 = load_content(DATA_DIR), load_content(d)
    rot = ["fallow", "winter_wheat"]
    q1 = water_measure(crops(c1, *rot), model(c1, series))
    q2 = water_measure(crops(c2, *rot), model(c2, series))
    assert q2.central > q1.central


# ---- warnings ------------------------------------------------------------------------------------------------------

def codes(content, fm, *ids):
    return {w.code: w for w in W.evaluate(crops(content, *ids), fm, content.warnings)}


def test_brief_example_ww_sw_chickpeas_warns_w1(content, series):
    fm = model(content, series)
    ws = codes(content, fm, "winter_wheat", "spring_wheat", "chickpeas")
    assert "W1" in ws and "W8" in ws and "W5" in ws
    assert "W1" not in codes(content, fm, "winter_wheat", "spring_wheat", "chickpeas", "spring_barley")


def test_w3_w9_w10_dry(content):
    dry = DailySeries.from_raw(FakeWeather(short=False, scale=0.4).daily(0, 0))
    fm = model(content, dry)
    assert units.mm_to_in(fm.mean_precip_mm) < 12
    ws = codes(content, fm, "spring_canola", "winter_wheat", "spring_peas", "spring_wheat", "lentils")
    assert {"W3", "W9", "W10"} <= set(ws) and "W2" not in ws
    wet = model(content, DailySeries.from_raw(FakeWeather(short=False, scale=1.5).daily(0, 0)))
    assert not ({"W3", "W9"} & set(codes(content, wet, "spring_canola", "winter_wheat", "spring_peas")))


def test_w4_uses_the_farmers_ph_only(content, series):
    unknown = codes(content, model(content, series), "lentils", "winter_wheat")
    assert unknown["W4"].key == "W4u" and unknown["W4"].priority > 50  # says pH is unknown, low priority
    acid = W.evaluate(crops(content, "lentils", "winter_wheat", "chickpeas"), model(content, series, ph=5.5),
                      content.warnings)
    keys = [w.key for w in acid if w.code == "W4"]
    assert keys == ["W4:lentils"]  # 5.5 < 5.7 for lentils; wheat (5.2–5.4) is fine; chickpeas have no figure
    assert not [w for w in W.evaluate(crops(content, "chickpeas", "winter_wheat"), model(content, series, ph=4.5),
                                      content.warnings) if w.key.startswith("W4:chick")]


def test_w5_w6_are_frequencies_and_follow_temperature(content, series):
    fm = model(content, series)
    w5 = codes(content, fm, "chickpeas", "winter_wheat")["W5"]
    assert "of 15 years" in w5.short and "of the last 15 years" in w5.text
    hit, of = fm.heat_frequency("W5")
    assert of == 15 and 1 <= hit < 15  # the fake's hot 2021 is in there
    hot = model(content, series, temp_f=5)
    assert hot.heat_frequency("W5")[0] >= hit
    assert hot.heat_frequency("W6")[0] <= fm.heat_frequency("W6")[0]  # warmer nights, fewer winter-kill nights
    assert "W6" in codes(content, fm, "winter_peas", "winter_wheat")


def test_w7_poor_drainage(content, series):
    poor = field_soil(FakeSoil(drainage="Somewhat poorly drained").soil({}), content.settings)
    fm = model(content, series, soil=poor)
    assert "W7" in codes(content, fm, "spring_peas", "winter_wheat")
    assert "W7" not in codes(content, model(content, series), "spring_peas", "winter_wheat")


def test_w8_herbicide_note(content, series):
    fm = model(content, series)
    assert "W8" in codes(content, fm, "winter_wheat", "lentils")
    assert "W8" in codes(content, fm, "lentils", "spring_canola", "winter_wheat")
    assert "W8" not in codes(content, fm, "fallow", "winter_wheat")


# ---- display edge --------------------------------------------------------------------------------------------------

def test_share_words():
    assert present.share_words(0.2) == "about 1 crop in 5"
    assert present.share_words(0.4) == "about 2 crops in 5"
    assert present.share_words(0.0) == "no crop"
    assert present.share_words(0.02) == "fewer than 1 crop in 20"
    assert present.share_words(1.0) == "every crop"
    assert present.inch(25.4) == "1.0 in"
    assert present.lbac(units.lb_ac_to_kg_ha(1234)) == "1,200 lb/acre"
