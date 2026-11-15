"""Peak greenness from MODIS 250 m composites: core logic and offline provider geometry."""
from __future__ import annotations

import datetime as dt

import pytest
from shapely.geometry import box, mapping

from fieldshift.core.greenness import peak_greenness, validate_payloads, year_peak
from fieldshift.providers.us.modis import (PIXEL_M, ModisNdvi, tile_transform, tiles_for,
                                           whole_pixel_mask)


def season_curve(year: int, peak: float, peak_doy: int = 150, pixels: int = 6, good: int | None = None,
                 start_doy: int = 1, end_doy: int = 365, step: int = 8) -> list[dict]:
    """Synthetic alternating Terra/Aqua composites with a triangular season."""
    obs = []
    for i, doy in enumerate(range(start_doy, end_doy, step)):
        nd = max(0.15, peak - abs(doy - peak_doy) * 0.006)
        obs.append({"date": (dt.date(year, 1, 1) + dt.timedelta(days=doy - 1)).isoformat(),
                    "ndvi": round(nd, 4), "pixels": pixels, "good_pixels": pixels if good is None else good,
                    "platform": "terra" if i % 2 == 0 else "aqua"})
    return obs


def payload(year: int, observations: list[dict]) -> dict:
    return {"year": year, "observations": observations, "pixel_size_m": PIXEL_M, "source": "test"}


def test_peak_per_year_and_dates():
    raws = [payload(2020, season_curve(2020, 0.80, peak_doy=150)),
            payload(2021, season_curve(2021, 0.55, peak_doy=140))]
    out = peak_greenness(raws)
    assert out["status"] == "ok" and out["whole_pixels"] == 6
    assert out["pixel_size_m"] == pytest.approx(231.656, abs=1e-3)
    y20, y21 = out["years"]
    assert (y20["year"], y21["year"]) == (2020, 2021)
    assert y20["peak_ndvi"] > y21["peak_ndvi"]
    assert y20["peak_ndvi"] <= y20["peak_single_ndvi"]  # smoothed peak never exceeds the single maximum
    assert abs((dt.date.fromisoformat(y20["peak_date"]) - dt.date(2020, 5, 29)).days) <= 8
    assert y20["reliable"] and y21["reliable"] and y20["reasons"] == []


def test_running_mean_damps_a_single_spike():
    obs = season_curve(2019, 0.60, peak_doy=160)
    spike = next(o for o in obs if o["date"] == "2019-04-23")
    spike["ndvi"] = 0.95
    y = year_peak(validate_payloads([payload(2019, obs)])[0][2019], 2019)
    assert y["peak_single_ndvi"] == pytest.approx(0.95)
    assert y["peak_ndvi"] < 0.80  # mean of the spike and a neighbour, not the spike
    plain = year_peak(validate_payloads([payload(2019, obs)])[0][2019], 2019, smooth=1)
    assert plain["peak_ndvi"] == pytest.approx(0.95)


def test_bad_quality_composites_are_ignored():
    obs = season_curve(2018, 0.70, peak_doy=150)
    for o in obs:
        if "2018-05-20" <= o["date"] <= "2018-06-10":
            o["ndvi"] = 0.99
            o["good_pixels"] = 2  # 2 of 6 good: below min_good_fraction 0.5
    y = peak_greenness([payload(2018, obs)])["years"][0]
    assert y["peak_single_ndvi"] < 0.99
    loose = peak_greenness([payload(2018, obs)], min_good_fraction=0.3)["years"][0]
    assert loose["peak_single_ndvi"] == pytest.approx(0.99)


def test_few_composites_and_gaps_are_flagged():
    sparse = [o for o in season_curve(2015, 0.7) if o["date"] < "2015-05-01" or o["date"] > "2015-07-15"]
    y = peak_greenness([payload(2015, sparse)])["years"][0]
    assert not y["reliable"] and "gap_in_season" in y["reasons"]
    few = [o for o in season_curve(2016, 0.7) if "2016-05-20" <= o["date"] <= "2016-06-20"]
    y = peak_greenness([payload(2016, few)])["years"][0]
    assert "few_good_composites" in y["reasons"] and "gap_in_season" in y["reasons"]
    lone = [{"date": "2017-06-01", "ndvi": 0.6, "pixels": 3, "good_pixels": 3, "platform": "terra"}]
    y = peak_greenness([payload(2017, lone)])["years"][0]
    assert y["peak_ndvi"] is None and y["peak_single_ndvi"] == 0.6 and "no_peak" in y["reasons"]


def test_terra_only_years_are_reliable():
    terra = season_curve(2001, 0.7, step=16)
    for o in terra:
        o["platform"] = "terra"
    y = peak_greenness([payload(2001, terra)])["years"][0]
    assert y["reliable"] and y["peak_ndvi"] is not None


def test_too_small_and_no_data():
    zero = [dict(o, ndvi=None, pixels=0, good_pixels=0) for o in season_curve(2020, 0.7)]
    out = peak_greenness([payload(2020, zero)])
    assert out["status"] == "too_small" and out["whole_pixels"] == 0 and out["years"] == []
    out = peak_greenness([payload(2020, season_curve(2020, 0.7, pixels=2))], min_whole_pixels=3)
    assert out["status"] == "too_small" and out["whole_pixels"] == 2
    assert peak_greenness([])["status"] == "no_data"
    assert peak_greenness([None, {"observations": None}])["status"] == "no_data"


def test_validation_drops_malformed_and_dedupes():
    obs = [
        {"date": "2020-06-01", "ndvi": 0.7, "pixels": 4, "good_pixels": 4, "platform": "terra"},
        {"date": "2020-06-01", "ndvi": 0.5, "pixels": 4, "good_pixels": 1, "platform": "terra"},  # duplicate, fewer good
        {"date": "2020-06-09", "ndvi": 1.7, "pixels": 4, "good_pixels": 4, "platform": "aqua"},   # out of range
        {"date": "2020-06-17", "ndvi": "x", "pixels": 4, "good_pixels": 4, "platform": "terra"},  # not a number
        {"date": "2020-06-25", "ndvi": 0.6, "pixels": 4, "good_pixels": 9, "platform": "aqua"},   # good capped
        {"date": "2020-07-03", "ndvi": 0.6, "pixels": 4, "good_pixels": 4, "platform": "sentinel"},
        {"date": "bad", "ndvi": 0.6, "pixels": 4, "good_pixels": 4, "platform": "terra"},
        {"ndvi": 0.6},
        {"date": "2020-07-11", "ndvi": 0.6, "pixels": 4, "good_pixels": 0, "platform": "terra"},  # no good pixel
        {"date": "2021-01-02", "ndvi": 0.3, "pixels": 4, "good_pixels": 4, "platform": "aqua"},   # next year's date
    ]
    years, size, source = validate_payloads([payload(2020, obs)])
    c20 = years[2020]
    assert [c.date.isoformat() for c in c20] == ["2020-06-01", "2020-06-09", "2020-06-17", "2020-06-25",
                                                  "2020-07-11"]
    assert c20[0].ndvi == 0.7 and c20[1].ndvi is None and c20[2].ndvi is None
    assert c20[3].good_pixels == 4 and c20[4].ndvi is None
    assert [c.date.year for c in years[2021]] == [2021]
    assert size == pytest.approx(PIXEL_M) and source == "test"


# ---- provider geometry, offline ----

def _grid_square(h, v, col, row, ncols, nrows, shift=(0.0, 0.0)):
    t = tile_transform(h, v)
    x0 = t.c + col * PIXEL_M + shift[0]
    y1 = t.f - row * PIXEL_M + shift[1]
    return mapping(box(x0, y1 - nrows * PIXEL_M, x0 + ncols * PIXEL_M, y1))


def test_tile_grid_matches_published_transforms():
    # From the items' proj:transform on the Planetary Computer.
    assert tile_transform(9, 4).c == pytest.approx(-10007554.677, abs=1e-3)
    assert tile_transform(10, 4).c == pytest.approx(-8895604.157333, abs=1e-3)
    assert tile_transform(10, 4).f == pytest.approx(5559752.598333, abs=1e-3)
    assert PIXEL_M == pytest.approx(231.65635826374987, abs=1e-6)
    geom = _grid_square(9, 4, 4795, 100, 10, 2)  # straddles the h09/h10 seam
    assert tiles_for(geom) == [(9, 4), (10, 4)]


def test_whole_pixels_need_centre_and_footprint_inside():
    t = tile_transform(9, 4)
    aligned = _grid_square(9, 4, 100, 200, 3, 2)
    win, mask = whole_pixel_mask(aligned, t, 4800, 4800)
    assert int(mask.sum()) == 6
    # Shifted by 40% of a pixel: every centre is still inside, but only footprints wholly inside count.
    shifted = _grid_square(9, 4, 100, 200, 3, 2, shift=(0.4 * PIXEL_M, 0.0))
    win, mask = whole_pixel_mask(shifted, t, 4800, 4800)
    assert int(mask.sum()) == 4
    # An inward buffer removes pixels touching the edge.
    assert whole_pixel_mask(aligned, t, 4800, 4800, edge_buffer_m=1.0) is None
    # Smaller than a pixel: none.
    tiny = _grid_square(9, 4, 100, 200, 0.9, 0.9)
    assert whole_pixel_mask(tiny, t, 4800, 4800) is None


class _Item:
    def __init__(self, id_):
        self.id = id_
        self.assets = {}


class _Search:
    def __init__(self, ids):
        self._ids = ids

    def items(self):
        return [_Item(i) for i in self._ids]


class _Client:
    def __init__(self, ids):
        self.ids = ids
        self.calls = []

    def search(self, **kw):
        self.calls.append(kw)
        return _Search(self.ids)


def test_provider_keeps_latest_reprocessing_and_skips_small_fields(monkeypatch):
    ids = ["MOD13Q1.A2021225.h09v04.061.2021243204133",
           "MOD13Q1.A2021225.h09v04.061.2026110160303",  # reprocessed: keep this one
           "MYD13Q1.A2021233.h09v04.061.2021251111534",
           "MYD13Q1.A2020361.h09v04.061.2021010001020"]  # starts in the previous year: dropped
    client = _Client(ids)
    m = ModisNdvi(today=dt.date(2026, 11, 15))
    monkeypatch.setattr(m, "_client", lambda: client)
    kept = m._items(2021, 9, 4)
    assert [i.id for i in kept] == ["MOD13Q1.A2021225.h09v04.061.2026110160303",
                                    "MYD13Q1.A2021233.h09v04.061.2021251111534"]
    assert client.calls[0]["query"] == {"modis:horizontal-tile": {"eq": 9}, "modis:vertical-tile": {"eq": 4}}

    def no_reads(*a, **k):
        raise AssertionError("no image should be read for a field without whole pixels")
    monkeypatch.setattr(m, "_read", no_reads)
    small = {"type": "Polygon", "coordinates": [[(-117.2400, 46.8500), (-117.2390, 46.8500),
                                                 (-117.2390, 46.8507), (-117.2400, 46.8507),
                                                 (-117.2400, 46.8500)]]}
    out = m.ndvi_year(small, 2021)
    assert out["year"] == 2021 and out["pixel_size_m"] == pytest.approx(PIXEL_M)
    assert [(o["date"], o["platform"], o["pixels"], o["good_pixels"], o["ndvi"]) for o in out["observations"]] == [
        ("2021-08-13", "terra", 0, 0, None), ("2021-08-21", "aqua", 0, 0, None)]
    assert peak_greenness([out])["status"] == "too_small"



def test_terra_only_pairs_across_an_unusable_composite():
    # Field D 2001, live: every other 16-day composite unusable; pairing must still reach the peak.
    obs = [("04-23", 0.791), ("05-09", None), ("05-25", 0.906), ("06-10", None), ("06-26", 0.843),
           ("07-12", 0.585), ("07-28", 0.3117)]
    raw = payload(2001, [{"date": f"2001-{d}", "ndvi": n, "pixels": 1, "good_pixels": 0 if n is None else 1,
                          "platform": "terra"} for d, n in obs])
    y = peak_greenness([raw])["years"][0]
    assert y["peak_ndvi"] == pytest.approx((0.906 + 0.843) / 2, abs=1e-4)
    assert y["peak_date"] == "2001-05-25"
    strict = peak_greenness([raw], pair_max_days=16)["years"][0]
    assert strict["peak_ndvi"] < 0.75  # what a 16-day rule would give


def test_window_mean_catches_early_dry_down():
    normal = season_curve(2019, 0.82, peak_doy=135)
    early = season_curve(2021, 0.82, peak_doy=115)
    out = peak_greenness([payload(2019, normal), payload(2021, early)])
    y19, y21 = out["years"]
    assert abs(y19["peak_ndvi"] - y21["peak_ndvi"]) < 0.02
    assert y21["window_mean_ndvi"] < y19["window_mean_ndvi"] - 0.05
    assert y19["window_composites"] >= 3
    few = [o for o in normal if not ("2019-05-01" <= o["date"] <= "2019-06-20")]
    assert peak_greenness([payload(2019, few)])["years"][0]["window_mean_ndvi"] is None
