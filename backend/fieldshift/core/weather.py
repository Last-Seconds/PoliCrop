"""A daily weather record as arrays over a complete calendar, with fast window sums.

Built from the WeatherProvider payload after validation (climate.validate_days).
Dates the source never provides by design (Daymet drops 31 December in leap
years: `calendar: "365_day"`) are marked `absent`, not missing: a window is
complete when every day is present or absent-by-design.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from .climate import Day, validate_days


def dropped_by_calendar(d: dt.date, calendar: str | None) -> bool:
    return calendar == "365_day" and d.month == 12 and d.day == 31 and (
        d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0))


@dataclass
class DailySeries:
    first: dt.date
    precip: np.ndarray  # mm/day, NaN where missing
    tmax: np.ndarray  # °C
    tmin: np.ndarray  # °C
    absent: np.ndarray  # bool: not provided by design (calendar)
    calendar: str | None = None
    source: str | None = None

    @property
    def last(self) -> dt.date:
        return self.first + dt.timedelta(days=len(self.precip) - 1)

    def idx(self, d: dt.date) -> int:
        return (d - self.first).days

    def covers(self, a: dt.date, b: dt.date) -> bool:
        return a >= self.first and b <= self.last

    @staticmethod
    def from_days(days: list[Day], calendar: str | None = None, source: str | None = None) -> "DailySeries":
        if not days:
            raise ValueError("no days")
        first, last = days[0].date, days[-1].date
        n = (last - first).days + 1
        p = np.full(n, np.nan)
        tx = np.full(n, np.nan)
        tn = np.full(n, np.nan)
        for d in days:
            i = (d.date - first).days
            if d.precip_mm is not None:
                p[i] = d.precip_mm
            if d.tmax_c is not None:
                tx[i] = d.tmax_c
            if d.tmin_c is not None:
                tn[i] = d.tmin_c
        absent = np.zeros(n, dtype=bool)
        if calendar == "365_day":
            for y in range(first.year, last.year + 1):
                d31 = dt.date(y, 12, 31)
                if first <= d31 <= last and dropped_by_calendar(d31, calendar):
                    i = (d31 - first).days
                    absent[i] = np.isnan(p[i])
        return DailySeries(first, p, tx, tn, absent, calendar, source)

    @staticmethod
    def from_raw(raw: dict) -> "DailySeries":
        return DailySeries.from_days(validate_days(raw), (raw or {}).get("calendar"), (raw or {}).get("source"))

    def adjusted(self, rain_factor: float = 1.0, rain_months: tuple[int, ...] = (), temp_delta_c: float = 0.0) -> "DailySeries":
        """A scenario copy: precipitation scaled in some months, temperatures shifted."""
        p = self.precip.copy()
        if rain_factor != 1.0 and rain_months:
            months = self.months()
            p[np.isin(months, rain_months)] *= rain_factor
        return DailySeries(self.first, p, self.tmax + temp_delta_c, self.tmin + temp_delta_c, self.absent,
                           self.calendar, self.source)

    def months(self) -> np.ndarray:
        if not hasattr(self, "_months"):
            ords = np.arange(len(self.precip)) + self.first.toordinal()
            self._months = np.array([dt.date.fromordinal(int(o)).month for o in ords])
        return self._months

    def _cum(self):
        if getattr(self, "_cum_cache", None) is None:
            vals = np.nan_to_num(self.precip, nan=0.0)
            missing = np.isnan(self.precip) & ~self.absent
            self._cum_cache = (np.concatenate([[0.0], np.cumsum(vals)]),
                               np.concatenate([[0], np.cumsum(missing)]))
        return self._cum_cache

    def precip_sum(self, a: dt.date, b: dt.date) -> tuple[float, int]:
        """(total mm from a to b inclusive, number of missing days). Raises if outside the record."""
        if not self.covers(a, b):
            raise IndexError(f"{a}..{b} outside the record {self.first}..{self.last}")
        cs, cm = self._cum()
        i, j = self.idx(a), self.idx(b) + 1
        return float(cs[j] - cs[i]), int(cm[j] - cm[i])

    def window(self, arr: np.ndarray, a: dt.date, b: dt.date) -> np.ndarray:
        return arr[self.idx(a): self.idx(b) + 1]
