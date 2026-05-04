"""Reusable local HTTP fixture server for browser tests."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit


class FixtureRequestHandler(BaseHTTPRequestHandler):
    """Serve a few canned pages for local-only Playwright tests."""

    def do_GET(self) -> None:  # noqa: N802
        """Serve a fixture route."""
        route = urlsplit(self.path)
        if route.path == "/cookie-set":
            self._send_html("<html><body>cookie set</body></html>", headers={"Set-Cookie": "gsv_fixture=1; Path=/"})
            return
        if route.path == "/dwell-test":
            body = "".join(f"<p>row {index}</p>" for index in range(100))
            self._send_html(f"<html><body>{body}</body></html>")
            return
        if route.path == "/cookie-consent":
            self._send_html("<html><body><button id='accept-cookies'>Accept</button></body></html>")
            return
        if route.path == "/home":
            if not self._has_auth_cookie():
                self._send_redirect("/login")
                return
            self._send_html("<html><head><title>Home</title></head><body><main id='home'>home</main></body></html>")
            return
        if route.path == "/public-home":
            self._send_html("<html><head><title>Public Home</title></head><body><main id='home'>home</main></body></html>")
            return
        if route.path == "/challenge":
            self._send_html(
                "<html><head><title>Challenge</title></head><body><main id='challenge'>verify</main></body></html>"
            )
            return
        if route.path == "/login":
            action = "/login?challenge=1" if parse_qs(route.query).get("challenge") else "/login"
            self._send_login_form(action=action)
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

    def do_POST(self) -> None:  # noqa: N802
        """Handle fixture login form submissions."""
        route = urlsplit(self.path)
        if route.path != "/login":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if parse_qs(route.query).get("challenge"):
            self._send_redirect("/challenge")
            return
        if username == "user@example.test" and password == "correct-password":
            self._send_redirect("/home", headers={"Set-Cookie": "gsv_auth=1; Path=/; SameSite=Lax"})
            return
        self._send_login_form(error=True)

    def log_message(self, _format: str, *args: object) -> None:
        """Silence test-server request logs."""

    def _send_html(self, body: str, *, headers: dict[str, str] | None = None, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_login_form(self, *, action: str = "/login", error: bool = False) -> None:
        error_html = "<p id='login-error'>invalid</p>" if error else ""
        self._send_html(
            f"""
            <html>
              <head><title>Login</title></head>
              <body>
                <button id="accept-cookies" type="button">Accept cookies</button>
                <button id="use-another-account" type="button">Use another account</button>
                {error_html}
                <form method="post" action="{action}">
                  <label>Username <input id="username" name="username"></label>
                  <label>Email <input name="email"></label>
                  <label>Password <input id="password" name="password" type="password"></label>
                  <button id="submit" type="submit">Sign in</button>
                </form>
              </body>
            </html>
            """
        )

    def _send_redirect(self, location: str, *, headers: dict[str, str] | None = None) -> None:
        payload = b""
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _has_auth_cookie(self) -> bool:
        cookie = self.headers.get("Cookie", "")
        return "gsv_auth=1" in cookie


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
