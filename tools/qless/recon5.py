"""Fifth-stage recon: settle the possibleBlocks query contract.

recon4 confirmed the two URL templates but not their parameters. This does
two things:

  1. Prints the code around the apptTimesUrl/scheduleApptUrl *uses* (not the
     config entry), which is where the parameters get assembled.
  2. Makes a small number of real read-only GETs against possibleBlocks with
     candidate parameter sets and prints the status and response, because the
     server's own validation errors name what it expects.

Deliberately few requests -- this is someone's booking system, not a fuzzing
target.
"""

import os
import pathlib
import re
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = "https://kiosk.na1.qless.com"
KIOSK_URL = os.environ.get(
    "QLESS_KIOSK_URL", f"{BASE}/kiosk/app/home/100100000129"
)
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))

QUEUE_ID = os.environ.get("QLESS_QUEUE_ID", "100100000746")
TXN_ID = os.environ.get("QLESS_TXN_ID", "100100004335")

CANDIDATES = [
    {},
    {"transactionTypeIds": TXN_ID},
    {"transactionTypeIds": TXN_ID, "numberOfDays": "30"},
    {"transactionTypeIds": TXN_ID, "startDate": "2026-09-09", "endDate": "2026-10-26"},
    {"transactionTypeIds": TXN_ID, "start": "2026-09-09", "end": "2026-10-26"},
    {"transactionTypeIds": TXN_ID, "resourceIds": "", "numDays": "30"},
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page()
        # Load the kiosk first so the request carries whatever session state
        # the app establishes (cookies, wssid) rather than arriving bare.
        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(3_000)

        body = ""
        res = page.request.get(f"{BASE}/kiosk/res/js/main.js?b=2.102.0", timeout=30_000)
        if res.ok:
            body = res.text()

        print("=" * 70)
        print("=== code around apptTimesUrl / scheduleApptUrl USES")
        print("=" * 70)
        for term in ("apptTimesUrl", "scheduleApptUrl"):
            hits = 0
            for m in re.finditer(re.escape(term), body):
                snippet = body[max(0, m.start() - 700) : m.end() + 900]
                if "urls." not in snippet and "Url:" in snippet and hits:
                    continue
                hits += 1
                print(f"\n--- {term} hit {hits} ---")
                print(snippet)
                if hits >= 2:
                    break

        print("\n" + "=" * 70)
        print(f"=== live GETs: possibleBlocks on queue {QUEUE_ID}")
        print("=" * 70)
        for params in CANDIDATES:
            qs = urllib.parse.urlencode(params)
            url = f"{BASE}/qless/api/v1/appointment/queue/{QUEUE_ID}/possibleBlocks"
            if qs:
                url += f"?{qs}"
            try:
                r = page.request.get(url, timeout=25_000)
                text = r.text()
                print(f"\n--- {qs or '(no params)'} -> HTTP {r.status} ---")
                print(text[:900])
            except Exception as exc:
                print(f"\n--- {qs or '(no params)'} -> ERROR {exc} ---")
            page.wait_for_timeout(1_200)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
