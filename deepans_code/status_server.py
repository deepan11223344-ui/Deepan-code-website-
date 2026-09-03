"""Minimal HTTP server to expose `get_system_info()` at /status.

Run with: python -m deepans_code.status_server
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
import socket
from typing import Tuple

from deepans_code.client import get_system_info


def _allowed_origins() -> list:
    raw = os.environ.get("DEEPANCODE_ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080")
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def _check_bearer(handler: BaseHTTPRequestHandler) -> bool:
    expected = os.environ.get("DEEPANCODE_API_TOKEN", "")
    if not expected:
        return False  # fail-closed: token required
    got = handler.headers.get("Authorization", "")
    if got.startswith("Bearer "):
        got = got[7:]
    return hmac.compare_digest(got, expected)


class StatusHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status_code=200, content_type="application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        origin = self.headers.get("Origin", "")
        if origin and origin.rstrip("/") in _allowed_origins():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            if not _check_bearer(self):
                self._set_headers(401, "application/json")
                self.wfile.write(b'{"error": "Unauthorized: set DEEPANCODE_API_TOKEN"}')
                return
            info = get_system_info()
            body = json.dumps(info, indent=2).encode("utf-8")
            self._set_headers(200, "application/json")
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            html = """
            <html>
            <head><title>DeepanCode Status</title></head>
            <body>
            <h1>DeepanCode Status</h1>
            <p>Open <a href="/status">/status</a> to see JSON output.</p>
            </body>
            </html>
            """
            self._set_headers(200, "text/html; charset=utf-8")
            self.wfile.write(html.encode("utf-8"))
        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"Not found")


def find_free_port(start: int = 8000, end: int = 8100) -> Tuple[str, int]:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return ("127.0.0.1", port)
            except OSError:
                continue
    return ("127.0.0.1", 8000)


def main(host: str = "127.0.0.1", port: int = 8000):
    server_address = (host, port)
    httpd = HTTPServer(server_address, StatusHandler)
    print(f"Serving status at http://{host}:{port}/status")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down server")
        httpd.server_close()


if __name__ == "__main__":
    host, port = find_free_port(8000, 8100)
    main(host, port)
