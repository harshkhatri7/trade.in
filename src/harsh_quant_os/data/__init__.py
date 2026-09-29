"""Provider-independent market data.

This package is the boundary. Adapters convert whatever a provider sent
into :class:`~harsh_quant_os.data.providers.Bar` and raise the typed
errors in :mod:`harsh_quant_os.data.errors`; nothing outside this package
ever sees a vendor type, a vendor error or a vendor's idea of a timeframe.

The design is in ``docs/architecture/data-platform.md``. What is here now
is the interface layer, the validation pipeline, the local dataset store
with its manifest, **one concrete adapter** (Kraken's public OHLC feed,
keyless by choice — see ``adapters.kraken`` for why), and the job that
ties those together: ``hqos data ingest`` in :mod:`harsh_quant_os.cli`
fetches, validates, writes the artefacts and registers the manifest row
in one command, quarantines the batch when validation refuses it, and
reports a refusal as a refusal rather than as an empty success. Adapters
for other providers, and any scheduled ingestion, are not implemented
here, and no document may say otherwise.
"""

from __future__ import annotations

from harsh_quant_os.data.adapters import KrakenProvider
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
from harsh_quant_os.data.store import (
    QuarantineRecord,
    StoredDataset,
    StoreRefused,
    quarantine_batch,
    read_bars,
    store_batch,
)
from harsh_quant_os.data.transport import HttpTransport, UrllibTransport
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
    "HttpTransport",
    "InvalidProviderPayload",
    "KrakenProvider",
    "MarketDataError",
    "MarketDataProvider",
    "PartialData",
    "ProviderUnavailable",
    "QuarantineRecord",
    "RateLimited",
    "StoreRefused",
    "StoredDataset",
    "UnsupportedRange",
    "UrllibTransport",
    "ValidationReport",
    "parse_rows",
    "quarantine_batch",
    "read_bars",
    "store_batch",
    "validate_bars",
]
