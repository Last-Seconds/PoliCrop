"""Tap a field to pick it: trace an outline from crop-map pixels that share the tapped spot's crop sequence.

USDA Crop Sequence Boundaries would be the natural source, but on 2026-11-15 they
could only be had as national multi-gigabyte downloads (see the report), so the
outline is built from what the app already caches: the county Cropland Data
Layer files. Pixels whose crop sequence over the recent years matches the tapped
pixel's (allowing a few years to differ, because the map has errors) and that
connect to it form the field. The outline is pulled in slightly so it stays
inside the field edge. It is an estimate the farmer confirms, not a surveyed
boundary.
"""
from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.windows import Window
from shapely.geometry import Point, mapping, shape
import shapely

from .cdl import CropScapeCountyCdl


def _erode(m: np.ndarray) -> np.ndarray:
    p = np.pad(m, 1, constant_values=False)
    out = np.ones_like(m)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out &= p[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out


def _dilate(m: np.ndarray) -> np.ndarray:
    p = np.pad(m, 1, constant_values=False)
    out = np.zeros_like(m)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out |= p[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out


class CdlFieldPicker:
    source = "Traced from the USDA Cropland Data Layer (pixels sharing one crop sequence)"

    def __init__(self, county: CropScapeCountyCdl, crop_codes: set[int]):
        self.county = county
        self.crop_codes = set(int(c) for c in crop_codes)  # classes that count as cropland

    def cached_years(self) -> list[int]:
        out = []
        for y in range(2008, 2100):
            p = self.county.cache.file_path("cdl_county", f"CDL_{y}_{self.county.fips}.tif")
            if p.exists() and p.stat().st_size > 0:
                out.append(y)
        return out

    def pick(self, lon: float, lat: float, years: int = 12, max_mismatch: int = 1, inset_m: float = 20.0,
             simplify_m: float = 20.0, window_px: int = 120, max_window_px: int = 480) -> dict:
        ys = self.cached_years()[-int(years):]
        if len(ys) < 4:
            raise RuntimeError("Not enough crop-map years are available to trace a field.")
        srcs = [rasterio.open(self.county.county_file(y)) for y in ys]
        try:
            crs = srcs[0].crs
            to_px = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            x, y = to_px.transform(lon, lat)
            col, row = ~srcs[0].transform @ (x, y)
            row, col = int(row), int(col)
            w = int(window_px)
            while True:
                win = Window(col - w, row - w, 2 * w + 1, 2 * w + 1)
                stack = np.stack([s.read(1, window=win, boundless=True, fill_value=0) for s in srcs])
                seq = stack[:, w, w]
                if (seq == 0).any():
                    raise ValueError("That spot is outside the county's crop map.")
                crop_years = sum(1 for v in seq if int(v) in self.crop_codes)
                if crop_years < len(seq) - max_mismatch:
                    raise ValueError("That spot does not look like a field on the crop map (roads, buildings, "
                                     "grass or trees in most years). Tap inside a field, or draw it.")
                same = (stack == seq[:, None, None]).sum(axis=0) >= len(seq) - max_mismatch
                opened = _dilate(_erode(same))
                mask = opened if opened[w, w] else same
                wt = srcs[0].window_transform(win)
                seed = Point(*(wt @ (w + 0.5, w + 0.5)))
                poly = None
                for geom, val in shapes(mask.astype(np.uint8), mask=mask, transform=wt):
                    if val == 1:
                        g = shape(geom)
                        if g.contains(seed):
                            poly = g
                            break
                if poly is None:
                    raise ValueError("No field outline could be traced at that spot.")
                minx, miny, maxx, maxy = poly.bounds
                bx0, by1 = wt @ (0, 0)
                bx1, by0 = wt @ (2 * w + 1, 2 * w + 1)
                touches = minx <= bx0 + 1 or maxx >= bx1 - 1 or miny <= by0 + 1 or maxy >= by1 - 1
                if touches and w < max_window_px:
                    w = min(max_window_px, w * 2)
                    continue
                break
        finally:
            for s in srcs:
                s.close()
        poly = poly.buffer(-float(inset_m)).simplify(float(simplify_m))
        if poly.is_empty:
            raise ValueError("The traced area is too narrow to be a field. Draw it instead.")
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        ll = shapely.transform(poly, lambda xy: np.column_stack(to_ll.transform(xy[:, 0], xy[:, 1])))
        return {
            "type": "Feature",
            "geometry": mapping(ll),
            "properties": {"years": ys, "sequence": [int(v) for v in seq], "touches_window_edge": bool(touches),
                           "source": self.source, "max_mismatch": int(max_mismatch)},
        }
