"""Fourth-stage recon: the appointment call's exact shape, compactly.

recon3 dumped too much source to read in a CI log. This narrows to two
questions:

  1. What are the SPA's route names? Loading the appointment route directly
     makes the app issue its own availability request, which is a better
     source of truth than any amount of reading minified code.
  2. How is the possibleBlocks URL actually built?

Output is deliberately small so it survives in the job log.
"""

import json
import os
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

KIOSK_URL = os.environ.get(
    "QLESS_KIOSK_URL", "https://kiosk.na1.qless.com/kiosk/app/home/100100000129"
)
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))
BASE = "https://kiosk.na1.qless.com"

ROUTE_RE = re.compile(r"['\"](?:#?/?)(app/[a-zA-Z0-9_\-/{}:]+)['\"]")
# Knockout/jQuery call sites: capture the statement around the endpoint.
CALL_RE = re.compile(
    r"[^\n;]{0,300}(?:possibleBlocks|appointment/queue|reserveSpot)[^\n;]{0,300}"
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page()
        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(3_000)
        res = page.request.get(f"{BASE}/kiosk/res/js/main.js?b=2.102.0", timeout=30_000)
        body = res.text() if res.ok else ""
        print(f"main.js: HTTP {res.status}, {len(body)} bytes")
        browser.close()

    (OUT / "main.js").write_text(body, encoding="utf-8")

    routes = sorted(set(ROUTE_RE.findall(body)))
    print(f"\n=== {len(routes)} SPA routes ===")
    for r in routes:
        print(f"  {r}")

    calls = CALL_RE.findall(body)
    # Keep only statements that look like they build a URL or issue a request.
    calls = [c.strip() for c in calls if re.search(r"url|get\(|post\(|ajax|\$\.", c, re.I)]
    seen, unique = set(), []
    for c in calls:
        key = c[:120]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    print(f"\n=== {len(unique)} appointment call sites ===")
    for c in unique[:12]:
        print(f"\n  {c[:600]}")

    (OUT / "call-sites.json").write_text(
        json.dumps(unique, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
