"""US Drought Monitor summary for the county: worst drought each crop year, the latest week.

Input is the provider payload (untrusted): weekly cumulative percent of the
county in each class (d0 = D0 or worse ... d4 = D4). County-wide, not the field.
"""
from __future__ import annotations

import datetime as dt

CLASS_WORDS = {"d0": "abnormally dry (D0)", "d1": "moderate drought (D1)", "d2": "severe drought (D2)",
               "d3": "extreme drought (D3)", "d4": "exceptional drought (D4)"}
KEYS = ("d0", "d1", "d2", "d3", "d4")


def _clean(raw: dict) -> list[dict]:
    out = []
    for r in (raw or {}).get("rows") or []:
        try:
            d = dt.date.fromisoformat(str(r["date"])[:10])
            vals = {k: float(r[k]) for k in KEYS}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(0.0 <= v <= 100.0 + 1e-6 for v in vals.values()):
            continue
        out.append({"date": d, **vals})
    return sorted(out, key=lambda r: r["date"])


def worst_class(row: dict, min_share: float) -> str | None:
    """The most severe class covering at least min_share percent of the county."""
    for k in reversed(KEYS):
        if row[k] >= min_share:
            return k
    return None


def summarise(raw: dict, start_month: int = 9, min_share: float = 50.0, highlight_year: int | None = None) -> dict:
    rows = _clean(raw)
    if not rows:
        raise ValueError("No usable Drought Monitor weeks.")
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        cy = r["date"].year + 1 if r["date"].month >= start_month else r["date"].year
        by_year.setdefault(cy, []).append(r)
    years = []
    for cy, rs in sorted(by_year.items()):
        peak = max(rs, key=lambda r: tuple(r[k] for k in reversed(KEYS)))
        years.append({
            "year": cy, "weeks": len(rs),
            "peak_date": peak["date"].isoformat(), **{f"peak_{k}": round(peak[k], 1) for k in KEYS},
            "worst_class": worst_class(peak, min_share),
            "weeks_d2_half": sum(1 for r in rs if r["d2"] >= min_share),
        })
    latest = rows[-1]
    lw = worst_class(latest, min_share)
    latest_text = (f"In the week of {latest['date']:%-d %B %Y}, "
                   + (f"{latest[lw]:.0f}% of the county was in {CLASS_WORDS[lw]} or worse." if lw
                      else "less than half the county was even abnormally dry."))
    hl = None
    if highlight_year is not None and highlight_year in by_year:
        y = next(x for x in years if x["year"] == highlight_year)
        k = y["worst_class"]
        hl = (f"In {dt.date.fromisoformat(y['peak_date']):%B %Y}, {y['peak_' + k]:.0f}% of Whitman County was in "
              f"{CLASS_WORDS[k]}" + (" — the most severe class." if k == "d4" else ".")) if k else None
    severe = [y["year"] for y in years if y["worst_class"] in ("d3", "d4")]
    return {
        "years": years, "first": rows[0]["date"].isoformat(), "last": latest["date"].isoformat(),
        "latest": {"date": latest["date"].isoformat(), **{k: latest[k] for k in KEYS}, "worst_class": lw,
                   "text": latest_text},
        "extreme_years": severe, "highlight_text": hl,
        "text": (f"Since {rows[0]['date'].year}, extreme or exceptional drought (D3–D4) covered at least half the "
                 f"county in {len(severe)} crop year{'s' if len(severe) != 1 else ''}"
                 + (f": {', '.join(str(y) for y in severe)}." if severe else ".")),
        "class_words": CLASS_WORDS, "min_share": min_share,
    }
