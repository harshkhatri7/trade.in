"""Provider-independent market data.

This package is the boundary. Adapters convert whatever a provider sent
into :class:`~harsh_quant_os.data.providers.Bar` and raise the typed
errors in :mod:`harsh_quant_os.data.errors`; nothing outside this package
ever sees a vendor type, a vendor error or a vendor's idea of a timeframe.

The design is in ``docs/architecture/data-platform.md``. What is here now
is the interface layer and the validation pipeline. Adapters, ingestion
and storage are not implemented yet, and no document may say otherwise.
"""

from __future__ import annotations

from harsh_quant_os.data.errors import (
    AuthenticationFailed,
    InvalidProviderPayload,
    MarketDataError,
    PartialData,
    ProviderUnavailable,
    RateLimited,
    UnsupportedRange,
)
from harsh_quant_os.data.providers import (
    Bar,
    BarRequest,
    HistoricalDataProvider,
    MarketDataProvider,
)
from harsh_quant_os.data.validation import (
    Gap,
    ValidationReport,
    parse_rows,
    validate_bars,
)

__all__ = [
    "AuthenticationFailed",
    "Bar",
    "BarRequest",
    "Gap",
    "HistoricalDataProvider",
    "InvalidProviderPayload",
    "MarketDataError",
    "MarketDataProvider",
    "PartialData",
    "ProviderUnavailable",
    "RateLimited",
    "UnsupportedRange",
    "ValidationReport",
    "parse_rows",
    "validate_bars",
]
