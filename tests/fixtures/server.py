"""Reusable local HTTP fixture server for browser tests."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class FixtureRequestHandler(BaseHTTPRequestHandler):
    """Serve a few canned pages for local-only Playwright tests."""

    def do_GET(self) -> None:  # noqa: N802
        """Serve a fixture route."""
        if self.path == "/cookie-set":
            self._send_html("<html><body>cookie set</body></html>", headers={"Set-Cookie": "gsv_fixture=1; Path=/"})
            return
        if self.path == "/dwell-test":
            body = "".join(f"<p>row {index}</p>" for index in range(100))
            self._send_html(f"<html><body>{body}</body></html>")
            return
        self._send_html(
            """
            <html>
              <body>
                <form>
                  <label>Name <input id="name" name="name"></label>
                  <button id="submit" type="submit">Submit</button>
                </form>
              </body>
            </html>
            """
        )

    def log_message(self, _format: str, *args: object) -> None:
        """Silence test-server request logs."""

    def _send_html(self, body: str, *, headers: dict[str, str] | None = None) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


@dataclass
class FixtureServer:
    """Running local HTTP fixture server."""

    server: ThreadingHTTPServer
    thread: Thread

    @property
    def url(self) -> str:
        """Return the base URL for the server."""
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        """Stop the fixture server."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_fixture_server() -> FixtureServer:
    """Start the fixture server on a random local port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureRequestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return FixtureServer(server=server, thread=thread)
