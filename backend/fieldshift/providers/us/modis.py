"""Field NDVI from MODIS 13Q1 v061 (Terra MOD13Q1 and Aqua MYD13Q1) on the Planetary Computer.

Collection `modis-13Q1-061`: 250 m (231.656 m on the sinusoidal grid), 16-day
maximum-value composites, Terra from February 2000, Aqua from July 2002. The
two satellites' composites are offset by 8 days, so together they give one
value roughly every 8 days.

Only pixels lying wholly inside the field are used. A 250 m pixel straddling
the boundary mixes the field with roads, neighbours and draws, and would blur
the very stress signal we want. "Wholly inside" is decided in two steps on
the MODIS sinusoidal grid:

1. `rasterio.features.geometry_mask(..., all_touched=False)` burns only the
   pixels whose centre falls inside the field polygon (GDAL's default rule);
2. each of those pixels' square footprint is then tested with shapely
   `covers`, and any pixel whose footprint pokes outside the polygon (by more
   than 1 mm, or than `edge_buffer_m` inwards if set) is dropped.

The pixel set depends only on the grid, so it is worked out once per field
from the global MODIS grid arithmetic before any image is opened; a field
holding no whole pixel returns its composites with zero pixels and no reads.

Pixel quality: the `pixel_reliability` layer is 0 good, 1 marginal ("useful,
but look at other QA information"), 2 snow/ice, 3 cloudy; fill is -1 in the
HDF and 255 in these COGs (stored as uint8). By default only 0 is accepted
(MOD13 C6/C6.1 User Guide, Didan et al.; Table "MOD13Q1 Pixel Reliability").

NDVI is stored as int16 with fill -3000 and valid range -2000..10000; the
value is DN x 0.0001. (The COG's GDAL `scale` tag reads 10000, the HDF-style
divisor; the STAC `raster:bands` scale says 0.0001. Both mean the same.)
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window
from shapely.geometry import box, shape
from shapely.prepared import prep

from .cdl import GDAL_ENV, PC_STAC

log = logging.getLogger(__name__)

COLLECTION = "modis-13Q1-061"
NDVI_ASSET = "250m_16_days_NDVI"
RELIABILITY_ASSET = "250m_16_days_pixel_reliability"
NDVI_SCALE = 0.0001
NDVI_FILL = -3000
NDVI_VALID = (-2000, 10000)

# MODIS land sinusoidal grid (MODLAND tile grid): sphere radius, global origin, 4800 px per 250 m tile.
SINUSOIDAL = CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs")
GRID_X0 = -20015109.354
GRID_Y0 = 10007554.677
TILE_PX = 4800
PIXEL_M = 2 * 20015109.354 / 36 / TILE_PX  # 231.656358263750 m
FOOTPRINT_TOL_M = 0.001
_PLATFORMS = {"MOD13Q1": "terra", "MYD13Q1": "aqua"}


def whole_pixel_mask(geom_sinu: dict, transform: Affine, width: int, height: int,
                     edge_buffer_m: float = 0.0) -> tuple[Window, np.ndarray] | None:
    """Window and boolean mask of the pixels wholly inside `geom_sinu` (raster CRS).

    Centre inside (geometry_mask, all_touched=False) AND full square footprint
    covered by the polygon shrunk by `edge_buffer_m` (with a 1 mm tolerance so a
    footprint edge lying exactly on the boundary is not lost to floating point).
    None if there are none.
    """
    field = shape(geom_sinu)
    inner = field.buffer(FOOTPRINT_TOL_M - edge_buffer_m)
    if inner.is_empty:
        return None
    left, bottom, right, top = field.bounds
    px, py = transform.a, -transform.e
    c0 = max(int(math.floor((left - transform.c) / px)), 0)
    c1 = min(int(math.ceil((right - transform.c) / px)), width)
    r0 = max(int(math.floor((transform.f - top) / py)), 0)
    r1 = min(int(math.ceil((transform.f - bottom) / py)), height)
    if c0 >= c1 or r0 >= r1:
        return None
    win = Window(c0, r0, c1 - c0, r1 - r0)
    wt = rasterio.windows.transform(win, transform)
    centre = geometry_mask([geom_sinu], out_shape=(win.height, win.width), transform=wt,
                           invert=True, all_touched=False)
    pinner = prep(inner)
    mask = np.zeros_like(centre)
    for r, c in zip(*np.nonzero(centre)):
        x0, y0 = wt @ (c, r)
        x1, y1 = wt @ (c + 1, r + 1)
        mask[r, c] = pinner.covers(box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return (win, mask) if mask.any() else None


def tiles_for(geom_sinu: dict) -> list[tuple[int, int]]:
    """MODIS (h, v) tiles touched by the geometry's bounding box."""
    left, bottom, right, top = shape(geom_sinu).bounds
    size = TILE_PX * PIXEL_M
    hs = range(int((left - GRID_X0) // size), int((right - GRID_X0) // size) + 1)
    vs = range(int((GRID_Y0 - top) // size), int((GRID_Y0 - bottom) // size) + 1)
    return [(h, v) for h in hs for v in vs]


def tile_transform(h: int, v: int) -> Affine:
    size = TILE_PX * PIXEL_M
    return Affine(PIXEL_M, 0.0, GRID_X0 + h * size, 0.0, -PIXEL_M, GRID_Y0 - v * size)


def _composite_start(item) -> dt.date:
    """Composite start date from the item id (e.g. MOD13Q1.A2021177.h09v04...)."""
    a = item.id.split(".")[1]
    return dt.date(int(a[1:5]), 1, 1) + dt.timedelta(days=int(a[5:8]) - 1)


class ModisNdvi:
    source = ("NASA MODIS Terra/Aqua Vegetation Indices 16-Day 250 m (MOD13Q1/MYD13Q1 v061) "
              "via Microsoft Planetary Computer (modis-13Q1-061)")

    def __init__(self, good_reliability: tuple[int, ...] = (0,), edge_buffer_m: float = 0.0,
                 first_year: int = 2000, workers: int = 16, today: dt.date | None = None):
        self.good = np.array(sorted(set(int(x) for x in good_reliability)), dtype=np.uint8)
        self.edge_buffer_m = float(edge_buffer_m)
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

    def _items(self, year: int, h: int, v: int) -> list:
        """Composites of tile (h, v) that start in `year` (the tile filter keeps the search fast)."""
        today = self._today or dt.date.today()
        end = min(dt.date(year, 12, 31), today)
        if end < dt.date(year, 1, 1):
            return []
        last_exc = None
        for attempt in range(3):
            try:
                items = list(self._client().search(
                    collections=[COLLECTION], datetime=f"{year}-01-01/{end.isoformat()}",
                    query={"modis:horizontal-tile": {"eq": h}, "modis:vertical-tile": {"eq": v}},
                    limit=100).items())
                break
            except Exception as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"MODIS search failed for {year} h{h:02d}v{v:02d}: {last_exc}")
        # Reprocessed composites appear as extra items (same product, date and tile, later production
        # stamp in the last id field); keep only the latest of each.
        latest: dict[tuple[str, str], object] = {}
        for it in items:
            parts = it.id.split(".")
            if parts[0] not in _PLATFORMS or _composite_start(it).year != year:
                continue
            key = (parts[0], parts[1])
            if key not in latest or parts[-1] > latest[key].id.split(".")[-1]:
                latest[key] = it
        return [latest[k] for k in sorted(latest)]

    def _read(self, item, expected: Affine, win: Window, mask: np.ndarray) -> tuple[int, int, float]:
        """(whole pixels, good pixels, sum of good NDVI) for one tile's composite."""
        last_exc = None
        for attempt in range(3):
            try:
                with rasterio.Env(**GDAL_ENV):
                    with rasterio.open(item.assets[NDVI_ASSET].href) as src:
                        if not np.allclose(tuple(src.transform)[:6], tuple(expected)[:6], atol=1e-3):
                            raise ValueError(f"unexpected grid in {item.id}: {src.transform}")
                        dn = src.read(1, window=win)
                    with rasterio.open(item.assets[RELIABILITY_ASSET].href) as src:
                        rel = src.read(1, window=win)
                break
            except ValueError:
                raise
            except Exception as exc:  # network hiccup or expired signature
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"could not read {item.id}: {last_exc}")
        good = (mask & np.isin(rel, self.good) & (dn != NDVI_FILL)
                & (dn >= NDVI_VALID[0]) & (dn <= NDVI_VALID[1]))
        n_good = int(good.sum())
        return int(mask.sum()), n_good, float(dn[good].astype(np.float64).sum() * NDVI_SCALE) if n_good else 0.0

    def ndvi_year(self, geometry: dict, year: int) -> dict:
        geom = transform_geom("EPSG:4326", SINUSOIDAL, geometry)
        tiles = tiles_for(geom)
        masks = {}
        for h, v in tiles:
            m = whole_pixel_mask(geom, tile_transform(h, v), TILE_PX, TILE_PX, self.edge_buffer_m)
            if m is not None:
                masks[(h, v)] = m
        # When no whole pixel exists, still list the composites (searched on the field's tile) with zero pixels.
        search_tiles = list(masks) or tiles[:1]
        items = []
        for h, v in search_tiles:
            items += [(it, (h, v)) for it in self._items(year, h, v)]

        groups: dict[tuple[dt.date, str], list] = defaultdict(list)
        for it, hv in items:
            groups[(_composite_start(it), _PLATFORMS[it.id.split(".")[0]])].append((it, hv))

        def one(entry):
            it, hv = entry
            if hv not in masks:
                return 0, 0, 0.0
            win, mask = masks[hv]
            try:
                return self._read(it, tile_transform(*hv), win, mask)
            except Exception as exc:
                log.warning("MODIS composite failed: %s", exc)
                return None

        entries = [e for k in sorted(groups) for e in groups[k]]
        with ThreadPoolExecutor(self.workers) as ex:
            results = dict(zip((e[0].id for e in entries), ex.map(one, entries)))
        failed = sum(1 for r in results.values() if r is None)
        if masks and entries and failed == len(entries):
            raise RuntimeError(f"all {failed} MODIS composites for {year} failed to read")

        observations = []
        for (date, platform) in sorted(groups):
            parts = [results[it.id] for it, _ in groups[(date, platform)]]
            if any(p is None for p in parts):
                continue  # a failed read is unknown, not zero
            pixels = sum(p[0] for p in parts)
            good = sum(p[1] for p in parts)
            total = sum(p[2] for p in parts)
            observations.append({"date": date.isoformat(), "ndvi": round(total / good, 4) if good else None,
                                 "pixels": pixels, "good_pixels": good, "platform": platform})
        return {"year": year, "observations": observations, "pixel_size_m": PIXEL_M, "source": self.source,
                "composites_failed": failed}
