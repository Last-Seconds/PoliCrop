"""Measure the field screen against brief 3's part S targets in a real browser (Playwright, Chromium).

Run from backend/ with the app on :8777:  python tools/screen_check.py [field letter A–E] [--shots DIR]
"""
from __future__ import annotations

import argparse
import json
import re

from playwright.sync_api import sync_playwright

WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.,–-]*")


def words(t: str) -> int:
    return len(WORDS.findall(t or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fields", nargs="*", default=list("ABCDE"))
    ap.add_argument("--url", default="http://localhost:8777/")
    ap.add_argument("--chrome", default=None, help="browser executable, if Playwright's own is not installed")
    ap.add_argument("--shots", default=None)
    args = ap.parse_args()
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
        for letter in args.fields:
            ctx = b.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=2, is_mobile=True, has_touch=True)
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(args.url)
            page.wait_for_selector("#demo-list button")
            page.locator("#demo-list button", has_text=f"field {letter}").click()
            page.wait_for_selector(".cmp-row", timeout=180000)
            page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0, 0)")
            m = page.evaluate("""() => {
              const rows = [...document.querySelectorAll('.cmp-row')].map(r => r.getBoundingClientRect().bottom);
              const cards = [...document.querySelectorAll('#cards .opt')].map(c => {
                const t = [...c.children].filter(x => !x.classList.contains('details')).map(x => x.innerText).join(' ');
                return t; });
              const first = document.querySelector('#cards .opt');
              return {rows, rowsBottom: Math.max(...rows), cards, headline: document.querySelector('#headline').innerText,
                      firstCardTop: first ? first.getBoundingClientRect().top + scrollY : null,
                      overflowX: document.documentElement.scrollWidth > innerWidth};
            }""")
            # Open every card's details and read the first layer (layer-2 boxes are hidden, so not counted).
            firsts = []
            for btn in page.locator("#cards .why-btn").all():
                btn.click()
            firsts = page.evaluate("""() => [...document.querySelectorAll('#cards .opt .details')].map(d => {
                const clone = d.cloneNode(true);
                clone.querySelectorAll('.layer2, .more-link, .card-actions').forEach(x => x.remove());
                return clone.innerText; })""")
            small = page.evaluate("""() => {
              const bad = new Set();
              for (const n of document.querySelectorAll('#view-field *')) {
                if (!n.offsetParent || !n.childNodes.length) continue;
                const own = [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
                if (own && parseFloat(getComputedStyle(n).fontSize) < 16) bad.add(n.className || n.tagName);
              }
              const tiny = [];
              for (const n of document.querySelectorAll('#view-field button, #view-field a, #view-field summary')) {
                const r = n.getBoundingClientRect();
                if (r.width && r.height < 44) tiny.push((n.className || n.tagName) + ':' + Math.round(r.height));
              }
              return {small: [...bad].slice(0, 12), tiny: [...new Set(tiny)].slice(0, 12)};
            }""")
            if args.shots:
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=f"{args.shots}/field_{letter}_top.png")
            page.locator("#btn-adjust").click()
            page.wait_for_selector("#adjust[open]")
            adj = page.evaluate("""() => {
              const body = document.querySelector('#adjust-body');
              const top = [...body.children].filter(x => !x.classList.contains('more-settings'));
              const ctrls = body.querySelectorAll('input, select, button.chip-toggle');
              return {topLevel: top.length, words: body.innerText.split(/\\s+/).length,
                      controlsAll: ctrls.length, height: body.scrollHeight,
                      hasDefaultLines: /Default:/.test(body.innerText)};
            }""")
            if args.shots:
                page.screenshot(path=f"{args.shots}/field_{letter}_adjust.png")
            res = {
                "headline_words": words(m["headline"]),
                "rows_bottom_px": round(m["rowsBottom"]), "rows_visible": m["rowsBottom"] <= 780, "rows": len(m["rows"]),
                "first_card_top_px": round(m["firstCardTop"]),
                "closed_card_words": [words(t) for t in m["cards"]],
                "first_layer_words": [words(t) for t in firsts],
                "adjust": adj, "horizontal_scroll": m["overflowX"], "text_under_16px": small["small"],
                "tappables_under_44px": small["tiny"], "errors": errors,
            }
            out[letter] = res
            print(letter, json.dumps(res, ensure_ascii=False))
            ctx.close()
        b.close()


if __name__ == "__main__":
    main()
