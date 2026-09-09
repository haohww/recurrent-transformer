"""Ninth-stage recon: real availability, plus the booking payload shape.

recon8 got HTTP 200 and a valid <timeBlocks/> envelope, and one attempt
returned a database error naming a DATETIME of year 271249291 -- epoch
milliseconds being read as seconds. So start/end are epoch SECONDS.

This queries with seconds, over a couple of window sizes (the app defaults
maxDays to 7, so a longer horizon may need either an explicit end or
paging), and prints the code that assembles the booking request, which is
the last unknown. The booking endpoint itself is still not called.
"""

import datetime as dt
import os
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

BASE = "https://kiosk.na1.qless.com"
KIOSK_URL = os.environ.get("QLESS_KIOSK_URL", f"{BASE}/kiosk/app/home/100100000129")
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))
QUEUE_ID = os.environ.get("QLESS_QUEUE_ID", "100100000746")
TXN_ID = os.environ.get("QLESS_TXN_ID", "100100004335")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page()
        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(2_500)

        r = page.request.get(f"{BASE}/qless/api/v1/wssid", timeout=20_000)
        wssid = ""
        if r.ok:
            try:
                wssid = (ET.fromstring(r.text()).text or "").strip()
            except ET.ParseError:
                wssid = r.text().strip()

        now_s = int(dt.datetime.now(dt.timezone.utc).timestamp())
        day = 24 * 3600

        def form(**over):
            f = {
                "locale": "en_US",
                "maxDays": "7",
                "partySize": "1",
                "remote": "true",
                "timeZone": "US/Pacific",
                "transactionTypeIds": TXN_ID,
                "wssid": wssid,
                "start": str(now_s),
            }
            f.update(over)
            return f

        url = f"{BASE}/qless/api/v1/appointment/queue/{QUEUE_ID}/possibleBlocks"
        attempts = [
            ("7 days from now (seconds)", form()),
            ("50 days, explicit end", form(maxDays="50", end=str(now_s + 50 * day))),
            ("window at +40d, 7 days", form(start=str(now_s + 40 * day))),
        ]
        for label, f in attempts:
            try:
                resp = page.request.post(url, form=f, timeout=30_000)
                text = resp.text()
                print(f"\n{'=' * 62}\n=== {label} -> HTTP {resp.status}, {len(text)} bytes\n{'=' * 62}")
                print(text[:2500])
                (OUT / f"blocks-{label.split()[0]}.xml").write_text(text, encoding="utf-8")
            except Exception as exc:
                print(f"\n=== {label} -> ERROR {exc}")
            page.wait_for_timeout(1_500)

        # The last unknown: what the booking POST sends.
        res = page.request.get(f"{BASE}/kiosk/res/js/main.js?b=2.102.0", timeout=30_000)
        body = res.text() if res.ok else ""
        print("\n" + "=" * 62)
        print("=== booking request assembly (scheduleApptUrl consumer)")
        print("=" * 62)
        shown = 0
        for m in re.finditer(r"scheduleApptUrl", body):
            snippet = body[max(0, m.start() - 2200) : m.end() + 1400]
            if "apptConfirmationEmailUrl:" in snippet and "localesUrl:" in snippet:
                continue
            shown += 1
            print(f"\n--- use {shown} ---")
            print(snippet)
            if shown >= 1:
                break
        if not shown:
            # Fall back to the appointment-object builder.
            for m in re.finditer(r"appointment\s*[:=]\s*\{", body):
                print("\n--- appointment object literal ---")
                print(body[m.start() : m.start() + 1600])
                break

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
