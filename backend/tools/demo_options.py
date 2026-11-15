"""Print the current rotation and the options shown for each example field (brief 3, part S report).

Run from backend/:  python tools/demo_options.py [--json out.json]
Uses the live providers through the file cache; run `python -m fieldshift.prewarm` first.
"""
from __future__ import annotations

import argparse
import json

from fieldshift.app import DATA_DIR, get_service

SYM = {1: "▲", 0: "●", -1: "▼", None: "–"}


def summarise(card: dict) -> dict:
    return {
        "label": card["label"],
        "crops": [s["crop"] for s in card["steps"]],
        "verdicts": {l["measure"]: l["verdict"] for l in card["lines"]},
        "cautions": [c["short"] for c in card["cautions"]],
        "nearby": (card["notes"].get("nearby") or {}).get("share"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the summary here as well")
    args = ap.parse_args()
    svc = get_service()
    fc = json.loads((DATA_DIR / "demo_fields.geojson").read_text())
    out = {}
    for feat in fc["features"]:
        name = feat["properties"]["name"]
        f = svc.make_field({"type": "polygon", "geometry": feat["geometry"]})
        res = svc.strategies(f, {})
        rows = [summarise(res["current"])] + [summarise(o) for o in res["options"]]
        out[name] = {"headline": res["headline"], "rows": rows}
        print(f"\n{name}")
        for h in res["headline"]:
            print(f"  | {h}")
        for r in rows:
            v = " ".join(f"{m[:3]}{SYM[r['verdicts'][m]]}" for m in ("water", "soil", "nitrogen", "variety"))
            nb = "" if r["nearby"] is None else f"  nearby {r['nearby'] * 100:.1f}%"
            print(f"  {r['label']:<22} {', '.join(r['crops']):<55} {v}{nb}")
            for c in r["cautions"]:
                print(f"      ! {c}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(out, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
