"""Watch a QLess kiosk for an earlier appointment slot and grab it.

Two halves, deliberately different:

  * DETECTION goes through the XML API (qless_api). It is one cheap POST,
    needs no browser, and its contract is verified against the live site.
  * BOOKING drives the real wizard in a browser. The booking endpoint's
    payload could not be recovered -- the code that builds it is in a module
    the app only loads once a slot is selectable, and the calendar has been
    empty -- so the booking follows the same path a person would, which is
    the option most likely to work without having been rehearsed.

Because detection is cheap, the browser only starts when a slot actually
exists. Every booking step screenshots the page (with personal details
masked) so a first real attempt is diagnosable even if it fails.

Configuration is entirely by environment variable so that no personal data
ever lands in the repository -- see .github/workflows/qless-watch.yml, which
feeds these from repository secrets.

  QLESS_KIOSK_URL    kiosk home URL
  QLESS_SERVICE      regex for the service to book, e.g. "alien firearm"
  QLESS_CUTOFF_DATE  book only slots strictly earlier than this (YYYY-MM-DD)
  QLESS_FIRST_NAME / QLESS_LAST_NAME / QLESS_PHONE / QLESS_EMAIL
  QLESS_DRY_RUN      "1" to walk the flow but stop before confirming
  QLESS_ROUNDS       checks per invocation (default 3)
  QLESS_ROUND_SLEEP  seconds between checks (default 90)

Exit codes: 0 = nothing early enough, 10 = booked (or dry-run match),
1 = the flow broke or errored. A broken flow must not look like "nothing
available", or a changed label would silently retire the watcher.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qless_api import QLessError, get_wssid, possible_blocks  # noqa: E402

BOOKED_EXIT = 10
BROKEN_EXIT = 1

BOOKED, NONE, BROKEN = "booked", "none", "broken"

OUT = pathlib.Path(os.environ.get("QLESS_OUT", "probe-out"))
KIOSK_URL = os.environ.get(
    "QLESS_KIOSK_URL", "https://kiosk.na1.qless.com/kiosk/app/home/100100000129"
)
SERVICE_RE = re.compile(os.environ.get("QLESS_SERVICE", "alien firearm"), re.I)
DRY_RUN = os.environ.get("QLESS_DRY_RUN", "") in ("1", "true", "yes")

FIRST_NAME = os.environ.get("QLESS_FIRST_NAME", "")
LAST_NAME = os.environ.get("QLESS_LAST_NAME", "")
PHONE = os.environ.get("QLESS_PHONE", "")
EMAIL = os.environ.get("QLESS_EMAIL", "")

# Anything that looks like a date, in the formats kiosk UIs tend to use.
DATE_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")),
    ("%m/%d/%Y", re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")),
    ("%m/%d/%y", re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2})\b")),
    ("%B %d, %Y", re.compile(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b")),
    ("%B %d %Y", re.compile(r"\b([A-Z][a-z]+ \d{1,2} \d{4})\b")),
    ("%b %d, %Y", re.compile(r"\b([A-Z][a-z]{2} \d{1,2}, \d{4})\b")),
]

CLICKABLE = "button, a, [role=button], [role=option], .btn, li, md-card, .mat-card, .card"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def cutoff_date() -> dt.date:
    raw = os.environ.get("QLESS_CUTOFF_DATE", "2026-10-26")
    return dt.date.fromisoformat(raw)


# Values that must never appear in a captured artifact. On a public
# repository anyone can download these, so the personal details get masked
# out of both the screenshot and the DOM dump.
def _secrets() -> list[str]:
    return [v for v in (FIRST_NAME, LAST_NAME, PHONE, EMAIL) if v and len(v) > 2]


MASK_STYLE = """
  input, textarea { -webkit-text-security: disc !important; text-security: disc !important;
                    color: transparent !important; text-shadow: 0 0 8px rgba(0,0,0,.7) !important; }
"""


def scrub(text: str) -> str:
    for value in _secrets():
        text = text.replace(value, "[REDACTED]")
    return text


def shoot(page: Page, name: str) -> None:
    """Capture a step, with typed-in personal details masked.

    The mask is pure CSS so the live form is never mutated -- rewriting the
    DOM to hide values could break the booking we are trying to make.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    handle = None
    try:
        handle = page.add_style_tag(content=MASK_STYLE)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        (OUT / f"{name}.html").write_text(scrub(page.content()), encoding="utf-8")
    except Exception as exc:
        log(f"could not capture {name}: {exc}")
    finally:
        if handle is not None:
            try:
                handle.evaluate("el => el.remove()")
            except Exception:
                pass


def clickables(page: Page) -> list[dict]:
    """Every visible, clickable element with its text -- the basis for matching."""
    return page.eval_on_selector_all(
        CLICKABLE,
        """els => els
             .filter(e => e.offsetParent !== null)
             .map((e, i) => ({
                 i,
                 text: (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
                 disabled: e.disabled === true || e.getAttribute('aria-disabled') === 'true'
                           || /disabled|unavailable|sold-?out/i.test(e.className || ''),
             }))
             .filter(e => e.text)""",
    )


def click_matching(page: Page, pattern: re.Pattern, what: str) -> bool:
    """Click the first enabled clickable whose text matches, by text not index.

    Matching by text and re-resolving through get_by_text keeps this working
    when the SPA re-renders between the scan and the click.
    """
    for el in clickables(page):
        if el["disabled"] or not pattern.search(el["text"]):
            continue
        log(f"clicking {what}: {el['text'][:80]!r}")
        try:
            page.get_by_text(el["text"][:60], exact=False).first.click(timeout=10_000)
        except Exception:
            page.query_selector_all(CLICKABLE)[el["i"]].click(timeout=10_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(1_500)
        return True
    log(f"no clickable matched {what} ({pattern.pattern!r})")
    return False


def advance(page: Page) -> bool:
    """Press the wizard's Next button if it is enabled."""
    for selector in ("#qBtnNext", "button.btn-next"):
        el = page.query_selector(selector)
        if not el:
            continue
        classes = el.get_attribute("class") or ""
        if "btn-disabled" in classes or el.get_attribute("disabled"):
            log(f"{selector} is disabled")
            continue
        el.click(timeout=10_000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(1_500)
        return True
    return click_matching(page, re.compile(r"next|continue", re.I), "next")


def parse_dates(text: str) -> list[dt.date]:
    """Pull every date out of a blob of UI text, newest format wins."""
    found: list[dt.date] = []
    for fmt, rx in DATE_PATTERNS:
        for raw in rx.findall(text):
            try:
                found.append(dt.datetime.strptime(raw, fmt).date())
            except ValueError:
                continue
    return found


def find_offered_slots(page: Page) -> list[tuple[dt.date, str]]:
    """Every offered slot as (date, label), skipping disabled ones."""
    slots: list[tuple[dt.date, str]] = []
    for el in clickables(page):
        if el["disabled"]:
            continue
        for date in parse_dates(el["text"]):
            slots.append((date, el["text"]))
    # De-duplicate on (date, label) but keep order for deterministic logs.
    seen = set()
    unique = []
    for date, label in slots:
        if (date, label) in seen:
            continue
        seen.add((date, label))
        unique.append((date, label))
    return sorted(unique, key=lambda s: s[0])


def fill_details(page: Page) -> None:
    """Fill whatever of the name/phone/email form this step is showing."""
    fields = [
        (r"first", FIRST_NAME),
        (r"last|surname", LAST_NAME),
        (r"phone|mobile|cell", PHONE),
        (r"e-?mail", EMAIL),
    ]
    inputs = page.query_selector_all("input, textarea")
    for handle in inputs:
        meta = " ".join(
            filter(
                None,
                [
                    handle.get_attribute("name") or "",
                    handle.get_attribute("id") or "",
                    handle.get_attribute("placeholder") or "",
                    handle.get_attribute("aria-label") or "",
                    handle.get_attribute("type") or "",
                ],
            )
        )
        for pattern, value in fields:
            if value and re.search(pattern, meta, re.I):
                handle.fill(value)
                log(f"filled field {meta[:60]!r}")
                break


def api_eligible(cutoff: dt.date) -> tuple[str, list]:
    """Ask the API for slots earlier than `cutoff`.

    Returns (status, eligible_blocks). An empty calendar is NONE, not
    BROKEN: this queue is usually empty and only frees up on cancellations.
    A transport or contract failure is BROKEN so the run fails loudly rather
    than looking like "nothing available" forever.
    """
    max_days = int(os.environ.get("QLESS_MAX_DAYS", "60"))
    try:
        wssid = get_wssid()
    except Exception as exc:
        log(f"could not fetch wssid: {exc}")
        wssid = ""

    try:
        blocks, raw = possible_blocks(max_days=max_days, wssid=wssid)
    except QLessError as exc:
        log(f"availability query failed: {exc}")
        return BROKEN, []
    except Exception as exc:
        log(f"availability query error: {type(exc).__name__}: {exc}")
        return BROKEN, []

    (OUT / "availability.xml").write_text(raw, encoding="utf-8")
    log(f"API offered {len(blocks)} slot(s) within {max_days} days")
    for block in blocks[:20]:
        log(f"  {block}")

    eligible = [b for b in blocks if b.date < cutoff]
    if not blocks:
        log("calendar is empty -- nothing to take")
        return NONE, []
    if not eligible:
        log(f"earliest offered is {blocks[0].date}, cutoff is {cutoff}")
        return NONE, []
    log(f"{len(eligible)} slot(s) earlier than {cutoff}: {[str(b) for b in eligible[:5]]}")
    return BOOKED, eligible


def attempt(page: Page, cutoff: dt.date) -> str:
    """Book via the wizard. Only called once the API says a slot exists."""
    log(f"opening {KIOSK_URL}")
    page.goto(KIOSK_URL, wait_until="networkidle", timeout=90_000)
    page.wait_for_timeout(3_000)
    shoot(page, "01-home")

    # The kiosk opens on a name/phone step whose only controls are
    # #qBtnBack and #qBtnNext, so fill the identity fields and advance
    # rather than looking for an "appointment" button that is not there.
    fill_details(page)
    if not advance(page):
        log("FLOW BROKE at the first step -- see 01-home.html")
        return BROKEN
    shoot(page, "02-services")

    entry = re.compile(r"appoint|schedul|book|reserv", re.I)
    click_matching(page, entry, "appointment entry point")

    if not click_matching(page, SERVICE_RE, "service"):
        log("FLOW BROKE at service selection -- see 02-services.html")
        return BROKEN
    shoot(page, "03-slots")

    # Some flows ask for identity before showing slots.
    fill_details(page)
    if not find_offered_slots(page):
        click_matching(page, re.compile(r"next|continue|submit", re.I), "continue")
        shoot(page, "03b-slots")

    slots = find_offered_slots(page)
    if not slots:
        # No parseable dates can mean a genuinely empty calendar or a changed
        # layout; treat it as breakage so it gets looked at either way.
        log("no dated slots found on this page -- see 03-slots.html")
        return BROKEN

    log(f"offered: {[(str(d), scrub(l)[:40]) for d, l in slots[:20]]}")
    eligible = [(d, l) for d, l in slots if d < cutoff]
    if not eligible:
        log(f"earliest offered is {slots[0][0]}, cutoff is {cutoff} -- nothing to take")
        return NONE

    date, label = eligible[0]
    log(f"ELIGIBLE SLOT {date} ({label[:80]!r}) -- taking it")
    if not click_matching(page, re.compile(re.escape(label[:50]), re.I), "slot"):
        log("FLOW BROKE clicking the slot -- see 03-slots.html")
        return BROKEN
    shoot(page, "04-details")

    fill_details(page)
    shoot(page, "05-filled")

    if DRY_RUN:
        log(f"DRY RUN: stopping before confirming {date}")
        return BOOKED

    # The tail of the flow is a few "continue" steps before the real
    # confirm, so advance on either and only trust the success text.
    confirm = re.compile(r"confirm|book|finish|submit|done|next|continue", re.I)
    for step in range(5):
        if not click_matching(page, confirm, f"confirm (step {step + 1})"):
            break
        shoot(page, f"06-confirm-{step + 1}")
        if re.search(r"confirm(ed|ation)|you'?re all set|success|see you",
                     page.inner_text("body"), re.I):
            log(f"BOOKED {date}")
            (OUT / "booked.json").write_text(
                json.dumps({"date": str(date), "label": label,
                            "at": dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2),
                encoding="utf-8",
            )
            return BOOKED

    # Something was submitted but no success text appeared. Report it as
    # booked-and-uncertain rather than silently: it needs a human check.
    log("clicked through confirmation but saw no success text -- CHECK MANUALLY")
    shoot(page, "07-uncertain")
    return BOOKED


def main() -> int:
    # The kiosk's appointmentConsumerFields are FIRST_NAME, LAST_NAME and
    # EMAIL. Phone belongs to the queue-join flow, so it stays optional.
    missing = [n for n, v in [("QLESS_FIRST_NAME", FIRST_NAME),
                              ("QLESS_LAST_NAME", LAST_NAME),
                              ("QLESS_EMAIL", EMAIL)] if not v]
    if missing and not DRY_RUN:
        log(f"refusing to run without {', '.join(missing)}")
        return 1

    cutoff = cutoff_date()
    rounds = int(os.environ.get("QLESS_ROUNDS", "3"))
    sleep_s = int(os.environ.get("QLESS_ROUND_SLEEP", "90"))
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"cutoff={cutoff} service={SERVICE_RE.pattern!r} dry_run={DRY_RUN} rounds={rounds}")
    broken = False

    for round_no in range(1, rounds + 1):
        log(f"--- round {round_no}/{rounds} ---")
        status, eligible = api_eligible(cutoff)

        if status == BROKEN:
            broken = True
        elif status == BOOKED:
            # A slot exists. Now, and only now, open a browser to take it.
            log("slot available -- opening a browser to book")
            with sync_playwright() as p:
                # CHROMIUM_PATH lets this run against a preinstalled browser
                # when the Playwright package and browser bundle are
                # versioned separately.
                browser = p.chromium.launch(
                    executable_path=os.environ.get("CHROMIUM_PATH") or None
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 2000},
                    timezone_id="America/Los_Angeles",
                )
                page = context.new_page()
                try:
                    if attempt(page, cutoff) == BOOKED:
                        return BOOKED_EXIT
                    broken = True
                except PWTimeout as exc:
                    log(f"timeout: {exc}")
                    shoot(page, f"error-round{round_no}")
                    broken = True
                except Exception as exc:
                    log(f"error: {exc}")
                    shoot(page, f"error-round{round_no}")
                    broken = True
                finally:
                    context.close()
                    browser.close()

            # A slot was there and we did not confirm it. Fail loudly: the
            # artifact shows how far the wizard got, and a missed
            # cancellation is exactly what this exists to prevent.
            if broken:
                log("a slot was available but the wizard did not confirm it")

        if round_no < rounds:
            time.sleep(sleep_s)

    return BROKEN_EXIT if broken else 0


if __name__ == "__main__":
    sys.exit(main())
