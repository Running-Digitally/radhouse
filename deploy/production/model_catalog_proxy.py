#!/usr/bin/env python3
"""Expose exactly one upstream OpenAI-compatible model catalog on loopback."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

MAX_BYTES = 1_048_576


def upstream() -> str:
    value = os.environ.get("RADHOUSE_MODEL_CATALOG_URL", "")
    parsed = urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        raise SystemExit("invalid catalog address") from None
    if (
        parsed.scheme != "http" or parsed.path != "/v1/models"
        or parsed.query or parsed.fragment or parsed.username or parsed.password
        or not address.is_private
    ):
        raise SystemExit("invalid catalog URL")
    return value


UPSTREAM = upstream()
OPENER = build_opener(ProxyHandler({}))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        if self.path == "/healthz":
            self.reply(200, b'{"status":"ready"}')
            return
        if self.path != "/v1/models":
            self.reply(404, b'{"code":"not_found"}')
            return
        try:
            with OPENER.open(Request(UPSTREAM, method="GET"), timeout=8) as response:
                if response.status != 200:
                    raise HTTPError(UPSTREAM, response.status, "upstream", {}, None)
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError("oversize")
            parsed = json.loads(body)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
                raise ValueError("invalid")
        except (HTTPError, URLError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self.reply(503, b'{"code":"catalog_unavailable"}')
            return
        self.reply(200, body)

    def reply(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8643), Handler)
    server.serve_forever()
