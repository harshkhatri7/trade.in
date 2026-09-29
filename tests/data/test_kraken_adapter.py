"""The one concrete adapter, asserted against the promises it makes.

Nothing here opens a socket. Every response is scripted, so a failure
means a rule moved rather than that a provider changed its mind — and a
request the script did not prepare for raises instead of quietly
answering itself, because an unexpected page answered with an empty body
would otherwise look exactly like an exhausted feed and pass by accident.

The candle values are deliberately obvious non-prices. What is under test
is which field lands where, what happens to a candle that has not closed,
and which typed failure a given answer produces — not any number that
could be mistaken for a price. Field order came from Kraken's own
documentation while the adapter was written; the live endpoint was
probed for its error responses, and those two strings are the ones
asserted here.
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
    KrakenProvider,
    MarketDataError,
    MarketDataProvider,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
    validate_bars,
)
from harsh_quant_os.data.adapters.kraken import NOT_RAISED_ERRORS, RAISED_ERRORS
from harsh_quant_os.data.errors import PartialData

#: The clock the adapter sees. Fixed, so "has this candle closed?" is
#: arithmetic instead of a race against the wall clock.
NOW = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)

SYMBOL = "XBTUSD"
INTERVAL = 60  # one minute, in Kraken's vocabulary


def _now() -> datetime:
    return NOW


def _at(hour: int, minute: int) -> int:
    """Epoch seconds for a time on the fixed day, before ``NOW``."""
    return int(datetime(2026, 3, 2, hour, minute, tzinfo=UTC).timestamp())


def _row(epoch: int) -> list[object]:
    """One candle, in the documented order and with string prices.

    ``[time, open, high, low, close, vwap, volume, count]`` — prices and
    volume as decimal strings, which is how the feed sends them and the
    reason nothing is rounded on the way in.
    """
    return [epoch, "100.00", "101.50", "99.25", "100.75", "100.40", "12.50", 42]


def _ohlc(*rows: list[object]) -> str:
    return json.dumps(
        {"error": [], "result": {"XXBTZUSD": list(rows), "last": rows[0][0] if rows else 0}}
    )


def _errors(*messages: str) -> str:
    return json.dumps({"error": list(messages)})


def _request(
    *,
    start: datetime | int,
    end: datetime | int | None = None,
    timeframe: Timeframe = Timeframe.M1,
    limit: int | None = None,
) -> BarRequest:
    """Build a request, accepting either a datetime or raw epoch seconds.

    ``_at`` deals in epochs because that is what the wire carries, so the
    conversion happens in one place rather than at every call site.
    """

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
    as an exhausted feed and the test would pass for the wrong reason.
    """

    def __init__(self, *responses: tuple[int, str]) -> None:
        self._responses = list(responses)
        self.requested: list[str] = []

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        self.requested.append(url)
        if not self._responses:
            raise AssertionError(f"the adapter made an unscripted request: {url}")
        return self._responses.pop(0)


class _AdvancingTransport:
    """A feed that always has more pages, forever.

    Used to prove that a range the adapter cannot finish is *refused*
    rather than answered with whatever it had managed to collect.
    """

    def __init__(self, origin: int) -> None:
        self._origin = origin
        self.calls = 0

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int, str]:
        first = self._origin + self.calls * 5 * INTERVAL
        self.calls += 1
        return 200, _ohlc(*(_row(first + index * INTERVAL) for index in range(5)))


def _provider(*responses: tuple[int, str]) -> tuple[KrakenProvider, _ScriptedTransport]:
    transport = _ScriptedTransport(*responses)
    return KrakenProvider(transport, now=_now), transport


def _provider_with(transport: HttpTransport) -> KrakenProvider:
    return KrakenProvider(transport, now=_now)


# -- what a candle becomes ------------------------------------------------


async def test_a_candle_becomes_a_bar_with_the_documented_fields_in_order() -> None:
    transport = _ScriptedTransport((200, _ohlc(_row(_at(11, 0)), _row(_at(11, 1)))))
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 1)))

    assert len(bars) == 2
    first = bars[0]
    assert first.open == Decimal("100.00"), "open read from the wrong position"
    assert first.high == Decimal("101.50"), "high read from the wrong position"
    assert first.low == Decimal("99.25"), "low read from the wrong position"
    assert first.close == Decimal("100.75"), "close read from the wrong position"
    assert first.volume == Decimal("12.50")
    assert first.timestamp == datetime(2026, 3, 2, 11, 0, tzinfo=UTC)
    assert first.timeframe is Timeframe.M1


async def test_the_symbol_that_comes_back_is_the_one_that_went_out() -> None:
    """The feed's internal key (``XXBTZUSD``) must never reach a bar.

    A dataset labelled with the provider's private spelling would be
    unfindable by everything that asked for ``XBTUSD``.
    """
    transport = _ScriptedTransport((200, _ohlc(_row(_at(11, 0)))))
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    assert [bar.symbol for bar in bars] == [SYMBOL]
    assert all(bar.symbol != "XXBTZUSD" for bar in bars)
    assert f"pair={SYMBOL}" in transport.requested[0]


async def test_a_candle_that_has_not_closed_is_not_returned() -> None:
    """A bar that has not finished is not data — it is an intention.

    Kraken documents the last candle as the current, not-yet-committed
    timeframe. Storing it would store a bar that could still change.
    """
    provider, _ = _provider((200, _ohlc(_row(_at(11, 0)), _row(int(NOW.timestamp())))))

    bars = await provider.fetch_bars(
        _request(start=_at_start(), end=datetime(2026, 3, 2, 12, 0, tzinfo=UTC))
    )

    assert [bar.timestamp for bar in bars] == [datetime(2026, 3, 2, 11, 0, tzinfo=UTC)]


async def test_a_window_that_ended_in_the_past_keeps_every_finished_candle() -> None:
    """Completion is arithmetic, not "it happened to be the last one".

    A series that ends an hour before now would be silently truncated by
    a rule that dropped whichever candle came last.
    """
    provider, _ = _provider((200, _ohlc(_row(_at(10, 0)), _row(_at(10, 1)))))

    bars = await provider.fetch_bars(_request(start=_at(10, 0), end=_at(10, 1)))

    assert [bar.timestamp.minute for bar in bars] == [0, 1], "a finished candle was dropped"


async def test_a_candle_that_breaks_its_own_ohlc_rules_quarantines_the_batch() -> None:
    """One bad row takes the batch, and the message does not quote it."""
    sentinel = "0.731415926"
    broken = [_at(11, 0), "100.00", "90.00", "99.25", "100.75", "100.40", sentinel, 42]
    provider, _ = _provider((200, _ohlc(broken, _row(_at(11, 1)))))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 1)))

    message = str(raised.value)
    assert "candle at 2026-03-02T11:00" in message, "the failing candle was not named"
    assert sentinel not in message, "the payload was echoed into a log message"


# -- what the adapter refuses to do --------------------------------------


async def test_a_page_sent_backwards_is_not_sorted_by_the_adapter() -> None:
    """Reordering would be repairing, and the report would not describe it.

    Validation's out-of-order check can only ever fire if the adapter
    leaves the provider's order alone, which is exactly why it must.
    """
    descending = [
        _row(_at(11, 2)),
        _row(_at(11, 1)),
        _row(_at(11, 0)),
    ]
    provider, _ = _provider((200, _ohlc(*descending)))

    bars = await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 2)))

    assert [bar.timestamp.minute for bar in bars] == [2, 1, 0], "the adapter sorted them"

    report = validate_bars(bars, timeframe=Timeframe.M1)
    assert report.status.value == "invalid"
    assert any("not strictly increasing" in reason for reason in report.reasons)


async def test_an_interval_the_feed_lacks_is_refused_by_name_not_approximated() -> None:
    for timeframe in (Timeframe.TICK, Timeframe.MN1):
        provider, transport = _provider()
        with pytest.raises(UnsupportedRange) as raised:
            await provider.fetch_bars(_request(start=_at_start(), timeframe=timeframe))
        assert timeframe.value in str(raised.value)
        assert "1m" in str(raised.value), "the refusal did not say what is supported"
        assert transport.requested == [], "a refused request was still sent"


async def test_the_pages_are_followed_until_the_range_is_covered() -> None:
    page_one = [_row(_at(10, minute)) for minute in range(5)]
    page_two = [_row(_at(10, minute)) for minute in range(5, 10)]
    transport = _ScriptedTransport((200, _ohlc(*page_one)), (200, _ohlc(*page_two)))
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(_request(start=_at(10, 0), end=_at(10, 9)))

    assert len(bars) == 10, "a page was not followed"
    assert len(transport.requested) == 2
    first = parse_qs(urlparse(transport.requested[0]).query)
    second = parse_qs(urlparse(transport.requested[1]).query)
    assert first["since"] != second["since"], "the second page asked for the first page again"
    assert int(second["since"][0]) > int(first["since"][0]), "pagination did not advance"


async def test_a_repeat_of_an_earlier_page_is_dropped_but_a_duplicate_within_a_page_is_not() -> (
    None
):
    """Two different kinds of repeat, which must not be confused.

    A candle re-sent at a page boundary is this adapter's own doing, so
    counting it would accuse the provider of something it did not do. A
    duplicate inside one page is the provider's own doing, and hiding it
    would make the validation report understate what arrived.
    """
    page_one = [_row(_at(10, 0)), _row(_at(10, 1)), _row(_at(10, 2))]
    page_two = [_row(_at(10, 2)), _row(_at(10, 3)), _row(_at(10, 3))]
    provider, _ = _provider((200, _ohlc(*page_one)), (200, _ohlc(*page_two)))

    bars = await provider.fetch_bars(_request(start=_at(10, 0), end=_at(10, 3)))

    assert [bar.timestamp.minute for bar in bars] == [0, 1, 2, 3, 3]

    report = validate_bars(bars, timeframe=Timeframe.M1)
    assert report.duplicates_removed == 1, "the provider's own duplicate was hidden"
    assert report.received == 5


async def test_a_page_that_makes_no_progress_stops_instead_of_looping() -> None:
    page = [_row(_at(10, 0)), _row(_at(10, 1)), _row(_at(10, 2))]
    transport = _ScriptedTransport((200, _ohlc(*page)), (200, _ohlc(*page)))
    provider = _provider_with(transport)

    bars = await provider.fetch_bars(_request(start=_at(10, 0), end=_at(10, 9)))

    assert len(transport.requested) == 2, "a stalled feed was asked a third time"
    assert len(bars) == 3


async def test_a_range_that_cannot_be_finished_is_refused_not_answered_short() -> None:
    """Fifty pages in, the honest answer is "I cannot", not "here is some".

    A short answer that looked complete would be indistinguishable from a
    complete one downstream — the failure mode ``PartialData`` exists to
    prevent, reached without the provider ever having admitted anything.
    """
    transport = _AdvancingTransport(_at(10, 0))
    # A clock far beyond the range, so that "reached the present" — which
    # is a different rule doing a different job — cannot end the loop
    # early. Only the page guard can, and it must be the one that fires.
    provider = KrakenProvider(transport, now=lambda: datetime(2035, 1, 1, tzinfo=UTC))
    request = _request(
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2030, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(request)

    assert "narrow the range" in str(raised.value)
    assert transport.calls == 50, "the guard did not trip where it says it does"


async def test_a_limit_returns_the_first_bars_after_the_start() -> None:
    rows = [_row(_at(10, minute)) for minute in range(10)]
    provider, _ = _provider((200, _ohlc(*rows)))

    bars = await provider.fetch_bars(_request(start=_at(10, 0), end=_at(10, 9), limit=3))

    assert [bar.timestamp.minute for bar in bars] == [0, 1, 2]
    assert len(bars) == 3


async def test_the_request_for_this_provider_carries_no_credential() -> None:
    """The structural claim in the module docstring, made testable.

    There is no key to leak because none is ever attached — which is a
    property of the request itself, not of how carefully someone wrote a
    log statement.
    """
    transport = _ScriptedTransport((200, _ohlc(_row(_at(11, 0)))))
    provider = _provider_with(transport)

    await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    assert transport.requested, "nothing was requested"
    for url in transport.requested:
        lowered = url.lower()
        for forbidden in ("key=", "secret", "token", "sign=", "auth"):
            assert forbidden not in lowered, f"{forbidden!r} appeared in {url}"


# -- typed failures -------------------------------------------------------


async def test_an_unknown_symbol_is_refused_by_name_rather_than_returning_empty() -> None:
    provider, _ = _provider((200, _errors("EQuery:Unknown asset pair")))

    with pytest.raises(UnsupportedRange) as raised:
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    message = str(raised.value)
    assert "Unknown asset pair" in message, "the provider's own words were dropped"
    assert SYMBOL in message


async def test_an_invalid_arguments_response_is_refused_too() -> None:
    provider, _ = _provider((200, _errors("EGeneral:Invalid arguments")))

    with pytest.raises(UnsupportedRange):
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))


async def test_a_provider_error_nobody_mapped_keeps_the_providers_own_words() -> None:
    """Two mappings are observed facts; the rest are not guesses either.

    An unmapped error goes out through the base class carrying exactly
    what the provider said, rather than being filed under a category
    that was inferred from the shape of a string.
    """
    provider, _ = _provider((200, _errors("ESomething:Not anticipated")))

    with pytest.raises(MarketDataError) as raised:
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    assert type(raised.value) is MarketDataError, "an unmapped error was categorised"
    assert "ESomething:Not anticipated" in str(raised.value)
    assert not isinstance(raised.value, (UnsupportedRange, RateLimited, ProviderUnavailable))


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, RateLimited),
        (403, AuthenticationFailed),
        (401, AuthenticationFailed),
        (503, ProviderUnavailable),
        (404, UnsupportedRange),
    ],
)
async def test_an_http_status_is_interpreted_by_the_adapter_not_the_transport(
    status: int, expected: type[MarketDataError]
) -> None:
    provider, _ = _provider((status, ""))

    with pytest.raises(expected):
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))


async def test_a_rate_limit_that_said_nothing_about_waiting_admits_it() -> None:
    provider, _ = _provider((429, ""))

    with pytest.raises(RateLimited) as raised:
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    assert raised.value.retry_after is None, "a wait time was invented"


async def test_a_body_that_is_not_json_is_a_payload_failure_not_a_crash() -> None:
    provider, _ = _provider((200, "<html>maintenance</html>"))

    with pytest.raises(InvalidProviderPayload) as raised:
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))

    message = str(raised.value)
    assert "not JSON" in message
    assert "<html>" not in message, "the body was echoed into a log message"


async def test_a_response_with_no_candle_array_is_a_payload_failure() -> None:
    provider, _ = _provider((200, json.dumps({"error": [], "result": {"last": 1}})))

    with pytest.raises(InvalidProviderPayload, match="no candles"):
        await provider.fetch_bars(_request(start=_at_start(), end=_at(11, 0)))


# -- the rest of the market-data protocol --------------------------------


async def test_latest_bars_asks_for_one_page_of_history() -> None:
    provider, transport = _provider(
        (
            200,
            _ohlc(
                _row(int((NOW - timedelta(minutes=2)).timestamp())),
                _row(int((NOW - timedelta(minutes=1)).timestamp())),
            ),
        )
    )

    bars = await provider.latest_bars(SYMBOL, Timeframe.M1)

    assert len(bars) == 2
    query = parse_qs(urlparse(transport.requested[0]).query)
    assert query["interval"] == ["1"]
    assert query["pair"] == [SYMBOL]
    # One page back from now, not "everything since the beginning".
    expected_start = int((NOW - timedelta(minutes=720)).timestamp()) - 1
    assert int(query["since"][0]) == expected_start


async def test_symbols_returns_the_providers_own_names_sorted() -> None:
    payload = json.dumps(
        {
            "error": [],
            "result": {
                "XBTUSD": {"altname": "XBTUSD"},
                "ETHUSD": {"altname": "ETHUSD"},
                "AAAXBB": {"altname": "AAAXBB"},
            },
        }
    )
    provider, _ = _provider((200, payload))

    assert await provider.symbols() == ["AAAXBB", "ETHUSD", "XBTUSD"]


async def test_a_symbols_response_with_no_names_is_a_payload_failure() -> None:
    provider, _ = _provider((200, json.dumps({"error": [], "result": {"X": {}}})))

    with pytest.raises(InvalidProviderPayload, match="altname"):
        await provider.symbols()


def test_the_provider_satisfies_both_declared_protocols() -> None:
    provider = KrakenProvider(_ScriptedTransport(), now=_now)

    assert isinstance(provider, HistoricalDataProvider)
    assert isinstance(provider, MarketDataProvider)


def test_the_documented_error_claims_cover_every_failure_and_agree() -> None:
    """The ``RAISED``/``NOT_RAISED`` lists are claims; this is the check.

    Together they must account for every failure the package declares,
    with nothing claimed by both — otherwise the module's promise that a
    reader can know which exceptions to expect would not be worth making.
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
    assert PartialData in NOT_RAISED_ERRORS


def _at_start() -> datetime:
    """The start every ``_at(h, m)`` request in this file begins at."""
    return datetime(2026, 3, 2, 11, 0, tzinfo=UTC)
