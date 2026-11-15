"""Nearby use: a histogram of yearly crop-role sequences around a field, from cached county CDL rasters.

For every 30 m pixel inside a geometry (normally the field grown by a radius), the pixel's
CDL code in each requested year is mapped to a crop role through a code -> role table the
caller builds from content (`fieldshift.core.nearby.code_roles`). The result counts how many
pixels share each role sequence. It is JSON-able so the file cache can store it, and it is
read by `fieldshift.core.nearby.NearbyUse`.

What counts as cropland (a choice, documented here and in the payload):
- A year whose code is in the code -> role table is a known role.
- A year whose code is not in the table (grass, hay, forest, developed, water, crops the
  tool does not model, double crops...) is "unknown" and written as `UNKNOWN` ("?").
  A pixel with more than `max_unknown_years` unknown years is not cropland for this purpose.
  With the default 0, only pixels that carry a modelled crop role in every year count.
- A pixel with code 0 (outside the county file / no data) in any year is outside the map;
  it is counted in `outside_pixels` and never in the denominator.

Alignment: the yearly county files can differ by a column or row at their edges. Each year
is read through the same geographic window with a boundless read (fill 0 = outside), after
checking that every year uses the same CRS, pixel size and pixel grid; years on a different
grid raise ValueError rather than being silently shifted.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds

from ...core.geometry import FieldGeometry, buffer_geojson
from .cdl import CropScapeCountyCdl, _coords

UNKNOWN = "?"  # a year whose crop-map class is not a modelled crop role
SEP = "|"
_OUTSIDE = 255  # internal code index for "no data / outside the county file"


def _check_grids(srcs: list) -> None:
    a = srcs[0]
    res = abs(a.transform.a)
    for s in srcs[1:]:
        if s.crs != a.crs:
            raise ValueError(f"crop-map years use different CRS: {a.crs} vs {s.crs}")
        if abs(abs(s.transform.a) - res) > 1e-6 or abs(abs(s.transform.e) - abs(a.transform.e)) > 1e-6:
            raise ValueError("crop-map years use different pixel sizes")
        if s.transform.b != 0 or s.transform.d != 0:
            raise ValueError("rotated crop-map grids are not supported")
        dx = (s.transform.c - a.transform.c) / res
        dy = (s.transform.f - a.transform.f) / res
        if abs(dx - round(dx)) > 1e-6 or abs(dy - round(dy)) > 1e-6:
            raise ValueError("crop-map years are on different pixel grids")


def role_sequence_histogram(paths: dict[int, Path | str], geometry_wgs84: dict, code_roles: dict[int, str],
                            max_unknown_years: int = 0, source: str = "USDA CDL") -> dict:
    """Histogram of per-pixel role sequences inside `geometry_wgs84` for the given year -> raster files.

    Returns {"years": [..ascending..], "sequences": {"cereal|fallow|...": pixel_count, ...},
             "cropland_pixels": int, "buffer_pixels": int, "outside_pixels": int, "non_cropland_pixels": int,
             "max_unknown_years": int, "roles_mapped": [role ids in code_roles], "unknown_token": "?",
             "pixel_size_m": float, "source": str}
    """
    years = sorted(int(y) for y in paths)
    if not years:
        raise ValueError("no crop-map years given")
    roles = sorted(set(code_roles.values()))
    if len(roles) + 2 > 254:
        raise ValueError("too many roles")
    unknown_idx = len(roles)
    lut = np.full(256, unknown_idx, dtype=np.uint8)
    for code, role in code_roles.items():
        if 0 < int(code) < 256:
            lut[int(code)] = roles.index(role)
    lut[0] = _OUTSIDE
    tokens = roles + [UNKNOWN]

    srcs = [rasterio.open(paths[y]) for y in years]
    try:
        _check_grids(srcs)
        ref = srcs[0]
        res = abs(ref.transform.a)
        geom = transform_geom("EPSG:4326", ref.crs, geometry_wgs84)
        xs, ys = _coords(geom)
        left, bottom, right, top = min(xs) - res, min(ys) - res, max(xs) + res, max(ys) + res
        win = from_bounds(left, bottom, right, top, ref.transform).round_offsets().round_lengths()
        wt = ref.window_transform(win)
        h, w = int(win.height), int(win.width)
        inside = geometry_mask([geom], out_shape=(h, w), transform=wt, invert=True)
        n_inside = int(inside.sum())
        idx = np.empty((len(years), n_inside), dtype=np.uint8)
        for i, s in enumerate(srcs):
            # The same geographic window in this year's own grid (grids checked aligned above).
            col = (wt.c - s.transform.c) / s.transform.a
            row = (wt.f - s.transform.f) / s.transform.e
            swin = Window(int(round(col)), int(round(row)), w, h)
            data = s.read(1, window=swin, boundless=True, fill_value=0)
            idx[i] = lut[data[inside]]
    finally:
        for s in srcs:
            s.close()

    outside = (idx == _OUTSIDE).any(axis=0)
    n_unknown = (idx == unknown_idx).sum(axis=0)
    crop = ~outside & (n_unknown <= max_unknown_years)
    kept = idx[:, crop].astype(np.int64)
    base = len(tokens)
    keys = np.zeros(kept.shape[1], dtype=np.int64)
    for i in range(len(years)):
        keys = keys * base + kept[i]
    uniq, counts = np.unique(keys, return_counts=True)
    sequences: dict[str, int] = {}
    for k, n in zip(uniq.tolist(), counts.tolist()):
        parts = []
        for _ in years:
            k, r = divmod(k, base)
            parts.append(tokens[r])
        sequences[SEP.join(reversed(parts))] = int(n)
    sequences = dict(sorted(sequences.items(), key=lambda kv: -kv[1]))
    n_outside = int(outside.sum())
    return {
        "years": years,
        "sequences": sequences,
        "cropland_pixels": int(crop.sum()),
        "buffer_pixels": n_inside,
        "outside_pixels": n_outside,
        "non_cropland_pixels": n_inside - n_outside - int(crop.sum()),
        "max_unknown_years": int(max_unknown_years),
        "roles_mapped": roles,
        "unknown_token": UNKNOWN,
        "pixel_size_m": float(res),
        "source": source,
    }


class CdlRoleSequences:
    """Role-sequence histograms around a field from the county CDL files (downloaded once, then local)."""

    def __init__(self, county: CropScapeCountyCdl):
        self.county = county

    @property
    def source(self) -> str:
        return f"{CropScapeCountyCdl.source} (FIPS {self.county.fips})"

    def cached_years(self, candidates: Iterable[int]) -> list[int]:
        """Years whose county file is already on disk (no network)."""
        out = []
        for y in candidates:
            p = self.county.cache.file_path("cdl_county", f"CDL_{y}_{self.county.fips}.tif")
            if p.exists() and p.stat().st_size > 0:
                out.append(int(y))
        return sorted(out)

    def histogram(self, field: FieldGeometry, years: list[int], code_roles: dict[int, str],
                  radius_km: float = 10.0, max_unknown_years: int = 0) -> dict:
        """The field grown by `radius_km`, as `role_sequence_histogram`, plus "radius_km"."""
        if not (0 < radius_km <= 100) or not math.isfinite(radius_km):
            raise ValueError("radius_km must be in (0, 100]")
        area = buffer_geojson(field, radius_km * 1000.0)
        paths = {y: self.county.county_file(y) for y in years}
        out = role_sequence_histogram(paths, area, code_roles, max_unknown_years, self.source)
        out["radius_km"] = float(radius_km)
        return out

