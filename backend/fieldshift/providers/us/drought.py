"""US Drought Monitor county statistics (University of Nebraska–Lincoln, NOAA, USDA). No key.

statisticsType=1 gives the cumulative percent of the county area in each class:
`d0` is the share in D0 or worse, ..., `d4` the share in D4.
"""
from __future__ import annotations

import datetime as dt

import httpx

from ..http import USER_AGENT, _retry

USDM_URL = ("https://usdmdataservices.unl.edu/api/CountyStatistics/"
            "GetDroughtSeverityStatisticsByAreaPercent")


class UsDroughtMonitor:
    source = "US Drought Monitor (National Drought Mitigation Center, University of Nebraska–Lincoln; NOAA; USDA)"

    def __init__(self, today: dt.date | None = None):
        self._today = today

    def county_weeks(self, fips: str, start: str, end: str | None = None) -> dict:
        """Weekly rows between two ISO dates: {"rows": [{"date", "none", "d0".."d4"}], "source"}."""
        end_d = dt.date.fromisoformat(end) if end else (self._today or dt.date.today())
        start_d = dt.date.fromisoformat(start)

        def go():
            r = httpx.get(USDM_URL, timeout=120, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                          params={"aoi": fips, "statisticsType": 1,
                                  "startdate": f"{start_d.month}/{start_d.day}/{start_d.year}",
                                  "enddate": f"{end_d.month}/{end_d.day}/{end_d.year}"})
            r.raise_for_status()
            return r.json()

        data = _retry(go)
        if not isinstance(data, list):
            raise RuntimeError(f"Drought Monitor returned {str(data)[:200]!r}")
        rows = []
        for rec in data:
            try:
                rows.append({"date": str(rec["mapDate"])[:10], "none": float(rec["none"]),
                             **{k: float(rec[k]) for k in ("d0", "d1", "d2", "d3", "d4")}})
            except (KeyError, TypeError, ValueError):
                continue
        if not rows:
            raise RuntimeError("Drought Monitor returned no usable weeks")
        return {"rows": sorted(rows, key=lambda r: r["date"]), "source": self.source, "fips": fips}
