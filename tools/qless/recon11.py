"""Eleventh-stage recon: the booking POST body, from source.

The availability contract is settled and the calendar is currently empty.
The remaining unknown is what the booking request sends.

This is read from the app's source rather than by experiment: a POST to the
appointment endpoint would create a real appointment, so it is never called
here.

Output is short and the important part is printed LAST, because the CI log
retrieval returns the tail.
"""

import json
import os
import pathlib
import re
import sys

import urllib.request

BASE = "https://kiosk.na1.qless.com"
OUT = pathlib.Path(os.environ.get("QLESS_RECON_OUT", "recon-out"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    body = fetch(f"{BASE}/kiosk/res/js/main.js?b=2.102.0")
    print(f"main.js: {len(body)} bytes")

    # Full context to the artifact; only tight excerpts to the log.
    dump = {}
    for term in ("scheduleApptUrl", "apptConfirmationEmailUrl", "scheduleAppointment",
                 "createAppointment", "bookAppointment"):
        hits = []
        for m in re.finditer(re.escape(term), body):
            hits.append(body[max(0, m.start() - 3000) : m.end() + 2000])
        dump[term] = hits
        print(f"  {term}: {len(hits)} occurrence(s)")
    (OUT / "booking-context.json").write_text(json.dumps(dump, indent=2), encoding="utf-8")

    # The object literals near the booking call: find assignments whose body
    # mentions the consumer fields a booking needs.
    print("\n=== candidate booking payload objects ===")
    shown = 0
    for m in re.finditer(r"\{[^{}]{60,1200}\}", body):
        chunk = m.group(0)
        score = sum(bool(re.search(p, chunk, re.I)) for p in
                    (r"firstName", r"lastName", r"email", r"wssid",
                     r"transactionTypeId", r"start", r"phone"))
        if score >= 4 and re.search(r"wssid", chunk, re.I):
            shown += 1
            print(f"\n--- candidate {shown} (matched {score} field names) ---")
            print(re.sub(r"\s+", " ", chunk)[:900])
            if shown >= 6:
                break
    if not shown:
        print("(none matched -- see booking-context.json in the artifact)")

    # Printed last so it survives log tailing: the exact keys the booking
    # call assembles, if a single object can be isolated.
    print("\n" + "=" * 66)
    print("=== FIELD NAMES NEAR scheduleApptUrl (the answer we need)")
    print("=" * 66)
    for hits in (dump.get("scheduleApptUrl") or []):
        keys = sorted(set(re.findall(r"\b([a-zA-Z][a-zA-Z0-9_]{2,24})\s*:", hits)))
        keys = [k for k in keys if k not in ("function", "return", "default")]
        if keys:
            print(json.dumps(keys, indent=1))
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
