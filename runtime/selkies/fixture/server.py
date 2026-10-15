"""Loopback-only synthetic page and bounded geometry/state evidence for tests."""
import http.server
import json
from pathlib import Path
import threading

pages = {}
pages_lock = threading.Lock()


class Fixture(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).parent), **kwargs)

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != "/state":
            return super().do_GET()
        with pages_lock:
            payload = json.dumps({"pages": pages}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/telemetry" or not 0 < size <= 8192:
            self.send_error(400)
            return
        value = json.loads(self.rfile.read(size))
        # Passwords and codes are never collected, even in this fixture.
        allowed = {"marker", "sequence", "focused", "name", "notes", "rects", "offset", "sensitive", "dropped"}
        if set(value) != allowed or not isinstance(value["marker"], str):
            self.send_error(400)
            return
        with pages_lock:
            previous = pages.get(value["marker"])
            # Concurrent HTTP reports may arrive out of input-event order.
            # Never replace newer field/feedback state with an older report.
            if previous is None or value["sequence"] >= previous["sequence"]:
                if len(pages) >= 8 and value["marker"] not in pages:
                    pages.pop(next(iter(pages)))
                pages[value["marker"]] = value
        self.send_response(204)
        self.end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", 18081), Fixture).serve_forever()
