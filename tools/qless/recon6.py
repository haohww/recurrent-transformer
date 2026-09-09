"""Sixth-stage recon: the possibleBlocks POST body.

recon5 established that possibleBlocks rejects GET with 405 -- it is a POST
endpoint, and the 405 body shows the server routing internally to api/v2.
What remains is the request body.

Two sources, cheapest first:

  1. The call site in main.js. The previous pass only printed the appConfig
     declarations, so this skips those and shows where apptTimesUrl is
     actually consumed.
  2. A few real POSTs. possibleBlocks only computes availability, so posting
     to it is read-only. The booking endpoint is deliberately NOT touched
     here -- a POST there would create a real appointment.
"""

import json
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "https://kiosk.na1.qless.com"
KIOSK_URL = os.environ.get("QLESS_KIOSK_URL", f"{BASE}/kiosk/app/home/100100000129")
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))
QUEUE_ID = os.environ.get("QLESS_QUEUE_ID", "100100000746")
TXN_ID = int(os.environ.get("QLESS_TXN_ID", "100100004335"))


def use_sites(body: str, term: str) -> list[str]:
    """Occurrences of `term` that are not the appConfig declaration."""
    out = []
    for m in re.finditer(re.escape(term), body):
        snippet = body[max(0, m.start() - 900) : m.end() + 1100]
        # The declaration block is recognisable by its neighbours.
        if "apptConfirmationEmailUrl:" in snippet and "localesUrl:" in snippet:
            continue
        out.append(snippet)
    return out


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

        print("=" * 70)
        print("=== apptTimesUrl / possibleBlocks CALL SITES (declarations skipped)")
        print("=" * 70)
        for term in ("apptTimesUrl", "possibleBlocks"):
            sites = use_sites(body, term)
            print(f"\n### {term}: {len(sites)} non-declaration occurrence(s)")
            for i, s in enumerate(sites[:2], 1):
                print(f"\n--- {term} use {i} ---")
                print(s)

        # The app fetches a web-service session id; POSTs may require it.
        wssid = None
        try:
            r = page.request.get(f"{BASE}/qless/api/v1/wssid", timeout=20_000)
            print(f"\n=== wssid -> HTTP {r.status} ===")
            print(r.text()[:300])
            wssid = r.text().strip()
        except Exception as exc:
            print(f"\n=== wssid -> ERROR {exc} ===")

        now_ms = int(time.time() * 1000)
        in_60d_ms = now_ms + 60 * 24 * 3600 * 1000
        bodies = [
            {"transactionTypeIds": [TXN_ID]},
            {"transactionTypeIds": [TXN_ID], "startTime": now_ms, "endTime": in_60d_ms},
            {"transactionTypeIds": [TXN_ID], "start": now_ms, "end": in_60d_ms,
             "numberOfSpots": 1},
            {"transactionTypeIds": [TXN_ID], "startDate": "2026-09-09",
             "endDate": "2026-11-08", "numberOfSpots": 1},
        ]

        url = f"{BASE}/qless/api/v1/appointment/queue/{QUEUE_ID}/possibleBlocks"
        print("\n" + "=" * 70)
        print("=== live POSTs: possibleBlocks (availability only, never booking)")
        print("=" * 70)
        for payload in bodies:
            for label, kwargs in (
                ("json", {"data": json.dumps(payload),
                          "headers": {"Content-Type": "application/json"}}),
            ):
                try:
                    r = page.request.post(url, timeout=25_000, **kwargs)
                    print(f"\n--- {label} {json.dumps(payload)[:120]} -> HTTP {r.status} ---")
                    print(r.text()[:1200])
                except Exception as exc:
                    print(f"\n--- {label} {json.dumps(payload)[:120]} -> ERROR {exc} ---")
                page.wait_for_timeout(1_200)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
