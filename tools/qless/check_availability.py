"""Print what the appointment API currently offers.

Run this whenever the flow needs verifying against the live site: it shows
the raw XML plus the parsed slots, at a couple of window sizes, so both the
request contract and the response parsing can be checked at a glance.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qless_api import DEFAULT_TZ, QLessError, get_wssid, possible_blocks  # noqa: E402


def main() -> int:
    try:
        wssid = get_wssid()
        print(f"wssid: {'obtained' if wssid else 'empty (the kiosk sends it blank too)'}")
    except Exception as exc:
        print(f"could not fetch wssid: {exc}")
        wssid = ""

    max_days_list = [int(x) for x in os.environ.get("QLESS_MAX_DAYS", "7,30,60").split(",")]
    time_zone = os.environ.get("QLESS_TZ", DEFAULT_TZ)
    failures = 0

    for max_days in max_days_list:
        print(f"\n{'=' * 64}\n=== maxDays={max_days} timeZone={time_zone}\n{'=' * 64}")
        try:
            blocks, raw = possible_blocks(
                max_days=max_days, time_zone=time_zone, wssid=wssid
            )
        except QLessError as exc:
            print(f"FAILED: {exc}")
            failures += 1
            continue
        except Exception as exc:
            print(f"FAILED: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        print(f"raw ({len(raw)} bytes): {raw[:700]}")
        print(f"\nparsed {len(blocks)} slot(s)")
        for block in blocks[:25]:
            print(f"  {block}  {block.raw}")
        if blocks:
            print(f"\nearliest: {blocks[0]}   latest: {blocks[-1]}")

    # A window that errors is a broken contract; an empty one is just no
    # availability. Only the former should fail the run.
    return 1 if failures == len(max_days_list) else 0


if __name__ == "__main__":
    sys.exit(main())
