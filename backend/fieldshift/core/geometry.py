"""Field geometry, kept abstract.

v0 supports a drawn polygon. A click-a-point or pick-a-parcel option is a new
FieldGeometry subclass plus an entry in FIELD_KINDS; nothing else changes,
because providers and core only ever ask a field for its polygon.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod

from pyproj import Geod
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

_GEOD = Geod(ellps="WGS84")


class FieldError(ValueError):
    """The field geometry is unusable; the message is shown to the user."""


class FieldGeometry(ABC):
    kind: str = "abstract"

    @abstractmethod
    def polygon(self) -> BaseGeometry:
        """The field outline in WGS84 longitude/latitude."""

    def centroid(self) -> tuple[float, float]:
        c = self.polygon().centroid
        return (c.x, c.y)

    def area_ha(self) -> float:
        area, _ = _GEOD.geometry_area_perimeter(self.polygon())
        return abs(area) / 10_000

    def geojson(self) -> dict:
        return mapping(self.polygon())

    def key(self) -> str:
        """Stable identifier for caching: same outline -> same key."""
        rounded = json.dumps(_round_coords(self.geojson()), sort_keys=True)
        return hashlib.sha1(f"{self.kind}:{rounded}".encode()).hexdigest()[:16]

    def spec(self) -> dict:
        return {"type": self.kind, "geometry": self.geojson()}


class PolygonField(FieldGeometry):
    kind = "polygon"

    def __init__(self, geometry: dict):
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise FieldError("The field must be drawn as a polygon.")
        try:
            geom = shape(geometry)
        except Exception as exc:  # malformed coordinates
            raise FieldError(f"The field outline could not be read ({exc}).") from None
        if geom.is_empty:
            raise FieldError("The field outline is empty.")
        for x, y in _iter_coords(geom):
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                raise FieldError("The field outline has coordinates outside longitude/latitude range.")
        if not geom.is_valid:
            fixed = geom.buffer(0)
            if fixed.is_empty or not fixed.is_valid:
                raise FieldError(f"The field outline crosses itself ({explain_validity(geom)}).")
            geom = fixed
        self._geom = geom

    def polygon(self) -> BaseGeometry:
        return self._geom


FIELD_KINDS = {"polygon": lambda spec: PolygonField(spec.get("geometry"))}


def field_from_spec(spec: dict) -> FieldGeometry:
    """Build a field from a request: {"type": "polygon", "geometry": <GeoJSON>}."""
    if not isinstance(spec, dict):
        raise FieldError("Missing field description.")
    kind = spec.get("type", "polygon")
    factory = FIELD_KINDS.get(kind)
    if factory is None:
        raise FieldError(f"Field type {kind!r} is not supported yet.")
    return factory(spec)


def check_field(field: FieldGeometry, region_geom: BaseGeometry, region_name: str,
                min_area_ha: float, max_area_ha: float) -> None:
    """Raise FieldError with a user-facing message if the field is not usable."""
    poly = field.polygon()
    if not poly.intersects(region_geom):
        raise FieldError(f"This field is outside {region_name}. This version covers {region_name} only.")
    outside = poly.difference(region_geom).area / poly.area if poly.area else 1.0
    if outside > 0.01:
        raise FieldError(
            f"Part of this field ({outside:.0%}) lies outside {region_name}. "
            f"Please draw a field fully inside {region_name}."
        )
    area = field.area_ha()
    if area < min_area_ha:
        raise FieldError(f"This field is very small ({area:.2f} ha). Please draw at least {min_area_ha} ha.")
    if area > max_area_ha:
        raise FieldError(f"This outline is {area:,.0f} ha, larger than a single field (limit {max_area_ha:,} ha).")


def _iter_coords(geom: BaseGeometry):
    polys = getattr(geom, "geoms", [geom])
    for p in polys:
        yield from p.exterior.coords
        for ring in p.interiors:
            yield from ring.coords


def _round_coords(obj):
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, (list, tuple)):
        return [_round_coords(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _round_coords(v) for k, v in obj.items()}
    return obj


def buffer_geojson(field: FieldGeometry, meters: float) -> dict:
    """The field outline grown by `meters`, using a local equidistant projection (works anywhere)."""
    import numpy as np
    import shapely
    from pyproj import CRS, Transformer

    lon, lat = field.centroid()
    local = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
    fwd = Transformer.from_crs("EPSG:4326", local, always_xy=True)
    inv = Transformer.from_crs(local, "EPSG:4326", always_xy=True)

    def via(t):
        return lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1]))

    grown = shapely.transform(field.polygon(), via(fwd)).buffer(meters)
    return mapping(shapely.transform(grown, via(inv)))
