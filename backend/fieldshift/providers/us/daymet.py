"""Daily weather from Daymet V4 R1 (NASA ORNL DAAC), single-pixel API, 1 km grid.

Daymet is released once a year, so the current, unfinished year is never in it.
Every Daymet year has 365 days: in leap years 31 December is dropped. The
payload says so (`calendar: "365_day"`) and the core treats those dates as
absent, not missing.
"""
from __future__ import annotations

import datetime as dt
import math

from ..http import get_text

DAYMET_URL = "https://daymet.ornl.gov/single-pixel/api/data"
FIRST_DATE = dt.date(1980, 1, 1)


def parse_daymet_csv(text: str) -> dict:
    """Parse the single-pixel CSV into the WeatherProvider payload. Raises ValueError on a bad file."""
    lines = text.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.lower().startswith("year,yday")), None)
    if header_idx is None:
        raise ValueError(f"Daymet response has no data header: {text[:200]!r}")
    meta = {}
    for ln in lines[:header_idx]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            meta[k.strip().lower()] = v.strip()
    cols = [c.strip().lower() for c in lines[header_idx].split(",")]

    def col(prefix: str) -> int | None:
        return next((i for i, c in enumerate(cols) if c.startswith(prefix)), None)

    i_year, i_yday = cols.index("year"), cols.index("yday")
    i_p, i_tx, i_tn, i_sw = col("prcp"), col("tmax"), col("tmin"), col("swe")
    if i_p is None:
        raise ValueError("Daymet response has no precipitation column")
    days = []
    for ln in lines[header_idx + 1:]:
        parts = ln.split(",")
        if len(parts) < len(cols):
            continue
        try:
            year, yday = int(parts[i_year]), int(float(parts[i_yday]))
            date = dt.date(year, 1, 1) + dt.timedelta(days=yday - 1)
        except ValueError:
            continue

        def num(i):
            if i is None:
                return None
            try:
                v = float(parts[i])
            except ValueError:
                return None
            return None if math.isnan(v) or v <= -9999 else v

        days.append({"date": date.isoformat(), "precip_mm": num(i_p), "tmax_c": num(i_tx), "tmin_c": num(i_tn),
                     "swe": num(i_sw)})
    if not days:
        raise ValueError("Daymet response contained no days")
    elevation = None
    if "elevation" in meta:
        try:
            elevation = float(meta["elevation"].split()[0])
        except ValueError:
            pass
    return {"days": days, "elevation_m": elevation, "tile": meta.get("tile")}


class DaymetWeather:
    source = "Daymet V4 R1 daily surface weather, 1 km grid (NASA ORNL DAAC), single-pixel API"

    def __init__(self, today: dt.date | None = None):
        self._today = today

    def daily(self, lon: float, lat: float) -> dict:
        today = self._today or dt.date.today()
        end = dt.date(today.year - 1, 12, 31)  # complete years only; Daymet truncates to its release
        text = get_text(DAYMET_URL, params={
            "lat": round(lat, 5), "lon": round(lon, 5), "vars": "prcp,tmax,tmin,swe",
            "start": FIRST_DATE.isoformat(), "end": end.isoformat(),
        }, timeout=180)
        parsed = parse_daymet_csv(text)
        return {
            "days": parsed["days"],
            "calendar": "365_day",
            "source": self.source,
            "spatial_resolution": "1 km",
            "grid_cell": {"center": [round(lon, 4), round(lat, 4)], "size_km": [1, 1],
                          "elevation_m": parsed["elevation_m"], "tile": parsed["tile"]},
        }


class SnapToDaymetGrid:
    """Round the point (about 500 m) so nearby requests share one cached record."""

    def __init__(self, inner, step_deg: float = 0.005):
        self.inner = inner
        self.step = step_deg

    def daily(self, lon: float, lat: float) -> dict:
        s = self.step
        return self.inner.daily(round(round(lon / s) * s, 4), round(round(lat / s) * s, 4))
