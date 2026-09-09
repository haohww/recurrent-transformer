"""Eighth-stage recon: possibleBlocks with the complete parameter set.

The call site's full object is:

    {end, locale, maxDays, partySize, remote, start, timeZone,
     transactionTypeIds, wssid}

Earlier attempts omitted locale, maxDays, partySize and remote, which is why
every one returned 400. The remaining unknown is the start/end format, so
this sends the full set in a few plausible encodings.

Availability only; the booking endpoint stays untouched.
"""

import datetime as dt
import os
import pathlib
import sys
import time
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
        print(f"wssid: {'obtained' if wssid else 'MISSING'}")

        now = dt.datetime.now(dt.timezone.utc)
        now_ms = int(time.time() * 1000)
        end_ms = now_ms + 50 * 24 * 3600 * 1000

        def base(**over):
            form = {
                "locale": "en_US",
                "maxDays": "7",
                "partySize": "1",
                "remote": "false",
                "timeZone": "US/Pacific",
                "transactionTypeIds": TXN_ID,
                "wssid": wssid,
            }
            form.update(over)
            return form

        attempts = [
            ("epoch ms start+end", base(start=str(now_ms), end=str(end_ms),
                                        maxDays="50")),
            ("epoch ms start, maxDays only", base(start=str(now_ms))),
            ("ISO start+end", base(start=now.strftime("%Y-%m-%dT%H:%M:%S"),
                                   end=(now + dt.timedelta(days=50)).strftime(
                                       "%Y-%m-%dT%H:%M:%S"), maxDays="50")),
            ("date-only start", base(start=now.strftime("%Y-%m-%d"), maxDays="50")),
            ("remote=true", base(start=str(now_ms), remote="true")),
        ]

        url = f"{BASE}/qless/api/v1/appointment/queue/{QUEUE_ID}/possibleBlocks"
        for label, form in attempts:
            try:
                resp = page.request.post(url, form=form, timeout=25_000)
                text = resp.text()
                print(f"\n{'=' * 60}\n=== {label} -> HTTP {resp.status}\n{'=' * 60}")
                print(f"start={form.get('start')} end={form.get('end')} maxDays={form['maxDays']}")
                print(text[:2000])
                if resp.ok and text.strip():
                    (OUT / f"blocks-{label.replace(' ', '_')}.xml").write_text(
                        text, encoding="utf-8"
                    )
            except Exception as exc:
                print(f"\n=== {label} -> ERROR {exc}")
            page.wait_for_timeout(1_200)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
