"""The transport, verified against a local server rather than assumed.

Two things need proving about it, and neither can be proven by mocking:
that an answer the server *did* give comes back as a value instead of
being raised, and that a request which never got an answer at all becomes
:class:`ProviderUnavailable` rather than escaping as a raw socket error.

So a tiny HTTP server runs on the loopback interface for these tests. It
binds to port zero, so nothing is claimed about a fixed port being free,
and it never leaves the machine. Nothing here contacts an external host —
a suite that reaches the internet to test its own plumbing is a suite
that goes red for reasons nobody reading the failure can fix.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harsh_quant_os.data import ProviderUnavailable, UrllibTransport

#: Bodies the local server knows how to serve. The 404 body is not JSON
#: on purpose: an error page must arrive as text rather than be mistaken
#: for something the caller should parse.
_PATHS: dict[str, tuple[int, bytes]] = {
    "/ok": (200, b'{"ok":true}'),
    "/missing": (404, b"<html>not here</html>"),
    "/broken": (503, b"unavailable"),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/whoami":
            # Echo what was sent, so the client's identity is asserted
            # from evidence rather than read back out of a constructor.
            body = (self.headers.get("User-Agent") or "").encode("utf-8")
            status = 200
        else:
            status, body = _PATHS.get(self.path, (500, b"unhandled path"))
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence the stdlib's per-request logging."""


@contextmanager
def _server() -> Iterator[str]:
    """A local HTTP server for the duration of the block."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        # The address this server bound to, not the string an attribute
        # happens to be typed as: it is 127.0.0.1 by construction above.
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_a_200_comes_back_as_a_value_not_an_exception() -> None:
    with _server() as base:
        transport = UrllibTransport(timeout=5.0)
        status, body = asyncio.run(transport.get(f"{base}/ok"))

    assert status == 200
    assert body == '{"ok":true}'


@pytest.mark.parametrize("path", ["/missing", "/broken"])
def test_a_refusal_is_still_an_answer_and_comes_back_as_one(path: str) -> None:
    """A 404 is not an exception: which meaning it has is the adapter's.

    If the transport raised here, no adapter could ever tell a wrong
    symbol from wrong credentials — two cases that need different typed
    failures and are told apart by a provider, not by a socket.
    """
    with _server() as base:
        transport = UrllibTransport(timeout=5.0)
        status, body = asyncio.run(transport.get(f"{base}{path}"))

    assert status in (404, 503)
    assert body, "the server's own body was dropped"


def test_a_request_that_never_got_an_answer_is_provider_unavailable() -> None:
    """No connection at all: nothing was received, so nothing is wrong
    with any data — exactly what ``ProviderUnavailable`` claims to mean.

    Port 1 on the loopback interface is refused rather than resolved, so
    this test's failure path stays on this machine.
    """
    transport = UrllibTransport(timeout=5.0)

    with pytest.raises(ProviderUnavailable):
        asyncio.run(transport.get("http://127.0.0.1:1/ohlc"))


def test_the_client_identifies_itself_to_the_provider() -> None:
    """Providers that ask who is calling get something other than a
    scraper's default, which is a reason for a feed to keep answering."""
    with _server() as base:
        transport = UrllibTransport(timeout=5.0)
        _, identity = asyncio.run(transport.get(f"{base}/whoami"))

    assert "harsh-quant-os" in identity, f"unexpected client identity: {identity!r}"
    assert identity != "Python-urllib", "the stdlib's own default was sent"
