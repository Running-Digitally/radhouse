"""Loopback-only static preview with the deployment's actual response headers."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import urlsplit

PUBLIC = Path(__file__).resolve().parent / "public"
HEADERS = [line.strip().split(": ", 1) for line in (PUBLIC / "_headers").read_text().splitlines() if line.startswith("  ")]


class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def end_headers(self):
        for key, value in HEADERS:
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        # Preview-only fixtures exercise the real sources without changing OS
        # preferences. None of these routes or assets belongs to public/.
        path = urlsplit(self.path).path
        body, mime = None, "text/html; charset=utf-8"
        if path == "/__qa/reduced-motion":
            html = (PUBLIC / "index.html").read_text()
            html = html.replace('href="/styles.css"', 'href="/__qa/reduced.css"')
            html = html.replace('href="/gallery.css"', 'href="/__qa/reduced-gallery.css"')
            html = html.replace('href="/platform-icons.css"', 'href="/__qa/reduced-icons.css"')
            html = html.replace('<script src="/journey.js"', '<script src="/__qa/preferences.js"></script><script src="/journey.js"')
            body = html.encode()
        elif path in {"/__qa/reduced.css", "/__qa/reduced-gallery.css", "/__qa/reduced-icons.css"}:
            source = {"/__qa/reduced.css": "styles.css", "/__qa/reduced-gallery.css": "gallery.css", "/__qa/reduced-icons.css": "platform-icons.css"}[path]
            body = re.sub(r"@media\s*\(prefers-reduced-motion:\s*reduce\)", "@media all", (PUBLIC / source).read_text()).encode()
            mime = "text/css"
        elif path == "/__qa/preferences.js":
            body = b"const nativeMedia=window.matchMedia.bind(window);window.matchMedia=q=>q==='(prefers-reduced-motion: reduce)'?{matches:true,media:q,addEventListener(){},removeEventListener(){}}:nativeMedia(q);"
            mime = "text/javascript"
        elif path == "/__qa/no-js":
            html = re.sub(r"<script\b[^>]*>.*?</script>", "", (PUBLIC / "index.html").read_text(), flags=re.S)
            body = html.replace("<noscript>", "<div>").replace("</noscript>", "</div>").encode()
        if body is None:
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        if code != 404:
            return super().send_error(code, message, explain)
        body = (PUBLIC / "404.html").read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, *_):
        # Suppress access logs for the synthetic local preview.
        pass


if __name__ == "__main__":
    print("Radhouse preview: http://127.0.0.1:8931/?analytics=preview", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8931), Preview).serve_forever()
