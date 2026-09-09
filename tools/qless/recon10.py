"""Tenth-stage recon: capture the app's own possibleBlocks request.

Guessing the start/end encoding has not converged -- epoch milliseconds and
epoch seconds both produce absurd DATETIME values server-side, and a
40-day input shift moved the reported year by exactly 3,456,000, so the
value is being reinterpreted in some way that is not worth deducing from
outside.

The reliable answer is to let the kiosk build the request itself: walk its
wizard and record the exact form body it posts to possibleBlocks.

Identity fields are filled with obviously fake placeholders -- never the
real applicant's details -- and the walk stops as soon as availability has
been captured, well before anything could be booked.
"""

import json
import os
import pathlib
import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = "https://kiosk.na1.qless.com"
KIOSK_URL = os.environ.get("QLESS_KIOSK_URL", f"{BASE}/kiosk/app/home/100100000129")
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))

# Deliberately fake: this walk must not look like, or become, a real booking.
FAKE = {"first": "Recon", "last": "Placeholder",
        "phone": "2065550100", "email": "recon@example.invalid"}

WATCH = re.compile(r"/appointment/|possibleBlocks|wssid", re.I)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page(viewport={"width": 1280, "height": 1400})

        def on_request(req):
            if WATCH.search(req.url):
                captured.append({
                    "method": req.method,
                    "url": req.url,
                    "post_data": req.post_data or "",
                })

        page.on("request", on_request)
        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(3_000)

        for step in range(1, 10):
            heading = ""
            for sel in ("h1", "h2", ".title", "#consumerInfoMsg"):
                try:
                    el = page.query_selector(sel)
                    if el:
                        heading = (el.inner_text() or "").strip()[:100]
                        if heading:
                            break
                except Exception:
                    pass

            inputs = page.query_selector_all("input:visible, select:visible")
            print(f"\n--- step {step}: {heading!r}, {len(inputs)} input(s) ---")

            for handle in inputs:
                meta = " ".join(filter(None, [
                    handle.get_attribute("name") or "",
                    handle.get_attribute("id") or "",
                    handle.get_attribute("placeholder") or "",
                    handle.get_attribute("type") or "",
                ]))
                value = None
                if re.search(r"first", meta, re.I):
                    value = FAKE["first"]
                elif re.search(r"last|surname", meta, re.I):
                    value = FAKE["last"]
                elif re.search(r"phone|mobile|cell|tel", meta, re.I):
                    value = FAKE["phone"]
                elif re.search(r"mail", meta, re.I):
                    value = FAKE["email"]
                if value:
                    try:
                        handle.fill(value)
                        print(f"    filled {meta[:50]!r}")
                    except Exception as exc:
                        print(f"    could not fill {meta[:40]!r}: {exc}")

            page.screenshot(path=str(OUT / f"wizard-{step:02d}.png"), full_page=True)

            # Prefer the service we care about when it is on screen.
            clicked = False
            for text in ("Alien Firearm License", "Appointment", "Make an Appointment"):
                try:
                    loc = page.get_by_text(text, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=5_000)
                        print(f"    clicked {text!r}")
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                nxt = page.query_selector("#qBtnNext")
                if nxt and "btn-disabled" not in (nxt.get_attribute("class") or ""):
                    nxt.click(timeout=5_000)
                    print("    clicked #qBtnNext")
                    clicked = True

            if not clicked:
                print("    nothing clickable -- stopping walk")
                break

            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2_000)

            if any("possibleBlocks" in c["url"] for c in captured):
                print("    possibleBlocks captured -- stopping before booking")
                break

        browser.close()

    print("\n" + "=" * 66)
    print("=== captured appointment-related requests")
    print("=" * 66)
    for c in captured:
        print(f"\n{c['method']} {c['url']}")
        if c["post_data"]:
            print("  body:")
            for k, v in urllib.parse.parse_qsl(c["post_data"]):
                print(f"    {k} = {v}")
            print(f"  raw: {c['post_data'][:500]}")
    (OUT / "captured-requests.json").write_text(
        json.dumps(captured, indent=2), encoding="utf-8"
    )
    if not any("possibleBlocks" in c["url"] for c in captured):
        print("\nNOTE: the wizard never reached availability -- see wizard-*.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
