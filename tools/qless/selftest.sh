#!/usr/bin/env bash
# Exercise every exit path of probe.py against a local stub of the kiosk, so
# the flow can be changed without waiting on a real cancellation.
#
# The stub matters for more than convenience: the live calendar has been
# empty throughout development, so a populated <timeBlocks> only ever exists
# here. This is where slot parsing and date filtering actually get tested.
#
#   0 = nothing early enough, 10 = booked, 1 = flow broke / errored
set -uo pipefail
cd "$(dirname "$0")"

PORT=${PORT:-8799}
EMPTY_PORT=$((PORT + 1))
python3 testdata/stub_server.py "$PORT" &
server=$!
# A second stub that reports no availability. It needs its own process
# because the running server cannot see a variable exported for the probe.
QLESS_STUB_EMPTY=1 python3 testdata/stub_server.py "$EMPTY_PORT" &
empty_server=$!
trap 'kill $server $empty_server 2>/dev/null' EXIT
sleep 1

BASE="http://127.0.0.1:${PORT}"
EMPTY_BASE="http://127.0.0.1:${EMPTY_PORT}"
common=(QLESS_API_BASE="$BASE" QLESS_KIOSK_URL="$BASE/fake_kiosk.html"
        QLESS_FIRST_NAME=Test QLESS_LAST_NAME=User QLESS_EMAIL=test@example.com
        QLESS_PHONE=0000000000 QLESS_ROUNDS=1)
[ -n "${CHROMIUM_PATH:-}" ] && common+=(CHROMIUM_PATH="$CHROMIUM_PATH")

fails=0
check() { # name want_exit extra_env...
  local name=$1 want=$2; shift 2
  env "${common[@]}" "$@" QLESS_OUT="$(mktemp -d)" python3 probe.py >/tmp/qless-selftest.log 2>&1
  local got=$?
  if [ "$got" = "$want" ]; then
    echo "ok   $name (exit $got)"
  else
    echo "FAIL $name: got exit $got, want $want"; tail -8 /tmp/qless-selftest.log; fails=$((fails+1))
  fi
}

# Stub offers 2026-10-14, 10-30 and 11-03.
check "books a slot before the cutoff"     10 QLESS_CUTOFF_DATE=2026-10-26
check "skips slots past the cutoff"         0 QLESS_CUTOFF_DATE=2026-10-01
check "empty calendar is not an error"      0 QLESS_CUTOFF_DATE=2026-10-26 QLESS_API_BASE="$EMPTY_BASE"
check "unreachable API fails loudly"        1 QLESS_CUTOFF_DATE=2026-10-26 QLESS_API_BASE=http://127.0.0.1:9
check "missing identity refuses to run"     1 QLESS_CUTOFF_DATE=2026-10-26 QLESS_EMAIL=
check "dry run stops before confirming"    10 QLESS_CUTOFF_DATE=2026-10-26 QLESS_DRY_RUN=1

echo
[ "$fails" = 0 ] && echo "all checks passed" || { echo "$fails check(s) failed"; exit 1; }
