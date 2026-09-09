"""Third-stage recon: read how the kiosk builds its appointment requests.

recon2 recovered the endpoint paths; what is still unknown is each call's
parameters and payload shape. Rather than guess and hammer the server with
malformed requests, this pulls the surrounding source out of the app's own
RequireJS modules and prints it, so the client can be written against the
real contract.

Read-only: fetches the app's public JavaScript and prints excerpts.
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

# Modules the appointment flow is likely to live in. RequireJS loads these
# lazily, so they are fetched directly rather than waited for.
CANDIDATE_MODULES = [
    "/kiosk/res/js/app/main.js",
    "/kiosk/res/js/app/appointment.js",
    "/kiosk/res/js/app/appointments.js",
    "/kiosk/res/js/app/api.js",
    "/kiosk/res/js/app/rest.js",
    "/kiosk/res/js/app/services.js",
    "/kiosk/res/js/main.js",
]

TERMS = [
    "possibleBlocks",
    "appointment/queue",
    "queuesTransactionTypesResources",
    "reserveSpot",
    "confirmationEmail",
    "transactionTypeId",
]


def context(body: str, term: str, before: int = 500, after: int = 900) -> list[str]:
    out = []
    for m in re.finditer(re.escape(term), body):
        out.append(body[max(0, m.start() - before) : m.end() + after])
        if len(out) >= 3:
            break
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bodies: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page()

        def on_response(resp):
            if resp.request.resource_type == "script":
                try:
                    bodies[resp.url] = resp.text()
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(6_000)

        # Pull candidate modules directly through the page's own origin, so
        # RequireJS lazy-loading does not hide the appointment code.
        for path in CANDIDATE_MODULES:
            url = BASE + path + "?b=2.102.0"
            try:
                res = page.request.get(url, timeout=20_000)
                if res.ok:
                    bodies[url] = res.text()
                    print(f"fetched {path} ({len(bodies[url])} bytes)")
                else:
                    print(f"skip {path} -> HTTP {res.status}")
            except Exception as exc:
                print(f"skip {path} -> {exc}")

        browser.close()

    (OUT / "script-inventory.json").write_text(
        json.dumps({u: len(b) for u, b in bodies.items()}, indent=2), encoding="utf-8"
    )

    for term in TERMS:
        print(f"\n{'=' * 70}\n=== {term}\n{'=' * 70}")
        hits = 0
        for url, body in bodies.items():
            for excerpt in context(body, term):
                hits += 1
                print(f"\n--- in {url.rsplit('/', 1)[-1]} ---")
                print(excerpt)
        if not hits:
            print("(not found in any fetched script)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
