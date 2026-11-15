"""Canned providers for offline tests: no network, deterministic data."""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# A square "county" around Pullman-ish coordinates and a field inside it.
REGION = {"type": "Polygon", "coordinates": [[[-117.6, 46.6], [-117.0, 46.6], [-117.0, 47.2],
                                              [-117.6, 47.2], [-117.6, 46.6]]]}
FIELD = {"type": "Polygon", "coordinates": [[[-117.30, 46.90], [-117.29, 46.90], [-117.29, 46.906],
                                             [-117.30, 46.906], [-117.30, 46.90]]]}
OUTSIDE = {"type": "Polygon", "coordinates": [[[-118.30, 46.90], [-118.29, 46.90], [-118.29, 46.906],
                                               [-118.30, 46.906], [-118.30, 46.90]]]}

# winter wheat (24) - spring wheat (23) - lentils (52), repeating; 2015 is a mixed year
ROTATION = [24, 23, 52]


class FakeRegion:
    def region(self):
        return {"id": "test", "name": "Test County", "geometry": REGION, "source": "fake"}


class FakeCrops:
    classification = "us_cdl"

    def __init__(self, years=range(2008, 2026), fail_years=()):
        self.years = list(years)
        self.fail_years = set(fail_years)
        self.calls = 0

    def available_years(self):
        return self.years

    def class_counts(self, geometry, year):
        self.calls += 1
        if year in self.fail_years:
            raise RuntimeError("service down")
        coords = geometry["coordinates"][0]
        big = abs(coords[0][0] - coords[1][0]) > 0.05  # the buffered crop-pool area
        if big:
            return {"year": year, "counts": {"24": 5000, "23": 2500, "52": 800, "53": 700, "21": 600,
                                             "31": 300, "61": 900, "176": 4000, "36": 10},
                    "source": "fake"}
        code = ROTATION[(year - 2008) % 3]
        counts = {str(code): 180, "176": 10}
        if year == 2015:
            counts = {str(code): 90, "21": 80, "176": 10}
        return {"year": year, "counts": counts, "source": "fake", "pixel_size_m": 30}

    def legend(self):
        return {}


class FakeWeather:
    """Wet winters, dry summers; one missing value (-999 equivalent) to check handling."""

    def daily(self, lon, lat):
        days = []
        d = dt.date(2000, 1, 1)
        while d <= dt.date(2005, 12, 31):
            wet = 3.0 if d.month in (11, 12, 1, 2) else (0.3 if d.month in (7, 8) else 1.5)
            tmax = 5 + 25 * math.sin(math.pi * (d.timetuple().tm_yday - 30) / 365)
            days.append({"date": d.isoformat(), "precip_mm": wet, "tmax_c": tmax, "tmin_c": tmax - 12})
            d += dt.timedelta(days=1)
        days[400]["precip_mm"] = None
        return {"days": days, "source": "fake", "spatial_resolution": "about 48 × 56 km", "grid_cell": None}


class FakeVegetation:
    def available_years(self):
        return [2023, 2024]

    def ndvi_year(self, geometry, year):
        obs = []
        d = dt.date(year, 1, 5)
        while d.year == year:
            doy = d.timetuple().tm_yday
            if 60 < doy < 330:  # winter gap (snow/cloud)
                ndvi = 0.15 if doy < 110 or doy > 220 else 0.75  # bare - green - bare
                obs.append({"date": d.isoformat(), "ndvi": ndvi, "valid_fraction": 0.95, "scene": f"s{doy}"})
            d += dt.timedelta(days=10)
        obs.append({"date": f"{year}-06-01", "ndvi": 0.7, "valid_fraction": 0.1, "scene": "cloudy"})
        obs.append({"date": "garbage", "ndvi": 0.7, "valid_fraction": 1})
        return {"year": year, "observations": obs, "source": "fake", "scenes_considered": len(obs),
                "scenes_failed": 0}
