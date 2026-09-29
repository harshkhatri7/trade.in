"""Getting bytes off the wire, without deciding what they mean.

The split is deliberate. A transport knows HTTP: how to open a socket,
follow a redirect, read a body. It does **not** know what a candle is,
which provider is being talked to, or what any given status code means
*for that provider* — because those differ per provider, and a transport
that guessed would be putting provider policy in the one place that
cannot be tested against a provider.

So the contract is narrow: return ``(status_code, body)`` and let the
adapter interpret. The single exception is a request that never got an
answer at all — no connection, DNS failure, timeout — which is
:class:`~harsh_quant_os.data.errors.ProviderUnavailable` regardless of
provider, because nothing was received and therefore nothing was wrong
with any data.

Adapters take a transport rather than constructing one. Tests inject a
double and never open a socket; a different HTTP client can be dropped in
without touching an adapter; and the ability to fetch does not depend on
which optional packages happen to be installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from harsh_quant_os.data.errors import ProviderUnavailable

__all__ = ["HttpTransport", "UrllibTransport"]

#: Enough for a research platform fetching a page at a time, short enough
#: that a stalled socket does not hold a worker for minutes.
DEFAULT_TIMEOUT_SECONDS = 30.0


@runtime_checkable
class HttpTransport(Protocol):
    """The seam between an adapter and the network."""

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        """GET ``url`` and return ``(status_code, body)``.

        A refusal is still an answer: ``404`` comes back as ``404`` rather
        than being raised, because whether it means "wrong symbol" or
        "wrong credentials" is the adapter's knowledge.

        Raises:
            ProviderUnavailable: the request never received an answer.
        """
        ...


class UrllibTransport:
    """A transport built on the standard library.

    Chosen over an HTTP client dependency so that installing this package
    is enough to reach a provider. Ingestion already has enough moving
    parts without the ability to make a request depending on an extra
    somebody has to remember to install — and the repository deliberately
    keeps heavy dependencies optional.

    Blocking calls run on a worker thread so a socket never holds the
    event loop hostage.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = "harsh-quant-os-research/0.1",
    ) -> None:
        self._timeout = timeout
        self._user_agent = user_agent

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        merged = {"User-Agent": self._user_agent, **dict(headers or {})}
        return await asyncio.to_thread(self._get_blocking, url, merged)

    def _get_blocking(self, url: str, headers: dict[str, str]) -> tuple[int, str]:
        # Requested explicitly rather than by default so an application can
        # identify itself; providers that ask to be identified get an
        # answer that does not look like a scraper's default.
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self._timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                status = response.getcode() or 0
                return status, response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            # HTTPError is an OSError subclass and must be caught first:
            # it carries an answer, which is exactly what the protocol
            # returns rather than raises.
            body = b""
            if exc.fp is not None:
                body = exc.read()
            return exc.code, body.decode("utf-8", errors="replace")
        except URLError as exc:
            # The reason only: urllib's own message here is the failure
            # itself ("Name or service not known", "timed out"), and this
            # code does not add the URL — an adapter that authenticates
            # through a query parameter must not have its credential
            # written into a log line by its transport.
            raise ProviderUnavailable(f"the provider could not be reached: {exc.reason}") from None
        except OSError as exc:
            # Timeouts and refused connections arrive here rather than as
            # URLError. Same rule about not adding the request URL.
            raise ProviderUnavailable(f"the provider could not be reached: {exc}") from None
