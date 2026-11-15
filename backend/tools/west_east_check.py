"""The west–east check of BUILD_BRIEF_2.md section 12.

A fallow year should add clearly more water for the following wheat in the dry
west (near LaCrosse) than in the wet east (near Pullman), and winter wheat after
fallow in the west should be short far less often than after a harvested crop.

Run from backend/:  python tools/west_east_check.py
Prints the brief's table for the two demo fields with their real soil storage,
and again with the prototype's single assumed storage of 10.6 in at both places.
"""
from __future__ import annotations

import json

import numpy as np

from fieldshift.app import DATA_DIR, get_service
from fieldshift.core import units
from fieldshift.core.replay import build_replay
from fieldshift.core.weather import DailySeries

FIELDS = {"Pullman (east)": "Demo field D — near Pullman", "LaCrosse (west)": "Demo field E — near LaCrosse (dry west)"}


def rows_for(series: DailySeries, capacity_mm: dict, settings) -> dict:
    rp = build_replay(series, capacity_mm, settings)
    thr = units.in_to_mm(float(settings["water.short_threshold_in"]))
    after_crop = rp.supply_for("0_150cm", "apr_jun", "harvested")
    after_fallow = rp.supply_for("0_150cm", "apr_jun", "fallow")
    norm_fallow = float(np.median(after_fallow))
    norm_crop = float(np.median(after_crop))
    j = int(np.where(rp.years == 2021)[0][0])
    full = (rp.years >= 1982) & (rp.years <= 2025)
    return {
        "Mean crop-year precipitation, 1982–2025": units.mm_to_in(float(rp.crop_year_precip_mm[full].mean())),
        "Median supply, wheat after a harvested crop": units.mm_to_in(norm_crop),
        "Median supply, wheat after fallow": units.mm_to_in(norm_fallow),
        "Gain from fallow": units.mm_to_in(norm_fallow - norm_crop),
        "Wheat after a crop, short of its after-fallow normal (full record)":
            float(np.mean((norm_fallow - after_crop) > thr)),
        "Wheat after fallow, short of the same (full record)": float(np.mean((norm_fallow - after_fallow) > thr)),
        "Wheat shortfall in 2021, after a harvested crop, against its own normal":
            units.mm_to_in(max(0.0, norm_crop - after_crop[j])),
        "Spring peas after a harvested crop, 2021 shortfall against their fixed 9.3 in need":
            units.mm_to_in(max(0.0, units.in_to_mm(9.3) - rp.supply_for("0_100cm", "apr_jul", "harvested")[j])),
        "_years": f"{int(rp.years[0])}–{int(rp.years[-1])} ({len(rp.years)} crop years)",
    }


def fmt(k: str, v) -> str:
    if isinstance(v, str):
        return v
    return f"{v:.0%}" if "short of" in k and "shortfall" not in k else f"{v:.1f} in"


def main() -> None:
    svc = get_service()
    feats = {f["properties"]["name"]: f for f in json.loads((DATA_DIR / "demo_fields.geojson").read_text())["features"]}
    results = {}
    for place, name in FIELDS.items():
        f = svc.make_field({"type": "polygon", "geometry": feats[name]["geometry"]})
        lon, lat = f.centroid()
        series = DailySeries.from_raw(svc.providers.weather.daily(lon, lat))
        soil = svc.field_soil(f)
        proto = {"0_100cm": units.in_to_mm(10.6), "0_150cm": units.in_to_mm(10.6)}
        results[place] = {"soil": rows_for(series, soil.capacity_mm, svc.content.settings),
                          "proto": rows_for(series, proto, svc.content.settings),
                          "capacity": {k: round(units.mm_to_in(v), 1) for k, v in soil.capacity_mm.items()},
                          "default": soil.capacity_default}
    for label, which in (("With each field's soil storage (0–150 cm)", "soil"),
                         ("With the prototype's assumed 10.6 in at both places", "proto")):
        print(f"\n{label}")
        if which == "soil":
            for p in FIELDS:
                print(f"  {p}: storage {results[p]['capacity']} in{' (default!)' if results[p]['default'] else ''}")
        places = list(FIELDS)
        print(f"| | {' | '.join(places)} |\n|---|---|---|")
        for k in results[places[0]][which]:
            print(f"| {k.lstrip('_')} | " + " | ".join(fmt(k, results[p][which][k]) for p in places) + " |")
    s, p = results["LaCrosse (west)"]["soil"], results["Pullman (east)"]["soil"]
    gain_ok = s["Gain from fallow"] > p["Gain from fallow"] + 0.5
    short_ok = s["Wheat after fallow, short of the same (full record)"] < \
        0.5 * s["Wheat after a crop, short of its after-fallow normal (full record)"]
    print(f"\nWest gains clearly more from fallow: {'PASS' if gain_ok else 'FAIL'}; "
          f"west wheat after fallow short far less often than after a crop: {'PASS' if short_ok else 'FAIL'}")


if __name__ == "__main__":
    main()
