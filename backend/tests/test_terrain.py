"""Offline tests for slope from an elevation grid (core/terrain.py)."""
from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

from fieldshift.core import terrain
from fieldshift.core.soil import FieldSoil

UTM11 = "EPSG:32611"
PX = 30.0
X0, Y0 = 490_000.0, 5_190_000.0  # near Pullman, UTM 11N


def plane_payload(slope_x_pct: float, slope_y_pct: float = 0.0, n: int = 20, border: int = 3, px: float = PX,
                  noise: np.ndarray | None = None) -> dict:
    jj, ii = np.meshgrid(np.arange(n), np.arange(n))
    z = 700 + jj * px * slope_x_pct / 100 + ii * px * slope_y_pct / 100
    if noise is not None:
        z = z + noise
    inside = np.zeros((n, n), bool)
    inside[border:n - border, border:n - border] = True
    return {"elevation_m": z.tolist(), "transform": [px, 0.0, X0, 0.0, -px, Y0], "crs": UTM11,
            "inside": inside.tolist(), "pixel_size_m": px, "source": "synthetic"}


def soil(rep=None, lo=None, hi=None, share=None, soils=None) -> FieldSoil:
    return FieldSoil(capacity_mm={"0_100cm": 200, "0_150cm": 300}, capacity_default=False,
                     slope_low=lo, slope_rep=rep, slope_high=hi, main_share=share, soils=soils or [])


# ---------------------------------------------------------------- slope
@pytest.mark.parametrize("sx,sy", [(8.0, 0.0), (0.0, 12.0), (3.0, 4.0), (20.0, 15.0)])
def test_plane_gives_its_slope(sx, sy):
    fs = terrain.field_slope(plane_payload(sx, sy))
    expect = (sx ** 2 + sy ** 2) ** 0.5
    assert fs.median_pct == pytest.approx(expect, abs=0.05)
    assert fs.max_pct == pytest.approx(expect, abs=0.05)
    assert fs.p90_pct == pytest.approx(expect, abs=0.05)


def test_slope_uses_pixel_size():
    a = terrain.field_slope(plane_payload(10.0, px=30.0))
    b = terrain.field_slope(plane_payload(10.0, px=10.0))
    assert a.median_pct == pytest.approx(10.0, abs=0.05) and b.median_pct == pytest.approx(10.0, abs=0.05)


def test_slope_border_and_missing_are_nan():
    z = np.full((5, 5), 100.0)
    z[2, 2] = np.nan
    s = terrain.slope_percent(z, 30.0)
    assert np.isnan(s[0]).all() and np.isnan(s[:, 0]).all()
    assert np.isnan(s[1:4, 1:4]).all()  # every interior pixel touches the hole


def test_shares_and_percentiles_on_two_slopes():
    # Left half 2%, right half 20%: piecewise plane, continuous at the join.
    n = 40
    jj, ii = np.meshgrid(np.arange(n), np.arange(n))
    x = jj * PX
    z = np.where(jj < n // 2, x * 0.02, (n // 2) * PX * 0.02 + (x - (n // 2) * PX) * 0.20)
    p = plane_payload(0, n=n)
    p["elevation_m"] = (700 + z).tolist()
    fs = terrain.field_slope(p, share_thresholds_pct=[15, 5, 10])
    assert list(fs.share_above) == ["5", "10", "15"]
    assert 0.4 < fs.share_above["15"] < 0.6
    assert fs.share_above["5"] == fs.share_above["15"] or fs.share_above["5"] - fs.share_above["15"] < 0.06
    assert fs.max_pct == pytest.approx(20.0, abs=0.05)
    assert fs.p90_pct == pytest.approx(20.0, abs=0.05)


def test_bad_payloads_degrade():
    for bad in (None, {}, {"elevation_m": [[1, 2]], "inside": [[True, True]], "transform": [30, 0, 0, 0, -30, 0],
                           "crs": UTM11},
                {**plane_payload(5), "crs": "+proj=utm"},
                {**plane_payload(5), "transform": [30, 0, 0, 0, 30, 0]},
                {**plane_payload(5), "inside": [[True]]}):
        fs = terrain.field_slope(bad)
        assert fs.median_pct is None and fs.error and fs.slope_class is None
        assert terrain.slope_overlay(fs) is None


def test_out_of_range_elevations_dropped():
    p = plane_payload(6.0)
    p["elevation_m"][10][10] = -32768
    p["elevation_m"][12][12] = None
    fs = terrain.field_slope(p)
    assert fs.median_pct == pytest.approx(6.0, abs=0.05)
    assert fs.pixels < 14 * 14


def test_too_small_field():
    p = plane_payload(6.0)
    inside = np.zeros((20, 20), bool)
    inside[5, 5] = True
    p["inside"] = inside.tolist()
    fs = terrain.field_slope(p)
    assert fs.median_pct is None and "too few" in fs.error


# ---------------------------------------------------------------- classes
@pytest.mark.parametrize("v,cls", [(0, "low"), (4.99, "low"), (5, "moderate"), (15, "moderate"), (15.01, "high"),
                                   (None, None)])
def test_class_thresholds(v, cls):
    assert terrain.classify(v, 5, 15) == cls


def test_class_thresholds_are_parameters():
    assert terrain.classify(8, low_below_pct=10, high_above_pct=20) == "low"
    fs = terrain.field_slope(plane_payload(8.0), low_below_pct=10, high_above_pct=20)
    assert fs.slope_class == "low"
    assert terrain.field_slope(plane_payload(8.0)).slope_class == "moderate"
    assert terrain.field_slope(plane_payload(18.0)).slope_class == "high"


# ---------------------------------------------------------------- vs soil survey
def test_consistent_when_close():
    c = terrain.compare_with_soil(terrain.field_slope(plane_payload(9.0)), soil(10, 7, 12, 0.8))
    assert c["verdict"] == "consistent" and c["agrees"] is True
    assert "agrees" in c["sentence"]


def test_gentler_inside_range_mentions_grid_smoothing():
    fs = terrain.field_slope(plane_payload(7.5))
    c = terrain.compare_with_soil(fs, soil(16, 7, 25, 0.63))
    assert c["verdict"] == "consistent"
    assert c["soil_class"] == "high" and c["elevation_class"] == "moderate"
    assert "30 m" in c["sentence"] and "Palouse" in c["sentence"] and "gentler" in c["sentence"]


def test_gentler_outside_range():
    c = terrain.compare_with_soil(terrain.field_slope(plane_payload(4.0)), soil(20, 15, 25, 0.9))
    assert c["verdict"] == "elevation_map_gentler" and c["agrees"] is False
    assert "smooths" in c["sentence"] and "trust the survey" in c["sentence"]


def test_small_main_soil_other_soils_steeper():
    # The demo-field-D pattern: main soil 0-3% on a quarter of the field, the rest 7-25%.
    soils = [{"share": 0.25, "slope_pct": [0, 2, 3]}, {"share": 0.40, "slope_pct": [7, 16, 25]},
             {"share": 0.35, "slope_pct": [7, 16, 25]}]
    c = terrain.compare_with_soil(terrain.field_slope(plane_payload(10.0)), soil(2, 0, 3, 0.25, soils))
    assert c["verdict"] == "consistent_with_other_soils"
    assert c["soil_weighted_rep_pct"] == pytest.approx(12.5, abs=0.05)
    assert "25% of the field" in c["sentence"] and "steeper" in c["sentence"]


def test_steeper_than_survey_explained():
    soils = [{"share": 0.9, "slope_pct": [0, 2, 3]}, {"share": 0.1, "slope_pct": [0, 2, 3]}]
    c = terrain.compare_with_soil(terrain.field_slope(plane_payload(12.0)), soil(2, 0, 3, 0.9, soils))
    assert c["verdict"] == "elevation_map_steeper"
    assert "measures this field directly" in c["sentence"]


def test_no_soil_slope_and_no_elevation():
    c = terrain.compare_with_soil(terrain.field_slope(plane_payload(6.0)), soil())
    assert c["verdict"] == "no_soil_slope" and c["agrees"] is None and "6%" in c["sentence"]
    c = terrain.compare_with_soil(terrain.field_slope(None), soil(16, 7, 25, 0.6))
    assert c["verdict"] == "no_elevation" and "16%" in c["sentence"]


def test_sentences_use_no_banned_terms():
    for s in (soil(16, 7, 25, 0.6), soil(2, 0, 3, 0.9), soil()):
        text = terrain.compare_with_soil(terrain.field_slope(plane_payload(9.0)), s)["sentence"]
        for banned in ("NDVI", "provisional", "dominated", "mm", "ha "):
            assert banned not in text


# ---------------------------------------------------------------- PNG
def _decode_png(data: bytes) -> np.ndarray:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat = 8, b""
    w = h = None
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + ln]
        (crc,) = struct.unpack(">I", data[pos + 8 + ln:pos + 12 + ln])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert (depth, ctype) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * 4)
    assert (raw[:, 0] == 0).all()
    return raw[:, 1:].reshape(h, w, 4)


def test_overlay_png_steep_is_striped_and_bounds_are_wgs84():
    fs = terrain.field_slope(plane_payload(20.0))
    png, meta = terrain.slope_overlay(fs, display_pixel_m=5.0)
    img = _decode_png(png)
    assert img.shape == (meta["height"], meta["width"], 4)
    (south, west), (north, east) = meta["bounds"]
    assert 46 < south < north < 47.5 and -118 < west < east < -116
    opaque = img[img[..., 3] > 0]
    colours = {tuple(p) for p in opaque}
    assert terrain.STRIPE_RGBA in colours and terrain.CLASS_STYLE["high"]["rgba"] in colours
    legend = {item["class"]: item for item in meta["legend"]}
    assert legend["high"]["share"] == 1.0 and legend["high"]["pattern"] == "stripes"
    assert legend["moderate"]["pattern"] == "solid" and legend["low"]["range"] == "under 5%"


def test_overlay_png_gentle_field_and_outside_transparent():
    fs = terrain.field_slope(plane_payload(2.0))
    png, meta = terrain.slope_overlay(fs)
    img = _decode_png(png)
    assert {tuple(p) for p in img[img[..., 3] > 0]} == {terrain.CLASS_STYLE["low"]["rgba"]}
    # With a diamond-shaped field outline, the image corners are outside the field: transparent.
    (s, w), (n, e) = meta["bounds"]
    cx, cy = (w + e) / 2, (s + n) / 2
    dx, dy = (e - w) / 4, (n - s) / 4
    geom = {"type": "Polygon", "coordinates": [[[cx, cy - dy], [cx + dx, cy], [cx, cy + dy], [cx - dx, cy],
                                                [cx, cy - dy]]]}
    png2, meta2 = terrain.slope_overlay(fs, geometry=geom)
    img2 = _decode_png(png2)
    assert img2[0, 0, 3] == 0 and img2[img2.shape[0] // 2, img2.shape[1] // 2, 3] > 0
