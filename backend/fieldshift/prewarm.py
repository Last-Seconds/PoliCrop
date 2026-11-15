"""Pre-warm the cache for the demo fields, so a demo works when remote services are slow.

    python -m fieldshift.prewarm             # all demo fields in data/demo_fields.geojson
    python -m fieldshift.prewarm --only 1    # just the first one
"""
from __future__ import annotations

import argparse
import json
import logging
import time

from .app import DATA_DIR, get_cache, get_service
from .core.geometry import field_from_spec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None, help="1-based index of a single demo field")
    ap.add_argument("--skip-vegetation", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    svc = get_service()
    svc.region()
    feats = json.loads((DATA_DIR / "demo_fields.geojson").read_text())["features"]
    if args.only:
        feats = [feats[args.only - 1]]
    try:
        t = time.time()
        ctx = svc.region_context()
        print(f"region context: drought {'ok' if 'drought' in ctx else ctx.get('drought_error')}, soil moisture "
              f"{'ok' if 'soil_moisture' in ctx else ctx.get('soil_moisture_error')} ({time.time() - t:.0f}s)")
    except Exception as exc:
        print(f"region context failed: {exc}")
    ov = svc.providers.overlay
    if ov:
        for y in ov.overlay_years()[-1:]:
            ov.overlay_png(y)
            print(f"overlay {y}: ok")
    for feat in feats:
        name = feat["properties"].get("name")
        f = svc.make_field({"type": "polygon", "geometry": feat["geometry"]})
        get_cache().put("fields", f.key(), f.spec(), ttl=None)
        t = time.time()
        h = svc.history(f)
        print(f"[{name}] history: {[(y['year'], y['name'], y['share']) for y in h['years']]} ({time.time() - t:.0f}s)")
        t = time.time()
        c = svc.climate(f)
        print(f"[{name}] climate: {c['record']} ({time.time() - t:.0f}s)")
        t = time.time()
        svc.soil(f)
        print(f"[{name}] soil ({time.time() - t:.0f}s)")
        st = svc.strategies(f, history=h)
        print(f"[{name}] strategies: current={[s['crop'] for s in st['current']['steps']]} "
              f"options={[[s['crop'] for s in a['steps']] for a in st['options']]}")
        t = time.time()
        for fn in (svc.slope, svc.station, svc.greenness_history):
            try:
                fn(f)
                print(f"[{name}] {fn.__name__} ({time.time() - t:.0f}s)")
            except Exception as exc:
                print(f"[{name}] {fn.__name__} failed: {exc}")
        if not args.skip_vegetation:
            for y in svc.vegetation_years():
                t = time.time()
                print(f"[{name}] vegetation {y}: {svc.vegetation_year(f, y)} ({time.time() - t:.0f}s)")
            v = svc.vegetation(f)
            print(f"[{name}] vegetation: {v['counts']}, bare periods {len(v['bare_periods'])}, gaps {len(v['gaps'])}")


if __name__ == "__main__":
    main()
