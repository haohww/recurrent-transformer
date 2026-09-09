"""Read-only reconnaissance of the QLess kiosk SPA.

Loads the kiosk page in a real browser, records every XHR/fetch the app makes
(URL, method, status, and JSON body), and dumps the rendered DOM. Nothing is
submitted and no personal data is sent -- this only maps out which endpoints
the booking flow uses so the probe can talk to them directly.
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
INTERESTING = re.compile(r"/(api|rest|v\d|graphql|queue|kiosk|appointment)", re.I)


def summarize(body: str, limit: int = 4000) -> str:
    body = body.strip()
    try:
        return json.dumps(json.loads(body), indent=2)[:limit]
    except Exception:
        return body[:limit]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    calls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page()

        def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            entry = {
                "method": req.method,
                "url": resp.url,
                "status": resp.status,
                "request_body": (req.post_data or "")[:2000],
                "response_body": "",
            }
            try:
                entry["response_body"] = summarize(resp.text())
            except Exception as exc:  # streamed/binary responses
                entry["response_body"] = f"<unreadable: {exc}>"
            calls.append(entry)

        page.on("response", on_response)

        page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
        page.wait_for_timeout(5_000)

        (OUT / "home.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(OUT / "home.png"), full_page=True)

        # Record the visible entry points so we know what the first click is.
        buttons = page.eval_on_selector_all(
            "button, a, [role=button], .btn, md-card, .mat-card",
            "els => els.map(e => ({tag: e.tagName, text: (e.innerText||'').trim().slice(0,120),"
            " cls: (e.className||'').toString().slice(0,120)})).filter(e => e.text)",
        )
        (OUT / "home-clickables.json").write_text(
            json.dumps(buttons, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        browser.close()

    (OUT / "network.json").write_text(
        json.dumps(calls, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n=== {len(calls)} XHR/fetch calls on page load ===")
    for c in calls:
        mark = "*" if INTERESTING.search(c["url"]) else " "
        print(f"{mark} {c['method']:6} {c['status']} {c['url']}")

    print("\n=== bodies of interesting calls ===")
    for c in calls:
        if not INTERESTING.search(c["url"]):
            continue
        print(f"\n--- {c['method']} {c['url']} -> {c['status']} ---")
        if c["request_body"]:
            print(f"request: {c['request_body']}")
        print(c["response_body"][:2500])

    print("\n=== visible entry points ===")
    print(json.dumps(buttons, indent=2, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
