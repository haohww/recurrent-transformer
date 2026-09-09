"""Offline stand-in for the kiosk, for the probe's self-tests.

Serves the wizard fixture plus the two API endpoints the probe uses. Its
value is that it can return a POPULATED <timeBlocks>, which the live site has
never produced during development -- so the slot-parsing path gets exercised
here rather than for the first time on a real cancellation.

The timeBlock attribute names are an assumption; the live response has only
ever been the empty <timeBlocks/>. qless_api parses several spellings for
that reason.
"""

import http.server
import pathlib
import sys

HERE = pathlib.Path(__file__).parent

# Matches the wizard fixture's offered times: one before the usual cutoff,
# two after, so filtering has something to reject.
BLOCKS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<timeBlocks>
  <timeBlock start="2026-10-14T09:30:00" duration="30" available="true"/>
  <timeBlock start="2026-10-30T13:00:00" duration="30" available="true"/>
  <timeBlock start="2026-11-03T10:00:00" duration="30" available="true"/>
</timeBlocks>
"""

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><timeBlocks/>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HERE), **kw)

    def log_message(self, *a):  # keep self-test output readable
        pass

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/qless/api/v1/wssid"):
            self._send('<?xml version="1.0" encoding="UTF-8"?><wssid>stub-wssid</wssid>')
            return
        super().do_GET()

    def do_POST(self):
        if "possibleBlocks" in self.path:
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            # QLESS_STUB_EMPTY lets a test ask for "no availability".
            import os
            self._send(EMPTY_XML if os.environ.get("QLESS_STUB_EMPTY") else BLOCKS_XML)
            return
        self._send("<error>unexpected POST</error>", status=404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
