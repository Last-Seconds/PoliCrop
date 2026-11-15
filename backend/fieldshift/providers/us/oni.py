"""NOAA's Oceanic Niño Index (brief 3, part D): columns season, year, total, anomaly. Information only."""
from __future__ import annotations

from ..http import get_text

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"


class NoaaOni:
    source = "NOAA Climate Prediction Center, Oceanic Niño Index (ONI)"

    def text(self) -> str:
        t = get_text(ONI_URL, timeout=60)
        if "SEAS" not in t[:200]:
            raise RuntimeError("unexpected reply for the ONI file")
        return t
