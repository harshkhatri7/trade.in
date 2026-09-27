# Data platform architecture

**Phase:** 0 — Foundation. **No ingestion exists yet (Phase 3).** The
provider-independent contracts that ingestion will use are implemented and
tested today.

---

## 1. Principles

1. **Provider independence.** Domain and quant code never import a vendor SDK.
   Adapters implement an interface; the interface is ours.
2. **Provenance on everything.** Every dataset records source, symbol,
   timestamp, ingestion time, timeframe, quality status, lineage and version.
3. **Never fabricate.** Missing data is reported as missing. Gaps are
   recorded as gaps; they are not interpolated, back-filled or guessed.
4. **Quality is a first-class state.** Data is `pending` until validated, and
   `suspect`/`invalid` data cannot be used for research conclusions.
5. **Reproducibility.** A result is only meaningful together with the exact
   dataset version that produced it.

---

## 2. Interfaces (planned)

```text
MarketDataProvider        current bars/ticks, symbols, sessions
HistoricalDataProvider    bar history for a symbol + timeframe + range
CorporateActionsProvider  splits, dividends, mergers
NewsProvider              headlines and events with timestamps
FundamentalsProvider      periodic financial statements
OptionsProvider           chains and greeks where available
```

Each interface:

- takes a **provider-neutral** instrument identifier;
- returns provider-neutral models with the provenance fields attached;
- raises typed errors for rate limits, auth failures, partial data and
  unsupported ranges;
- is implemented by adapters under `packages/data/adapters/`.

Adding a provider means adding an adapter — never editing domain code.

---

## 3. Ingestion pipeline

```text
SOURCE ──► INGEST ──► VALIDATE ──► NORMALISE ──► STORE ──► PUBLISH
              │           │            │           │          │
              │           │            │           │          └─ quality = valid
              │           │            │           └─ raw + normalised + manifest
              │           │            └─ provider labels → Timeframe
              │           └─ schema, ordering, gaps, duplicates, outliers
              └─ recorded ingested_at, source, run id
```

Validation checks (Phase 3):

| Check            | Failure action                                            |
| ---------------- | --------------------------------------------------------- |
| Schema/typing    | Quarantine the batch; never coerce silently               |
| Timestamp order  | Reject the batch; record the reason                       |
| Gaps             | Record explicit gap intervals in metadata                 |
| Duplicates       | Drop with a counted, logged report                         |
| Outliers         | Flag `suspect`; never winsorise silently                  |
| Session/calendar | Compare against the instrument's session rules            |
| Cross-check      | Optional second source; disagreement ⇒ `suspect`          |

---

## 4. Storage layout

```text
data/
├── raw/        immutable ingested artefacts (never edited in place)
├── clean/      normalised, validated datasets
├── features/   derived feature matrices (recipe + input versions recorded)
├── exports/    user-requested extracts
└── cache/      disposable recomputation cache
```

None of these are committed to Git. `data/.gitignore` keeps the directory
skeleton while excluding contents. The manifest (which lives in PostgreSQL in
Phase 2) maps logical dataset names to physical files and versions.

---

## 5. Timeframes

Provider labels are normalised into the `Timeframe` enum implemented in
`harsh_quant_os.contracts.provenance`:

`tick`, `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, `1mo`.

Timestamps are timezone-aware; storage is UTC; session times are resolved
using the instrument's exchange calendar, never the machine's local clock.

---

## 6. Current state (Phase 0)

Implemented and tested:

- `DatasetProvenance` model with validation: timezone required,
  `ingested_at >= timestamp`, `invalid` datasets rejected, closed schema
  (`extra="forbid"`), frozen after creation.
- `DataQualityStatus` and `Timeframe` enums mirrored in TypeScript with a
  parity test.

Not implemented: providers, adapters, ingestion, validation runs, storage
manifests.

---

## 7. Phase 3 exit criteria

- Two paths into storage: historical backfill and incremental update.
- Full provenance on every stored dataset.
- Validation report per ingestion run, stored and queryable.
- Gaps reported as gaps; no invented values anywhere.
- A dataset can be re-ingested and produce an identical version.
