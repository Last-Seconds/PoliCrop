"""USDA Cropland Data Layer: crop-type class counts inside a geometry.

Two sources, one provider:
- Microsoft Planetary Computer `usda-cdl` (cropland asset), 2008-2021.
- USDA CropScape county files (GetCDLFile?fips=...), for later years and as a
  fallback. Bounding-box extraction from CropScape regularly timed out in
  testing; the county-wide files are served from a server-side cache and are
  fast, so each year's county file is downloaded once and read locally.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import re
import threading
from pathlib import Path

import numpy as np
import rasterio
import rasterio.errors
import rasterio.io
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds

from ...cache import FileCache
from ..http import download, get_text

log = logging.getLogger(__name__)

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
CDL_SERVICE = "https://nassgeodata.gmu.edu/axis2/services/CDLService"
GDAL_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="1",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff")


def window_counts(src, geometry_wgs84: dict) -> tuple[dict[str, int], float]:
    """Pixel counts per class inside the geometry, for an open single-band dataset."""
    geom = transform_geom("EPSG:4326", src.crs, geometry_wgs84)
    xs, ys = _coords(geom)
    res = abs(src.transform.a)
    left, bottom, right, top = min(xs) - res, min(ys) - res, max(xs) + res, max(ys) + res
    db = src.bounds
    left, bottom, right, top = max(left, db.left), max(bottom, db.bottom), min(right, db.right), min(top, db.top)
    if left >= right or bottom >= top:
        return {}, res
    win = from_bounds(left, bottom, right, top, src.transform).round_offsets().round_lengths()
    win = win.intersection(Window(0, 0, src.width, src.height))
    data = src.read(1, window=win)
    wt = src.window_transform(win)
    inside = geometry_mask([geom], out_shape=data.shape, transform=wt, invert=True)
    if not inside.any():  # field smaller than a pixel: take touched pixels
        inside = geometry_mask([geom], out_shape=data.shape, transform=wt, invert=True, all_touched=True)
    vals = data[inside]
    counts = np.bincount(vals.astype(np.int64).ravel(), minlength=256) if vals.size else np.zeros(256, int)
    return {str(c): int(n) for c, n in enumerate(counts) if n and c != 0}, res


def _coords(geom: dict):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0])
            ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(geom["coordinates"])
    return xs, ys


class PlanetaryComputerCdl:
    source = "USDA CDL via Microsoft Planetary Computer (usda-cdl)"

    def __init__(self):
        self._local = threading.local()

    def _client(self):
        if not hasattr(self._local, "client"):
            import planetary_computer
            import pystac_client
            self._local.client = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
        return self._local.client

    def available_years(self) -> list[int]:
        col = self._client().get_collection("usda-cdl")
        start, end = col.extent.temporal.intervals[0]
        return list(range(start.year, end.year + 1))

    def class_counts(self, geometry: dict, year: int) -> dict:
        items = list(self._client().search(
            collections=["usda-cdl"], intersects=geometry, datetime=str(year),
            query={"usda_cdl:type": {"eq": "cropland"}}).items())
        if not items:
            raise RuntimeError(f"no Planetary Computer CDL tile for {year}")
        total: dict[str, int] = {}
        res = 30.0
        with rasterio.Env(**GDAL_ENV):
            for it in items:
                with rasterio.open(it.assets["cropland"].href) as src:
                    counts, res = window_counts(src, geometry)
                for k, v in counts.items():
                    total[k] = total.get(k, 0) + v
        return {"year": year, "counts": total, "source": self.source, "pixel_size_m": res}


class CropScapeCountyCdl:
    source = "USDA CDL via CropScape county file"

    def __init__(self, fips: str, cache: FileCache, first_year: int = 2008):
        self.fips = fips
        self.cache = cache
        self.first_year = first_year
        self._dl_lock = threading.Lock()

    def latest_year(self) -> int:
        """Newest CDL year.

        The service names its valid year range in the error for an out-of-range
        year (seen with both HTTP 200 and HTTP 500 responses). If that fails,
        fall back to asking for county files, newest year first.
        """
        import httpx

        from ..http import USER_AGENT
        for probe_year in (dt.date.today().year + 1, dt.date.today().year + 5):
            try:
                r = httpx.get(f"{CDL_SERVICE}/GetCDLValue", timeout=90, headers={"User-Agent": USER_AGENT},
                              params={"year": probe_year, "x": -1621316, "y": 2837386})
                m = re.search(r"between (\d{4}) and (\d{4})", r.text)
                if m:
                    return int(m.group(2))
            except httpx.HTTPError as exc:
                log.warning("CDL year probe failed: %s", exc)
        for year in range(dt.date.today().year, dt.date.today().year - 4, -1):
            try:
                text = get_text(f"{CDL_SERVICE}/GetCDLFile", params={"year": year, "fips": self.fips},
                                timeout=120, attempts=1)
                if "<returnURL>" in text:
                    return year
            except Exception:
                continue
        raise RuntimeError("could not determine the latest CDL year from CropScape")

    def available_years(self) -> list[int]:
        return list(range(self.first_year, self.latest_year() + 1))

    def county_file(self, year: int) -> Path:
        path = self.cache.file_path("cdl_county", f"CDL_{year}_{self.fips}.tif")
        if path.exists() and path.stat().st_size > 0:
            return path
        with self._dl_lock:
            if path.exists() and path.stat().st_size > 0:
                return path
            text = get_text(f"{CDL_SERVICE}/GetCDLFile", params={"year": year, "fips": self.fips}, timeout=180)
            m = re.search(r"<returnURL>([^<]+)</returnURL>", text)
            if not m:
                raise RuntimeError(f"CropScape returned no file for {year}: {text[:200]!r}")
            log.info("downloading CDL county file %s", m.group(1))
            download(m.group(1), path)
            with rasterio.open(path) as src:  # validate before trusting it
                if src.count < 1 or src.crs is None:
                    path.unlink(missing_ok=True)
                    raise RuntimeError("downloaded CDL file is not a valid raster")
        return path

    def class_counts(self, geometry: dict, year: int) -> dict:
        with rasterio.open(self.county_file(year)) as src:
            counts, res = window_counts(src, geometry)
        return {"year": year, "counts": counts, "source": f"{self.source} (FIPS {self.fips})", "pixel_size_m": res}


class UsCdlProvider:
    """CropHistoryProvider for the US: Planetary Computer where it has the year, CropScape otherwise."""
    classification = "us_cdl"

    def __init__(self, pc: PlanetaryComputerCdl, cropscape: CropScapeCountyCdl, pc_years: list[int] | None = None):
        self.pc = pc
        self.cropscape = cropscape
        self._pc_years = pc_years

    def _pc_year_set(self) -> set[int]:
        if self._pc_years is None:
            try:
                self._pc_years = self.pc.available_years()
            except Exception as exc:
                log.warning("Planetary Computer CDL years unavailable: %s", exc)
                return set()
        return set(self._pc_years)

    def available_years(self) -> list[int]:
        years = set(self._pc_year_set())
        try:
            years |= set(range(self.cropscape.first_year, self.cropscape.latest_year() + 1))
        except Exception as exc:
            log.warning("CropScape latest year unavailable: %s", exc)
        if not years:
            raise RuntimeError("no crop-type map years available")
        return sorted(y for y in years if y >= self.cropscape.first_year)

    def class_counts(self, geometry: dict, year: int) -> dict:
        order = [self.pc, self.cropscape] if year in self._pc_year_set() else [self.cropscape]
        errors = []
        for src in order:
            try:
                return src.class_counts(geometry, year)
            except Exception as exc:
                log.warning("%s failed for %s: %s", type(src).__name__, year, exc)
                errors.append(f"{type(src).__name__}: {exc}")
        raise RuntimeError("; ".join(errors))

    def legend(self) -> dict:
        return {}  # the legend comes from data/us/cdl_legend.json


class CdlOverlay:
    """The county crop-type map as a PNG for the map view (MapOverlayProvider)."""

    def __init__(self, cropscape: CropScapeCountyCdl, cache: FileCache, legend: dict[int, dict],
                 years: callable):
        self.cropscape = cropscape
        self.cache = cache
        self.legend = legend
        self._years = years

    def overlay_years(self) -> list[int]:
        return self._years()

    def overlay_png(self, year: int) -> tuple[bytes, dict]:
        import json

        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject

        png = self.cache.file_path("overlay", f"cdl_{self.cropscape.fips}_{year}.png")
        meta_path = png.with_suffix(".json")
        if png.exists() and meta_path.exists():
            return png.read_bytes(), json.loads(meta_path.read_text())
        with rasterio.open(self.cropscape.county_file(year)) as src:
            dst_crs = "EPSG:3857"
            transform, width, height = calculate_default_transform(
                src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=40)
            data = np.zeros((height, width), dtype=np.uint8)
            reproject(rasterio.band(src, 1), data, src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=dst_crs, resampling=Resampling.nearest)
            try:
                cmap = src.colormap(1)
            except ValueError:
                cmap = {}
        lut = np.zeros((256, 4), dtype=np.uint8)
        for code in range(1, 256):
            hexcol = self.legend.get(code, {}).get("color")
            if hexcol:
                rgb = tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
            elif code in cmap:
                rgb = cmap[code][:3]
            else:
                continue
            lut[code] = (*rgb, 210)
        rgba = lut[data]
        buf = io.BytesIO()
        import warnings
        with warnings.catch_warnings(), rasterio.io.MemoryFile() as mem:
            warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
            with mem.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as dst:
                dst.write(np.moveaxis(rgba, 2, 0))
            buf.write(mem.read())
        from pyproj import Transformer
        inv = Transformer.from_crs(3857, 4326, always_xy=True)
        west, north = inv.transform(transform.c, transform.f)
        east, south = inv.transform(transform.c + transform.a * width, transform.f + transform.e * height)
        vals, cnts = np.unique(data[data > 0], return_counts=True)
        total = cnts.sum() or 1
        legend = [{"code": int(v), "name": self.legend.get(int(v), {}).get("name", f"Class {v}"),
                   "color": self.legend.get(int(v), {}).get("color", "#999999"), "share": round(float(c / total), 4)}
                  for v, c in sorted(zip(vals, cnts), key=lambda t: -t[1]) if c / total >= 0.005]
        meta = {"year": year, "bounds": [[south, west], [north, east]], "legend": legend,
                "source": f"USDA NASS Cropland Data Layer {year} (CropScape)"}
        png.write_bytes(buf.getvalue())
        meta_path.write_text(json.dumps(meta))
        return buf.getvalue(), meta
