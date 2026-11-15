"""Slope across a field from an elevation grid, and how it compares with the soil survey.

Input is the TerrainProvider payload (untrusted; see providers/us/nasadem.py):
an elevation grid in a local metric CRS around the field, with a mask of the
pixels inside it. Output:

- `field_slope`: slope statistics over the field's pixels and a sensitivity
  class (brief 6.3: low under 5%, moderate 5 to 15%, high above 15%; the
  thresholds are parameters).
- `compare_with_soil`: whether the elevation map and the soil survey's slope
  tell the same story, with one plain sentence for the farmer explaining any
  difference (brief 12).
- `slope_overlay`: an RGBA PNG of the slope classes over the field, in Web
  Mercator pixels with WGS84 bounds, for a Leaflet image overlay. Classes are
  told apart by pattern and opacity as well as colour: gentle ground is a faint
  tint, moderate a solid fill, steep a striped fill.

Slope method: Horn (1981), the 3x3 weighted finite difference used by GDAL and
ArcGIS. Slope is rise over run in percent (100 x tan(angle)). Pixels on the
grid edge or next to missing elevation have no slope. Horn's smoothing plus the
30 m grid understate short, steep slopes; the Palouse's hills are exactly that.
"""
from __future__ import annotations

import math
import re
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

ELEV_RANGE_M = (-500.0, 9000.0)
MIN_PIXELS = 4


class TerrainError(ValueError):
    """The elevation payload is unusable."""


# ---------------------------------------------------------------- grid + slope
@dataclass
class ElevationGrid:
    elevation_m: np.ndarray  # float, NaN = no data; rows north to south
    inside: np.ndarray  # bool
    transform: tuple[float, float, float, float, float, float]  # a, b, c, d, e, f
    crs: str
    source: str | None = None

    @property
    def dx(self) -> float:
        return abs(self.transform[0])

    @property
    def dy(self) -> float:
        return abs(self.transform[4])


def parse_grid(raw: dict) -> ElevationGrid:
    """Validate the provider payload and turn it into arrays."""
    if not isinstance(raw, dict):
        raise TerrainError("elevation payload is not an object")
    try:
        elev = np.array([[np.nan if v is None else float(v) for v in row] for row in raw["elevation_m"]],
                        dtype=float)
        inside = np.array(raw["inside"], dtype=bool)
        tf = tuple(float(v) for v in raw["transform"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainError(f"elevation payload malformed: {exc}") from exc
    if elev.ndim != 2 or elev.shape[0] < 3 or elev.shape[1] < 3:
        raise TerrainError("elevation grid must be at least 3 x 3")
    if inside.shape != elev.shape:
        raise TerrainError("field mask does not match the elevation grid")
    if len(tf) != 6 or tf[1] != 0 or tf[3] != 0 or not (0 < tf[0] < 1000) or not (-1000 < tf[4] < 0):
        raise TerrainError("elevation grid must be north-up with metre pixels")
    crs = str(raw.get("crs") or "")
    if not re.fullmatch(r"EPSG:\d{4,6}", crs):
        raise TerrainError(f"unexpected CRS {crs!r}")
    bad = ~np.isfinite(elev) | (elev < ELEV_RANGE_M[0]) | (elev > ELEV_RANGE_M[1])
    elev[bad] = np.nan
    return ElevationGrid(elev, inside, tf, crs, raw.get("source"))


def slope_percent(elev: np.ndarray, dx: float, dy: float | None = None) -> np.ndarray:
    """Slope in percent by Horn's method; NaN on the border and next to missing values."""
    z = np.asarray(elev, dtype=float)
    dy = dx if dy is None else dy
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * dy)
    out[1:-1, 1:-1] = 100.0 * np.hypot(dzdx, dzdy)
    out[np.isnan(z)] = np.nan  # Horn ignores the centre value; a hole stays a hole
    return out


def classify(slope_pct: float | None, low_below_pct: float = 5.0, high_above_pct: float = 15.0) -> str | None:
    """low / moderate / high, matching FieldSoil.sensitivity (brief 6.3)."""
    if slope_pct is None or slope_pct != slope_pct:
        return None
    if slope_pct < low_below_pct:
        return "low"
    if slope_pct > high_above_pct:
        return "high"
    return "moderate"


# ---------------------------------------------------------------- field stats
@dataclass
class FieldSlope:
    pixels: int
    pixel_size_m: float
    median_pct: float | None
    p75_pct: float | None
    p90_pct: float | None
    max_pct: float | None
    mean_pct: float | None
    share_above: dict[str, float]  # "<threshold pct>" -> share of the field's pixels steeper than that
    slope_class: str | None  # from the median
    low_below_pct: float
    high_above_pct: float
    summary: str
    source: str | None = None
    error: str | None = None
    grid: ElevationGrid | None = field(default=None, repr=False)
    slope: np.ndarray | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "pixels": self.pixels,
            "pixel_size_m": self.pixel_size_m,
            "slope_pct": {"median": self.median_pct, "p75": self.p75_pct, "p90": self.p90_pct,
                          "max": self.max_pct, "mean": self.mean_pct},
            "share_above": self.share_above,
            "class": self.slope_class,
            "thresholds_pct": {"low_below": self.low_below_pct, "high_above": self.high_above_pct},
            "summary": self.summary,
            "source": self.source,
            "error": self.error,
        }


def _r(v: float) -> float:
    return round(float(v), 1)


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "unknown"
    return f"{v:.1f}%" if v < 3 else f"{round(v):d}%"


def unavailable(error: str, low_below_pct: float = 5.0, high_above_pct: float = 15.0) -> FieldSlope:
    return FieldSlope(0, 0.0, None, None, None, None, None, {}, None, low_below_pct, high_above_pct,
                      "Slope from the elevation map is not available for this field.", error=error)


def field_slope(raw: dict | None, low_below_pct: float = 5.0, high_above_pct: float = 15.0,
                share_thresholds_pct: tuple[float, ...] | list[float] = (5.0, 15.0)) -> FieldSlope:
    """Slope statistics over the pixels inside the field. Never raises on bad data."""
    try:
        grid = parse_grid(raw or {})
    except TerrainError as exc:
        return unavailable(str(exc), low_below_pct, high_above_pct)
    slope = slope_percent(grid.elevation_m, grid.dx, grid.dy)
    vals = slope[grid.inside & np.isfinite(slope)]
    if vals.size < MIN_PIXELS:
        out = unavailable("too few elevation pixels inside the field", low_below_pct, high_above_pct)
        out.grid, out.slope, out.source = grid, slope, grid.source
        return out
    med, p75, p90 = (float(np.percentile(vals, q)) for q in (50, 75, 90))
    shares = {f"{t:g}": round(float((vals > t).mean()), 3) for t in sorted(float(t) for t in share_thresholds_pct)}
    cls = classify(med, low_below_pct, high_above_pct)
    steep = float((vals > high_above_pct).mean())
    summary = (f"On the elevation map, the typical slope across this field is {fmt_pct(med)} "
               f"(a rise of about {max(1, round(med))} ft per 100 ft); a quarter of the field is steeper than "
               f"{fmt_pct(p75)}")
    if steep >= 0.005:
        summary += f", and {_share_words(steep)} of it is steeper than {high_above_pct:g}%."
    else:
        summary += f", and almost none of it is steeper than {high_above_pct:g}%."
    return FieldSlope(
        pixels=int(vals.size), pixel_size_m=_r(grid.dx), median_pct=_r(med), p75_pct=_r(p75), p90_pct=_r(p90),
        max_pct=_r(vals.max()), mean_pct=_r(vals.mean()), share_above=shares, slope_class=cls,
        low_below_pct=low_below_pct, high_above_pct=high_above_pct, summary=summary, source=grid.source,
        grid=grid, slope=slope)


def _share_words(share: float) -> str:
    pct = share * 100
    if pct < 1:
        return "less than 1%"
    return f"about {round(pct)}%"


# ---------------------------------------------------------------- vs soil survey
def _soil_weighted_rep(soils: list[dict] | None) -> tuple[float | None, float]:
    """Area-weighted representative slope of all mapped soils, and the share of the field it covers."""
    pairs = []
    for s in soils or []:
        try:
            share = float(s.get("share"))
            rep = (s.get("slope_pct") or [None, None, None])[1]
            rep = None if rep is None else float(rep)
        except (TypeError, ValueError, AttributeError, IndexError):
            continue
        if rep is not None and 0 < share <= 1 and 0 <= rep <= 100:
            pairs.append((rep, share))
    covered = sum(s for _, s in pairs)
    if not pairs or covered < 0.5:
        return None, covered
    return sum(r * s for r, s in pairs) / covered, covered


def _steeper_soils(soils: list[dict] | None, than: float) -> tuple[float, float | None, float | None]:
    """Share of the field in soils mapped steeper than `than`, and their slope range."""
    share, lows, highs = 0.0, [], []
    for s in soils or []:
        try:
            sp = s.get("slope_pct") or [None, None, None]
            rep = float(sp[1])
            if rep > than:
                share += float(s.get("share") or 0)
                if sp[0] is not None:
                    lows.append(float(sp[0]))
                if sp[2] is not None:
                    highs.append(float(sp[2]))
        except (TypeError, ValueError, AttributeError, IndexError):
            continue
    return share, (min(lows) if lows else None), (max(highs) if highs else None)


def _range(lo, hi) -> str:
    if lo is None or hi is None:
        return ""
    return f"{lo:g} to {hi:g}%"


def compare_with_soil(fs: FieldSlope, soil, agree_within_pct: float = 3.0) -> dict:
    """Do the elevation map and the soil survey agree on how steep the field is?

    `soil` is a core.soil.FieldSoil (or anything with slope_low/slope_rep/slope_high,
    main_share and soils). The elevation map's median slope is compared with the
    main soil's representative slope; they agree when they lie within
    `agree_within_pct` percentage points, fall in the same class, or the median
    sits inside the main soil's mapped range. Failing that, the area-weighted
    representative slope of all mapped soils is tried (a main soil can cover a
    small part of a field).

    {"verdict": "consistent" | "consistent_with_other_soils" | "elevation_map_gentler"
                | "elevation_map_steeper" | "no_soil_slope" | "no_elevation",
     "agrees": bool | None,
     "elevation_median_pct", "elevation_p90_pct", "elevation_class",
     "soil_rep_pct", "soil_range_pct": [low, high] | None, "soil_class", "soil_main_share",
     "soil_weighted_rep_pct", "soil_weighted_class",
     "sentence": str}
    """
    lo_t, hi_t = fs.low_below_pct, fs.high_above_pct
    rep = getattr(soil, "slope_rep", None)
    s_lo, s_hi = getattr(soil, "slope_low", None), getattr(soil, "slope_high", None)
    main_share = getattr(soil, "main_share", None)
    soils = getattr(soil, "soils", None) or []
    wrep, _covered = _soil_weighted_rep(soils)
    med, p90 = fs.median_pct, fs.p90_pct
    out = {
        "verdict": None, "agrees": None,
        "elevation_median_pct": med, "elevation_p90_pct": p90, "elevation_class": fs.slope_class,
        "soil_rep_pct": rep, "soil_range_pct": [s_lo, s_hi] if s_lo is not None and s_hi is not None else None,
        "soil_class": classify(rep, lo_t, hi_t), "soil_main_share": main_share,
        "soil_weighted_rep_pct": _r(wrep) if wrep is not None else None,
        "soil_weighted_class": classify(wrep, lo_t, hi_t),
        "sentence": "",
    }

    def how(value: float | None, lo=None, hi=None) -> str | None:
        """close / same_class / in_range, or None when they disagree."""
        if value is None or med is None:
            return None
        if abs(med - value) <= agree_within_pct:
            return "close"
        if classify(value, lo_t, hi_t) == fs.slope_class:
            return "same_class"
        if lo is not None and hi is not None and lo <= med <= hi:
            return "in_range"
        return None

    grid_note = (f"The elevation map is a {fs.pixel_size_m:g} m (about {round(fs.pixel_size_m * 3.28 / 5) * 5:g} ft) "
                 "grid, so it smooths out the short, steep hills of the Palouse and tends to show "
                 "them gentler than they are.")

    if med is None:
        out["verdict"] = "no_elevation"
        if rep is not None:
            rng = _range(s_lo, s_hi)
            out["sentence"] = (f"The slope map is not available; the soil survey puts the main soil at {fmt_pct(rep)}"
                               + (f" (mapped {rng})." if rng else "."))
        else:
            out["sentence"] = "Neither the elevation map nor the soil survey gives a slope for this field."
        return out
    if rep is None and wrep is None:
        out["verdict"] = "no_soil_slope"
        out["sentence"] = (f"The soil survey gives no slope for this field, so only the elevation map is shown "
                           f"(typical slope {fmt_pct(med)}).")
        return out

    main_words = (f"The soil survey maps the main soil" +
                  (f" (about {round(main_share * 100)}% of the field)" if main_share else "") +
                  f" at {fmt_pct(rep)}" + (f", within a range of {_range(s_lo, s_hi)}" if _range(s_lo, s_hi) else ""))

    def gentler_tail(ref: float) -> str:
        s = " " + grid_note
        if p90 is not None and p90 > med:
            s += f" On the elevation map, the steepest tenth of the field ({fmt_pct(p90)} and more) is closer to the survey's figure."
        return s if med < ref - agree_within_pct else ""

    main_how = how(rep, s_lo, s_hi) if rep is not None else None
    if main_how:
        out["verdict"], out["agrees"] = "consistent", True
        if main_how == "in_range" and med < rep:
            out["sentence"] = (f"{main_words}. The elevation map's typical {fmt_pct(med)} falls inside that range, "
                               f"though below the survey's typical figure." + gentler_tail(rep))
        elif main_how == "in_range":
            out["sentence"] = (f"{main_words}. The elevation map's typical {fmt_pct(med)} falls inside that range, "
                               f"though above the survey's typical figure.")
        elif main_how == "same_class":
            out["sentence"] = (f"{main_words}; the elevation map's typical {fmt_pct(med)} puts the field in the same "
                               f"{fs.slope_class} slope class." + gentler_tail(rep))
        else:
            out["sentence"] = f"{main_words}; the elevation map's typical {fmt_pct(med)} agrees with it."
        return out

    w_how = how(wrep)
    if w_how:
        out["verdict"], out["agrees"] = "consistent_with_other_soils", True
        link = "close to" if w_how == "close" else f"in the same {fs.slope_class} slope class as"
        if rep is not None:
            out["sentence"] = (f"{main_words}, but the other soils here are mapped "
                               f"{'steeper' if wrep > rep else 'gentler'}: across all the soils on this field the "
                               f"survey's typical slope is {fmt_pct(wrep)}, {link} the elevation map's "
                               f"{fmt_pct(med)}.")
        else:
            out["sentence"] = (f"Across the soils mapped on this field the survey's typical slope is {fmt_pct(wrep)}, "
                               f"{link} the elevation map's {fmt_pct(med)}.")
        out["sentence"] += gentler_tail(wrep)
        return out

    ref = rep if rep is not None else wrep
    out["agrees"] = False
    if med < ref:
        out["verdict"] = "elevation_map_gentler"
        s = (f"{main_words}, steeper than the elevation map's typical {fmt_pct(med)}. {grid_note} "
             if rep is not None else
             f"The soil survey's typical slope for this field is {fmt_pct(ref)}, steeper than the elevation map's "
             f"{fmt_pct(med)}. {grid_note} ")
        if p90 is not None and p90 >= ref - agree_within_pct:
            s += f"On the elevation map, the steepest tenth of the field ({fmt_pct(p90)} and more) is closer to the survey's figure. "
        s += "Where they differ, trust the survey's slope class for how much soil protection matters."
        out["sentence"] = s.strip()
        return out

    out["verdict"] = "elevation_map_steeper"
    steep_share, st_lo, st_hi = _steeper_soils(soils, ref)
    s = (f"{main_words}, gentler than the elevation map's typical {fmt_pct(med)}." if rep is not None else
         f"The soil survey's typical slope for this field is {fmt_pct(ref)}, gentler than the elevation map's "
         f"{fmt_pct(med)}.")
    if steep_share >= 0.1:
        s += (f" Other soils covering about {round(steep_share * 100)}% of the field are mapped steeper"
              + (f" ({_range(st_lo, st_hi)})" if _range(st_lo, st_hi) else "")
              + ", which fits the elevation map.")
    else:
        s += (" The survey's figure is a typical value for that soil wherever it is mapped, not a measurement of "
              "this field; the elevation map measures this field directly.")
    s += " The steeper ground on the slope map is where soil protection matters most."
    out["sentence"] = s
    return out


# ---------------------------------------------------------------- slope map PNG
CLASS_STYLE = {
    # RGBA; pattern is how the class is told apart without colour
    "low": {"rgba": (230, 230, 210, 70), "pattern": "faint", "label": "Gentle"},
    "moderate": {"rgba": (230, 159, 0, 170), "pattern": "solid", "label": "Moderate"},
    "high": {"rgba": (178, 24, 43, 220), "pattern": "stripes", "label": "Steep"},
}
STRIPE_RGBA = (255, 255, 255, 230)


def _png(rgba: np.ndarray) -> bytes:
    """Encode an (h, w, 4) uint8 array as PNG (no dependencies beyond zlib)."""
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def slope_overlay(fs: FieldSlope, geometry: dict | None = None, display_pixel_m: float = 5.0,
                  stripe_period_px: int = 6, max_size_px: int = 1024) -> tuple[bytes, dict] | None:
    """PNG of slope classes over the field, and its metadata for a Leaflet image overlay.

    The image is on a regular Web Mercator grid (what Leaflet draws), sampled from
    the metric slope grid by nearest neighbour. Pixels outside the field are
    transparent; the field is `geometry` (WGS84 GeoJSON) when given, else the
    grid's inside mask. Returns None when there is no slope grid.

    meta: {"bounds": [[south, west], [north, east]], "width": int, "height": int,
           "legend": [{"class", "label", "range", "color": "#RRGGBB", "pattern", "share"}],
           "source": str}
    """
    if fs.grid is None or fs.slope is None:
        return None
    from pyproj import Transformer

    g, slope = fs.grid, fs.slope
    a, _, c, _, e, f = g.transform
    h, w = slope.shape
    to_merc = Transformer.from_crs(g.crs, "EPSG:3857", always_xy=True)
    to_grid = Transformer.from_crs("EPSG:3857", g.crs, always_xy=True)
    to_ll = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

    rows, cols = np.nonzero(g.inside)
    if geometry is not None:
        import shapely
        from shapely.geometry import shape
        ll_to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        poly_m = shapely.transform(shape(geometry),
                                   lambda xy: np.column_stack(ll_to_merc.transform(xy[:, 0], xy[:, 1])))
        mx0, my0, mx1, my1 = poly_m.bounds
    else:
        poly_m = None
        xs = np.concatenate([c + cols * a, c + (cols + 1) * a])
        ys = np.concatenate([f + rows * e, f + (rows + 1) * e])
        mxs, mys = to_merc.transform(xs, ys)
        mx0, mx1, my0, my1 = float(np.min(mxs)), float(np.max(mxs)), float(np.min(mys)), float(np.max(mys))

    # Web Mercator metres are stretched by 1/cos(latitude).
    _, lat_c = to_ll.transform((mx0 + mx1) / 2, (my0 + my1) / 2)
    step = display_pixel_m / max(math.cos(math.radians(lat_c)), 0.1)
    step = max(step, max(mx1 - mx0, my1 - my0) / max_size_px)
    ow, oh = max(1, int(math.ceil((mx1 - mx0) / step))), max(1, int(math.ceil((my1 - my0) / step)))
    mx1, my0 = mx0 + ow * step, my1 - oh * step

    jj, ii = np.meshgrid(np.arange(ow), np.arange(oh))
    px = mx0 + (jj + 0.5) * step
    py = my1 - (ii + 0.5) * step
    gx, gy = to_grid.transform(px.ravel(), py.ravel())
    col = np.floor((np.asarray(gx) - c) / a).astype(int).reshape(oh, ow)
    row = np.floor((np.asarray(gy) - f) / e).astype(int).reshape(oh, ow)
    ok = (row >= 0) & (row < h) & (col >= 0) & (col < w)
    rr, cc = np.clip(row, 0, h - 1), np.clip(col, 0, w - 1)
    sv = np.where(ok, slope[rr, cc], np.nan)
    if poly_m is not None:
        show = shapely.contains_xy(poly_m, px, py)
    else:
        show = ok & g.inside[rr, cc]
    show &= np.isfinite(sv)

    rgba = np.zeros((oh, ow, 4), dtype=np.uint8)
    lo_t, hi_t = fs.low_below_pct, fs.high_above_pct
    masks = {"low": show & (sv < lo_t), "moderate": show & (sv >= lo_t) & (sv <= hi_t), "high": show & (sv > hi_t)}
    for cls, m in masks.items():
        rgba[m] = CLASS_STYLE[cls]["rgba"]
    stripes = ((ii + jj) % max(stripe_period_px, 3)) < max(stripe_period_px // 3, 1)
    rgba[masks["high"] & stripes] = STRIPE_RGBA

    west, north = to_ll.transform(mx0, my1)
    east, south = to_ll.transform(mx1, my0)
    vals = fs.slope[g.inside & np.isfinite(fs.slope)]
    n = max(vals.size, 1)
    shares = {"low": float((vals < lo_t).sum() / n), "moderate": float(((vals >= lo_t) & (vals <= hi_t)).sum() / n),
              "high": float((vals > hi_t).sum() / n)}
    ranges = {"low": f"under {lo_t:g}%", "moderate": f"{lo_t:g} to {hi_t:g}%", "high": f"over {hi_t:g}%"}
    legend = [{"class": k, "label": st["label"], "range": ranges[k],
               "color": "#%02X%02X%02X" % st["rgba"][:3], "pattern": st["pattern"], "share": round(shares[k], 3)}
              for k, st in CLASS_STYLE.items()]
    meta = {"bounds": [[south, west], [north, east]], "width": ow, "height": oh, "legend": legend,
            "source": g.source}
    return _png(rgba), meta
