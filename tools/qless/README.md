# QLess appointment watcher

Watches a QLess kiosk for an appointment slot earlier than a cutoff date and
books it. Runs on GitHub Actions, so it keeps working with your laptop closed.

Built for the case where slots only open up when somebody else cancels: the
window is minutes, so the probe books immediately rather than notifying and
waiting for a human.

## Pieces

| File | What it does |
| --- | --- |
| `probe.py` | Drives the kiosk in headless Chromium: find service → read slots → book the earliest one before the cutoff |
| `recon.py` | Read-only. Dumps the kiosk's network calls and DOM, for repairing selectors |
| `selftest.sh` | Runs every exit path against `testdata/fake_kiosk.html`, no real site needed |
| `../../.github/workflows/qless-watch.yml` | The every-5-minutes schedule |
| `../../.github/workflows/qless-recon.yml` | Manual recon run |

Exit codes: `0` nothing early enough, `10` booked, `1` the flow broke or
errored. A broken flow deliberately fails the workflow run so GitHub emails
you — otherwise a renamed button would silently retire the watcher.

## Setup

1. **Repository secrets** (Settings → Secrets and variables → Actions →
   Secrets). These hold personal data, so they are secrets, never committed:

   - `QLESS_FIRST_NAME`
   - `QLESS_LAST_NAME`
   - `QLESS_PHONE`
   - `QLESS_EMAIL`

2. **Repository variables** (same page, Variables tab) — optional, these are
   the defaults already in the workflow:

   - `QLESS_KIOSK_URL` — kiosk home URL
   - `QLESS_SERVICE` — regex for the service, default `alien firearm`
   - `QLESS_CUTOFF_DATE` — default `2026-10-26`
   - `QLESS_ROUNDS` / `QLESS_ROUND_SLEEP` — checks per run and the gap
     between them, default 3 × 90s

3. **Confirm the flow matches the real site.** Run the *QLess recon* workflow
   once, then run *QLess appointment watch* manually with `dry_run: true`. The
   `probe-out` artifact has a screenshot and the DOM for every step, so any
   step that stopped matching is visible. Adjust the regexes at the top of
   `probe.py` (`entry`, `SERVICE_RE`, `confirm`) to the site's real labels.

4. Once a dry run reaches the confirmation page, let the schedule run.

## After it books

The run creates a GitHub issue with the slot it took (which emails you), and
then **disables its own schedule** so it cannot book a second appointment.
Check the confirmation email from the kiosk. To resume watching:
`gh workflow enable qless-watch.yml`.

## Things worth knowing

- **Verify the booking yourself.** If the site changes its confirmation
  wording the probe logs `CHECK MANUALLY` and still reports success; the
  screenshots in the artifact show what actually happened.
- **The 5-minute cron is best-effort.** GitHub queues scheduled runs and skips
  them under load, so real gaps vary. That is why each run also re-checks
  internally.
- **GitHub disables schedules after 60 days of repository inactivity**, and
  scheduled runs consume Actions minutes on private repositories.
- **Check the site's terms of use.** This automates a booking you are entitled
  to make, but automated access to public booking systems is often restricted,
  and aggressive polling can get an IP blocked. 5 minutes is already brisk.

## Local development

```sh
pip install playwright && python -m playwright install chromium
bash tools/qless/selftest.sh
```
