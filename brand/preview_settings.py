"""Serve only the agent design fixture and its public assets on loopback."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ALLOWED = {
    "/": ROOT / "agent-settings.html",
    "/agent-settings.html": ROOT / "agent-settings.html",
    "/agent-settings.css": ROOT / "agent-settings.css",
    "/agent-settings.js": ROOT / "agent-settings.js",
    "/radhouse-mark.svg": ROOT / "radhouse-mark.svg",
    "/navigation.js": ROOT / "agent-icon-snapshot" / "navigation.js",
    "/navigation.css": ROOT / "agent-icon-snapshot" / "navigation.css",
    **{f"/characters/{name}.png": ROOT / "characters" / f"{name}.png" for name in ("ember", "moss", "aster", "lumi")},
}

class PreviewHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        return str(ALLOWED.get(urlparse(path).path, ROOT / ".not-found"))

    def do_GET(self):
        if urlparse(self.path).path not in ALLOWED:
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if urlparse(self.path).path not in ALLOWED:
            self.send_error(404)
            return
        super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=61491)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"Radhouse agent preview: http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()
