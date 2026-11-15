"""Find candidate demo fields: blocks that are one crop per year, rotating among local crops.

Reads the cached CropScape county files (downloads missing ones) and prints
square candidate fields as GeoJSON. Run from backend/:
    python tools/find_demo_fields.py --years 2014-2025
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import rasterio
from pyproj import Transformer

from fieldshift.app import get_cache
from fieldshift.providers.us.cdl import CropScapeCountyCdl

LOCAL = {21, 23, 24, 31, 51, 52, 53, 61, 42}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2014-2025")
    ap.add_argument("--block", type=int, default=14)
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    y0, y1 = map(int, a.years.split("-"))
    cs = CropScapeCountyCdl("53075", get_cache())
    stack = []
    for y in range(y0, y1 + 1):
        with rasterio.open(cs.county_file(y)) as src:
            stack.append(src.read(1))
            transform, crs = src.transform, src.crs
    h = min(s.shape[0] for s in stack); w = min(s.shape[1] for s in stack)
    stack = np.stack([s[:h, :w] for s in stack])
    b = a.block
    found = []
    for r in range(0, h - b, b // 2):
        for c in range(0, w - b, b // 2):
            blk = stack[:, r:r + b, c:c + b].reshape(len(stack), -1)
            modes, shares = [], []
            for yr in blk:
                v, n = np.unique(yr, return_counts=True)
                i = n.argmax(); modes.append(int(v[i])); shares.append(n[i] / yr.size)
            if min(shares) < 0.9 or not set(modes) <= LOCAL:
                continue
            distinct = len(set(modes))
            changes = sum(m1 != m2 for m1, m2 in zip(modes, modes[1:]))
            if distinct >= 3 and changes >= len(modes) - 2:
                found.append((distinct, changes, float(np.mean(shares)), r, c, modes))
    found.sort(key=lambda t: (-t[0], -t[2]))
    inv = Transformer.from_crs(crs, 4326, always_xy=True)
    picked, feats = [], []
    for d, ch, ms, r, c, modes in found:
        if any(abs(r - pr) < 150 and abs(c - pc) < 150 for pr, pc in picked):
            continue  # spread them out
        picked.append((r, c))
        x0, y0_ = transform * (c + 1, r + 1); x1, y1_ = transform * (c + b - 1, r + b - 1)
        ring = [inv.transform(x, y) for x, y in [(x0, y0_), (x1, y0_), (x1, y1_), (x0, y1_), (x0, y0_)]]
        ring = [[round(x, 6), round(y, 6)] for x, y in ring]
        feats.append({"type": "Feature", "properties": {"modes": modes, "mean_share": round(ms, 3)},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}})
        print(len(feats), modes, round(ms, 3), ring[0])
        if len(feats) >= a.n:
            break
    print(json.dumps({"type": "FeatureCollection", "features": feats}))


if __name__ == "__main__":
    main()
