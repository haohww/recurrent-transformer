"""Second-stage recon: recover the kiosk's appointment API surface.

The first pass showed the kiosk speaks a plain XML REST API under
/qless/api/v1/kiosk/, which is a far better target than clicking a
JavaScript wizard. What is still missing is the availability and booking
endpoints, so rather than guess at URLs this reads them out of the app's own
JavaScript bundles, and dumps the home DOM outline in case the UI is still
needed as a fallback.

Read-only: it fetches the app's own assets and prints what it finds.
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

# Any string in the bundle that looks like a kiosk API path.
PATH_RE = re.compile(r"""['"`]([^'"`\s]*?(?:api/v\d|/qless/)[^'"`\s]{0,160})['"`]""")
# Appointment-flow terms worth surfacing separately.
APPT_RE = re.compile(r"appoint|available|slot|reserv|book|schedul|timeslot", re.I)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scripts: list[str] = []
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
        page.wait_for_timeout(4_000)

        scripts = page.eval_on_selector_all(
            "script[src]", "els => els.map(e => e.src)"
        )

        # Everything with text, not just things that look like buttons -- the
        # first pass only saw a disabled Back/Next pair, so the real entry
        # point is some other element.
        outline = page.eval_on_selector_all(
            "*",
            """els => els
                 .filter(e => e.offsetParent !== null && e.children.length === 0)
                 .map(e => ({tag: e.tagName, cls: (e.className||'').toString().slice(0,80),
                             id: e.id || '', text: (e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,100)}))
                 .filter(e => e.text)
                 .slice(0, 120)""",
        )
        (OUT / "home-outline.json").write_text(
            json.dumps(outline, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (OUT / "home2.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(OUT / "home2.png"), full_page=True)
        browser.close()

    print(f"=== {len(scripts)} script tags ===")
    for s in scripts:
        print(f"  {s}")

    found: set[str] = set()
    for url, body in bodies.items():
        for match in PATH_RE.findall(body):
            found.add(match)
    (OUT / "api-paths.json").write_text(
        json.dumps(sorted(found), indent=2), encoding="utf-8"
    )

    appt = sorted(p for p in found if APPT_RE.search(p))
    print(f"\n=== {len(appt)} appointment-related API paths (of {len(found)} total) ===")
    for path in appt:
        print(f"  {path}")

    print("\n=== all other API paths ===")
    for path in sorted(found - set(appt)):
        print(f"  {path}")

    print("\n=== home DOM outline (leaf elements with text) ===")
    print(json.dumps(outline, indent=2, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
