# packages/data — Data access libraries (Phase 3)

Provider-independent interfaces and adapters for market data, historical data,
corporate events, news, fundamentals and options.

**Status: not implemented.** Phase 0 defined the contracts the adapters must
satisfy:

- `harsh_quant_os.contracts.provenance.DatasetProvenance`
- `DataQualityStatus` and `Timeframe` enums
- TypeScript mirrors with a parity test

Planned shape:

```text
packages/data/
├── interfaces/        # MarketDataProvider, HistoricalDataProvider, ...
├── adapters/          # one directory per provider
├── validation/        # schema, ordering, gaps, duplicates, outliers
└── manifest/          # dataset index and versions
```

Rules: domain code never imports a vendor SDK; every dataset carries full
provenance; missing data is reported as missing, never invented.

See [docs/architecture/data-platform.md](../../docs/architecture/data-platform.md).
