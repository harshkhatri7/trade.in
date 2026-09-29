"""The provider-neutral market-data interface, asserted rather than assumed.

Four properties are worth testing because each is easy to lose:

* a bar that cannot describe one bar is refused at the boundary;
* a missing volume stays missing instead of becoming a zero;
* prices are exact and survive a serialisation round trip unchanged;
* no module in the platform imports a vendor SDK, which is what
  "provider-independent" has to mean in order to be worth saying.

Nothing here touches the network. The provider doubles are local objects;
the interface is what is under test, not any particular provider.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts.provenance import Timeframe
from harsh_quant_os.data import (
    AuthenticationFailed,
    Bar,
    BarRequest,
    HistoricalDataProvider,
    InvalidProviderPayload,
    MarketDataError,
    PartialData,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Vendor SDKs that must never appear in domain code. Adapters live behind
#: the interface, so an import of one of these anywhere in ``src/`` means
#: the boundary has been crossed. data-platform.md principle 1.
VENDOR_SDK_ROOTS = {
    "yfinance",
    "alpha_vantage",
    "pandas_datareader",
    "ccxt",
    "alpaca",
    "ib_insync",
    "robin_stocks",
    "bloomberg",
    "polygon",
    "tiingo",
    "twelvedata",
}


def _bar(
    *,
    open_price: Decimal = Decimal("100.00"),
    high: Decimal = Decimal("101.50"),
    low: Decimal = Decimal("99.25"),
    close: Decimal = Decimal("100.75"),
    volume: Decimal | None = Decimal("123456"),
    timestamp: datetime | None = None,
) -> Bar:
    return Bar(
        symbol="TEST.NEUTRAL",
        timeframe=Timeframe.D1,
        timestamp=timestamp if timestamp is not None else datetime(2026, 1, 2, tzinfo=UTC),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class _FakeHistoricalProvider:
    """A local double: returns exactly what it was handed."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars
        self.requests: list[BarRequest] = []

    async def fetch_bars(self, request: BarRequest) -> list[Bar]:
        self.requests.append(request)
        return list(self._bars)


def test_a_bar_is_frozen_so_provenance_cannot_be_rewritten_after_the_fact() -> None:
    bar = _bar()

    with pytest.raises(ValidationError, match="frozen"):
        bar.close = Decimal("999.00")  # type: ignore[misc]

    assert bar.close == Decimal("100.75"), "the assignment was not refused"


def test_a_bar_refuses_fields_that_are_not_part_of_the_contract() -> None:
    """A provider's extra field must not ride along into storage."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Bar(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.D1,
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            provider_name="someone",  # type: ignore[call-arg]
        )


def test_a_naive_bar_timestamp_is_rejected_rather_than_assumed_to_be_local() -> None:
    with pytest.raises(ValidationError, match="timezone aware"):
        _bar(timestamp=datetime(2026, 1, 2))


def test_a_bar_whose_high_sits_below_its_own_close_is_refused() -> None:
    """Caught here, where the message can still name the bar."""
    with pytest.raises(ValidationError, match="high"):
        _bar(high=Decimal("99.00"), low=Decimal("98.00"), close=Decimal("100.75"))


def test_a_bar_whose_low_sits_above_its_own_open_is_refused() -> None:
    with pytest.raises(ValidationError, match="low"):
        _bar(high=Decimal("101.50"), low=Decimal("101.00"), open_price=Decimal("100.00"))


def test_negative_prices_are_allowed_because_futures_have_settled_below_zero() -> None:
    """The absence of a positivity rule is deliberate; this pins it."""
    bar = _bar(
        open_price=Decimal("-10.00"),
        high=Decimal("-5.00"),
        low=Decimal("-30.00"),
        close=Decimal("-20.00"),
        volume=Decimal("10"),
    )

    assert bar.close == Decimal("-20.00")


def test_a_bar_without_reported_volume_keeps_none_instead_of_inventing_a_zero() -> None:
    """Zero would claim nothing traded. The provider said nothing at all."""
    assert _bar(volume=None).volume is None
    assert _bar(volume=None).volume != 0


def test_negative_volume_is_refused() -> None:
    with pytest.raises(ValidationError, match="volume cannot be negative"):
        _bar(volume=Decimal("-1"))


def test_a_price_survives_a_serialisation_round_trip_unchanged() -> None:
    """The value stored must be the value the provider sent, exactly.

    The high and low are widened to contain the close because the OHLC
    check would otherwise refuse the bar - which is the correct behaviour,
    and not what this test is here to examine.
    """
    original = _bar(
        high=Decimal("130.00"),
        low=Decimal("90.00"),
        close=Decimal("123.456789012345"),
    )

    restored = Bar.model_validate_json(original.model_dump_json())

    assert restored.close == original.close == Decimal("123.456789012345")


def test_a_request_with_end_before_start_is_refused() -> None:
    with pytest.raises(ValidationError, match="precedes start"):
        BarRequest(
            symbol="TEST.NEUTRAL",
            timeframe=Timeframe.D1,
            start=datetime(2026, 2, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_a_naive_request_bound_is_refused() -> None:
    with pytest.raises(ValidationError, match="timezone aware"):
        BarRequest(symbol="TEST.NEUTRAL", timeframe=Timeframe.D1, start=datetime(2026, 1, 1))


def test_an_unbounded_request_is_valid_so_recent_history_can_be_asked_for() -> None:
    request = BarRequest(
        symbol="TEST.NEUTRAL", timeframe=Timeframe.M15, start=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert request.end is None
    assert request.limit is None


def test_every_provider_failure_is_catchable_through_one_base_class() -> None:
    failures: list[MarketDataError] = [
        AuthenticationFailed("credentials rejected"),
        InvalidProviderPayload("row 12 has no close"),
        PartialData("short", requested=100, received=40),
        ProviderUnavailable("connection refused"),
        RateLimited("slow down", retry_after=timedelta(seconds=30)),
        UnsupportedRange("1m before 2010 is not offered"),
    ]

    for failure in failures:
        assert isinstance(failure, MarketDataError)
        assert isinstance(failure, Exception)


def test_partial_data_carries_both_counts_so_the_shortfall_can_be_logged() -> None:
    error = PartialData("short", requested=100, received=40)

    assert (error.requested, error.received) == (100, 40)


def test_a_rate_limit_that_did_not_say_how_long_reports_none_rather_than_zero() -> None:
    assert RateLimited("slow down").retry_after is None
    assert RateLimited("slow down", retry_after=timedelta(seconds=5)).retry_after == timedelta(
        seconds=5
    )


async def test_a_local_double_satisfies_the_historical_provider_protocol() -> None:
    bars = [_bar()]
    provider = _FakeHistoricalProvider(bars)
    request = BarRequest(
        symbol="TEST.NEUTRAL", timeframe=Timeframe.D1, start=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert isinstance(provider, HistoricalDataProvider)
    assert list(await provider.fetch_bars(request)) == bars
    assert provider.requests == [request], "the double did not record what it was asked"


def test_no_module_in_the_platform_imports_a_vendor_sdk() -> None:
    """data-platform.md principle 1, made executable.

    Provider independence is the sort of rule that erodes one convenient
    import at a time. Parsing every file under ``src/`` turns "domain code
    never imports a vendor SDK" into something a red build can contradict.
    """
    offenders: list[str] = []

    for path in sorted((REPO_ROOT / "src" / "harsh_quant_os").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            for name in imported:
                root = name.split(".")[0].strip()
                if root in VENDOR_SDK_ROOTS:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} imports {name}")

    assert offenders == [], "vendor SDKs crossed the provider boundary:\n" + "\n".join(offenders)
