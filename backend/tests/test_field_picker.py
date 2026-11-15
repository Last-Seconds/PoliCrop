"""Tap to pick a field: tracing from synthetic crop-map rasters (offline)."""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import shape

from fieldshift.cache import FileCache
from fieldshift.core.geometry import PolygonField
from fieldshift.providers.us.field_picker import CdlFieldPicker

ORIGIN = (-1692585.0, 2888745.0)  # EPSG:5070, like the Whitman County files


class FakeCounty:
    fips = "53075"

    def __init__(self, cache):
        self.cache = cache

    def county_file(self, year):
        return self.cache.file_path("cdl_county", f"CDL_{year}_{self.fips}.tif")


def write_years(cache, years, n=200):
    for i, y in enumerate(years):
        a = np.full((n, n), 176, dtype=np.uint8)  # grassland around
        a[40:120, 50:150] = 24 if i % 2 else 61  # a wheat–fallow field, 80 × 100 pixels
        a[40:120, 150:190] = 23 if i % 2 else 52  # a neighbour with a different sequence
        a[130:140, :] = 121  # a road
        if i == 3:
            a[60:70, 60:70] = 23  # one misclassified year inside the field
        with rasterio.open(cache.file_path("cdl_county", f"CDL_{y}_53075.tif"), "w", driver="GTiff", width=n,
                           height=n, count=1, dtype="uint8", crs="EPSG:5070",
                           transform=from_origin(*ORIGIN, 30, 30)) as dst:
            dst.write(a, 1)


def lonlat(col, row):
    x, y = ORIGIN[0] + (col + 0.5) * 30, ORIGIN[1] - (row + 0.5) * 30
    return Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True).transform(x, y)


def test_traces_the_field_and_not_its_neighbour(tmp_path):
    cache = FileCache(tmp_path)
    write_years(cache, range(2014, 2026))
    picker = CdlFieldPicker(FakeCounty(cache), {24, 61, 23, 52})
    feat = picker.pick(*lonlat(65, 65), years=12, max_mismatch=1, inset_m=20, simplify_m=10)
    poly = shape(feat["geometry"])
    area_ha = PolygonField(feat["geometry"]).area_ha()
    full = 80 * 100 * 900 / 10_000  # 720 ha before the inset
    assert 0.85 * full < area_ha < full  # pulled in by 20 m, the misclassified patch kept
    assert not poly.contains(shape({"type": "Point", "coordinates": list(lonlat(170, 80))}))
    assert feat["properties"]["sequence"][:2] == [61, 24]


def test_refuses_roads_and_grass(tmp_path):
    cache = FileCache(tmp_path)
    write_years(cache, range(2014, 2026))
    picker = CdlFieldPicker(FakeCounty(cache), {24, 61, 23, 52})
    with pytest.raises(ValueError, match="does not look like a field"):
        picker.pick(*lonlat(10, 10))
    with pytest.raises(ValueError, match="does not look like a field"):
        picker.pick(*lonlat(100, 135))


def test_needs_enough_years(tmp_path):
    cache = FileCache(tmp_path)
    write_years(cache, range(2023, 2026))
    with pytest.raises(RuntimeError, match="Not enough"):
        CdlFieldPicker(FakeCounty(cache), {24, 61}).pick(*lonlat(65, 65))
