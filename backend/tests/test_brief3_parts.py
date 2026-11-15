"""Brief 3, parts A to E: done-criteria that can be checked offline (section 11)."""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile

import numpy as np
import pytest

from fieldshift.core import fitting, records, units
from fieldshift.core.content import load_content
from fieldshift.core.geometry import field_from_spec
from fieldshift.core.records import Record
from fieldshift.core.service import FieldService, Providers
from fieldshift.core.weather import DailySeries
from fieldshift.core.yearindex import build_index

from .fakes import DATA_DIR, FIELD, FakeCrops, FakeRegion, FakeSoil, FakeVegetation, FakeWeather


@pytest.fixture(scope="module")
def content():
    return load_content(DATA_DIR)


@pytest.fixture(scope="module")
def service(content):
    return FieldService(content, Providers(FakeRegion(), FakeCrops(), FakeWeather(short=False), FakeVegetation(),
                                           soil=FakeSoil()), today=dt.date(2026, 11, 14))


@pytest.fixture(scope="module")
def field():
    return field_from_spec({"type": "polygon", "geometry": FIELD})


@pytest.fixture(scope="module")
def series():
    return DailySeries.from_raw(FakeWeather(short=False).daily(0, 0))


CAP = {"0_100cm": 200.0, "0_150cm": 300.0}


def yi(content, series):
    return build_index(series, CAP, content.settings)


def recs(*rows):
    return [Record(y, c, v, r) for y, c, v, r in rows]


def test_no_records_and_outside_the_season_window_change_nothing(service, field):
    a = service.strategies(field, {})
    b = service.strategies(field, {"records": [], "fit": True})
    strip = lambda s: {k: v for k, v in s.items() if k not in ("inputs", "generation", "records")}  # noqa: E731
    assert strip(a) == strip(b)
    assert service.season(field, {})["status"] == "hidden"  # 14 November: outside 1 January to 31 May


def test_blend_weight_is_exactly_n_eff_over_n_eff_plus_k(content, series):
    idx = yi(content, series)
    rs = recs((2020, "winter_wheat", 5000, None), (2022, "winter_wheat", 5200, None), (2024, "winter_wheat", 4700, None))
    w = fitting.weigh(rs, idx, {}, content, 2026)
    lv = fitting.farm_levels(w, {"winter_wheat": 1.0}, content, {"winter_wheat": units.lb_ac_to_kg_ha(4800)})["winter_wheat"]
    n_eff = sum(x.weight for x in w)
    assert lv.w == pytest.approx(n_eff / (n_eff + 5))
    assert lv.level_kg_ha == pytest.approx(lv.w * lv.farm_level_kg_ha + (1 - lv.w) * units.lb_ac_to_kg_ha(4800))


def test_one_extreme_record_moves_the_level_by_its_share_only(content, series):
    idx = yi(content, series)
    reg = units.lb_ac_to_kg_ha(4800)
    w = fitting.weigh(recs((2024, "winter_wheat", 40000, None)), idx, {}, content, 2026)
    lv = fitting.farm_levels(w, {"winter_wheat": 1.0}, content, {"winter_wheat": reg})["winter_wheat"]
    assert lv.w <= 1 / 6 + 1e-9  # one full-weight record: at most 1 / (1 + k)
    assert lv.level_kg_ha - reg == pytest.approx(lv.w * (lv.farm_level_kg_ha - reg))


def test_hail_is_left_out_of_fitting_and_still_charted(content, series):
    idx = yi(content, series)
    rs = recs((2020, "winter_wheat", 5000, None), (2021, "winter_wheat", 1500, "hail_frost"))
    w = fitting.weigh(rs, idx, {}, content, 2026)
    assert w[1].weight == 0 and w[0].weight > 0
    lv = fitting.farm_levels(w, {"winter_wheat": 1.0}, content, {"winter_wheat": units.lb_ac_to_kg_ha(4800)})
    cmp = fitting.compare_records(w, lv, {"winter_wheat": 1.0}, content)
    assert [r["year"] for r in cmp["rows"]] == [2020, 2021] and cmp["rows"][1]["reason"] == "hail_frost"
    unknown = fitting.weigh(recs((2021, "winter_wheat", 1500, "unknown")), idx, {}, content, 2026)[0]
    assert unknown.reason_w == 0.5


def test_ageing_ten_years_halves_the_weight(content, series):
    idx = yi(content, series)
    rs = recs((2018, "winter_wheat", 5000, None), (2020, "spring_wheat", 3500, None))
    a = sum(x.weight for x in fitting.weigh(rs, idx, {}, content, 2026))
    b = sum(x.weight for x in fitting.weigh(rs, idx, {}, content, 2036))
    assert b == pytest.approx(a / 2)


def test_typed_and_uploaded_and_total_give_the_same_record(service, field, content):
    acres = units.ha_to_acres(field.area_ha())
    typed = service.check_records(field, [{"year": 2022, "crop": "winter_wheat", "value": 70, "unit": "bu"},
                                          {"year": 2021, "crop": "lentils", "value": round(1100 * acres), "unit": "lb",
                                           "basis": "total"}])["rows"]
    sheet = records.write_xlsx(records.template_rows([(2022, "Winter wheat", "bu"), (2021, "Lentils", "lb")]))
    # Fill the harvest column of the downloaded blank sheet, as a farmer would, then load it.
    z = zipfile.ZipFile(io.BytesIO(sheet))
    xml = z.read("xl/worksheets/sheet1.xml").decode()
    xml = xml.replace('<row r="2"><c r="A2"><v>2022</v></c><c r="B2" t="inlineStr"><is><t>Winter wheat</t></is></c>',
                      '<row r="2"><c r="A2"><v>2022</v></c><c r="B2" t="inlineStr"><is><t>Winter wheat</t></is></c><c r="C2"><v>70</v></c>')
    xml = xml.replace('<c r="E3" t="inlineStr"><is><t>per acre</t></is></c>',
                      f'<c r="E3" t="inlineStr"><is><t>total</t></is></c>').replace(
        '<row r="3"><c r="A3"><v>2021</v></c><c r="B3" t="inlineStr"><is><t>Lentils</t></is></c>',
        f'<row r="3"><c r="A3"><v>2021</v></c><c r="B3" t="inlineStr"><is><t>Lentils</t></is></c><c r="C3"><v>{round(1100 * acres)}</v></c>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            out.writestr(n, xml if n == "xl/worksheets/sheet1.xml" else z.read(n))
    up = service.read_records(field, "harvests.xlsx", buf.getvalue())["rows"]
    t = {(r["year"], r["crop"]): r["yield_lb_ac"] for r in typed}
    u = {(r["year"], r["crop"]): r["yield_lb_ac"] for r in up if r["status"] == "ok"}
    assert t == u
    assert t[(2022, "winter_wheat")] == pytest.approx(70 * 60)
    assert t[(2021, "lentils")] == pytest.approx(1100, rel=0.01)  # the total divided by the field's area


def test_bad_rows_and_macro_workbooks(service, field):
    text = "Year,Crop,Yield (bu/ac)\n2022,winter wheat,72\n2021,mystery crop,50\n2020,spring wheat,-3\n2019,barley,61\n"
    rows = service.read_records(field, "mine.csv", text.encode())["rows"]
    by = {r["year"]: r for r in rows}
    assert by[2022]["status"] == "ok" and by[2019]["status"] == "ok"
    assert by[2021]["status"] == "error" and "not recognised" in by[2021]["reason"]
    assert by[2020]["status"] == "error" and "zero or less" in by[2020]["reason"]
    assert by[2019]["yield_lb_ac"] == pytest.approx(61 * 48)  # barley bushels are 48 lb
    with pytest.raises(records.FileRefused):
        service.read_records(field, "macro.xlsm", b"PK\x03\x04whatever")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types>macroEnabled</Types>")
        z.writestr("xl/vbaProject.bin", b"\x00")
    with pytest.raises(records.FileRefused):
        service.read_records(field, "renamed.xlsx", buf.getvalue())
    big = service.read_records(field, "x.csv", "Year,Crop,Yield\n2022,winter wheat,900\n".encode())["rows"][0]
    assert big["status"] == "confirm"  # above three times the typical yield: kept only if confirmed


def _cereal_records(content, series, years, noise=0.0, ew=0.70):
    """Records generated from the model with a known e_winter."""
    t = fitting._index_table(series, CAP, content, ew, 1.0)
    out = []
    rng = np.random.default_rng(1)
    for y in years:
        x = t.at(y, "autumn", "harvested")
        out.append(Record(y, "winter_wheat", 4800 * max(0.05, 1 + x) * (1 + rng.normal(0, noise)), None))
    return out


def test_similar_years_move_a_fitted_constant_less(content, series):
    idx = yi(content, series)
    var = float(np.var(idx.series("autumn", "harvested")))
    order = np.argsort(idx.series("autumn", "harvested"))
    yrs = [int(y) for y in idx.years]
    middle = [yrs[i] for i in order[len(order) // 2 - 3: len(order) // 2 + 3]]
    spread = [yrs[i] for i in order[::len(order) // 6][:6]]
    fits = {}
    for name, ys in (("similar", middle), ("spread", spread)):
        w = fitting.weigh(_cereal_records(content, series, ys), idx, {}, content, 2026)
        fits[name] = fitting.fit_constants(w, series, CAP, content, {"winter_wheat": 1.0}, var, _check=False)
    assert fits["similar"].w_fit < 0.5 * fits["spread"].w_fit
    w = fitting.weigh(_cereal_records(content, series, middle), idx, {}, content, 2026)
    full = fitting.fit_constants(w, series, CAP, content, {"winter_wheat": 1.0}, var)
    assert full.coverage  # the farmer is told the records cover too narrow a range


def test_fitting_is_refused_when_the_self_check_fails(content, series):
    idx = yi(content, series)
    var = float(np.var(idx.series("autumn", "harvested")))
    rng = np.random.default_rng(3)
    noise = [Record(int(y), "winter_wheat", float(rng.uniform(2000, 7000)), None) for y in idx.years[-12:]]
    r = fitting.fit_constants(fitting.weigh(noise, idx, {}, content, 2026), series, CAP, content, {"winter_wheat": 1.0}, var)
    assert not r.applied and "better than your average" in r.message


def test_undo_returns_to_regional_values(service, field):
    ex = service.example_records(field)["records"]
    on = service.strategies(field, {"records": ex, "fit": True})
    off = service.strategies(field, {"records": ex, "fit": False})
    assert off["records"]["constants"] == {} and off["records"]["fit"] is None
    assert on["records"]["fit_on"] is True


def test_borrowed_values_name_their_crops(service, field):
    ex = [r for r in service.example_records(field)["records"] if r["crop"] == "winter_wheat"]
    s = service.strategies(field, {"records": ex, "example_records": True})
    borrowed = [l for l in s["records"]["levels"] if l["borrowed_from"]]
    assert borrowed and all(l["borrowed_from"] == ["Winter wheat"] for l in borrowed)
    text = " ".join(" ".join(e["lines"]) for o in s["options"] for e in o["details"]["evidence"])
    if "borrowed" in text:
        assert "estimated from your winter wheat records" in text
    assert "Example data, not a real farm" in text or "example data" in " ".join(
        e["text"] for o in s["options"] for e in o["first"]["evidence"])


def test_season_replay_dry_and_wet(content, service, field):
    from fieldshift.core import season as S
    from fieldshift.core.replay import build_replay
    thr = units.in_to_mm(1.5)
    dry = build_replay(DailySeries.from_raw(FakeWeather(short=False, scale=0.45).daily(0, 0)),
                       {"0_100cm": 200, "0_150cm": 300}, content.settings)
    r = S.replay_check(S.past_years(dry, "harvested", "0_150cm", "apr_jun", thr))
    # Synthetic weather: about half caught. On the real dry-west example field the check caught 5 of 8.
    assert r["refill_share"] < 2 / 3 and r["caught"] >= 0.4 * r["short_years"] and r["false_alarms"] <= r["caught"]
    wet = build_replay(DailySeries.from_raw(FakeWeather(short=False, scale=1.6).daily(0, 0)),
                       {"0_100cm": 150, "0_150cm": 220}, content.settings)
    assert S.replay_check(S.past_years(wet, "harvested", "0_150cm", "apr_jun", thr))["refill_share"] >= 2 / 3
    assert S.min_stored_guideline(content.settings, 15.2)["spring_in"] == 3.0  # [S27] Table 5-11, 14 to 16 in


def test_no_output_is_worded_as_a_forecast(service, field):
    s = service.strategies(field, {"records": service.example_records(field)["records"], "fit": True})
    blob = str(s).lower()
    assert not re.search(r"\b(will yield|next year will|we predict|forecast(s|ed)? (that|a yield))\b", blob)
