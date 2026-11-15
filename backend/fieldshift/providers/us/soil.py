"""Soil for a field from USDA NRCS data, two routes combined.

- gNATSGO rasters on the Microsoft Planetary Computer (10 m): the `mukey` raster
  gives each soil map unit's share of the field, and `aws0_100` / `aws0_150`
  give plant-available water storage. A window read; fast.
  Units checked against Soil Data Access at the same spot (2026-11-15): the
  rasters are in millimetres (200 = SDA's 20 cm).
- Soil Data Access (SDA) tabular service: names, drainage class, slope range,
  hydrologic group and erodibility for those map units. Every SDA call took
  about 60 s when tested, so results are cached forever; if it fails, the
  storage figures still work and the attributes are reported missing.
"""
from __future__ import annotations

import logging
import threading

import httpx
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds

from ..http import USER_AGENT, _retry
from .cdl import GDAL_ENV, PC_STAC, _coords

log = logging.getLogger(__name__)
SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
NODATA_INT = 2147483647


class GnatsgoRasters:
    source = "USDA NRCS gNATSGO rasters (July 2020) via Microsoft Planetary Computer (gnatsgo-rasters)"

    def __init__(self):
        self._local = threading.local()

    def _client(self):
        if not hasattr(self._local, "client"):
            import planetary_computer
            import pystac_client
            self._local.client = pystac_client.Client.open(PC_STAC, modifier=planetary_computer.sign_inplace)
        return self._local.client

    def read(self, geometry: dict) -> dict:
        """Per map unit inside the field: pixel count and mean storage (mm) at 0–100 and 0–150 cm."""
        items = list(self._client().search(collections=["gnatsgo-rasters"], intersects=geometry).items())
        if not items:
            raise RuntimeError("no gNATSGO tile covers the field")
        per: dict[int, dict] = {}
        total = 0
        with rasterio.Env(**GDAL_ENV):
            for it in items:
                arrays = {}
                for asset in ("mukey", "aws0_100", "aws0_150"):
                    with rasterio.open(it.assets[asset].href) as src:
                        g = transform_geom("EPSG:4326", src.crs, geometry)
                        xs, ys = _coords(g)
                        b = src.bounds
                        left, bottom = max(min(xs), b.left), max(min(ys), b.bottom)
                        right, top = min(max(xs), b.right), min(max(ys), b.top)
                        if left >= right or bottom >= top:
                            break  # this tile does not reach the field (STAC boxes overlap)
                        win = from_bounds(left, bottom, right, top, src.transform).round_offsets().round_lengths()
                        win = win.intersection(Window(0, 0, src.width, src.height))
                        data = src.read(1, window=win)
                        inside = geometry_mask([g], out_shape=data.shape, transform=src.window_transform(win),
                                               invert=True, all_touched=False)
                        if not inside.any():
                            inside = geometry_mask([g], out_shape=data.shape, transform=src.window_transform(win),
                                                   invert=True, all_touched=True)
                        arrays[asset] = (data, inside)
                if len(arrays) < 3:
                    continue
                mk, inside = arrays["mukey"]
                sel = inside & (mk != NODATA_INT) & (mk > 0)
                for key in np.unique(mk[sel]):
                    m = sel & (mk == key)
                    rec = per.setdefault(int(key), {"pixels": 0, "aws100": [], "aws150": []})
                    rec["pixels"] += int(m.sum())
                    for asset, slot in (("aws0_100", "aws100"), ("aws0_150", "aws150")):
                        vals = arrays[asset][0][m].astype(float)
                        vals = vals[(vals >= 0) & (vals < 5000)]
                        if vals.size:
                            rec[slot].append((float(vals.mean()), int(vals.size)))
                total += int(sel.sum())
        if not total:
            raise RuntimeError("gNATSGO has no soil map unit inside the field")

        def wmean(lst):
            n = sum(c for _, c in lst)
            return round(sum(v * c for v, c in lst) / n, 1) if n else None

        units = [{"mukey": str(k), "pixels": v["pixels"], "area_share": round(v["pixels"] / total, 4),
                  "aws0_100_mm": wmean(v["aws100"]), "aws0_150_mm": wmean(v["aws150"])}
                 for k, v in sorted(per.items(), key=lambda kv: -kv[1]["pixels"])]
        return {"map_units": units, "pixel_size_m": 10, "source": self.source}


class SoilDataAccess:
    source = "USDA NRCS Soil Data Access (SSURGO tabular data)"

    def attributes(self, mukeys: list[str]) -> dict:
        keys = sorted({int(k) for k in mukeys})  # integers only: nothing user-supplied reaches the SQL
        if not keys:
            return {"components": [], "source": self.source}
        sql = (
            "SELECT mu.mukey, mu.muname, c.compname, c.comppct_r, c.drainagecl, c.slope_l, c.slope_r, c.slope_h, "
            "c.hydgrp, ma.aws0100wta, ma.aws0150wta, "
            "(SELECT TOP 1 ch.kwfact FROM chorizon ch WHERE ch.cokey = c.cokey ORDER BY ch.hzdept_r) AS kw_top "
            "FROM mapunit mu JOIN component c ON c.mukey = mu.mukey JOIN muaggatt ma ON ma.mukey = mu.mukey "
            f"WHERE c.majcompflag = 'Yes' AND mu.mukey IN ({','.join(str(k) for k in keys)})"
        )

        def go():
            r = httpx.post(SDA_URL, json={"format": "JSON+COLUMNNAME", "query": sql}, timeout=180,
                           headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r.json()

        data = _retry(go, attempts=2, backoff=3)
        table = (data or {}).get("Table") or []
        if not table:
            raise RuntimeError("Soil Data Access returned no rows")
        cols = table[0]
        rows = [dict(zip(cols, row)) for row in table[1:]]
        return {"components": rows, "source": self.source}


class UsSoilProvider:
    """SoilProvider: combines the raster shares with SDA attributes."""

    def __init__(self, rasters, sda):
        self.rasters = rasters
        self.sda = sda

    def soil(self, geometry: dict) -> dict:
        base = self.rasters.read(geometry)
        units = base["map_units"]
        out = {"map_units": units, "source": base["source"], "attributes_source": None, "attributes_error": None}
        try:
            # Small slivers add SDA time but no information.
            keys = [u["mukey"] for u in units if u["area_share"] >= 0.01] or [units[0]["mukey"]]
            attrs = self.sda.attributes(keys)
            by_key: dict[str, list] = {}
            for row in attrs.get("components") or []:
                by_key.setdefault(str(row.get("mukey")), []).append(row)
            for u in units:
                rows = by_key.get(u["mukey"], [])
                u["name"] = rows[0].get("muname") if rows else None
                u["components"] = [{
                    "name": r.get("compname"), "pct": r.get("comppct_r"), "drainage": r.get("drainagecl"),
                    "slope_low": r.get("slope_l"), "slope_rep": r.get("slope_r"), "slope_high": r.get("slope_h"),
                    "hydgrp": r.get("hydgrp"), "kw": r.get("kw_top"),
                    "aws0_100_cm": r.get("aws0100wta"), "aws0_150_cm": r.get("aws0150wta"),
                } for r in rows]
            out["attributes_source"] = attrs.get("source")
        except Exception as exc:  # degrade: storage still works
            log.warning("Soil Data Access failed: %s", exc)
            out["attributes_error"] = str(exc)
        return out
