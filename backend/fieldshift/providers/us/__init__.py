"""US provider set: TIGER boundary, USDA CDL, NASA POWER, Sentinel-2 — each behind the cache."""
from __future__ import annotations

import datetime as dt

from ...cache import CachedProvider, FileCache
from ...core.content import Content
from ...core.service import Providers
from .cdl import CdlOverlay, CropScapeCountyCdl, PlanetaryComputerCdl, UsCdlProvider
from .power import NasaPowerWeather, SnapToGrid
from .sentinel2 import Sentinel2Ndvi
from .tiger import TigerCountyRegion

DAY = 86400.0


def build_us_providers(content: Content, cache: FileCache) -> Providers:
    region_cfg = content.region
    fips = str(region_cfg["fips"])
    s = content.settings

    region = CachedProvider(TigerCountyRegion(fips, region_cfg["id"], region_cfg["name"]), cache,
                            "tiger", ["region"], lambda m, a, r: 30 * DAY)

    pc = CachedProvider(PlanetaryComputerCdl(), cache, "cdl_pc", ["available_years"], lambda m, a, r: 7 * DAY)
    cropscape = CropScapeCountyCdl(fips, cache)
    cropscape_cached = CachedProvider(cropscape, cache, "cdl_cropscape", ["latest_year"], lambda m, a, r: 1 * DAY)
    # available_years is not cached here: its parts are, and a degraded answer
    # (one source down) must not be remembered.
    crops = CachedProvider(UsCdlProvider(pc, cropscape_cached), cache, "cdl", ["class_counts"])

    weather = SnapToGrid(CachedProvider(NasaPowerWeather(), cache, "power", ["daily"], lambda m, a, r: 3 * DAY))

    def ndvi_ttl(method, args, result):
        if method == "ndvi_year" and args[1] >= dt.date.today().year:
            return 2 * DAY  # current year keeps growing
        return None if method == "ndvi_year" else 7 * DAY

    vegetation = CachedProvider(
        Sentinel2Ndvi(s["vegetation.masked_scl_classes"], s["vegetation.max_scene_cloud_cover"]),
        cache, "s2_ndvi", ["ndvi_year"], ndvi_ttl)

    overlay = CdlOverlay(cropscape, cache, content.legend("us_cdl"),
                         years=lambda: [y for y in crops.available_years() if y > 2021] or crops.available_years())
    return Providers(region=region, crops=crops, weather=weather, vegetation=vegetation, overlay=overlay)
