"""Provider-independent interfaces for market data.

The rules these types enforce, and why:

1. **No vendor type crosses the boundary.** An adapter converts whatever
   its provider sent into :class:`Bar` *before* returning. Everything
   downstream - validation, storage, research - sees only these types, so
   replacing a provider cannot change a single line of domain code.

2. **Prices are ``Decimal``, not ``float``.** What gets stored must be
   what the provider sent. A ``float`` rounds on the way in, before anyone
   has decided that rounding is acceptable, and a rounded price then
   propagates into every statistic computed from it. Converting to
   ``float`` for numerical work belongs to the quant layer, where it is a
   deliberate, visible step.

3. **A missing value stays missing.** ``volume`` is ``None`` when the
   provider did not report one. It is never ``0`` - a zero is a claim
   that nothing traded, and that claim would be invented.

4. **OHLC consistency is checked at the boundary.** A bar whose high sits
   below its own close is a broken payload, not a data point. Catching it
   here means the failure names the bar instead of surfacing as a
   nonsensical return three stages later.

5. **Prices are not required to be positive.** It would be easy and wrong
   to add ``> 0``: futures have settled below zero. Validity is decided by
   the OHLC relationships, not by a sign.

Timestamps are timezone-aware and interpreted as UTC; a naive timestamp
is rejected rather than assumed to be local time, because assuming is how
two machines disagree about which bar came first.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harsh_quant_os.contracts.provenance import Timeframe

__all__ = [
    "Bar",
    "BarRequest",
    "HistoricalDataProvider",
    "MarketDataProvider",
]


class Bar(BaseModel):
    """One OHLCV bar in provider-neutral form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, description="Provider-neutral instrument identifier.")
    timeframe: Timeframe
    #: The bar's **open** time. Timezone required, UTC stored.
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    #: ``None`` means the provider reported no volume. Never defaulted to 0.
    volume: Decimal | None = None

    @field_validator("timestamp")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone aware; naive values are rejected")
        return value

    @field_validator("volume")
    @classmethod
    def _reject_negative_volume(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError(f"volume cannot be negative, got {value}")
        return value

    @model_validator(mode="after")
    def _check_ohlc(self) -> Bar:
        """The four prices must describe one bar, not four unrelated ones."""
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(
                f"high {self.high} is below open {self.open}, close {self.close} "
                f"or low {self.low} for {self.symbol} at {self.timestamp.isoformat()}"
            )
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(
                f"low {self.low} is above open {self.open}, close {self.close} "
                f"or high {self.high} for {self.symbol} at {self.timestamp.isoformat()}"
            )
        return self


class BarRequest(BaseModel):
    """A request for bar history, expressed without any provider vocabulary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: Timeframe
    start: datetime
    end: datetime | None = Field(default=None, description="Inclusive upper bound, when known.")
    limit: int | None = Field(default=None, ge=1, description="Maximum bars, when bounded.")

    @field_validator("start", "end")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("request bounds must be timezone aware; naive values are rejected")
        return value

    @model_validator(mode="after")
    def _check_range(self) -> BarRequest:
        if self.end is not None and self.end < self.start:
            raise ValueError(f"end {self.end.isoformat()} precedes start {self.start.isoformat()}")
        return self


@runtime_checkable
class HistoricalDataProvider(Protocol):
    """Bar history for a symbol, timeframe and range.

    Implementations raise the typed errors in
    :mod:`harsh_quant_os.data.errors`. Returning a shorter series than was
    asked for without raising :class:`~harsh_quant_os.data.errors.PartialData`
    is not permitted: a truncated answer and a complete answer look
    identical to the caller otherwise, and they are not the same data.
    """

    async def fetch_bars(self, request: BarRequest) -> Sequence[Bar]:
        """Return the bars matching ``request``, or raise a typed error."""
        ...


@runtime_checkable
class MarketDataProvider(Protocol):
    """Current bars and the symbol universe, for live-ish views."""

    async def latest_bars(self, symbol: str, timeframe: Timeframe) -> Sequence[Bar]:
        """Return the most recent bars for ``symbol``, newest last."""
        ...

    async def symbols(self) -> Sequence[str]:
        """Return the provider's tradable symbols, provider-neutral."""
        ...
