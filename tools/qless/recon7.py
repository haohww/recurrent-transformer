"""Seventh-stage recon: the full possibleBlocks parameter set.

recon6 found the call site and confirmed wssid is obtainable, but the log
truncated the head of the parameter object and JSON bodies all returned 400.
The kiosk uses jQuery, which posts form-encoded rather than JSON, so this:

  1. Prints the whole parameter object by anchoring on its last field.
  2. Posts form-encoded, with wssid, which is what the app actually sends.

Still availability-only. The booking endpoint stays untouched.
"""

import os
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

BASE = "https://kiosk.na1.qless.com"
KIOSK_URL = os.environ.get("QLESS_KIOSK_URL", f"{BASE}/kiosk/app/home/100100000129")
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))
QUEUE_ID = os.environ.get("QLESS_QUEUE_ID", "100100000746")
TXN_ID = os.environ.get("QLESS_TXN_ID", "100100004335")
TZ = "US/Pacific"


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
        print("=== the whole possibleBlocks parameter object")
        print("=" * 70)
        for m in re.finditer(r"wssid:\s*self\.wssid\(\)", body):
            print("\n--- anchored on `wssid: self.wssid()` ---")
            print(body[max(0, m.start() - 2600) : m.end() + 200])
            break

        # A fresh session id, exactly as the app fetches it.
        wssid = ""
        r = page.request.get(f"{BASE}/qless/api/v1/wssid", timeout=20_000)
        if r.ok:
            try:
                wssid = (ET.fromstring(r.text()).text or "").strip()
            except ET.ParseError:
                wssid = r.text().strip()
        print(f"\n=== wssid: {'obtained' if wssid else 'MISSING'} ===")

        now_ms = int(time.time() * 1000)
        end_ms = now_ms + 60 * 24 * 3600 * 1000
        attempts = [
            {"wssid": wssid, "transactionTypeIds": TXN_ID, "timeZone": TZ},
            {"wssid": wssid, "transactionTypeIds": TXN_ID, "timeZone": TZ,
             "start": str(now_ms)},
            {"wssid": wssid, "transactionTypeIds": TXN_ID, "timeZone": TZ,
             "start": str(now_ms), "end": str(end_ms)},
            {"wssid": wssid, "transactionTypeIds": TXN_ID, "timeZone": TZ,
             "start": str(now_ms), "numberOfDays": "60", "numberOfSpots": "1"},
        ]

        url = f"{BASE}/qless/api/v1/appointment/queue/{QUEUE_ID}/possibleBlocks"
        print("\n" + "=" * 70)
        print("=== form-encoded POSTs (availability only)")
        print("=" * 70)
        for form in attempts:
            shown = {k: (v[:12] + "..." if k == "wssid" and v else v)
                     for k, v in form.items()}
            try:
                resp = page.request.post(url, form=form, timeout=25_000)
                text = resp.text()
                print(f"\n--- {shown} -> HTTP {resp.status} ---")
                print(text[:1500])
            except Exception as exc:
                print(f"\n--- {shown} -> ERROR {exc} ---")
            page.wait_for_timeout(1_200)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
