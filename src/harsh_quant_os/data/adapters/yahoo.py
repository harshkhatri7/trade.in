"""Yahoo Finance's public chart endpoint, behind our own interface.

**Why this provider was chosen.** Like ``adapters.kraken`` it needs no
key, no account and no credential of any kind, so the class of bug that
writes a secret into a log line is *structurally impossible* in this
adapter rather than merely avoided, because there is nothing in it to
write. It is also the keyless public endpoint found that carries Indian
exchange symbols — NSE indices and equities (``^NSEI``,
``RELIANCE.NS``, ``TCS.NS``) and BSE (``^BSESN``, ``TCS.BO``) — which
is what makes those markets reachable from this platform at all. Any
other symbol the service quotes is reachable the same way; the symbol
is the caller's spelling and nothing here guesses at a mapping between
venues.

**Everything stated below about the endpoint was checked against the
live service while this file was written, not recalled:**

- ``interval=1d`` with ``period1``/``period2`` served **1426 daily bars**
  spanning 2021-01-01 to now for ``^NSEI`` in one request — years of
  daily history fit in a single page;
- ``dataGranularity`` echoed the requested interval exactly for every
  interval tried — ``1m``, ``1h``, ``4h``, ``1d``, ``1wk``, ``1mo``.
  ``4h`` genuinely returns four-hour bars; that was checked rather than
  assumed, because serving a different interval than was asked for
  would silently pass one timeframe off as another;
- **intraday history is short, and out-of-range windows are refused
  with an empty body.** A fresh 7-day ``1m`` window answered **HTTP
  200**; 30 days back answered **HTTP 422**; ``5m`` over ``range=3mo``
  answered **422**; ``1h`` at 90 days answered 200; and ``1h`` at 400
  days *also* answered 200 — with the **same 385 bars as the 90-day
  window**, i.e. silently clipped to what the feed still holds. That
  silent clip is why this adapter measures where the returned series
  begins and raises :class:`~harsh_quant_os.data.errors.PartialData`
  rather than passing a short series off as a complete one. It is the
  one structural difference from ``adapters.kraken``, which never
  raises ``PartialData`` because its feed answers a ``since`` cursor
  instead of clipping;
- an unknown symbol answers **HTTP 404 with an empty body** — there is
  no error document to read, so the status is the only signal;
- a *burst* of requests flipped symbols that had served seconds
  earlier to **404 with a JSON body** reading ``No data found, symbol
  may be delisted``, and the same symbols answered 200 again after
  about thirty seconds. Status alone therefore never proves a symbol
  is unknown: when a 400/404/422 arrives with a body, the provider's
  own description is quoted into the failure, and when the body is
  empty the message says only what was observed;
- coverage is the feed's business *per symbol*: ``TCS.BO`` served a
  full year of daily bars (listing 2002) while ``RELIANCE.BO`` and
  ``INFY.BO`` answered with a single current-session bar and an
  identical recent ``firstTradeDate`` — so nothing here promises
  per-symbol history, and provenance records the symbol as spelled;
- the five-year daily series contained **5 timestamps at which all
  five quote fields were null** — a real shape of this feed, not a
  hypothetical. A row with every price null carries no observation, so
  it is skipped: absence stays absence, and validation finds the hole
  from the timestamps themselves. A row with *some* prices present and
  others null would require inventing a price and is refused instead;
- on an intraday window that includes the running session, the feed
  emitted its **in-progress marker out of order**: for ``^NSEI`` at
  ``1h`` over 2026-07-01..now, a flat row stamped ``2026-10-01T10:00``
  (open = close = the previous bar's close, i.e. the current price, not
  an hour of trading) appeared at index 301 of 463, between two August
  bars. Validation refused the batch for non-increasing timestamps —
  which is the right answer for a series that is not a series — and the
  quarantined payload is what proved the shape. Bounding the window to
  ``--end 2026-09-30`` (sessions that have finished) removed the marker
  and the same request ingested 448 bars. Nothing here sorts or rewrites
  timestamps to make such a batch pass;
- prices arrive as **JSON numbers**. ``json.loads`` is given
  ``parse_float=Decimal`` so the decimal text the feed sent reaches
  ``Decimal`` unchanged — the same "nothing is rounded on the way in"
  property Kraken gets by sending decimal *strings*;
- the transport's own plain ``User-Agent`` is answered with HTTP 200,
  identically to a browser's — no disguise is needed, so none is used;
- a body may also carry an ``error`` object inside a 200
  (``chart.error``). That shape was **not observed** live while writing
  this — the observed failures are HTTP statuses with empty bodies — so
  the branch in :meth:`YahooProvider._interpret` is defensive and is
  labelled as such there.

**Two properties of this feed shape the code:**

1. **The newest bar may still be running.** Completion is decided by
   arithmetic (``now >= open + interval``), never by "it happened to be
   last". For ``1mo`` the interval used is a conservative 31 days, so a
   monthly bar is admitted only after every possible month has closed
   over it — late, never early; an unfinished bar would be an invented
   bar.

2. **Symbol spelling is the caller's.** ``^NSEI`` and ``TCS.BO`` are
   what was asked for, and that is what lands on the bar. The NSE and
   BSE listings of one company are *not* unified into one series —
   they are two venues with two order books, and merging them would be
   a claim. Provenance records ``source`` so a symbol stays
   attributable to its namespace.

**What this adapter does not claim.** It satisfies only
:class:`~harsh_quant_os.data.providers.HistoricalDataProvider`. A
keyless feed offers no honest way to enumerate every symbol it serves,
and inventing a universe would be guessing; ``symbols`` is therefore
deliberately absent, which makes :class:`~harsh_quant_os.data.providers.MarketDataProvider`
unimplementable-by-omission rather than implemented-with-a-fabrication.
``latest_bars`` exists because it is a bounded window of the same
history and answers no question about a universe.

What this adapter can and cannot raise is not left to the reader:
:attr:`RAISED_ERRORS` lists the typed failures it produces — including
``PartialData``, unlike Kraken — and :attr:`NOT_RAISED_ERRORS` lists the
ones it never does, with why.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from urllib.parse import quote, urlencode

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
    "YahooProvider",
]

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

#: Provider label to the endpoint's own ``interval`` value, checked
#: live: every entry below answered with ``dataGranularity`` equal to
#: what was asked. ``tick`` is deliberately absent — the feed has no
#: tick stream, and substituting the nearest thing that does exist
#: would be answering a question nobody asked. Asking for one raises
#: ``UnsupportedRange`` naming what *is* supported.
_INTERVAL_TEXT: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MN1: "1mo",
}

#: How much elapsed time counts as "finished" for each timeframe.
#:
#: Everything but the month is its exact length. A month is not a
#: fixed length, so ``MN1`` uses a **conservative 31 days**: a monthly
#: bar is admitted only after the longest possible month has closed
#: over it. That admits the current month's bar late — after 31 days —
#: and never early. The opposite rule would store a bar that could
#: still change.
_COMPLETION: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
    Timeframe.MN1: timedelta(days=31),
}

#: How far one request may span, per timeframe — from the observed
#: behaviour above, not from documentation:
#:
#: * minute-level intervals: **6 days** (7 days served; 30 refused
#:   with HTTP 422), with margin;
#: * hour-level intervals: **60 days** (90 days served);
#: * day, week and month: ``timedelta.max`` — one request for the
#:   whole window, because multi-year daily history was observed to
#:   arrive in a single page.
_PAGE_WINDOW: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(days=6),
    Timeframe.M5: timedelta(days=6),
    Timeframe.M15: timedelta(days=6),
    Timeframe.M30: timedelta(days=6),
    Timeframe.H1: timedelta(days=60),
    Timeframe.H4: timedelta(days=60),
    Timeframe.D1: timedelta.max,
    Timeframe.W1: timedelta.max,
    Timeframe.MN1: timedelta.max,
}

#: A safety net, not a policy: it stops a bad range from looping
#: forever. At six days a page it would take fifty pages — eight years
#: of minute-level history, far past anything the feed retains —
#: before tripping, and tripping raises rather than returning a short
#: answer that looked complete.
_MAX_PAGES = 50

#: How many intervals back :meth:`YahooProvider.latest_bars` reaches.
_LATEST_BARS = 400

#: ...capped so that a month-sized interval does not ask for
#: thirty-four years of history in one call.
_LATEST_MAX_SPAN = timedelta(days=1095)

#: A head gap up to this long never counts as a shortfall: markets are
#: closed on weekends and holidays, so a series legitimately begins
#: days after a window opens. Where a timeframe's own completion
#: interval is longer — ``1mo`` at 31 days — that is used instead, for
#: the same reason: a monthly bar's open time can sit a whole month
#: before a window that still contains it.
_HEAD_GRACE = timedelta(days=7)

#: ...and a head gap must also be this large a fraction of the window
#: before it counts. A week-long suspension inside a long window is
#: absence for validation to find; only a gap that dominates the
#: window looks like "the feed no longer holds this era".
_HEAD_FRACTION = 0.25

#: The typed failures this adapter produces. ``PartialData`` is the
#: difference from ``adapters.kraken``: this feed was *observed*
#: silently clipping a 400-day request to the ~90 days it still
#: holds, so a short series here is a real, detected condition and
#: reporting it as a complete one would be the quiet failure
#: ``PartialData`` exists to prevent.
RAISED_ERRORS = (
    AuthenticationFailed,
    InvalidProviderPayload,
    MarketDataError,
    PartialData,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
)

#: Failures this adapter never produces, and why. Nothing is listed:
#: every typed failure in :mod:`harsh_quant_os.data.errors` is
#: reachable here — statuses map to four of them, payload shape to
#: ``InvalidProviderPayload``, transport to ``ProviderUnavailable``,
#: and observed clipping to ``PartialData``. An empty mapping is still
#: asserted against the full set by the test suite, so this claim
#: staying empty is itself checked.
NOT_RAISED_ERRORS: dict[type[MarketDataError], str] = {}


def _clock() -> datetime:
    return datetime.now(tz=UTC)


def _as_epoch(value: object) -> int | None:
    """Epoch seconds, or ``None`` when this is not one.

    JSON numbers arrive as ``int`` or ``Decimal`` (this adapter parses
    floats as ``Decimal``); strings and floats are accepted too because
    a feed may spell a timestamp either way. ``bool`` is excluded: it is
    an ``int`` in Python, so ``true`` would otherwise read as a
    timestamp one second after the epoch — a plausible-looking wrong
    answer rather than a refusal.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _error_description(body: str) -> str | None:
    """The provider's own words from a JSON error document, if one arrived.

    Observed on 404 responses in two shapes: empty (an unknown symbol —
    nothing to read) and carrying ``chart.error`` with a description
    (a *known* symbol during a burst of requests, which recovered after
    about thirty seconds). An empty or unreadable body says nothing, so
    nothing is invented to fill it; a body that speaks is quoted, since
    the failure message must not contradict the provider.
    """
    if not body.strip():
        return None
    try:
        payload = json.loads(body, parse_float=Decimal)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    chart = payload.get("chart")
    error = chart.get("error") if isinstance(chart, dict) else None
    if isinstance(error, dict):
        description = error.get("description") or error.get("code")
        if description:
            return str(description)
    return None


class YahooProvider:
    """The public chart endpoint, satisfying the historical protocol.

    Args:
        transport: how requests are made. Injected, so tests never open
            a socket and a different client can be substituted.
        now: clock, injectable so that "is this bar finished?" can be
            decided deterministically in a test instead of by luck.
    """

    #: Where bars this provider fetches actually came from, and what
    #: provenance records for them. Read off the code that fetches
    #: rather than typed at a command line: a source an operator could
    #: enter is a source an operator could get wrong, and provenance
    #: that can be edited describes nothing when it is later relied
    #: upon. The URL carries no credential, so provenance rows never
    #: carry one either.
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
        """Fetch bars covering ``request``, oldest first.

        Bounded by ``end`` and/or ``limit``, or — if neither is set —
        fetched until the present. Intraday ranges are fetched in the
        windows the feed was observed to serve; day, week and month in
        a single request.

        Pages are assembled in the order the provider sent them and are
        never sorted: ordering is exactly what validation exists to
        judge, and reordering in the adapter would mean the report
        describes something other than what arrived. A bar repeated
        from an *earlier page* is dropped, because that repetition is
        an artefact of how this adapter paged and not a finding about
        the provider — while a duplicate inside a single page is left
        in, so validation counts it and the manifest records it.

        Raises:
            PartialData: bars arrived, but the series begins well
                after the requested start although the symbol already
                traded by then — the observed silent clip. A short
                series and a complete one must not look identical
                downstream.
        """
        interval_text = self._interval(request.timeframe)
        completion = _COMPLETION[request.timeframe]
        now = self._now()
        upper = now if request.end is None else min(request.end, now)
        if upper < request.start:
            # Every bar asked for is still in the future; there is
            # nothing to fetch and nothing to claim. Answering the
            # empty window rather than sending a request whose
            # period1 sits after its period2.
            return []

        window_span = _PAGE_WINDOW[request.timeframe]
        collected: list[Bar] = []
        page_bound: set[datetime] = set()
        first_traded: int | None = None
        cursor = request.start

        for _ in range(_MAX_PAGES):
            # Never ``cursor + window_span`` directly: the daily, weekly
            # and monthly windows are "everything", and adding them to a
            # real date would overflow the calendar. Remaining distance
            # first, then the smaller of the two.
            remaining = upper - cursor
            window_end = upper if window_span >= remaining else cursor + window_span
            # The window is stretched one interval at each end: a bar
            # exactly on a boundary must be served by some page, and
            # whether the endpoints are inclusive is the feed's own
            # business. The repeats this provokes are dropped below —
            # they are this adapter's own paging artefact.
            page, traded = await self._page(
                symbol=request.symbol,
                interval_text=interval_text,
                timeframe=request.timeframe,
                period1=max(0, int((cursor - completion).timestamp())),
                period2=int((window_end + completion).timestamp()),
            )
            if first_traded is None and traded is not None:
                first_traded = traded

            seen_this_page: set[datetime] = set()
            for bar in page:
                # A repeat from an *earlier page* is this adapter's own
                # paging artefact and is dropped. A duplicate within
                # this page is the provider's own doing and is left in,
                # so validation counts it — which is why the bound set
                # only grows at the page's end, not as bars arrive.
                if bar.timestamp in page_bound:
                    continue
                if bar.timestamp + completion > now:
                    # Not finished yet: a bar that has not closed is
                    # not data — it is an intention.
                    continue
                if bar.timestamp < request.start:
                    continue
                if request.end is not None and bar.timestamp > request.end:
                    continue
                seen_this_page.add(bar.timestamp)
                collected.append(bar)
            page_bound |= seen_this_page

            if window_end >= upper:
                break
            # Deliberately not conditioned on a non-empty page: a
            # window with no trading (a holiday week) is an answer,
            # not the end of the history, and stopping there would
            # truncate the range at the first closed market.
            cursor = window_end
        else:
            raise UnsupportedRange(
                f"covering {request.start.isoformat()} needed more than {_MAX_PAGES} "
                f"pages for {request.symbol!r}; narrow the range"
            )

        self._check_coverage(
            collected,
            request=request,
            upper=upper,
            completion=completion,
            first_traded=first_traded,
        )

        if request.limit is not None:
            collected = collected[: request.limit]
        return collected

    # -- convenience, not the MarketDataProvider protocol -----------------

    async def latest_bars(self, symbol: str, timeframe: Timeframe) -> list[Bar]:
        """The most recent bars, oldest first.

        A bounded window of the same history rather than an unbounded
        reach: :data:`_LATEST_BARS` intervals back, capped for the
        month-sized interval. This method alone does not make the
        provider a ``MarketDataProvider`` — see the module docstring.
        """
        self._interval(timeframe)
        completion = _COMPLETION[timeframe]
        span = min(completion * _LATEST_BARS, _LATEST_MAX_SPAN)
        return await self.fetch_bars(
            BarRequest(symbol=symbol, timeframe=timeframe, start=self._now() - span)
        )

    # -- internals --------------------------------------------------------

    @staticmethod
    def _interval(timeframe: Timeframe) -> str:
        interval_text = _INTERVAL_TEXT.get(timeframe)
        if interval_text is None:
            supported = ", ".join(value.value for value in _INTERVAL_TEXT)
            raise UnsupportedRange(
                f"the chart feed has no {timeframe.value} interval; it serves {supported}"
            )
        return interval_text

    async def _page(
        self,
        *,
        symbol: str,
        interval_text: str,
        timeframe: Timeframe,
        period1: int,
        period2: int,
    ) -> tuple[list[Bar], int | None]:
        """One window of history: bars, plus when the symbol first traded.

        ``first traded`` comes back with every page because the
        coverage check needs it to tell "the feed no longer holds this
        era" apart from "the symbol did not exist yet" — the two look
        identical in the bars themselves.
        """
        query = urlencode({"interval": interval_text, "period1": period1, "period2": period2})
        # ``quote`` so that ``^NSEI`` reaches the wire as ``%5ENSEI``
        # and a symbol can never alter the query around it.
        url = f"{_BASE_URL}/{quote(symbol, safe='')}?{query}"
        chart = self._interpret(
            *await self._transport.get(url),
            about=f"symbol {symbol!r}",
        )

        result = chart.get("result")
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            raise InvalidProviderPayload(
                f"yahoo's chart response has no result object for {symbol!r}"
            )
        entry = result[0]

        self._check_granularity(entry, interval_text=interval_text, symbol=symbol)
        meta = entry.get("meta")
        first_traded = _as_epoch(meta.get("firstTradeDate")) if isinstance(meta, dict) else None

        timestamps = entry.get("timestamp")
        if timestamps is None:
            # An empty window is an answer: nothing traded between
            # these bounds. Missing ``timestamp`` with a present
            # result is that shape.
            return [], first_traded
        if not isinstance(timestamps, list):
            raise InvalidProviderPayload(
                f"yahoo's chart result for {symbol!r} has no bar timestamps"
            )

        quote_series = self._quote_series(entry, expected=len(timestamps), symbol=symbol)
        bars: list[Bar] = []
        for index, raw_epoch in enumerate(timestamps):
            epoch = _as_epoch(raw_epoch)
            if epoch is None:
                # The value itself is left out of the message: an
                # unreadable timestamp is a thing to locate, not to
                # quote.
                raise InvalidProviderPayload(f"bar {index} has a timestamp that is not a number")
            try:
                timestamp = datetime.fromtimestamp(epoch, tz=UTC)
            except (OverflowError, OSError, ValueError):
                raise InvalidProviderPayload(
                    f"bar {index} has a timestamp outside the range this machine can hold"
                ) from None

            prices = {name: quote_series[name][index] for name in ("open", "high", "low", "close")}
            missing = [name for name, value in prices.items() if value is None]
            if len(missing) == 4:
                # Every price null: the feed recorded no observation at
                # this timestamp. Skipping is not repairing — there is
                # no bar here to skip *around*, and validation finds
                # the resulting hole from the timestamps, which is
                # where the evidence actually is.
                continue
            if missing:
                # Some prices present and others null: reading this bar
                # would require inventing the missing price. Refused,
                # naming the position and the absent fields — never
                # the values, because a payload can contain anything
                # and this string ends up in a log.
                raise InvalidProviderPayload(
                    f"bar at {timestamp.isoformat()} (position {index}) has "
                    f"{4 - len(missing)} of 4 prices; missing "
                    f"{', '.join(missing)} — a partial bar would need an "
                    "invented price"
                )

            payload: dict[str, object] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": timestamp,
                "open": prices["open"],
                "high": prices["high"],
                "low": prices["low"],
                "close": prices["close"],
                "volume": quote_series["volume"][index],
            }
            try:
                bars.append(Bar.model_validate(payload))
            except ValidationError as exc:
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first.get("loc", ())) or "the bar"
                raise InvalidProviderPayload(
                    f"bar at {timestamp.isoformat()} (position {index}) failed schema "
                    f"validation at field '{location}': {first.get('msg')}"
                ) from None
        return bars, first_traded

    @staticmethod
    def _quote_series(
        entry: dict[str, object], *, expected: int, symbol: str
    ) -> dict[str, list[object]]:
        """The parallel price arrays, checked for shape — not content.

        Lengths must match the timestamp array: a feed that answered
        with fewer closes than timestamps would otherwise line prices
        up against the wrong moments, which is the kind of quiet
        misreading a payload check exists to stop. Values are handed
        on exactly as they arrived; a value that will not read fails
        later as a validation error naming a field.
        """
        indicators = entry.get("indicators")
        if not isinstance(indicators, dict):
            raise InvalidProviderPayload(
                f"yahoo's chart result for {symbol!r} has no indicators object"
            )
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
            raise InvalidProviderPayload(f"yahoo's chart result for {symbol!r} has no quote series")
        series = quotes[0]

        columns: dict[str, list[object]] = {}
        for name in ("open", "high", "low", "close"):
            values = series.get(name)
            if not isinstance(values, list) or len(values) != expected:
                found = len(values) if isinstance(values, list) else type(values).__name__
                raise InvalidProviderPayload(
                    f"yahoo's chart result for {symbol!r} has {found} {name} entries; "
                    f"expected {expected}"
                )
            columns[name] = values

        volumes = series.get("volume")
        if volumes is None:
            # The feed omitted volume entirely for this series. That is
            # "no volume reported", which is ``None`` — never ``0``,
            # because zero is a claim that nothing traded.
            columns["volume"] = [None] * expected
        elif isinstance(volumes, list) and len(volumes) == expected:
            columns["volume"] = volumes
        else:
            found = len(volumes) if isinstance(volumes, list) else type(volumes).__name__
            raise InvalidProviderPayload(
                f"yahoo's chart result for {symbol!r} has {found} volume entries; "
                f"expected {expected}"
            )
        return columns

    @staticmethod
    def _check_granularity(entry: dict[str, object], *, interval_text: str, symbol: str) -> None:
        """Refuse bars served at a different interval than was asked.

        Observed to echo correctly for every interval tried — which is
        exactly why it is checked: if a feed ever answered a ``1h``
        request with ``1d`` bars, those bars would carry the right
        symbol and plausible prices while being the wrong timeframe,
        and nothing downstream could tell.
        """
        meta = entry.get("meta")
        granularity = meta.get("dataGranularity") if isinstance(meta, dict) else None
        if isinstance(granularity, str) and granularity and granularity != interval_text:
            raise InvalidProviderPayload(
                f"yahoo served {granularity!r} bars for a {interval_text!r} request "
                f"for {symbol!r}: the timeframe asked for is not the timeframe "
                "that arrived"
            )

    @staticmethod
    def _interpret(status: int, body: str, *, about: str = "") -> dict[str, object]:
        """Turn an HTTP answer into the chart envelope, or a typed failure.

        The status mappings are provider-independent, as in
        ``adapters.kraken``. The one mapping that *is* an observation
        is 404: an unknown symbol answered 404 with an **empty** body
        while this file was written, so there is no error document to
        read and the status carries the whole meaning. 400 and 422 were
        both observed with empty bodies as well, on windows the feed no
        longer serves.

        ``about`` says what was being asked — the symbol — so a log
        line from a batch of several symbols can be told apart without
        reconstructing the request that produced it.
        """
        where = f" ({about})" if about else ""

        if status in (401, 403):
            raise AuthenticationFailed(f"yahoo refused the request{where} with HTTP {status}")
        if status == 429:
            raise RateLimited(f"yahoo asked this client to slow down{where}")
        if status == 404:
            description = _error_description(body)
            if description:
                # A 404 arrived both *empty* (an unknown symbol) and
                # *carrying this document* (a known symbol during a
                # burst of requests, recovered after ~30 seconds).
                # Quoting the feed's own words is honest in both
                # cases; "does not know that symbol" would be a claim
                # the body contradicts.
                raise UnsupportedRange(f"yahoo did not serve that symbol{where}: {description}")
            raise UnsupportedRange(f"yahoo does not know that symbol{where}")
        if status in (400, 422):
            description = _error_description(body)
            if description:
                raise UnsupportedRange(f"yahoo answered HTTP {status}{where}: {description}")
            raise UnsupportedRange(
                f"yahoo answered HTTP {status}{where}, which this adapter cannot serve"
            )
        if status == 408 or 500 <= status < 600:
            raise ProviderUnavailable(f"yahoo answered HTTP {status}{where}")
        if status != 200:
            raise UnsupportedRange(
                f"yahoo answered HTTP {status}{where}, which this adapter cannot serve"
            )

        try:
            # ``parse_float=Decimal``: the decimal text on the wire is
            # what reaches the schema. A JSON number routed through a
            # binary float first would be rounded before anyone had
            # decided that rounding is acceptable.
            payload = json.loads(body, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise InvalidProviderPayload(f"yahoo's response was not JSON: {exc.msg}") from None
        if not isinstance(payload, dict):
            raise InvalidProviderPayload(
                "yahoo's response was JSON but not an object, so it has no chart envelope"
            )

        chart = payload.get("chart")
        if not isinstance(chart, dict):
            raise InvalidProviderPayload("yahoo's response has no 'chart' object")

        # Defensive: this shape (an error object inside HTTP 200) was
        # documented but *not* observed while writing this file —
        # every observed failure was a status with an empty body. It is
        # handled so that a feed that starts using it fails loudly
        # rather than as a missing result.
        error = chart.get("error")
        if isinstance(error, dict) and error:
            description = str(error.get("description") or error.get("code") or error)
            lowered = description.lower()
            if "not found" in lowered or "no data found" in lowered:
                raise UnsupportedRange(f"yahoo does not know that symbol{where}: {description}")
            raise MarketDataError(f"yahoo rejected the request{where}: {description}")
        if error is not None:
            raise InvalidProviderPayload(
                "yahoo's chart envelope carries an error that is not an object"
            )
        return chart

    @staticmethod
    def _check_coverage(
        bars: list[Bar],
        *,
        request: BarRequest,
        upper: datetime,
        completion: timedelta,
        first_traded: int | None,
    ) -> None:
        """Compare where the series begins with where the window did.

        Two reasons a series can start later than the window: the feed
        no longer holds the earlier era (observed: a 400-day hourly
        request served only the most recent ~90 days), or the symbol
        had not traded yet (``firstTradeDate`` says so). Only the
        first is a shortfall. The thresholds forgive the second, plus
        weekends, holidays and suspensions short enough to be a hole
        for validation to find rather than a different dataset.
        """
        if not bars:
            # Nothing arrived at all. The caller reports an empty
            # window as an empty window — that message claims no
            # completeness, so there is nothing here to contradict.
            return

        first = min(bar.timestamp for bar in bars)
        last = max(bar.timestamp for bar in bars)

        coverage_start = request.start
        if first_traded is not None:
            traded_at = datetime.fromtimestamp(first_traded, tz=UTC)
            if traded_at > coverage_start:
                # The window opens before the symbol existed: the feed
                # cannot serve what there was no market for, and that
                # is absence, not a shortfall.
                coverage_start = traded_at

        if first <= coverage_start:
            return

        gap = first - coverage_start
        grace = max(_HEAD_GRACE, completion)
        if gap <= grace:
            return
        span = upper - coverage_start
        if span <= timedelta(0) or gap / span <= _HEAD_FRACTION:
            return

        requested_days = ceil(span.total_seconds() / 86_400)
        received_days = ceil((last - first).total_seconds() / 86_400) + 1
        raise PartialData(
            f"yahoo served {received_days} days of the {requested_days}-day window "
            f"for {request.symbol!r}: its series begins {first.isoformat()}, long "
            f"after the requested start {coverage_start.isoformat()}. A shorter "
            "series must not be passed off as the asked-for one; ask for a window "
            "the feed still holds",
            requested=requested_days,
            received=received_days,
        )
