"""Station check: ACIS parsing (offline, canned replies) and the pure comparison logic."""
from __future__ import annotations

import datetime as dt

import pytest

from fieldshift.core import station as st
from fieldshift.providers.us import acis

# ---------------------------------------------------------------- ACIS parsing

META_REPLY = {"meta": [
    {"ll": [-117.1861, 46.76016], "sids": ["456789 2", "USC00456789 6", "PLMW1 7"], "elev": 2515.0,
     "valid_daterange": [["1940-10-21", "2026-11-12"]], "name": "PULLMAN 2 NW"},
    {"ll": [-117.35528, 46.88251], "sids": ["US1WAWM0001 6", "WAWM0001 10"], "elev": 2204.0,
     "valid_daterange": [["2008-07-01", "2016-07-08"]], "name": "COLFAX 0.4 ESE"},
    {"sids": ["999999 2"], "name": "NO LOCATION", "valid_daterange": [["1950-01-01", "2020-01-01"]]},
]}

DATA_REPLY = {
    "meta": {"uid": 25794, "ll": [-117.1861, 46.76016], "sids": ["456789 2", "USC00456789 6"],
             "state": "WA", "elev": 2515.0, "name": "PULLMAN 2 NW"},
    "data": [
        ["1983-10-07", "0.00", "50", "32"],
        ["1983-10-08", "S", "M", "30"],
        ["1983-10-09", "M", "M", "M"],
        ["1983-10-10", "0.10A", "212", "-40"],
        ["1983-10-11", "T", "41", "23"],
    ],
}


@pytest.mark.parametrize("raw, mm, flag", [
    ("M", None, "M"),
    ("T", 0.0, "T"),
    ("S", None, "S"),
    ("0.62A", 15.75, "A"),
    ("TA", 0.0, "A"),
    ("0.10", 2.54, None),
    ("1", 25.4, None),
    ("0.1X", None, "M"),
    ("", None, "M"),
    (None, None, "M"),
    ("-0.5", None, "M"),
])
def test_parse_precip(raw, mm, flag):
    assert acis.parse_precip(raw) == (mm, flag)


def test_parse_temp_converts_fahrenheit():
    assert acis.parse_temp("32") == 0.0
    assert acis.parse_temp("212") == 100.0
    assert acis.parse_temp("-40") == -40.0
    assert acis.parse_temp("M") is None
    assert acis.parse_temp("50A") is None


def test_parse_stations():
    stations = acis.parse_stations(META_REPLY)
    assert [s["id"] for s in stations] == ["USC00456789", "US1WAWM0001"]  # GHCN id preferred; no-ll dropped
    p = stations[0]
    assert p["lon"] == -117.1861 and p["lat"] == 46.76016
    assert p["elevation_m"] == pytest.approx(2515 * 0.3048, abs=0.05)
    assert p["valid_daterange"] == [["1940-10-21", "2026-11-12"]]


@pytest.mark.parametrize("reply", [{"error": "99"}, {"nometa": []}, ["not", "a", "dict"], None])
def test_parse_stations_rejects_unusable_reply(reply):
    with pytest.raises(RuntimeError):
        acis.parse_stations(reply)


def test_parse_daily():
    out = acis.parse_daily(DATA_REPLY, "USC00456789")
    days = {d["date"]: d for d in out["days"]}
    assert days["1983-10-08"]["precip_flag"] == "S" and days["1983-10-08"]["precip_mm"] is None
    assert days["1983-10-09"]["precip_flag"] == "M"
    assert days["1983-10-10"]["precip_flag"] == "A" and days["1983-10-10"]["precip_mm"] == 2.54
    assert days["1983-10-10"]["tmax_c"] == 100.0 and days["1983-10-10"]["tmin_c"] == -40.0
    assert days["1983-10-11"]["precip_mm"] == 0.0 and days["1983-10-11"]["precip_flag"] == "T"
    assert out["station"]["name"] == "PULLMAN 2 NW"
    assert out["calendar"] == "standard"


@pytest.mark.parametrize("reply", [
    {"error": "no data available"},
    {"meta": {}, "data": []},
    {"data": [["1983-10-07", "0.00"]]},
    {"data": [["10/07/1983", "0.00", "50", "32"]]},
])
def test_parse_daily_rejects_unusable_reply(reply):
    with pytest.raises(RuntimeError):
        acis.parse_daily(reply, "X")


def test_acis_requests(monkeypatch):
    calls = []

    def fake_post(url, body, timeout=120, attempts=3):
        calls.append((url, body))
        return META_REPLY if url.endswith("StnMeta") else DATA_REPLY

    monkeypatch.setattr(acis, "post_json", fake_post)
    client = acis.AcisStations()
    assert client.stations("53075")["stations"][0]["id"] == "USC00456789"
    assert calls[0][1] == {"county": "53075", "meta": "name,sids,ll,elev,valid_daterange", "elems": "pcpn"}
    client.daily("USC00456789", "1983-10-07", "1983-10-11")
    body = calls[1][1]
    assert body["sid"] == "USC00456789" and body["sdate"] == "1983-10-07" and body["edate"] == "1983-10-11"
    assert [e["name"] for e in body["elems"]] == ["pcpn", "maxt", "mint"]
    with pytest.raises(ValueError):
        client.stations("530")


# ----------------------------------------------------------- accumulation rules

def _days(start: dt.date, values: list) -> list[dict]:
    """Station payload days from (mm, flag) pairs or plain numbers."""
    out = []
    for i, v in enumerate(values):
        mm, flag = v if isinstance(v, tuple) else (v, None)
        out.append({"date": (start + dt.timedelta(days=i)).isoformat(), "precip_mm": mm, "precip_flag": flag})
    return out


def _usable(days, start_month=9):
    dates, vals, flags = st._parse_station_days(days)
    return st.usable_for_totals(dates, vals, flags, start_month)


def test_accumulation_run_counts_as_a_whole():
    d0 = dt.date(2000, 10, 1)
    u = _usable(_days(d0, [1.0, (None, "S"), (None, "M"), (None, "M"), (6.0, "A"), (0.0, "T")]))
    assert u["usable"] == [True, True, True, True, True, True]
    assert u["amount"] == [1.0, 0.0, 0.0, 0.0, 6.0, 0.0]
    assert u["runs_used"] == 1 and u["runs_rejected"] == 0
    assert u["run"][1:5] == [1, 1, 1, 1] and u["run"][0] == -1


def test_accumulation_without_total_or_start_is_unusable():
    d0 = dt.date(2000, 10, 1)
    # S never closed by an A: the rain was not reported
    u = _usable(_days(d0, [(None, "S"), (None, "M"), 2.0]))
    assert u["usable"] == [False, False, True] and u["runs_rejected"] == 1
    # an A with no S before it: its period is unknown
    u = _usable(_days(d0, [1.0, (None, "M"), (4.0, "A"), 1.0]))
    assert u["usable"] == [True, False, False, True] and u["runs_rejected"] == 1


def test_accumulation_across_crop_years_is_unusable():
    u = _usable(_days(dt.date(2000, 8, 30), [(None, "S"), (None, "M"), (5.0, "A"), 1.0]), start_month=9)
    assert u["usable"] == [False, False, False, True]
    u = _usable(_days(dt.date(2000, 8, 30), [(None, "S"), (None, "M"), (5.0, "A"), 1.0]), start_month=1)
    assert u["usable"] == [True, True, True, True]


# --------------------------------------------------------------- crop-year totals

def _span(a: dt.date, b: dt.date) -> list[dt.date]:
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


def _grid(a: dt.date, b: dt.date, mm: float) -> dict:
    """A Daymet-like payload: 31 December dropped in leap years."""
    days = [{"date": d.isoformat(), "precip_mm": mm, "tmax_c": 10.0, "tmin_c": 0.0}
            for d in _span(a, b) if not (d.month == 12 and d.day == 31 and d.year % 4 == 0)]
    return {"days": days, "calendar": "365_day", "source": "test grid"}


def _station_days(a: dt.date, b: dt.date, mm: float, missing: set[dt.date] = frozenset()) -> list[dict]:
    return [{"date": d.isoformat(), "precip_mm": None if d in missing else mm,
             "precip_flag": "M" if d in missing else None} for d in _span(a, b)]


def test_compare_totals_same_days_and_completeness():
    a, b = dt.date(2019, 9, 1), dt.date(2021, 8, 31)  # crop years 2020 and 2021
    gap = {dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(10)}  # 10 days out of crop year 2020
    comp = st.compare_totals(_station_days(a, b, 1.0, gap), _grid(a, b, 1.1), min_complete_fraction=0.98)
    assert [r["year"] for r in comp["rows"]] == [2021]
    assert [e["year"] for e in comp["excluded"]] == [2020]
    row = comp["rows"][0]
    # crop year 2021 holds 31 Dec 2020, which the grid leaves out by design: not counted against it
    assert row["days_expected"] == 364 and row["days_compared"] == 364
    assert row["station_mm"] == pytest.approx(364.0) and row["grid_mm"] == pytest.approx(400.4)
    # a looser threshold keeps 2020, summing both sources over the same 356 days
    comp = st.compare_totals(_station_days(a, b, 1.0, gap), _grid(a, b, 1.1), min_complete_fraction=0.95)
    r2020 = comp["rows"][0]
    assert r2020["year"] == 2020 and r2020["days_compared"] == 356 and r2020["days_expected"] == 366
    assert r2020["station_mm"] == pytest.approx(356.0) and r2020["grid_mm"] == pytest.approx(391.6)


def test_compare_totals_only_whole_crop_years_in_both_records():
    comp = st.compare_totals(_station_days(dt.date(2019, 9, 15), dt.date(2022, 8, 31), 1.0),
                             _grid(dt.date(2019, 1, 1), dt.date(2021, 12, 31), 1.0))
    assert [r["year"] for r in comp["rows"]] == [2021]


def test_compare_totals_accumulation_uses_grid_over_whole_run():
    a, b = dt.date(2018, 9, 1), dt.date(2019, 8, 31)
    days = _station_days(a, b, 1.0)
    i = (dt.date(2019, 3, 10) - a).days
    days[i].update(precip_mm=None, precip_flag="S")
    days[i + 1].update(precip_mm=None, precip_flag="M")
    days[i + 2].update(precip_mm=3.0, precip_flag="A")
    comp = st.compare_totals(days, _grid(a, b, 1.0), min_complete_fraction=1.0)
    row = comp["rows"][0]
    assert row["station_mm"] == pytest.approx(365.0) and row["grid_mm"] == pytest.approx(365.0)
    assert row["accumulated_days"] == 3 and comp["runs_used"] == 1


# ---------------------------------------------------------------- station choice

FIELD = (-117.2383, 46.8473)


def _station(sid, lon, lat, start="1940-01-01", end="2026-11-01", name=None):
    return {"id": sid, "name": name or sid, "lon": lon, "lat": lat, "elevation_m": 700.0,
            "valid_daterange": [[start, end]]}


def test_distance_km():
    assert st.distance_km(0, 0, 0, 1) == pytest.approx(111.195, abs=0.01)
    assert st.distance_km(-117.1861, 46.76016, -117.883, 46.8167) == pytest.approx(53.5, abs=1.0)


def test_candidate_stations_filters_and_orders():
    stations = [
        _station("FAR", -118.5, 46.8),  # about 96 km away
        _station("SHORT", -117.24, 46.85, start="2015-01-01"),  # nearest but short record
        _station("B", -117.18, 46.76),
        _station("A", -117.35, 46.88),
    ]
    period = (dt.date(1980, 9, 1), dt.date(2025, 8, 31))
    got = st.candidate_stations(stations, *FIELD, period=period, min_years=20, max_distance_km=40)
    assert [s["id"] for s in got] == ["A", "B"]
    assert got[0]["distance_km"] < got[1]["distance_km"]
    assert got[0]["record_years"] == pytest.approx(45.0, abs=0.1)  # counted inside the period only


def test_display_name():
    assert st.display_name("PULLMAN 2 NW") == "Pullman 2 NW"
    assert st.display_name("ST. JOHN") == "St. John"
    assert st.display_name("PULLMAN MOSCOW REGIONAL AP") == "Pullman Moscow Regional AP"


def _long_payloads(first_cy: int, last_cy: int, wet: float, station_mm: dict, gaps: dict):
    a, b = dt.date(first_cy - 1, 9, 1), dt.date(last_cy, 8, 31)
    grid = _grid(a, b, wet)
    payloads = {sid: _station_days(a, b, mm, gaps.get(sid, set())) for sid, mm in station_mm.items()}
    return grid, payloads


def test_station_check_picks_nearest_with_enough_complete_years():
    # the nearest station has a gap every year, so it never has a complete crop year
    gaps = {"NEAR": {dt.date(y, 1, d) for y in range(1980, 2006) for d in range(1, 15)}}
    grid, payloads = _long_payloads(1981, 2005, 1.05, {"NEAR": 1.0, "NEXT": 1.0, "THIRD": 2.0}, gaps)
    stations = [_station("THIRD", -117.5, 46.9), _station("NEXT", -117.18, 46.76, name="PULLMAN 2 NW"),
                _station("NEAR", -117.24, 46.85)]
    fetched = []

    def fetch(sid, a, b):
        fetched.append((sid, a, b))
        return {"days": payloads[sid]}

    out = st.station_check(stations, fetch, grid, *FIELD, min_years=20)
    assert out["status"] == "ok"
    assert out["station"]["id"] == "NEXT" and out["station"]["name"] == "Pullman 2 NW"
    assert [f[0] for f in fetched] == ["NEAR", "NEXT"]  # stops at the first usable one
    assert fetched[0][1:] == ("1980-09-01", "2005-08-31")
    assert out["candidates_tried"][0]["outcome"].startswith("only 0")
    assert out["years_compared"] == 25 and out["first_year"] == 1981 and out["last_year"] == 2005
    assert out["percent_difference"] == pytest.approx(5.0, abs=0.01)
    assert out["within_tolerance"] is True
    assert out["grid_mean_in"] == pytest.approx(out["grid_mean_mm"] / 25.4, abs=0.01)
    assert out["typical_difference_mm"] == pytest.approx(out["station_mean_mm"] * 0.05, rel=0.01)
    assert out["text"].startswith("Over 25 crop years, the grid estimate for your field was within 5% of "
                                  "the Pullman 2 NW weather station, ")
    assert out["text"].endswith("miles away.")
    assert out["parameters"]["min_years"] == 20
    assert set(out["rows"][0]) >= {"year", "label", "station_mm", "grid_mm", "station_in", "grid_in",
                                   "difference_mm", "difference_in"}


def test_station_check_reports_a_large_difference_with_its_direction():
    grid, payloads = _long_payloads(1981, 2005, 1.25, {"S": 1.0}, {})
    out = st.station_check([_station("S", -117.24, 46.84)], lambda sid, a, b: {"days": payloads[sid]},
                           grid, *FIELD)
    assert out["percent_difference"] == pytest.approx(25.0, abs=0.01) and out["within_tolerance"] is False
    assert "25% wetter than the S weather station, less than a mile away." in out["text"]


def test_station_check_no_station_and_fetch_failure():
    grid, _ = _long_payloads(1981, 2005, 1.0, {}, {})

    def boom(sid, a, b):
        raise RuntimeError("ACIS StnData: no data available")

    out = st.station_check([_station("X", -117.24, 46.84)], boom, grid, *FIELD)
    assert out["status"] == "no_station"
    assert out["candidates_tried"][0]["outcome"].startswith("fetch failed")
    assert "No weather station within 25 miles" in out["text"]
    out = st.station_check([], boom, grid, *FIELD)
    assert out["status"] == "no_station" and out["candidates_tried"] == []
