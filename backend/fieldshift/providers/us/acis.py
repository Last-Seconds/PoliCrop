"""NOAA weather-station records through ACIS (Applied Climate Information System).

Two calls, no key:
    StnMeta  stations in a county that report precipitation, with their period of record
    StnData  daily precipitation, high and low for one station

ACIS returns values as strings in inches and °F. This module converts them to
internal units (mm, °C) and keeps the precipitation flags, because they change
what a day can be used for:

    "M"           missing                          precip_mm None, flag "M"
    "T"           trace (too little to measure)    precip_mm 0.0,  flag "T"
    "S"           first day of a multi-day
                  accumulation                       precip_mm None, flag "S"
    "0.62A"       accumulated amount, last day of
                  the accumulation                   precip_mm 15.75, flag "A"
    "0.10"        an ordinary daily value           precip_mm 2.54, flag None

ACIS writes an accumulation as S on its first day, M on the days between and
the amount with A on its last day (S, M, M, 0.25A); checked against NOAA's
GHCN-Daily day counts (DAPR) for LaCrosse. So for daily statistics none of
those days is usable (the day's own rain is unknown). For totals over a period
the run S ... A is usable as a whole: the A amount is the run's total. That decision is made in
fieldshift.core.station, not here; this module only reports what ACIS said.
A value ACIS sends that is none of the above is treated as missing (flag "M").

ACIS answers HTTP 200 with {"error": "..."} when a request fails (unknown
station, bad county); that raises RuntimeError, as does any unexpected shape.
"""
from __future__ import annotations

import datetime as dt
import re

import httpx

from ...core import units
from ..http import USER_AGENT, _retry

ACIS_URL = "https://data.rcc-acis.org"
SOURCE = "NOAA cooperative and other weather stations through ACIS (data.rcc-acis.org)"
M_PER_FT = 0.3048

# ACIS station-id type codes (the number after the id in "sids").
SID_TYPE_GHCN = "6"
SID_TYPE_COOP = "2"

_VALUE = re.compile(r"^(-?\d+(?:\.\d+)?)([A-Za-z]?)$")


def post_json(url: str, body: dict, timeout: float = 120, attempts: int = 3):
    """POST a JSON body and return the decoded JSON reply, with the shared retry policy."""
    def go():
        r = httpx.post(url, json=body, timeout=timeout, headers={"User-Agent": USER_AGENT},
                       follow_redirects=True)
        r.raise_for_status()
        return r.json()
    return _retry(go, attempts)


def _check(reply, call: str) -> dict:
    if not isinstance(reply, dict):
        raise RuntimeError(f"ACIS {call}: unexpected reply {str(reply)[:200]!r}")
    if "error" in reply:
        raise RuntimeError(f"ACIS {call}: {reply['error']}")
    return reply


def parse_precip(raw) -> tuple[float | None, str | None]:
    """One ACIS precipitation string -> (mm or None, flag). See the module docstring."""
    s = str(raw).strip() if raw is not None else "M"
    if s in ("", "M"):
        return None, "M"
    if s == "T":
        return 0.0, "T"
    if s == "S":
        return None, "S"
    if s in ("TA", "AT"):  # an accumulation that came to a trace
        return 0.0, "A"
    m = _VALUE.match(s)
    if not m:
        return None, "M"
    inches, flag = float(m.group(1)), m.group(2).upper()
    if inches < 0:
        return None, "M"
    if flag == "A":
        return round(units.in_to_mm(inches), 2), "A"
    if flag:  # an unknown trailing flag: do not guess what it means
        return None, "M"
    return round(units.in_to_mm(inches), 2), None


def parse_temp(raw) -> float | None:
    """One ACIS temperature string (°F) -> °C, or None when missing or flagged."""
    s = str(raw).strip() if raw is not None else "M"
    m = _VALUE.match(s)
    if not m or m.group(2):
        return None
    return round(units.f_to_c(float(m.group(1))), 2)


def _sid_parts(sids) -> list[tuple[str, str]]:
    out = []
    for s in sids or []:
        parts = str(s).split()
        if parts:
            out.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return out


def preferred_id(sids) -> str | None:
    """The id to ask StnData for: the GHCN-Daily id (e.g. USC00456789) when there is one."""
    parts = _sid_parts(sids)
    for want in (SID_TYPE_GHCN, SID_TYPE_COOP):
        for ident, typ in parts:
            if typ == want:
                return ident
    return parts[0][0] if parts else None


def _station(meta: dict) -> dict | None:
    ll = meta.get("ll")
    if not (isinstance(ll, (list, tuple)) and len(ll) == 2):
        return None
    try:
        lon, lat = float(ll[0]), float(ll[1])
    except (TypeError, ValueError):
        return None
    sid = preferred_id(meta.get("sids"))
    if not sid:
        return None
    ranges = []
    for r in meta.get("valid_daterange") or []:
        try:
            a, b = dt.date.fromisoformat(r[0]), dt.date.fromisoformat(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if a <= b:
            ranges.append([a.isoformat(), b.isoformat()])
    elev = meta.get("elev")
    try:
        elev_m = round(float(elev) * M_PER_FT, 1) if elev is not None else None
    except (TypeError, ValueError):
        elev_m = None
    return {
        "id": sid, "name": str(meta.get("name") or sid),
        "sids": [f"{i} {t}".strip() for i, t in _sid_parts(meta.get("sids"))],
        "lon": lon, "lat": lat, "elevation_m": elev_m,
        "state": meta.get("state"), "uid": meta.get("uid"),
        "valid_daterange": ranges,
    }


def parse_stations(reply) -> list[dict]:
    reply = _check(reply, "StnMeta")
    meta = reply.get("meta")
    if not isinstance(meta, list):
        raise RuntimeError(f"ACIS StnMeta: no station list in reply {str(reply)[:200]!r}")
    return [s for s in (_station(m) for m in meta if isinstance(m, dict)) if s]


def parse_daily(reply, sid: str) -> dict:
    reply = _check(reply, "StnData")
    data = reply.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"ACIS StnData {sid}: no data rows")
    days, seen = [], set()
    for row in data:
        if not (isinstance(row, (list, tuple)) and len(row) >= 4):
            raise RuntimeError(f"ACIS StnData {sid}: unexpected row {row!r}")
        try:
            d = dt.date.fromisoformat(str(row[0]))
        except ValueError as exc:
            raise RuntimeError(f"ACIS StnData {sid}: bad date {row[0]!r}") from exc
        if d in seen:
            continue
        seen.add(d)
        p, flag = parse_precip(row[1])
        days.append({"date": d.isoformat(), "precip_mm": p, "precip_flag": flag,
                     "tmax_c": parse_temp(row[2]), "tmin_c": parse_temp(row[3])})
    days.sort(key=lambda r: r["date"])
    meta = reply.get("meta") if isinstance(reply.get("meta"), dict) else {}
    station = _station(meta) if meta else None
    return {
        "sid": sid,
        "station": station,
        "days": days,
        "calendar": "standard",
        "precip_flags": {"M": "missing", "T": "trace, counted as 0",
                         "S": "rain included in the next A value",
                         "A": "accumulated over this day and the S days before it"},
        "source": SOURCE,
    }


class AcisStations:
    source = SOURCE

    def __init__(self, base_url: str = ACIS_URL, timeout: float = 120):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def stations(self, fips: str) -> dict:
        """Stations in a county (5-digit FIPS) that report precipitation.

        {"county": str, "stations": [{"id", "name", "sids", "lon", "lat", "elevation_m",
          "state", "uid", "valid_daterange": [["YYYY-MM-DD", "YYYY-MM-DD"], ...]}], "source": str}
        """
        fips = str(fips).strip()
        if not re.fullmatch(r"\d{5}", fips):
            raise ValueError(f"county FIPS must be 5 digits, got {fips!r}")
        reply = post_json(f"{self.base}/StnMeta", {
            "county": fips, "meta": "name,sids,ll,elev,valid_daterange", "elems": "pcpn",
        }, timeout=self.timeout)
        return {"county": fips, "stations": parse_stations(reply), "source": self.source}

    def daily(self, sid: str, start: str, end: str) -> dict:
        """Daily precipitation (mm, with ACIS flag), high and low (°C) from start to end inclusive.

        {"sid": str, "station": {...}|None, "calendar": "standard", "source": str,
         "days": [{"date": "YYYY-MM-DD", "precip_mm": float|None, "precip_flag": None|"M"|"T"|"S"|"A",
                   "tmax_c": float|None, "tmin_c": float|None}, ...]}
        """
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if a > b:
            raise ValueError(f"start {start} after end {end}")
        reply = post_json(f"{self.base}/StnData", {
            "sid": sid, "sdate": a.isoformat(), "edate": b.isoformat(),
            "elems": [{"name": "pcpn"}, {"name": "maxt"}, {"name": "mint"}],
            "meta": "name,sids,ll,elev",
        }, timeout=self.timeout)
        return parse_daily(reply, sid)
