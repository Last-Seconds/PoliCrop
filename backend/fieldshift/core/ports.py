"""Provider interfaces: what the core asks for, never how it is fetched.

Core logic only talks to these protocols. The US implementation lives in
fieldshift.providers.us; another country is a new provider set implementing the
same protocols. Return values are plain JSON-compatible dicts and lists so the
cache layer can store them unchanged; the core validates everything it receives
(external data is untrusted input).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RegionProvider(Protocol):
    def region(self) -> dict:
        """{"id", "name", "geometry": GeoJSON in WGS84, "source"}"""


@runtime_checkable
class CropHistoryProvider(Protocol):
    classification: str  # key into Crop.class_codes, e.g. "us_cdl"

    def available_years(self) -> list[int]:
        """Years with a crop-type map, ascending."""

    def class_counts(self, geometry: dict, year: int) -> dict:
        """Pixel counts per class code inside the geometry for one year.

        {"year": int, "counts": {"<code>": int, ...}, "source": str,
         "pixel_size_m": float}
        """

    def legend(self) -> dict:
        """{"<code>": {"name": str, "color": "#RRGGBB"}} for classes this provider may return."""


@runtime_checkable
class WeatherProvider(Protocol):
    def daily(self, lon: float, lat: float) -> dict:
        """Longest available daily record for a point.

        {"days": [{"date": "YYYY-MM-DD", "precip_mm": float|None,
                    "tmax_c": float|None, "tmin_c": float|None}, ...],
         "source": str, "spatial_resolution": str, "grid_cell": {...}|None}
        """


@runtime_checkable
class VegetationProvider(Protocol):
    def available_years(self) -> list[int]:
        """Years with imagery, ascending."""

    def ndvi_year(self, geometry: dict, year: int) -> dict:
        """Field-average NDVI observations for one calendar year.

        {"year": int, "observations": [{"date": "YYYY-MM-DD", "ndvi": float|None,
          "valid_fraction": float, "scene": str}], "source": str,
          "scenes_considered": int, "scenes_failed": int}
        """


class MapOverlayProvider(Protocol):
    """Optional: a crop-type map image for the map view."""

    def overlay_years(self) -> list[int]: ...

    def overlay_png(self, year: int) -> tuple[bytes, dict]:
        """(PNG bytes, {"bounds": [[south, west], [north, east]], "legend": [...], "year": int})"""
