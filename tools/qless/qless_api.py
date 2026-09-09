"""Client for the QLess kiosk appointment API.

The contract here was recovered by capturing what the kiosk's own wizard
sends (tools/qless/recon10.py). Two details are easy to get wrong and cost
several rounds of 400s and server-side DATETIME errors:

  * possibleBlocks is a POST, not a GET.
  * It takes `start` and `end` EMPTY. The window is driven by `maxDays`
    alone. Sending a timestamp in `start` gets it reinterpreted into an
    absurd year and the query fails inside the database.

All nine form fields must be present even when blank, or the request is
rejected with a bare 400.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://kiosk.na1.qless.com"
API = f"{BASE}/qless/api/v1"

# King County Courthouse records unit; "CPL/AFL Appointments".
DEFAULT_LOCATION = "100100000129"
DEFAULT_QUEUE = "100100000746"
DEFAULT_TXN_TYPE = "100100004335"  # Alien Firearm License
DEFAULT_TZ = "US/Pacific"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


class QLessError(RuntimeError):
    """The API answered, but not with something usable."""


@dataclasses.dataclass(frozen=True)
class Block:
    """One offered appointment slot."""

    start: dt.datetime
    raw: dict[str, str]

    @property
    def date(self) -> dt.date:
        return self.start.date()

    def __str__(self) -> str:
        return self.start.strftime("%Y-%m-%d %H:%M")


def _request(url: str, data: bytes | None = None, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml, text/xml, */*",
            "X-Requested-With": "XMLHttpRequest",
            **({"Content-Type": "application/x-www-form-urlencoded"} if data else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def get_wssid(timeout: int = 30) -> str:
    """Fetch the web-service session id the form fields expect."""
    text = _request(f"{API}/wssid", timeout=timeout)
    try:
        return (ET.fromstring(text).text or "").strip()
    except ET.ParseError:
        return text.strip()


def _parse_start(attrs: dict[str, str]) -> dt.datetime | None:
    """Pull a datetime out of a timeBlock's attributes.

    The attribute name is not pinned down by the capture, so this accepts
    the plausible spellings and both epoch and ISO encodings rather than
    failing on a rename.
    """
    for key in ("start", "startTime", "time", "begin", "startDate"):
        value = attrs.get(key)
        if not value:
            continue
        if value.isdigit():
            number = int(value)
            # Epoch seconds vs milliseconds, decided by magnitude.
            if number > 10_000_000_000:
                number //= 1000
            return dt.datetime.fromtimestamp(number, dt.timezone.utc)
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def possible_blocks(
    *,
    queue_id: str = DEFAULT_QUEUE,
    txn_type_id: str = DEFAULT_TXN_TYPE,
    max_days: int = 7,
    time_zone: str = DEFAULT_TZ,
    wssid: str | None = None,
    timeout: int = 30,
) -> tuple[list[Block], str]:
    """Offered slots within `max_days`, plus the raw XML for diagnostics.

    Every field is sent, blank where the kiosk sends it blank -- `start`,
    `end` and `partySize` included. Omitting any of them yields a bare 400.
    """
    form = {
        "end": "",
        "locale": "en",
        "maxDays": str(max_days),
        "partySize": "",
        "remote": "true",
        "start": "",
        "timeZone": time_zone,
        "transactionTypeIds": txn_type_id,
        "wssid": wssid if wssid is not None else "",
    }
    url = f"{API}/appointment/queue/{queue_id}/possibleBlocks"
    text = _request(url, data=urllib.parse.urlencode(form).encode(), timeout=timeout)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise QLessError(f"unparseable response: {exc}: {text[:300]}") from exc

    if root.tag == "error":
        raise QLessError(f"server error: {(root.text or '').strip()[:300]}")

    blocks: list[Block] = []
    for node in root.iter():
        if node is root:
            continue
        start = _parse_start(node.attrib)
        if start is not None:
            blocks.append(Block(start=start, raw=dict(node.attrib)))

    return sorted(blocks, key=lambda b: b.start), text
