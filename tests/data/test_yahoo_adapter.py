"""The Yahoo adapter, asserted against the promises it makes.

Nothing here opens a socket. Every response is scripted, so a failure
means a rule moved rather than that a provider changed its mind — and a
request the script did not prepare for raises instead of quietly
answering itself, because an unscripted page answered with an empty body
would otherwise look exactly like an exhausted feed and pass by accident.

The values are deliberately non-prices with the obvious shape. What is
under test is which field lands where, which typed failure a given
answer produces, when a short series is *refused* rather than returned,
and that a null is never read as a zero — not any number that could be
mistaken for a result.

The response shapes come from probing the live endpoint while the
adapter was written: the chart envelope with parallel quote arrays,
``dataGranularity`` echoing the requested interval, an empty body behind
HTTP 404/400/422, and the observed silent clip that ``PartialData``
exists to catch. Those are the strings and shapes asserted here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from harsh_quant_os.contracts.provenance import Timeframe
from harsh_quant_os.data import (
    AuthenticationFailed,
    BarRequest,
    HistoricalDataProvider,
    HttpTransport,
    InvalidProviderPayload,
    MarketDataError,
    MarketDataProvider,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
    YahooProvider,
    validate_bars,
)
from harsh_quant_os.data.adapters.yahoo import NOT_RAISED_ERRORS, RAISED_ERRORS
from harsh_quant_os.data.errors import PartialData

#: The clock the adapter sees. Fixed, so "has this bar closed?" is
#: arithmetic instead of a race against the wall clock.
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SYMBOL = "^NSEI"

#: From the live probe: ^NSEI's first trade date (2007-09-17), old
#: enough to sit before every window requested in this file.
FIRST_TRADED = 1_190_000_700


def _now() -> datetime:
    return NOW


def _stamp(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Epoch seconds for a time, always before ``NOW`` when <= Aug 2026."""
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def _payload(
    stamps: list[object],
    *,
    granularity: str = "1d",
    first_traded: int | None = FIRST_TRADED,
    opens: list[object] | None = None,
    highs: list[object] | None = None,
    lows: list[object] | None = None,
    closes: list[object] | None = None,
    volumes: list[object] | None = None,
    omit_volume: bool = False,
    with_timestamp: bool = True,
) -> str:
    """One chart envelope, shaped as the live endpoint answered it.

    Prices are JSON *numbers*, as the feed sends them — which is why the
    adapter parses floats as ``Decimal``. ``None`` entries are the real
    all-null rows the five-year daily series contained.
    """
    n = len(stamps)
    quote: dict[str, list[object]] = {
        "open": list(opens) if opens is not None else [100.0] * n,
        "high": list(highs) if highs is not None else [101.0] * n,
        "low": list(lows) if lows is not None else [99.0] * n,
        "close": list(closes) if closes is not None else [100.5] * n,
    }
    if not omit_volume:
        quote["volume"] = list(volumes) if volumes is not None else [10.0] * n

    entry: dict[str, object] = {
        "meta": {
            "currency": "INR",
            "symbol": SYMBOL,
            "exchangeName": "NSI",
            "instrumentType": "INDEX",
            "firstTradeDate": first_traded,
            "dataGranularity": granularity,
        },
        "indicators": {"quote": [quote]},
    }
    if with_timestamp:
        entry["timestamp"] = list(stamps)
    return json.dumps(
        {"chart": {"result": [entry], "error": None}},
    )


def _request(
    *,
    start: datetime | int,
    end: datetime | int | None = None,
    timeframe: Timeframe = Timeframe.D1,
    limit: int | None = None,
) -> BarRequest:
    """Build a request from datetimes or raw epoch seconds."""

    def as_datetime(value: datetime | int) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromtimestamp(value, tz=UTC)

    return BarRequest(
        symbol=SYMBOL,
        timeframe=timeframe,
        start=as_datetime(start),
        end=None if end is None else as_datetime(end),
        limit=limit,
    )


class _ScriptedTransport:
    """Answers from canned responses and refuses to invent one.

    An unscripted request is a failure of the test's premise. Raising is
    the point: if this returned an empty page, the adapter would treat it
    as an exhausted window and the test would pass for the wrong reason.
    """

    def __init__(self, *responses: tuple[int, str]) -> None:
        self._responses = list(responses)
        self.requested: list[str] = []

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        self.requested.append(url)
        if not self._responses:
            raise AssertionError(f"the adapter made an unscripted request: {url}")
        return self._responses.pop(0)


class _EndlessEmptyTransport:
    """A feed whose windows are always empty — a range that never finishes.

    Used to prove that a range the adapter cannot cover is *refused*
    rather than answered with whatever it had managed to collect.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        self.calls += 1
        return 200, _payload([], granularity="1m")


def _provider(*responses: tuple[int, str]) -> tuple[YahooProvider, _ScriptedTransport]:
    transport = _ScriptedTransport(*responses)
    return YahooProvider(transport, now=_now), transport


def _provider_with(transport: HttpTransport) -> YahooProvider:
    return YahooProvider(transport, now=_now)


# -- what a bar becomes ----------------------------------------------------


async def test_a_chart_becomes_bars_with_the_documented_fields() -> None:
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, 3), _stamp(2026, 8, 4)])),
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert len(bars) == 2
    first = bars[0]
    assert first.symbol == SYMBOL
    assert first.timeframe is Timeframe.D1
    assert first.timestamp == datetime(2026, 8, 3, tzinfo=UTC)
    assert first.open == Decimal("100.0")
    assert first.high == Decimal("101.0")
    assert first.low == Decimal("99.0")
    assert first.close == Decimal("100.5")
    assert first.volume == Decimal("10.0")


async def test_decimal_text_reaches_the_schema_without_a_float_detour() -> None:
    """The reason ``parse_float=Decimal`` exists, made testable.

    The wire carries ``100.123456789012345678``. Through a binary
    double first, that becomes ``100.12345678901235`` — a different
    number, rounded before anyone decided rounding was acceptable. The
    assertion below is on the *full* precision, so the test fails if
    the parse route ever changes.
    """
    body = (
        '{"chart":{"result":[{"meta":{"currency":"INR","symbol":"^NSEI",'
        f'"firstTradeDate":{FIRST_TRADED},"dataGranularity":"1d"}},'
        f'"timestamp":[{_stamp(2026, 8, 3)}],'
        '"indicators":{"quote":[{"open":[100.123456789012345678],'
        '"high":[101.0],"low":[99.0],"close":[100.5],"volume":[10.0]}]}}],'
        '"error":null}}'
    )
    provider, _ = _provider((200, body))

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert bars[0].open == Decimal("100.123456789012345678"), "the price was rounded"


async def test_the_symbol_that_went_out_is_the_symbol_that_comes_back() -> None:
    provider, transport = _provider((200, _payload([_stamp(2026, 8, 3)])))

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert [bar.symbol for bar in bars] == [SYMBOL]
    assert transport.requested, "nothing was requested"
    # ``^NSEI`` reaches the wire as ``%5ENSEI``: quoted, so no symbol
    # can alter the query around it.
    assert "%5E" in transport.requested[0], "the symbol was not quoted into the path"


async def test_a_bar_that_has_not_closed_is_not_returned() -> None:
    """A bar that has not finished is not data — it is an intention.

    The newest bar in a window ending at ``NOW`` could still change;
    completion is arithmetic (open + 1 day), never "it was last".
    """
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, 1), _stamp(2026, 8, 31), _stamp(2026, 9, 1)])),
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=NOW))

    assert [bar.timestamp.day for bar in bars] == [1, 31], "an unfinished bar was kept"


async def test_a_window_that_ended_in_the_past_keeps_every_finished_bar() -> None:
    """Completion is arithmetic, not "it happened to be the last one".

    A series that ends a month before now would be silently truncated
    by a rule that dropped whichever bar came last — including the bar
    sitting exactly on the window's end.
    """
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, 8), _stamp(2026, 8, 9), _stamp(2026, 8, 10)]))
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 8), end=_stamp(2026, 8, 10)))

    assert [bar.timestamp.day for bar in bars] == [8, 9, 10], "a finished bar was dropped"


async def test_a_bar_that_breaks_its_own_ohlc_rules_quarantines_the_batch() -> None:
    """One bad row takes the batch, and the message does not quote it."""
    sentinel = "1234.5678"
    body = _payload(
        [_stamp(2026, 8, 3), _stamp(2026, 8, 4)],
        highs=[90.0, 101.0],
        volumes=[sentinel, 10.0],
    )
    provider, _ = _provider((200, body))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "2026-08-03T00:00" in message, "the failing bar was not named"
    assert "failed schema validation" in message
    assert sentinel not in message, "the payload was echoed into a log message"


# -- nulls: absence is not a number ----------------------------------------


async def test_a_row_with_every_price_null_is_skipped_not_coerced() -> None:
    """The observed shape of this feed: a timestamp with no prices.

    Such a row carries no observation. Skipping keeps absence an
    absence; reading it as zero would invent a session where the feed
    recorded nothing, and validation finds the resulting hole from the
    timestamps.
    """
    provider, _ = _provider(
        (
            200,
            _payload(
                [_stamp(2026, 8, 3), _stamp(2026, 8, 4), _stamp(2026, 8, 5)],
                opens=[100.0, None, 100.0],
                highs=[101.0, None, 101.0],
                lows=[99.0, None, 99.0],
                closes=[100.5, None, 100.5],
                volumes=[10.0, None, 10.0],
            ),
        )
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert [bar.timestamp.day for bar in bars] == [3, 5], "the null row became a bar"


async def test_a_row_with_only_some_prices_null_is_refused_not_filled() -> None:
    """A partial bar would need an invented price to become a ``Bar``.

    Refused naming the position and the missing field — never the
    values, which are the payload's business and end up in logs.
    """
    sentinel = "777.0"
    body = _payload(
        [_stamp(2026, 8, 3), _stamp(2026, 8, 4)],
        closes=[100.5, None],
        opens=[100.0, sentinel],
    )
    provider, _ = _provider((200, body))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "missing close" in message, "the absent field was not named"
    assert "3 of 4" in message
    assert sentinel not in message, "the payload was echoed into a log message"


async def test_no_volume_reported_is_none_and_never_zero() -> None:
    """Zero is a claim that nothing traded; ``None`` is a claim of nothing."""
    provider, _ = _provider((200, _payload([_stamp(2026, 8, 3)], omit_volume=True)))

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert bars[0].volume is None, "a missing volume was read as a number"

    provider, _ = _provider((200, _payload([_stamp(2026, 8, 3)], volumes=[None])))
    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert bars[0].volume is None, "an explicitly null volume was read as a number"


# -- what the adapter refuses to do ----------------------------------------


async def test_an_interval_the_feed_lacks_is_refused_by_name_not_approximated() -> None:
    provider, transport = _provider()

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), timeframe=Timeframe.TICK))

    message = str(raised.value)
    assert "tick" in message
    assert "1m" in message, "the refusal did not say what is supported"
    assert transport.requested == [], "a refused request was still sent"


@pytest.mark.parametrize(
    ("timeframe", "interval_text", "stamp"),
    [
        (Timeframe.M1, "1m", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.M5, "5m", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.M15, "15m", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.M30, "30m", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.H1, "1h", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.H4, "4h", _stamp(2026, 8, 3, 10, 0)),
        (Timeframe.D1, "1d", _stamp(2026, 8, 3)),
        (Timeframe.W1, "1wk", _stamp(2026, 8, 3)),
        (Timeframe.MN1, "1mo", _stamp(2026, 6, 1)),
    ],
)
async def test_every_supported_timeframe_asks_for_the_interval_that_was_probed(
    timeframe: Timeframe, interval_text: str, stamp: int
) -> None:
    """Each mapping below was checked live: the feed answered with
    ``dataGranularity`` equal to what was asked, ``4h`` included. The
    query carries the same spelling, so a future drift between the
    mapping and the wire is caught here rather than as bars of the
    wrong length.
    """
    provider, transport = _provider(
        (200, _payload([stamp], granularity=interval_text)),
    )

    bars = await provider.fetch_bars(
        _request(start=stamp - 86_400, end=stamp + 86_400, timeframe=timeframe)
    )

    assert len(bars) == 1, f"the {interval_text} bar did not survive the mapping"
    query = parse_qs(urlparse(transport.requested[0]).query)
    assert query["interval"] == [interval_text]


async def test_bars_served_at_a_different_interval_are_refused() -> None:
    """The check behind the mapping: a right symbol and plausible
    prices at the wrong timeframe must not pass as the asked-for one —
    nothing downstream could tell.
    """
    provider, _ = _provider((200, _payload([_stamp(2026, 8, 3)], granularity="1wk")))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "'1wk'" in message and "'1d'" in message


async def test_a_limit_returns_the_first_bars_after_the_start() -> None:
    stamps: list[object] = [_stamp(2026, 8, day) for day in (1, 2, 3, 4, 5)]
    provider, _ = _provider((200, _payload(stamps)))

    bars = await provider.fetch_bars(
        _request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31), limit=3)
    )

    assert [bar.timestamp.day for bar in bars] == [1, 2, 3]
    assert len(bars) == 3


async def test_the_request_for_this_provider_carries_no_credential() -> None:
    """The structural claim in the module docstring, made testable.

    There is no key to leak because none is ever attached — a property
    of the request itself, not of how carefully someone wrote a log
    statement.
    """
    provider, transport = _provider((200, _payload([_stamp(2026, 8, 3)])))

    await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert transport.requested, "nothing was requested"
    for url in transport.requested:
        lowered = url.lower()
        for forbidden in ("key=", "secret", "token", "sign=", "auth"):
            assert forbidden not in lowered, f"{forbidden!r} appeared in {url}"


async def test_a_window_entirely_in_the_future_is_answered_empty_without_a_request() -> None:
    """There is nothing to fetch and nothing to claim.

    Sending period1 after period2 would ask the feed to invent an
    answer for time it does not have.
    """
    provider, transport = _provider()

    bars = await provider.fetch_bars(_request(start=_stamp(2027, 1, 1), end=_stamp(2027, 2, 1)))

    assert bars == []
    assert transport.requested == [], "a future window was fetched anyway"


# -- paging over a long intraday range -------------------------------------


async def test_intraday_windows_are_paged_forward_and_boundary_repeats_are_dropped() -> None:
    """Minute-level history arrives six days at a time, forward.

    The first window ends on the boundary bar; the second window's
    period deliberately overlaps it, because whether the endpoints are
    inclusive is the feed's business. The repeat is this adapter's own
    paging artefact and is dropped — while a duplicate *within* a page
    is the provider's doing and is left for validation to count.
    """
    transport = _ScriptedTransport(
        (200, _payload([_stamp(2026, 8, 3), _stamp(2026, 8, 9)], granularity="1m")),
        (200, _payload([_stamp(2026, 8, 9), _stamp(2026, 8, 12)], granularity="1m")),
        (200, _payload([_stamp(2026, 8, 15)], granularity="1m")),
    )
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(
        _request(start=_stamp(2026, 8, 3), end=_stamp(2026, 8, 18), timeframe=Timeframe.M1)
    )

    assert [bar.timestamp for bar in bars] == [
        datetime(2026, 8, 3, tzinfo=UTC),
        datetime(2026, 8, 9, tzinfo=UTC),
        datetime(2026, 8, 12, tzinfo=UTC),
        datetime(2026, 8, 15, tzinfo=UTC),
    ]
    assert len(transport.requested) == 3, "a window was not followed"
    periods = [parse_qs(urlparse(url).query)["period1"] for url in transport.requested]
    assert int(periods[1][0]) > int(periods[0][0]), "paging did not advance"
    assert int(periods[2][0]) > int(periods[1][0]), "paging did not advance"


async def test_a_window_with_no_trading_does_not_end_the_range() -> None:
    """A holiday week is an answer, not the end of the history.

    Stopping at the first empty window would truncate the range at the
    first closed market — exactly how a series silently becomes a
    different series.
    """
    transport = _ScriptedTransport(
        (200, _payload([], granularity="1m")),
        (
            200,
            _payload(
                [_stamp(2026, 8, 9), _stamp(2026, 8, 10), _stamp(2026, 8, 11)], granularity="1m"
            ),
        ),
    )
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(
        _request(start=_stamp(2026, 8, 3), end=_stamp(2026, 8, 15), timeframe=Timeframe.M1)
    )

    assert len(transport.requested) == 2, "the empty window stopped the paging"
    assert [bar.timestamp.day for bar in bars] == [9, 10, 11]


async def test_a_range_that_cannot_be_finished_is_refused_not_answered_short() -> None:
    """Fifty windows in, the honest answer is "I cannot", not "here is some".

    A short answer that looked complete would be indistinguishable
    from a complete one downstream — the failure ``PartialData``
    exists to prevent, reached without anyone admitting anything.
    """
    transport = _EndlessEmptyTransport()
    provider = YahooProvider(transport, now=_now)
    request = _request(
        start=_stamp(2020, 1, 1),
        end=_stamp(2026, 1, 1),
        timeframe=Timeframe.M1,
    )

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(request)

    assert "narrow the range" in str(raised.value)
    assert transport.calls == 50, "the guard did not trip where it says it does"


# -- short series must not look complete -----------------------------------


async def test_a_series_beginning_long_after_the_window_is_a_shortfall_not_an_answer() -> None:
    """The observed silent clip: 400 days asked, ~90 served, HTTP 200.

    ``firstTradeDate`` says the symbol traded the whole time, the gap
    dominates the window, and no weekend is 200 days long — so the
    honest report is ``PartialData`` with both counts, not bars that
    quietly begin where the feed's retention happens to.
    """
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, day) for day in range(3, 13)])),
    )
    request = _request(start=_stamp(2026, 1, 1), end=_stamp(2026, 9, 1))

    with pytest.raises(PartialData) as raised:
        await provider.fetch_bars(request)

    error = raised.value
    assert isinstance(error.requested, int) and isinstance(error.received, int)
    assert error.received < error.requested, "the shortfall claimed no shortfall"
    assert SYMBOL in str(error)
    assert "days of the" in str(error)


async def test_a_window_opening_before_the_symbol_traded_is_not_a_shortfall() -> None:
    """The feed cannot serve what there was no market for.

    ``firstTradeDate`` inside the window moves the measuring point, so
    a symbol's own beginning is never mistaken for clipped history.
    """
    provider, _ = _provider(
        (
            200,
            _payload(
                [_stamp(2026, 8, day) for day in range(10, 13)], first_traded=_stamp(2026, 8, 10)
            ),
        ),
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 1, 1), end=_stamp(2026, 9, 1)))

    assert len(bars) == 3, "a legitimate beginning was refused"


async def test_a_head_gap_of_weekends_and_holidays_is_not_a_shortfall() -> None:
    """Markets are closed sometimes; that is absence, not a clipped feed.

    Seven days of grace covers a long weekend and the holidays around
    it, so the ordinary shape of an equity calendar never trips the
    shortfall check.
    """
    provider, _ = _provider((200, _payload([_stamp(2026, 8, day) for day in (5, 6, 7)])))

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert len(bars) == 3, "an ordinary market holiday was reported as a shortfall"


async def test_a_suspension_short_relative_to_the_window_is_left_for_validation() -> None:
    """A hole inside a long window is validation's finding, not a different dataset.

    The check guards the *head* of the series against a feed that no
    longer holds an era; a month-long gap in a long window arrives
    with the rest of the history and is counted by the timestamp rules,
    where the evidence is.
    """
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 2, 1), _stamp(2026, 2, 2)])),
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 1, 1), end=_stamp(2026, 9, 1)))

    assert len(bars) == 2, "a head gap under a quarter of the window was refused"


# -- order is the provider's business, not the adapter's -------------------


async def test_a_page_sent_backwards_is_not_sorted_by_the_adapter() -> None:
    """Reordering would be repairing, and the report would not describe it.

    Validation's out-of-order check can only ever fire if the adapter
    leaves the provider's order alone, which is exactly why it must.
    """
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, 5), _stamp(2026, 8, 4), _stamp(2026, 8, 3)])),
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert [bar.timestamp.day for bar in bars] == [5, 4, 3], "the adapter sorted them"

    report = validate_bars(bars, timeframe=Timeframe.D1)
    assert report.status.value == "invalid"
    assert any("not strictly increasing" in reason for reason in report.reasons)


async def test_a_duplicate_within_one_page_is_left_for_validation_to_count() -> None:
    provider, _ = _provider(
        (200, _payload([_stamp(2026, 8, 3), _stamp(2026, 8, 3), _stamp(2026, 8, 4)]))
    )

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert len(bars) == 3, "the provider's own duplicate was hidden"

    report = validate_bars(bars, timeframe=Timeframe.D1)
    assert report.duplicates_removed == 1, "the provider's own duplicate was hidden"
    assert report.received == 3


# -- typed failures ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, RateLimited),
        (403, AuthenticationFailed),
        (401, AuthenticationFailed),
        (503, ProviderUnavailable),
        (404, UnsupportedRange),
        (422, UnsupportedRange),
        (400, UnsupportedRange),
        (418, UnsupportedRange),
    ],
)
async def test_an_http_status_is_interpreted_by_the_adapter_not_the_transport(
    status: int, expected: type[MarketDataError]
) -> None:
    provider, _ = _provider((status, ""))

    with pytest.raises(expected):
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))


async def test_a_404_says_the_symbol_is_unknown_because_that_was_the_observed_answer() -> None:
    """The first observed status mapping, not a convention.

    An unknown symbol answered 404 with an **empty** body while this
    adapter was written: there is no error document to read, so the
    refusal must name the symbol itself rather than quote a message
    that does not exist. A later 404 *with* a body — a burst flipping
    known symbols — is covered separately below.
    """
    provider, _ = _provider((404, ""))

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "does not know that symbol" in message
    assert SYMBOL in message


async def test_a_404_that_carries_a_body_quotes_the_providers_own_words() -> None:
    """The *second* observed 404 flavor, and why the first is not reused.

    A burst of requests flipped symbols that had served seconds earlier
    to 404 — this time with a JSON error document rather than an empty
    body — and the same symbols answered 200 again after about thirty
    seconds. "Does not know that symbol" would contradict a provider
    that said something else, so the description is quoted, with the
    symbol still named.
    """
    body = json.dumps(
        {
            "chart": {
                "result": None,
                "error": {
                    "code": "Not Found",
                    "description": "No data found, symbol may be delisted",
                },
            }
        }
    )
    provider, _ = _provider((404, body))

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "No data found, symbol may be delisted" in message, "the provider's words were dropped"
    assert SYMBOL in message
    assert "does not know that symbol" not in message, "a claim the body contradicts"


async def test_a_refusal_that_carries_a_body_is_quoted_not_summarised() -> None:
    """Same rule for 422: the observed shape was an empty body, but a
    body that arrives gets quoted rather than paraphrased into a
    summary the provider did not give.
    """
    body = json.dumps(
        {
            "chart": {
                "result": None,
                "error": {"code": "RangeError", "description": "Requested range not served"},
            }
        }
    )
    provider, _ = _provider((422, body))

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "Requested range not served" in message
    assert "422" in message


async def test_a_rate_limit_that_said_nothing_about_waiting_admits_it() -> None:
    provider, _ = _provider((429, ""))

    with pytest.raises(RateLimited) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert raised.value.retry_after is None, "a wait time was invented"


async def test_a_body_that_is_not_json_is_a_payload_failure_not_a_crash() -> None:
    provider, _ = _provider((200, "<html>maintenance</html>"))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "not JSON" in message
    assert "<html>" not in message, "the body was echoed into a log message"


async def test_json_that_is_not_an_envelope_is_a_payload_failure() -> None:
    provider, _ = _provider((200, "[1, 2, 3]"))

    with pytest.raises(InvalidProviderPayload, match="not an object"):
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    provider, _ = _provider((200, '{"foo": 1}'))

    with pytest.raises(InvalidProviderPayload, match="no 'chart' object"):
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))


async def test_a_response_with_no_result_is_a_payload_failure() -> None:
    for body in (
        json.dumps({"chart": {"result": [], "error": None}}),
        json.dumps({"chart": {"result": None, "error": None}}),
    ):
        provider, _ = _provider((200, body))
        with pytest.raises(InvalidProviderPayload, match="no result"):
            await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))


async def test_an_error_object_inside_a_200_keeps_the_providers_own_words() -> None:
    """Defensive: not observed live, but handled so a feed that starts
    using this shape fails loudly instead of as a missing result.
    """
    not_found = json.dumps(
        {
            "chart": {
                "result": None,
                "error": {
                    "code": "Not Found",
                    "description": "No data found, symbol may be delisted",
                },
            }
        }
    )
    provider, _ = _provider((200, not_found))
    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))
    assert SYMBOL in str(raised.value)

    unexpected = json.dumps(
        {"chart": {"result": None, "error": {"code": "Bad", "description": "Something odd"}}}
    )
    provider, _ = _provider((200, unexpected))
    with pytest.raises(MarketDataError) as raised_other:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))
    assert type(raised_other.value) is MarketDataError, "an unmapped error was categorised"
    assert "Something odd" in str(raised_other.value)


async def test_a_quote_series_that_does_not_match_its_timestamps_is_refused() -> None:
    """Lined up wrong, a shorter close array would put prices at the
    wrong moments — the quiet misreading a shape check exists to stop.
    """
    body = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"dataGranularity": "1d", "firstTradeDate": FIRST_TRADED},
                        "timestamp": [_stamp(2026, 8, 3), _stamp(2026, 8, 4)],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0],
                                    "high": [101.0],
                                    "low": [99.0],
                                    "close": [100.5],
                                    "volume": [10.0],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    )
    provider, _ = _provider((200, body))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert "1 open entries; expected 2" in str(raised.value)


async def test_a_timestamp_that_is_not_a_number_is_a_payload_failure() -> None:
    provider, _ = _provider((200, _payload(["oops"])))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    message = str(raised.value)
    assert "not a number" in message
    assert "oops" not in message, "the timestamp was echoed into a log message"


async def test_a_result_without_timestamps_is_an_empty_window_not_an_error() -> None:
    """The feed's shape for "nothing traded in this bounds".

    Distinct from an error: no bars arrived because none existed, and
    the caller reports an empty window as an empty window.
    """
    provider, _ = _provider((200, _payload([], with_timestamp=False)))

    bars = await provider.fetch_bars(_request(start=_stamp(2026, 8, 1), end=_stamp(2026, 8, 31)))

    assert bars == []


# -- the month-sized interval ----------------------------------------------


async def test_a_monthly_bar_is_admitted_only_after_thirty_one_days() -> None:
    """A month is not a fixed length, so completion is conservative.

    The rule waits out the longest possible month: the current month's
    bar can only be admitted late — never while it could still change.
    """
    provider, transport = _provider(
        (200, _payload([_stamp(2026, 8, 1), _stamp(2026, 9, 1)], granularity="1mo")),
    )

    bars = await provider.fetch_bars(
        _request(start=_stamp(2026, 8, 1), end=NOW, timeframe=Timeframe.MN1)
    )

    assert [bar.timestamp.month for bar in bars] == [8], "the current month's bar was stored"
    query = parse_qs(urlparse(transport.requested[0]).query)
    assert query["interval"] == ["1mo"]


# -- the rest of the protocol -----------------------------------------------


async def test_latest_bars_asks_for_one_bounded_window_back_from_now() -> None:
    provider, transport = _provider(
        (
            200,
            _payload(
                [
                    int((NOW - timedelta(minutes=2)).timestamp()),
                    int((NOW - timedelta(minutes=1)).timestamp()),
                ],
                granularity="1m",
            ),
        )
    )

    bars = await provider.latest_bars(SYMBOL, Timeframe.M1)

    assert len(bars) == 2
    query = parse_qs(urlparse(transport.requested[0]).query)
    assert query["interval"] == ["1m"]
    expected_start = int((NOW - timedelta(minutes=401)).timestamp())
    assert int(query["period1"][0]) == expected_start


def test_the_provider_satisfies_the_historical_protocol_only() -> None:
    """Both halves of the claim in the module docstring.

    It *is* a ``HistoricalDataProvider``. It is deliberately *not* a
    ``MarketDataProvider``: no ``symbols`` exists, because a keyless
    feed offers no honest way to enumerate its universe and inventing
    one would be guessing. The type system enforces what the docstring
    promises.
    """
    provider = YahooProvider(_ScriptedTransport(), now=_now)

    assert isinstance(provider, HistoricalDataProvider)
    assert not isinstance(provider, MarketDataProvider)


def test_the_documented_error_claims_cover_every_failure_and_agree() -> None:
    """The ``RAISED``/``NOT_RAISED`` lists are claims; this is the check.

    Together they must account for every failure the package declares,
    with nothing claimed by both. The structural difference from the
    Kraken adapter is asserted too: ``PartialData`` is raised *here*
    because this feed was observed silently clipping a long window,
    and never raised *there* because its feed answers a cursor.
    """
    every_failure = {
        AuthenticationFailed,
        InvalidProviderPayload,
        MarketDataError,
        PartialData,
        ProviderUnavailable,
        RateLimited,
        UnsupportedRange,
    }

    assert set(RAISED_ERRORS) | set(NOT_RAISED_ERRORS) == every_failure
    assert set(RAISED_ERRORS).isdisjoint(NOT_RAISED_ERRORS)
    assert all(reason.strip() for reason in NOT_RAISED_ERRORS.values())
    assert PartialData in RAISED_ERRORS, "the observed silent clip would go unreported"
