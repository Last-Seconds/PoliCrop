"""Topsoil moisture from NASA's SMAP satellite, served by USDA Crop-CASMA (NASS / NASA / George Mason University).

OGC WCS 2.0.1, no key. One MapServer map file per year
(`/WMS/SMAP-9KM-WEEKLY-TOP_<year>.map`), one coverage per week and statistic,
e.g. `SMAP-9KM-WEEKLY-TOP_2021_30_2021.07.26_2021.08.01_AVERAGE`. Native grid:
EPSG:5070, about 9 km; values are volumetric soil moisture (m³/m³) of the top
5 cm, nodata −9999. Tested 2026-11-15: 0.6 s per weekly coverage for the county.
"""
from __future__ import annotations

import io
import re

import httpx
import numpy as np
import rasterio
from pyproj import Transformer

from ..http import USER_AGENT, _retry

WCS = "https://cloud.csiss.gmu.edu/smap_server/cgi-bin/mapserv"
_ID = re.compile(r"<wcs:CoverageId>(SMAP-9KM-WEEKLY-TOP_(\d{4})_(\d+)_(\d{4}\.\d{2}\.\d{2})_(\d{4}\.\d{2}\.\d{2})_AVERAGE)<")


def _get(params: dict, timeout: float = 60) -> httpx.Response:
    def go():
        r = httpx.get(WCS, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r
    return _retry(go)


class CropCasmaSoilMoisture:
    source = "NASA SMAP 9 km weekly topsoil moisture via USDA Crop-CASMA (WCS)"

    def weeks(self, year: int) -> dict:
        """{"year", "weeks": [{"id", "week", "start", "end"}]} for the weekly averages of one year."""
        r = _get({"MAP": f"/WMS/SMAP-9KM-WEEKLY-TOP_{int(year)}.map", "SERVICE": "WCS", "VERSION": "2.0.1",
                  "REQUEST": "GetCapabilities"})
        weeks = [{"id": m.group(1), "week": int(m.group(3)), "start": m.group(4).replace(".", "-"),
                  "end": m.group(5).replace(".", "-")} for m in _ID.finditer(r.text)]
        if not weeks:
            raise RuntimeError(f"Crop-CASMA lists no weekly soil moisture for {year}")
        return {"year": int(year), "weeks": sorted(weeks, key=lambda w: w["start"])}

    def week_grid(self, year: int, coverage_id: str, bbox_wgs84: list[float]) -> dict:
        """Cell values inside a lon/lat box: {"values": [...], "lons": [...], "lats": [...], "id"}."""
        to = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
        w, s, e, n = bbox_wgs84
        xs, ys = to.transform([w, e, w, e], [s, s, n, n])
        r = _get({"MAP": f"/WMS/SMAP-9KM-WEEKLY-TOP_{int(year)}.map", "SERVICE": "WCS", "VERSION": "2.0.1",
                  "REQUEST": "GetCoverage", "COVERAGEID": coverage_id, "FORMAT": "image/tiff",
                  "SUBSET": [f"x({min(xs)},{max(xs)})", f"y({min(ys)},{max(ys)})"]})
        if "tiff" not in r.headers.get("content-type", ""):
            raise RuntimeError(f"Crop-CASMA returned {r.text[:200]!r}")
        with rasterio.open(io.BytesIO(r.content)) as src:
            a = src.read(1).astype(float)
            nod = src.nodata
            rows, cols = np.indices(a.shape)
            cx, cy = rasterio.transform.xy(src.transform, rows.ravel(), cols.ravel())
        back = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
        lons, lats = back.transform(np.asarray(cx), np.asarray(cy))
        vals = a.ravel()
        vals = [None if (nod is not None and v == nod) or not np.isfinite(v) else round(float(v), 4) for v in vals]
        return {"id": coverage_id, "values": vals, "lons": [round(float(x), 5) for x in lons],
                "lats": [round(float(y), 5) for y in lats], "source": self.source}
