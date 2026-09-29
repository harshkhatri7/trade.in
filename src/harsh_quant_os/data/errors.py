"""Typed failures a market-data provider can produce.

Each has its own class because the handling differs, and an adapter must
never be forced to parse a message to find out what happened:

* :class:`RateLimited` is transient and says how long to wait.
* :class:`AuthenticationFailed` is permanent until credentials change;
  retrying it blindly burns the remaining quota.
* :class:`PartialData` means the provider answered with *less* than was
  asked for. The caller decides whether the shortfall is acceptable,
  because silently returning a shorter series is exactly how a backtest
  quietly becomes a different backtest.
* :class:`UnsupportedRange` means the request itself cannot be served.
* :class:`ProviderUnavailable` is a transport failure - nothing was
  received, so nothing was wrong with the data.
* :class:`InvalidProviderPayload` means the payload failed schema checks
  and must be quarantined rather than coerced into shape.

**Messages never carry credentials, connection strings or signed query
parameters.** These exceptions travel into logs and CLI output; an adapter
is responsible for that at the point where it formats the message, and the
rule is stated here so there is one place to look for it.
"""

from __future__ import annotations

from datetime import timedelta

__all__ = [
    "AuthenticationFailed",
    "InvalidProviderPayload",
    "MarketDataError",
    "PartialData",
    "ProviderUnavailable",
    "RateLimited",
    "UnsupportedRange",
]


class MarketDataError(Exception):
    """Base class for every provider failure."""


class RateLimited(MarketDataError):
    """The provider asked us to slow down.

    ``retry_after`` is ``None`` when the provider did not say how long -
    which is not the same as "immediately".
    """

    def __init__(self, message: str, *, retry_after: timedelta | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AuthenticationFailed(MarketDataError):
    """Credentials were rejected. Retrying will not help."""


class PartialData(MarketDataError):
    """Less arrived than was requested.

    Both numbers are kept so a caller can log *how* short the answer was
    without having to reconstruct it from the series.
    """

    def __init__(self, message: str, *, requested: int, received: int) -> None:
        super().__init__(message)
        self.requested = requested
        self.received = received


class UnsupportedRange(MarketDataError):
    """The requested range, symbol or timeframe cannot be served."""


class ProviderUnavailable(MarketDataError):
    """The provider could not be reached: a transport failure, not bad data."""


class InvalidProviderPayload(MarketDataError):
    """The payload failed schema validation and must be quarantined."""
