"""Field-average NDVI from Sentinel-2 L2A on the Planetary Computer.

Reads only the field's window from each image (no scene downloads), masks
cloud, shadow and snow with the SCL band, and removes the +1000 reflectance
offset used from processing baseline 04.00 (January 2022) onwards.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import from_bounds
from shapely.geometry import box, shape

from .cdl import GDAL_ENV, PC_STAC, _coords

log = logging.getLogger(__name__)
BOA_OFFSET = 1000


class Sentinel2Ndvi:
    source = "Copernicus Sentinel-2 Level-2A via Microsoft Planetary Computer (sentinel-2-l2a)"

    def __init__(self, masked_scl: list[int], max_cloud_cover: float, first_year: int = 2017,
                 workers: int = 16, today: dt.date | None = None):
        self.masked_scl = np.array(sorted(set(int(x) for x in masked_scl)), dtype=np.uint8)
        self.max_cloud = float(max_cloud_cover)
        self.first_year = first_year
        self.workers = workers
        self._today = today
        self._local = threading.local()

    def _client(self):
        if not hasattr(self._local, "client"):
            import planetary_computer
            import pystac_client
            self._local.client = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
        return self._local.client

    def available_years(self) -> list[int]:
        return list(range(self.first_year, (self._today or dt.date.today()).year + 1))

    def _items(self, geometry: dict, year: int) -> list:
        today = self._today or dt.date.today()
        end = min(dt.date(year, 12, 31), today)
        if end < dt.date(year, 1, 1):
            return []
        items = list(self._client().search(
            collections=["sentinel-2-l2a"], intersects=geometry,
            datetime=f"{year}-01-01/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": self.max_cloud}}).items())
        # Overlapping MGRS tiles carry the same acquisition twice; keep one per date,
        # preferring a tile that contains the whole field, then the least cloudy.
        field = shape(geometry)
        best: dict[dt.date, tuple] = {}
        for it in items:
            d = it.datetime.date()
            contains = box(*it.bbox).contains(field)
            rank = (not contains, it.properties.get("eo:cloud_cover", 100))
            if d not in best or rank < best[d][0]:
                best[d] = (rank, it)
        return [best[d][1] for d in sorted(best)]

    def _read(self, item, geometry: dict) -> dict:
        baseline = item.properties.get("s2:processing_baseline") or "0"
        try:
            offset = BOA_OFFSET if float(baseline) >= 4.0 else 0
        except ValueError:
            offset = 0
        last_exc = None
        for attempt in range(3):
            try:
                with rasterio.Env(**GDAL_ENV):
                    with rasterio.open(item.assets["B04"].href) as red_src:
                        geom = transform_geom("EPSG:4326", red_src.crs, geometry)
                        xs, ys = _coords(geom)
                        win = from_bounds(min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + 10,
                                          red_src.transform).round_offsets().round_lengths()
                        red = red_src.read(1, window=win, boundless=True, fill_value=0).astype(np.float32)
                        wt = red_src.window_transform(win)
                        bounds = rasterio.windows.bounds(win, red_src.transform)
                    with rasterio.open(item.assets["B08"].href) as nir_src:
                        nir = nir_src.read(1, window=from_bounds(*bounds, nir_src.transform).round_offsets()
                                           .round_lengths(), boundless=True, fill_value=0,
                                           out_shape=red.shape).astype(np.float32)
                    with rasterio.open(item.assets["SCL"].href) as scl_src:
                        scl = scl_src.read(1, window=from_bounds(*bounds, scl_src.transform), boundless=True,
                                           fill_value=0, out_shape=red.shape, resampling=Resampling.nearest)
                break
            except Exception as exc:  # network hiccup or expired signature
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"could not read {item.id}: {last_exc}")
        inside = geometry_mask([geom], out_shape=red.shape, transform=wt, invert=True)
        if not inside.any():
            inside = geometry_mask([geom], out_shape=red.shape, transform=wt, invert=True, all_touched=True)
        red -= offset
        nir -= offset
        valid = inside & ~np.isin(scl, self.masked_scl) & (red > 0) & (nir > 0)
        n_inside = int(inside.sum())
        n_valid = int(valid.sum())
        ndvi = None
        if n_valid:
            r, n = red[valid], nir[valid]
            ndvi = float(np.mean((n - r) / (n + r)))
        return {"date": item.datetime.date().isoformat(), "ndvi": ndvi,
                "valid_fraction": n_valid / n_inside if n_inside else 0.0, "scene": item.id}

    def ndvi_year(self, geometry: dict, year: int) -> dict:
        items = self._items(geometry, year)
        observations, failed = [], 0

        def one(it):
            try:
                return self._read(it, geometry)
            except Exception as exc:
                log.warning("Sentinel-2 scene failed: %s", exc)
                return None

        with ThreadPoolExecutor(self.workers) as ex:
            for res in ex.map(one, items):
                if res is None:
                    failed += 1
                else:
                    observations.append(res)
        if items and failed == len(items):
            raise RuntimeError(f"all {failed} Sentinel-2 images for {year} failed to read")
        return {"year": year, "observations": observations, "source": self.source,
                "scenes_considered": len(items), "scenes_failed": failed}
