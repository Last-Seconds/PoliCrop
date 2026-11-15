"""County boundary from US Census TIGERweb (TIGER/Line geometry)."""
from __future__ import annotations

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..http import get_json

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"


class TigerCountyRegion:
    def __init__(self, fips: str, region_id: str, name: str):
        self.fips = fips
        self.region_id = region_id
        self.name = name

    def region(self) -> dict:
        data = get_json(TIGERWEB, params={"where": f"GEOID='{self.fips}'", "outFields": "GEOID,NAME",
                                          "outSR": 4326, "f": "geojson"}, timeout=60)
        feats = data.get("features") or []
        if not feats:
            raise RuntimeError(f"TIGERweb returned no county with GEOID {self.fips}")
        geom = unary_union([shape(f["geometry"]) for f in feats])
        if geom.is_empty or geom.area <= 0:
            raise RuntimeError("TIGERweb returned an empty county geometry")
        minx, miny, maxx, maxy = geom.bounds
        if not (-180 <= minx < maxx <= 180 and -90 <= miny < maxy <= 90):
            raise RuntimeError("TIGERweb county geometry is not in longitude/latitude")
        return {"id": self.region_id, "name": self.name, "geometry": mapping(geom),
                "source": "US Census Bureau TIGERweb (TIGER/Line), State_County layer"}
