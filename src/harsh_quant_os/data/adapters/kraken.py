"""Kraken's public OHLC feed, behind our own interface.

**Why this provider was chosen.** It needs no key, no account and no
credential of any kind. That matters beyond convenience: the class of bug
that writes a secret into a log line is *structurally impossible* in this
adapter rather than merely avoided, because there is nothing in it to
write. Its prices also arrive as decimal strings rather than JSON
numbers, so nothing is rounded on the way in before anyone has decided
that rounding is acceptable.

**Everything stated about the endpoint below was checked against the live
service while this file was written, not recalled:**

- an unknown pair answers **HTTP 200** with
  ``{"error":["EQuery:Unknown asset pair"]}``;
- an invalid interval answers **HTTP 200** with
  ``{"error":["EGeneral:Invalid arguments"]}`` — so a 200 here is not
  success, and the ``error`` array has to be read first;
- candles are ``[time, open, high, low, close, vwap, volume, count]``,
  per Kraken's historical-data guide. A cross-check against a second
  venue for the same minute aligned on time and differed on price, which
  is what two different order books should do; the field order itself
  comes from Kraken's documentation, and the observed range relationship
  (``high >= open >= low``) is consistent with it;
- ``AssetPairs`` returns an ``altname`` for each pair.

**Two properties of this feed shape the code:**

1. **The final candle of a series is the current, not-yet-committed
   timeframe.** Storing it would store a bar that has not finished — an
   invented bar. Completion is decided by arithmetic (``now >= open +
   interval``) rather than by "it happened to be last", so a window that
   ends in the past keeps every candle it should.

2. **Symbol spelling is this provider's.** ``XBTUSD`` is Kraken's
   ``altname``. Cross-provider asset-code unification — XBT against BTC,
   and every other pair — is *not* implemented, and inventing a mapping
   table would be guessing. Provenance records ``source`` for exactly
   this reason: a symbol is always attributable to the namespace it came
   from.

What this adapter can and cannot raise is not left to the reader:
:attr:`RAISED_ERRORS` lists the typed failures it produces, and
:attr:`NOT_RAISED_ERRORS` lists the ones it never does, with why.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from pydantic import ValidationError

from harsh_quant_os.contracts.provenance import Timeframe
from harsh_quant_os.data.errors import (
    AuthenticationFailed,
    InvalidProviderPayload,
    MarketDataError,
    PartialData,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
)
from harsh_quant_os.data.providers import Bar, BarRequest
from harsh_quant_os.data.transport import HttpTransport

__all__ = [
    "NOT_RAISED_ERRORS",
    "RAISED_ERRORS",
    "KrakenProvider",
]

_BASE_URL = "https://api.kraken.com/0/public"

#: Kraken returns at most this many candles per request.
_PAGE_SIZE = 720

#: A safety net, not a policy: it stops a bad range from looping forever.
#: At 720 candles a page it would take fifty pages — tens of thousands of
#: bars — before tripping, and tripping raises rather than returning a
#: short answer that looked complete.
_MAX_PAGES = 50

#: Provider label to Kraken's ``interval`` value, in minutes.
#:
#: ``tick`` and ``1mo`` are deliberately absent. The feed offers no tick
#: stream and no monthly interval, and substituting the nearest thing that
#: does exist would be answering a question nobody asked. Asking for one
#: raises ``UnsupportedRange`` naming what *is* supported.
_INTERVAL_MINUTES: dict[Timeframe, int] = {
    Timeframe.M1: 1,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.M30: 30,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
    Timeframe.W1: 10080,
}

#: The typed failures this adapter produces. Enumerated so the claim can
#: be asserted rather than believed.
RAISED_ERRORS = (
    AuthenticationFailed,
    InvalidProviderPayload,
    MarketDataError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
)

#: Failures this adapter never produces, and why. ``PartialData`` is the
#: interesting one: a keyless public feed never tells us it held anything
#: back, so raising it would mean claiming knowledge we do not have. Gaps
#: are found by validation from the timestamps themselves, which is where
#: the evidence actually is.
NOT_RAISED_ERRORS: dict[type[MarketDataError], str] = {
    PartialData: (
        "nothing here can tell that it withheld data; gaps are found by "
        "validation from the timestamps, not by asking the provider"
    ),
}


def _clock() -> datetime:
    return datetime.now(tz=UTC)


def _as_epoch(value: object) -> int | None:
    """Epoch seconds, or ``None`` when this is not one.

    Accepts both shapes the feed uses: a JSON number and a numeric string.
    ``bool`` is excluded because it is an ``int`` in Python, so ``true``
    would otherwise read as a timestamp one second after the epoch — a
    plausible-looking wrong answer rather than a refusal.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


class KrakenProvider:
    """Kraken's public REST feed, satisfying both provider protocols.

    Args:
        transport: how requests are made. Injected, so tests never open a
            socket and a different client can be substituted.
        now: clock, injectable so that "is this candle finished?" can be
            decided deterministically in a test instead of by luck.
    """

    #: Where candles this provider fetches actually came from, and what
    #: provenance records for them. Read off the code that fetches rather
    #: than typed at a command line: a source an operator could enter is
    #: a source an operator could get wrong, and provenance that can be
    #: edited describes nothing when it is later relied upon.
    source: str = _BASE_URL

    def __init__(
        self,
        transport: HttpTransport,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._now = now or _clock

    # -- HistoricalDataProvider ------------------------------------------

    async def fetch_bars(self, request: BarRequest) -> list[Bar]:
        """Fetch candles covering ``request``, oldest first.

        Bounded by ``end`` and/or ``limit``, or — if neither is set —
        fetched until the present.

        Pages are assembled in the order the provider sent them and are
        never sorted: ordering is exactly what validation exists to judge,
        and reordering in the adapter would mean the report describes
        something other than what arrived. A candle repeated from an
        *earlier page* is dropped, because that repetition is an artefact
        of how this adapter paged and not a finding about the provider —
        while a duplicate inside a single page is left in, so validation
        counts it and the manifest records it.
        """
        minutes = self._interval(request.timeframe)
        interval = timedelta(minutes=minutes)
        now = self._now()

        collected: list[Bar] = []
        page_bound: set[datetime] = set()
        since = int(request.start.timestamp()) - 1
        previous_last: int | None = None

        for _ in range(_MAX_PAGES):
            rows = await self._candles(symbol=request.symbol, minutes=minutes, since=since)
            if not rows:
                break

            # Read the whole page before judging any of it. One row that
            # will not read quarantines the batch rather than losing the
            # rows around it, and the page's newest candle is what decides
            # whether pagination has anything left to do.
            page_bars = [
                self._bar(row, index=index, symbol=request.symbol, timeframe=request.timeframe)
                for index, row in enumerate(rows)
            ]
            last_time = int(max(bar.timestamp.timestamp() for bar in page_bars))
            seen_this_page: set[datetime] = set()

            for bar in page_bars:
                # A repeat of a candle from an *earlier page* is an
                # artefact of how this adapter paged, not a finding about
                # the provider, so it is dropped here. A duplicate within
                # one page is the provider's own doing and is left in for
                # validation to count — dropping it here would make the
                # report describe something other than what arrived.
                if bar.timestamp in page_bound:
                    continue
                # Not finished yet: a bar that has not closed is not data.
                if bar.timestamp + interval > now:
                    continue
                if bar.timestamp < request.start:
                    continue
                if request.end is not None and bar.timestamp > request.end:
                    continue
                seen_this_page.add(bar.timestamp)
                collected.append(bar)

            page_bound |= seen_this_page

            if request.end is not None and last_time >= int(request.end.timestamp()):
                break
            if request.limit is not None and len(collected) >= request.limit:
                break
            if last_time + minutes * 60 >= now.timestamp():
                break
            if previous_last is not None and last_time <= previous_last:
                break

            previous_last = last_time
            # +1 second, not +1 candle: it guarantees forward progress
            # under either reading of whether ``since`` is inclusive.
            since = last_time + 1
        else:
            raise UnsupportedRange(
                f"covering {request.start.isoformat()} needed more than {_MAX_PAGES} "
                f"pages of {_PAGE_SIZE} candles; narrow the range"
            )

        if request.limit is not None:
            collected = collected[: request.limit]
        return collected

    # -- MarketDataProvider ----------------------------------------------

    async def latest_bars(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        """The most recent candles, oldest first.

        One provider page is requested rather than an unbounded range:
        the feed has no "everything" call, and asking for more than it
        will serve would be a request this adapter cannot honour.
        """
        minutes = self._interval(timeframe)
        start = self._now() - timedelta(minutes=minutes * _PAGE_SIZE)
        return await self.fetch_bars(BarRequest(symbol=symbol, timeframe=timeframe, start=start))

    async def symbols(self) -> list[str]:
        """The provider's tradable pairs, as the provider spells them.

        See the module docstring: these are Kraken's ``altname`` codes,
        not a unified cross-provider vocabulary, and provenance is what
        makes that attributable later.
        """
        payload = self._interpret(*await self._transport.get(f"{_BASE_URL}/AssetPairs"))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise InvalidProviderPayload("kraken's AssetPairs response has no 'result' object")

        names = [
            str(entry["altname"])
            for entry in result.values()
            if isinstance(entry, dict) and entry.get("altname")
        ]
        if not names:
            raise InvalidProviderPayload(
                "kraken's AssetPairs response contained no altname for any pair"
            )
        return sorted(names)

    # -- internals --------------------------------------------------------

    @staticmethod
    def _interval(timeframe: Timeframe) -> int:
        minutes = _INTERVAL_MINUTES.get(timeframe)
        if minutes is None:
            supported = ", ".join(value.value for value in _INTERVAL_MINUTES)
            raise UnsupportedRange(
                f"kraken's public OHLC feed has no {timeframe.value} interval; "
                f"it serves {supported}"
            )
        return minutes

    async def _candles(self, *, symbol: str, minutes: int, since: int) -> list[Sequence[object]]:
        query = urlencode({"pair": symbol, "interval": minutes, "since": since})
        payload = self._interpret(
            *await self._transport.get(f"{_BASE_URL}/OHLC?{query}"),
            about=f"symbol {symbol!r}",
        )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise InvalidProviderPayload("kraken's OHLC response has no 'result' object")

        # The pair key is the provider's own spelling (``XXBTZUSD`` for a
        # request that said ``XBTUSD``), and ``last`` sits beside it. The
        # caller's symbol is what goes on the bar, so the internal key
        # never reaches storage.
        for key, value in result.items():
            if key != "last" and isinstance(value, list):
                return value

        raise InvalidProviderPayload(f"kraken's OHLC response contained no candles for {symbol!r}")

    def _interpret(self, status: int, body: str, *, about: str = "") -> dict[str, object]:
        """Turn an HTTP answer into a payload, or into a typed failure.

        Mappings by status are provider-independent. The two mappings
        inside the ``error`` array are the two responses actually
        observed; anything else Kraken says is returned to the caller
        through the base class carrying the provider's own words, rather
        than being filed under a category that was guessed at.

        ``about`` says what was being asked — the symbol, when there was
        one — so a log line from a batch of several symbols can be told
        apart without reconstructing the request that produced it.
        """
        where = f" ({about})" if about else ""

        if status in (401, 403):
            raise AuthenticationFailed(f"kraken refused the request{where} with HTTP {status}")
        if status == 429:
            raise RateLimited(f"kraken asked this client to slow down{where}")
        if status == 408 or 500 <= status < 600:
            raise ProviderUnavailable(f"kraken answered HTTP {status}{where}")
        if status != 200:
            raise UnsupportedRange(
                f"kraken answered HTTP {status}{where}, which this adapter cannot serve"
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise InvalidProviderPayload(f"kraken's response was not JSON: {exc.msg}") from None
        if not isinstance(payload, dict):
            raise InvalidProviderPayload(
                "kraken's response was JSON but not an object, so it has no error array"
            )

        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            text = "; ".join(str(entry) for entry in errors)
            lowered = text.lower()
            if "unknown asset pair" in lowered:
                raise UnsupportedRange(f"kraken does not know that symbol{where}: {text}")
            if "invalid arguments" in lowered:
                raise UnsupportedRange(f"kraken rejected the request{where}: {text}")
            raise MarketDataError(f"kraken rejected the request{where}: {text}")
        return payload

    @staticmethod
    def _bar(row: Sequence[object], *, index: int, symbol: str, timeframe: Timeframe) -> Bar:
        """Read one candle. A row that will not read quarantines the batch.

        The message names the candle's position and the field that failed,
        never the row's values: a payload can contain anything and this
        string ends up in a log. Values are handed to the schema exactly as
        they arrived rather than converted here first, so a price that will
        not parse fails as a validation error naming a field instead of
        escaping as an exception from a conversion nobody chose to wrap.
        """
        if len(row) < 7:
            raise InvalidProviderPayload(
                f"candle {index} has {len(row)} fields; expected 8 "
                "[time, open, high, low, close, vwap, volume, count]"
            )
        epoch = _as_epoch(row[0])
        if epoch is None:
            # The value itself is left out of the message: an unreadable
            # timestamp is a thing to locate, not to quote.
            raise InvalidProviderPayload(f"candle {index} has a timestamp that is not a number")
        try:
            timestamp = datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError):
            raise InvalidProviderPayload(
                f"candle {index} has a timestamp outside the range this machine can hold"
            ) from None

        payload: dict[str, object] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": timestamp,
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[6],
        }
        try:
            return Bar.model_validate(payload)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ())) or "the bar"
            raise InvalidProviderPayload(
                f"candle at {timestamp.isoformat()} (position {index}) failed schema "
                f"validation at field '{location}': {first.get('msg')}"
            ) from None
