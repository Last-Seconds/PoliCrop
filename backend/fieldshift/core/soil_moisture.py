"""County topsoil moisture by season from weekly satellite grids (regional context, never scored).

Input: per year, weekly grids of volumetric soil moisture (m³/m³, top 5 cm) with
cell centres; cells whose centre lies in the region are averaged.
"""
from __future__ import annotations

import datetime as dt
from statistics import mean

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry


def week_mean(grid: dict, region: BaseGeometry) -> float | None:
    vals = []
    for v, x, y in zip(grid.get("values") or [], grid.get("lons") or [], grid.get("lats") or []):
        if v is None or not (0.0 <= float(v) <= 0.8):
            continue
        if region.contains(Point(float(x), float(y))):
            vals.append(float(v))
    return mean(vals) if vals else None


def seasonal(weekly: dict[int, list[tuple[str, float | None]]], months: tuple[int, int], highlight_year: int | None,
             min_weeks: int) -> dict:
    """weekly: year -> [(week start ISO, county mean)]. Mean over weeks starting in the month range."""
    rows = []
    for y in sorted(weekly):
        vals = [v for d, v in weekly[y] if v is not None and months[0] <= dt.date.fromisoformat(d).month <= months[1]]
        rows.append({"year": y, "mean": round(mean(vals), 4) if len(vals) >= min_weeks else None, "weeks": len(vals)})
    good = [r for r in rows if r["mean"] is not None]
    if not good:
        return {"years": rows, "text": None}
    avg = mean(r["mean"] for r in good)
    driest = min(good, key=lambda r: r["mean"])
    hl = next((r for r in good if r["year"] == highlight_year), None)
    text = (f"Across {good[0]['year']}–{good[-1]['year']}, topsoil water in the county averaged {avg * 100:.0f}% by volume "
            f"from {_mon(months[0])} to {_mon(months[1])}; the driest season was {driest['year']} "
            f"({driest['mean'] * 100:.0f}%)")
    if hl and hl is not driest:
        text += f", and {hl['year']} had {hl['mean'] * 100:.0f}%"
    return {"years": rows, "average": round(avg, 4), "driest_year": driest["year"], "text": text + "."}


def _mon(m: int) -> str:
    return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December"][m - 1]
