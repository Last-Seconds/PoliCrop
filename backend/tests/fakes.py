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
        xs = [p[0] for p in geometry["coordinates"][0]]
        big = max(xs) - min(xs) > 0.05  # the buffered crop-pool area
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
    """Wet winters, dry summers.

    short=True: 2000-2005 with one missing value (climate tests).
    short=False: 1980-2025 like Daymet (31 Dec dropped in leap years), with
    deterministic year-to-year variation and a dry, hot 2021 (replay tests).
    `scale` multiplies all precipitation (a wetter or drier place).
    """

    def __init__(self, short=True, scale=1.0):
        self.short = short
        self.scale = scale

    def daily(self, lon, lat):
        days = []
        first, last = (dt.date(2000, 1, 1), dt.date(2005, 12, 31)) if self.short else \
            (dt.date(1980, 1, 1), dt.date(2025, 12, 31))
        d = first
        while d <= last:
            if not self.short and d.month == 12 and d.day == 31 and d.year % 4 == 0:
                d += dt.timedelta(days=1)
                continue  # Daymet's 365-day calendar
            wet = 3.0 if d.month in (11, 12, 1, 2) else (0.3 if d.month in (7, 8) else 1.5)
            if not self.short:
                wet *= 0.6 + 0.8 * ((d.year * 7919) % 13) / 12  # 0.6 .. 1.4 by year
                if d.year == 2021 and 3 <= d.month <= 7:
                    wet *= 0.3
            tmax = 5 + 25 * math.sin(math.pi * (d.timetuple().tm_yday - 30) / 365)
            if d.year == 2021 and d.month in (6, 7):
                tmax += 12
            days.append({"date": d.isoformat(), "precip_mm": round(wet * self.scale, 3), "tmax_c": tmax,
                         "tmin_c": tmax - 12})
            d += dt.timedelta(days=1)
        if self.short:
            days[400]["precip_mm"] = None
        return {"days": days, "source": "fake", "spatial_resolution": "1 km", "grid_cell": None,
                "calendar": "standard" if self.short else "365_day"}


class FakeSoil:
    def __init__(self, fail=False, drainage="Well drained", slope=16):
        self.fail = fail
        self.drainage = drainage
        self.slope = slope

    def soil(self, geometry):
        if self.fail:
            raise RuntimeError("soil service down")
        comp = lambda name, pct: {"name": name, "pct": pct, "drainage": self.drainage, "slope_low": 7,
                                  "slope_rep": self.slope, "slope_high": 25, "hydgrp": "B", "kw": 0.37}
        return {"map_units": [
            {"mukey": "1", "area_share": 0.7, "aws0_100_mm": 200.0, "aws0_150_mm": 300.0,
             "name": "Palouse silt loam, 7 to 25 percent slopes", "components": [comp("Palouse", 100)]},
            {"mukey": "2", "area_share": 0.3, "aws0_100_mm": 180.0, "aws0_150_mm": 260.0,
             "name": "Thatuna silt loam", "components": [comp("Thatuna", 100)]},
        ], "source": "fake soil", "attributes_source": "fake", "attributes_error": None}


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
