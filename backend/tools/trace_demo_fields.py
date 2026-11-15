"""Trace real field outlines around seed points: connected pixels sharing the seed's crop sequence.

Run from backend/:  python tools/trace_demo_fields.py > ../data/demo_fields.geojson
Append only seeds not yet in the file:  python tools/trace_demo_fields.py --append ../data/demo_fields.geojson
"""
from __future__ import annotations

import json
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import mapping, shape
import shapely

from fieldshift.app import get_cache
from fieldshift.providers.us.cdl import CropScapeCountyCdl

SEEDS = [  # (name, lon, lat) from tools/find_demo_fields.py
    ("Demo field A — north of Colfax", -117.222776, 47.231392),
    ("Demo field B — near Steptoe", -117.355602, 47.128746),
    ("Demo field C — west of Colfax", -117.317714, 46.988695),
    ("Demo field D — near Pullman", -117.243403, 46.84862),
    # Dry west: winter wheat alternating with fallow 2014–2025 (found by scanning blocks within
    # 12 km of LaCrosse for a clean wheat–fallow sequence).
    ("Demo field E — near LaCrosse (dry west)", -117.872204, 46.794072),
]
YEARS = range(2014, 2026)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--append", help="existing GeoJSON: trace only seeds whose name is not in it, write it back")
    args = ap.parse_args()
    existing = None
    seeds = SEEDS
    if args.append:
        existing = json.load(open(args.append))
        have = {f["properties"]["name"] for f in existing["features"]}
        seeds = [s for s in SEEDS if s[0] not in have]
    cs = CropScapeCountyCdl("53075", get_cache())
    arrs = []
    for y in YEARS:
        with rasterio.open(cs.county_file(y)) as src:
            arrs.append(src.read(1)); tr, crs = src.transform, src.crs
    h = min(a.shape[0] for a in arrs); w = min(a.shape[1] for a in arrs)
    stack = np.stack([a[:h, :w] for a in arrs])
    to_px = Transformer.from_crs(4326, crs, always_xy=True)
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True)
    feats = []
    for name, lon, lat in seeds:
        x, y = to_px.transform(lon, lat)
        col, row = ~tr * (x, y)
        row, col = int(row) + 6, int(col) + 6  # centre of the 14-px block
        seq = stack[:, row, col]
        same = (stack == seq[:, None, None]).sum(axis=0) >= len(seq) - 1  # allow one mismatching year
        lab, _ = ndimage.label(ndimage.binary_opening(same, iterations=1))
        comp = lab == lab[row, col]
        polys = [shape(g) for g, v in shapes(comp.astype(np.uint8), mask=comp, transform=tr) if v == 1]
        poly = max(polys, key=lambda p: p.area).buffer(-20).simplify(20)  # stay inside the field edge
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        poly = shapely.transform(poly, lambda xy: np.column_stack(to_ll.transform(xy[:, 0], xy[:, 1])))
        coords = [[round(a, 6), round(b, 6)] for a, b in poly.exterior.coords]
        print(name, f"{poly.area * 1e4:.2f}", len(coords), [int(v) for v in seq], file=sys.stderr)
        feats.append({"type": "Feature", "properties": {"name": name, "note": (
            "Outline traced from pixels that share this field's 2014–2025 crop sequence in the CDL; "
            "a demo field, not a surveyed boundary.")},
            "geometry": {"type": "Polygon", "coordinates": [coords]}})
    if existing is not None:
        existing["features"].extend(feats)
        with open(args.append, "w") as fh:
            json.dump(existing, fh, indent=1, ensure_ascii=False)
        print(f"appended {len(feats)} field(s) to {args.append}", file=sys.stderr)
    else:
        print(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))


if __name__ == "__main__":
    main()
