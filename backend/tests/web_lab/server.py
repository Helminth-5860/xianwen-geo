from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

INDEX = b"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>Public lab page</title>
    <script>throw new Error("must never execute")</script>
  </head>
  <body>
    <h1>Safe public lab content</h1>
    <iframe src="http://metadata.invalid/"></iframe>
  </body>
</html>
"""

DRIP_DELAY_SECONDS = 0.45
REDIRECT_DELAY_SECONDS = 0.75


class LabHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *args):
        return None

    def _safe_send(self, payload: bytes) -> bool:
        try:
            self.connection.sendall(payload)
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _normal(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(INDEX)))
        self.send_header("Connection", "close")
        self.end_headers()
        self._safe_send(INDEX)

    def _slow_headers(self) -> None:
        pieces = (
            b"HTTP/1.1 200 OK\r\n",
            b"X-Lab-One: one\r\n",
            b"X-Lab-Two: two\r\n",
            b"Content-Type: text/plain; charset=utf-8\r\n",
            b"Content-Length: 4\r\n",
            b"Connection: close\r\n",
            b"\r\n",
            b"safe",
        )
        for index, piece in enumerate(pieces):
            if not self._safe_send(piece):
                return
            if index < len(pieces) - 1:
                time.sleep(DRIP_DELAY_SECONDS)

    def _slow_fixed(self) -> None:
        if not self._safe_send(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: 8\r\n"
            b"Connection: close\r\n\r\n"
        ):
            return
        for byte in b"slowbody":
            if not self._safe_send(bytes([byte])):
                return
            time.sleep(DRIP_DELAY_SECONDS)

    def _slow_chunked(self) -> None:
        if not self._safe_send(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: close\r\n\r\n"
        ):
            return
        for byte in b"slowbody":
            frame = b"1\r\n" + bytes([byte]) + b"\r\n"
            if not self._safe_send(frame):
                return
            time.sleep(DRIP_DELAY_SECONDS)
        self._safe_send(b"0\r\n\r\n")

    def _slow_redirect(self, hop: int) -> None:
        time.sleep(REDIRECT_DELAY_SECONDS)
        if hop < 4:
            location = f"/slow-redirect/{hop + 1}".encode("ascii")
            payload = (
                b"HTTP/1.1 302 Found\r\n"
                + b"Location: "
                + location
                + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            self._safe_send(payload)
            return
        self._safe_send(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: 4\r\n"
            b"Connection: close\r\n\r\nsafe"
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/slow-headers":
            self._slow_headers()
            return
        if path == "/slow-fixed":
            self._slow_fixed()
            return
        if path == "/slow-chunked":
            self._slow_chunked()
            return
        if path.startswith("/slow-redirect/"):
            try:
                hop = int(path.rsplit("/", 1)[1])
            except ValueError:
                self.send_error(404)
                return
            self._slow_redirect(hop)
            return
        if path == "/":
            self._normal()
            return
        self.send_error(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 80), LabHandler).serve_forever()
