#!/usr/bin/env bash
# Exercise every exit path of probe.py against a local fake kiosk, so the flow
# logic can be changed without waiting on the real site to have availability.
#
#   0 = nothing early enough, 10 = booked, 1 = flow broke / errored
set -uo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8731}
python3 -m http.server "$PORT" --directory testdata >/dev/null 2>&1 &
server=$!
trap 'kill $server 2>/dev/null' EXIT
sleep 1

URL="http://127.0.0.1:${PORT}/fake_kiosk.html"
common=(QLESS_KIOSK_URL="$URL" QLESS_FIRST_NAME=Test QLESS_LAST_NAME=User
        QLESS_PHONE=0000000000 QLESS_EMAIL=test@example.com QLESS_ROUNDS=1)
[ -n "${CHROMIUM_PATH:-}" ] && common+=(CHROMIUM_PATH="$CHROMIUM_PATH")

fails=0
check() { # name want_exit extra_env...
  local name=$1 want=$2; shift 2
  env "${common[@]}" "$@" QLESS_OUT="$(mktemp -d)" python3 probe.py >/tmp/qless-selftest.log 2>&1
  local got=$?
  if [ "$got" = "$want" ]; then
    echo "ok   $name (exit $got)"
  else
    echo "FAIL $name: got exit $got, want $want"; tail -5 /tmp/qless-selftest.log; fails=$((fails+1))
  fi
}

check "books an eligible slot"      10 QLESS_SERVICE="alien firearm" QLESS_CUTOFF_DATE=2026-10-26
check "skips slots past the cutoff"  0 QLESS_SERVICE="alien firearm" QLESS_CUTOFF_DATE=2026-10-01
check "reports a changed label"      1 QLESS_SERVICE="passport renewal" QLESS_CUTOFF_DATE=2026-10-26
check "reports an unreachable site"  1 QLESS_SERVICE="alien firearm" QLESS_KIOSK_URL=http://127.0.0.1:9/
check "dry run stops before confirm" 10 QLESS_SERVICE="alien firearm" QLESS_CUTOFF_DATE=2026-10-26 QLESS_DRY_RUN=1

echo
[ "$fails" = 0 ] && echo "all checks passed" || { echo "$fails check(s) failed"; exit 1; }
