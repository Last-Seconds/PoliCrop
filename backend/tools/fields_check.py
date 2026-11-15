"""Brief 3, part F done-criteria in a real browser (Playwright, Chromium).

Run from backend/ with the app on :8777:  python tools/fields_check.py [--chrome PATH]
1. Save two fields, change settings in each, reload: both are there with their settings.
2. Download, clear storage, load the file: the same fields give the same results.
3. A damaged file is refused with a reason and changes nothing.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def verdicts(page) -> list:
    page.wait_for_selector(".cmp-row", timeout=180000)
    page.wait_for_function("() => !document.querySelector('#cards .loading')")
    return page.evaluate("() => [...document.querySelectorAll('.cmp-row')].map(r => r.innerText.replace(/\\s+/g, ' '))")


def open_demo(page, letter):
    page.goto(page.url.split("#")[0] + "#")
    page.wait_for_selector("#demo-list button")
    page.locator("#demo-list button", has_text=f"field {letter}").click()
    return verdicts(page)


def save(page, name):
    page.locator("#save-box button", has_text="Save").click()
    page.locator("#save-box input").fill(name)
    page.locator("#save-box button[type=submit]").click()
    page.wait_for_selector("#saved-mark:not([hidden])")


def set_top_priority(page, measure_label):
    page.locator("#btn-adjust").click()
    page.locator(".radio", has_text=measure_label).first.click()
    page.locator("#adjust-apply").click()
    page.wait_for_timeout(300)
    return verdicts(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8777/")
    ap.add_argument("--chrome", default=None)
    args = ap.parse_args()
    ok = True

    def check(cond, what):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1100, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(args.url)
        page.evaluate("localStorage.clear()")

        open_demo(page, "A")
        save(page, "North field")
        a_res = set_top_priority(page, "Nitrogen")
        open_demo(page, "E")
        save(page, "West field")
        e_res = set_top_priority(page, "Soil protection")

        page.reload()
        page.goto(args.url.split("#")[0] + "#")
        page.wait_for_selector(".myfield")
        names = page.locator(".myfield-open strong").all_inner_texts()
        check(sorted(names) == ["North field", "West field"], f"both saved fields listed after reload: {names}")
        page.locator(".myfield-open", has_text="North field").click()
        check(verdicts(page) == a_res, "North field reopens with its settings (same results)")
        check("nitrogen first" in page.locator("#adjust-summary").inner_text(), "North field keeps nitrogen first")
        page.goto(args.url + "#")
        page.locator(".myfield-open", has_text="West field").click()
        check(verdicts(page) == e_res, "West field reopens with its settings (same results)")

        # 2. download, clear, load
        page.goto(args.url + "#")
        with page.expect_download() as dl:
            page.locator("button", has_text="Download my fields").click()
        path = Path(tempfile.mkdtemp()) / "fields.json"
        dl.value.save_as(path)
        data = json.loads(path.read_text())
        check(data["format"] == "fieldshift-fields" and len(data["fields"]) == 2, "download holds two fields")
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector("#my-fields")
        check(page.locator(".myfield").count() == 0, "storage cleared")
        page.locator("#my-fields input[type=file]").set_input_files(str(path))
        page.wait_for_selector(".myfield")
        page.locator(".myfield-open", has_text="North field").click()
        check(verdicts(page) == a_res, "North field from the file gives the same results")
        page.goto(args.url + "#")
        page.locator(".myfield-open", has_text="West field").click()
        check(verdicts(page) == e_res, "West field from the file gives the same results")

        # 3. damaged files
        page.goto(args.url + "#")
        before = page.evaluate("localStorage.getItem('fieldshift.fields')")
        bad = dict(data)
        bad["fields"] = [dict(data["fields"][0]), {**data["fields"][1], "geometry": {"type": "Polygon", "coordinates": [[[1, 2]]]}}]
        cases = {"broken outline": json.dumps(bad), "not JSON": "{not json", "wrong kind": json.dumps({"hello": 1}),
                 "newer version": json.dumps({**data, "version": 99})}
        for what, text in cases.items():
            f = path.with_name(f"bad-{what.replace(' ', '_')}.json")
            f.write_text(text)
            page.locator("#my-fields input[type=file]").set_input_files(str(f))
            page.wait_for_selector("#file-msg .error")
            msg = page.locator("#file-msg").inner_text()
            after = page.evaluate("localStorage.getItem('fieldshift.fields')")
            check("not loaded" in msg and after == before, f"{what}: refused with a reason ({msg.strip()[:90]}…), nothing changed")
            page.evaluate("document.querySelector('#file-msg').replaceChildren()")
        b.close()
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    main()
