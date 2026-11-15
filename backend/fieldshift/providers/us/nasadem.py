"""NASA NASADEM elevation around a field (TerrainProvider).

Microsoft Planetary Computer collection `nasadem`, asset `elevation`: 1 arc-second
(about 31 m north-south, 21 m east-west at 47° N) in 1° tiles such as
NASADEM_HGT_n46w118, EPSG:4326, int16 whole metres, nodata -32768.

The window around the field (plus a buffer, so slope can be computed at the
field edge) is read from every tile it touches, mosaicked in geographic
coordinates (rasterio.merge; neighbouring tiles share their edge row, so there
is no seam), and then reprojected with bilinear resampling onto a north-up grid
in the field's UTM zone, so the core can compute slope in metres.
"""
from __future__ import annotations

import logging
import math
import threading

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_bounds, transform_geom

from .cdl import GDAL_ENV, PC_STAC, _coords

log = logging.getLogger(__name__)


def utm_epsg(lon: float, lat: float) -> int:
    zone = int(math.floor((lon + 180.0) / 6.0)) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


class NasademTerrain:
    source = "NASA NASADEM (1 arc-second, about 30 m) via Microsoft Planetary Computer (nasadem)"

    def __init__(self, pixel_size_m: float = 30.0):
        self.pixel_size_m = float(pixel_size_m)
        self._local = threading.local()

    def _client(self):
        if not hasattr(self._local, "client"):
            import planetary_computer
            import pystac_client
            self._local.client = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
        return self._local.client

    def elevation(self, geometry: dict, buffer_m: float = 90.0) -> dict:
        """Elevation grid around the field in a local metric CRS.

        {"elevation_m": [[float|None, ...], ...]   rows north to south, None = no data
         "transform": [a, b, c, d, e, f]             affine, metres, in `crs` (a = pixel width, e = -pixel height)
         "crs": "EPSG:326zz"                         UTM zone of the field centre
         "inside": [[bool, ...], ...]                pixel centre inside the field (all touched if none is)
         "pixel_size_m": float,
         "buffer_m": float,
         "tiles": [str, ...]                         NASADEM tile ids read
         "source": str}
        """
        xs, ys = _coords(geometry)
        lon0, lat0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        crs = f"EPSG:{utm_epsg(lon0, lat0)}"
        g = transform_geom("EPSG:4326", crs, geometry)
        gx, gy = _coords(g)
        px = self.pixel_size_m
        pad = max(float(buffer_m), 2 * px)
        left = math.floor((min(gx) - pad) / px) * px
        top = math.ceil((max(gy) + pad) / px) * px
        width = int(math.ceil((max(gx) + pad - left) / px))
        height = int(math.ceil((top - (min(gy) - pad)) / px))
        if width * height > 4_000_000:
            raise ValueError("field too large for an elevation window read")
        dst_transform = Affine(px, 0.0, left, 0.0, -px, top)
        right, bottom = left + width * px, top - height * px

        # Geographic box of the destination grid, with a margin of a few source pixels for bilinear.
        w, s, e, n = transform_bounds(crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)
        m = 3 / 3600
        w, s, e, n = w - m, s - m, e + m, n + m
        box = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
        items = list(self._client().search(collections=["nasadem"], intersects=box).items())
        if not items:
            raise RuntimeError("no NASADEM tile covers the field")

        with rasterio.Env(**GDAL_ENV):
            opened = [(it.id, rasterio.open(it.assets["elevation"].href)) for it in items]
            srcs = [sr for _, sr in opened]
            try:
                used = [(i, sr) for i, sr in opened if not (sr.bounds.right <= w or sr.bounds.left >= e
                                                           or sr.bounds.top <= s or sr.bounds.bottom >= n)]
                tiles = sorted(i for i, _ in used)
                srcs_used = [sr for _, sr in used]
                if not srcs_used:
                    raise RuntimeError("no NASADEM tile reaches the field")
                nodata = srcs_used[0].nodata if srcs_used[0].nodata is not None else -32768
                mosaic, mosaic_tf = merge(srcs_used, bounds=(w, s, e, n), nodata=nodata)
                src_crs = srcs_used[0].crs
            finally:
                for sr in srcs:
                    sr.close()

        src = mosaic[0].astype(np.float32)
        src[src == nodata] = np.nan
        src[(src < -500) | (src > 9000)] = np.nan
        dst = np.full((height, width), np.nan, dtype=np.float32)
        reproject(src, dst, src_transform=mosaic_tf, src_crs=src_crs, src_nodata=np.nan,
                  dst_transform=dst_transform, dst_crs=crs, dst_nodata=np.nan, resampling=Resampling.bilinear)

        inside = geometry_mask([g], out_shape=dst.shape, transform=dst_transform, invert=True)
        if not inside.any():
            inside = geometry_mask([g], out_shape=dst.shape, transform=dst_transform, invert=True, all_touched=True)

        elev = [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in dst]
        return {
            "elevation_m": elev,
            "transform": [dst_transform.a, dst_transform.b, dst_transform.c,
                          dst_transform.d, dst_transform.e, dst_transform.f],
            "crs": crs,
            "inside": inside.tolist(),
            "pixel_size_m": px,
            "buffer_m": float(buffer_m),
            "tiles": tiles,
            "source": self.source,
        }
