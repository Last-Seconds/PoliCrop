"""US provider set: TIGER boundary, USDA CDL, Daymet, USDA soils, Sentinel-2 — each behind the cache."""
from __future__ import annotations

import datetime as dt

from ...cache import CachedProvider, FileCache
from ...core.content import Content
from ...core.service import Providers
from .cdl import CdlOverlay, CropScapeCountyCdl, PlanetaryComputerCdl, UsCdlProvider
from .acis import AcisStations
from .oni import NoaaOni
from .cdl_sequences import CdlRoleSequences
from .daymet import DaymetWeather, SnapToDaymetGrid
from .drought import UsDroughtMonitor
from .nasadem import NasademTerrain
from .modis import ModisNdvi
from .field_picker import CdlFieldPicker
from .casma import CropCasmaSoilMoisture
from .sentinel2 import Sentinel2Ndvi
from .soil import GnatsgoRasters, SoilDataAccess, UsSoilProvider
from .tiger import TigerCountyRegion

DAY = 86400.0


class SequenceHistograms:
    """JSON-argument adapter around CdlRoleSequences so the file cache can key on plain values."""

    def __init__(self, inner: CdlRoleSequences):
        self.inner = inner

    def histogram(self, geometry: dict, years: list, code_roles: list, radius_km: float, max_unknown_years: int) -> dict:
        from ...core.geometry import PolygonField
        return self.inner.histogram(PolygonField(geometry), [int(y) for y in years],
                                    {int(k): str(v) for k, v in code_roles}, float(radius_km), int(max_unknown_years))


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

    # Daymet is released once a year: refresh monthly so a new year appears.
    weather = SnapToDaymetGrid(CachedProvider(DaymetWeather(), cache, "daymet", ["daily"], lambda m, a, r: 30 * DAY))

    # Soil: the raster read and the (slow) attribute query are cached separately,
    # so a failed attribute query is retried next time instead of being remembered.
    soil = UsSoilProvider(CachedProvider(GnatsgoRasters(), cache, "gnatsgo", ["read"]),
                          CachedProvider(SoilDataAccess(), cache, "sda", ["attributes"]))

    def ndvi_ttl(method, args, result):
        if method == "ndvi_year" and args[1] >= dt.date.today().year:
            return 2 * DAY  # current year keeps growing
        return None if method == "ndvi_year" else 7 * DAY

    vegetation = CachedProvider(
        Sentinel2Ndvi(s["vegetation.masked_scl_classes"], s["vegetation.max_scene_cloud_cover"]),
        cache, "s2_ndvi", ["ndvi_year"], ndvi_ttl)

    overlay = CdlOverlay(cropscape, cache, content.legend("us_cdl"),
                         years=lambda: [y for y in crops.available_years() if y > 2021] or crops.available_years())
    drought = CachedProvider(UsDroughtMonitor(), cache, "usdm", ["county_weeks"], lambda m, a, r: 1 * DAY)
    sequences = CachedProvider(SequenceHistograms(CdlRoleSequences(cropscape)), cache, "cdl_seq", ["histogram"])
    crop_codes = {code for c in content.crops for code in c.codes(crops.classification)}
    boundaries = CdlFieldPicker(cropscape, crop_codes)
    stations = CachedProvider(AcisStations(), cache, "acis", ["stations", "daily"], lambda m, a, r: 30 * DAY)
    return Providers(region=region, crops=crops, weather=weather, vegetation=vegetation, overlay=overlay,
                     soil=soil, drought=drought, sequences=sequences, stations=stations, boundaries=boundaries,
                     oni=CachedProvider(NoaaOni(), cache, "oni", ["text"], lambda m, a, r: 7 * DAY),
                     soil_moisture=CachedProvider(CropCasmaSoilMoisture(), cache, "casma", ["weeks", "week_grid"],
                                                  lambda m, a, r: None if int(a[0]) < dt.date.today().year else 7 * DAY),
                     terrain=CachedProvider(NasademTerrain(float(s["terrain.pixel_size_m"])), cache, "nasadem", ["elevation"]),
                     long_vegetation=CachedProvider(
                         ModisNdvi(tuple(int(x) for x in s["modis.good_reliability"]), float(s["modis.edge_buffer_m"])),
                         cache, "modis", ["ndvi_year"], ndvi_ttl))
