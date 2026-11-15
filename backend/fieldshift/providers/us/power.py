"""Daily weather from NASA POWER (point API, Agroclimatology community)."""
from __future__ import annotations

import datetime as dt
import math

from ..http import get_json

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FIRST_DATE = dt.date(1981, 1, 1)
# POWER meteorology comes from the MERRA-2 grid: 0.5 deg latitude x 0.625 deg longitude.
CELL_LAT, CELL_LON = 0.5, 0.625


def grid_cell(lon: float, lat: float) -> dict:
    lat_c = round(lat / CELL_LAT) * CELL_LAT
    lon_c = round((lon + 180) / CELL_LON) * CELL_LON - 180
    km_ns = CELL_LAT * 111.32
    km_ew = CELL_LON * 111.32 * math.cos(math.radians(lat_c))
    return {
        "center": [round(lon_c, 4), round(lat_c, 4)],
        "bounds": [[lat_c - CELL_LAT / 2, lon_c - CELL_LON / 2], [lat_c + CELL_LAT / 2, lon_c + CELL_LON / 2]],
        "size_km": [round(km_ew), round(km_ns)],
    }


class NasaPowerWeather:
    source = "NASA POWER daily point API (community AG): PRECTOTCORR, T2M_MAX, T2M_MIN"

    def __init__(self, today: dt.date | None = None):
        self._today = today

    def daily(self, lon: float, lat: float) -> dict:
        end = (self._today or dt.date.today()) - dt.timedelta(days=1)
        data = get_json(POWER_URL, params={
            "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN", "community": "AG",
            "longitude": round(lon, 4), "latitude": round(lat, 4),
            "start": FIRST_DATE.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "format": "JSON",
        }, timeout=180)
        params = (data.get("properties") or {}).get("parameter") or {}
        precip, tmax, tmin = (params.get(k) or {} for k in ("PRECTOTCORR", "T2M_MAX", "T2M_MIN"))
        if not precip:
            raise RuntimeError(f"NASA POWER returned no precipitation data: {str(data)[:200]}")
        fill = (data.get("header") or {}).get("fill_value", -999)

        def val(d: dict, key: str):
            v = d.get(key)
            return None if v is None or v == fill or (isinstance(v, (int, float)) and v <= -999) else v

        days = []
        for key in sorted(precip):
            try:
                date = dt.datetime.strptime(key, "%Y%m%d").date()
            except ValueError:
                continue
            days.append({"date": date.isoformat(), "precip_mm": val(precip, key),
                         "tmax_c": val(tmax, key), "tmin_c": val(tmin, key)})
        cell = grid_cell(lon, lat)
        return {
            "days": days,
            "source": self.source,
            "spatial_resolution": f"about {cell['size_km'][0]} × {cell['size_km'][1]} km "
                                  f"({CELL_LAT}° × {CELL_LON}°)",
            "grid_cell": cell,
        }


class SnapToGrid:
    """Ask for the grid-cell centre, so every field in one cell shares one cached record."""

    def __init__(self, inner):
        self.inner = inner

    def daily(self, lon: float, lat: float) -> dict:
        lon_c, lat_c = grid_cell(lon, lat)["center"]
        return self.inner.daily(lon_c, lat_c)
