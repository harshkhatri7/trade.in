# Data platform architecture

**Phase:** 3 — Market-data engine. The provider-independent **interfaces
are implemented and tested**; ingestion, validation runs and the storage
manifest are not, and section 6 says exactly where the line is.

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

## 2. Interfaces

```text
MarketDataProvider        current bars/ticks, symbols, sessions
HistoricalDataProvider    bar history for a symbol + timeframe + range
CorporateActionsProvider  splits, dividends, mergers
NewsProvider              headlines and events with timestamps
FundamentalsProvider      periodic financial statements
OptionsProvider           chains and greeks where available
```

**State:** `MarketDataProvider` and `HistoricalDataProvider` are
implemented as `Protocol`s in `harsh_quant_os.data.providers`, with the
typed failures they raise in `harsh_quant_os.data.errors`
(`RateLimited`, `AuthenticationFailed`, `PartialData`,
`UnsupportedRange`, `ProviderUnavailable`, `InvalidProviderPayload`).
The other four interfaces have **no** implementation and no return model
yet — defining those models before their consumers exist would be a guess
with constraints attached.

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

Validation checks (Phase 3), and for each one what actually exists in
`harsh_quant_os.data.validation`:

| Check            | Failure action                                            | State                          |
| ---------------- | --------------------------------------------------------- | ------------------------------ |
| Schema/typing    | Quarantine the batch; never coerce silently               | `parse_rows`                   |
| Timestamp order  | Reject the batch; record the reason                       | `validate_bars` — rejected, not sorted |
| Gaps             | Record explicit gap intervals in metadata                 | `validate_bars` — recorded, never filled |
| Duplicates       | Drop with a counted, logged report                         | `validate_bars` — first bar at a timestamp wins; a duplicate that *disagreed* with the bar kept is counted separately and makes the batch `suspect` |
| Outliers         | Flag `suspect`; never winsorise silently                  | `validate_bars` — modified z-score, threshold configurable, reported not adjusted |
| Session/calendar | Compare against the instrument's session rules            | **Not implemented** — no exchange calendar exists |
| Cross-check      | Optional second source; disagreement ⇒ `suspect`          | **Not implemented** — no second provider exists |

Two caveats that the report states rather than hides:

- **Outliers are not judged** on a batch shorter than the configured
  minimum, or when every bar has the same range. Both appear in the
  report's `notes`. A series with no variation is not evidence that it has
  no outliers; it is a rule with nothing to measure with.
- **Daily gaps are computed against raw one-day spacing.** Until a session
  calendar exists, weekends and holidays appear as gaps. That is a true
  statement about what arrived, and the report says so instead of
  pretending the calendar was known. Gaps never change a batch's quality
  status by themselves.

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

## 6. Current state (Phase 3, interface layer only)

Implemented and tested:

- `DatasetProvenance` model with validation: timezone required,
  `ingested_at >= timestamp`, `invalid` datasets rejected, closed schema
  (`extra="forbid"`), frozen after creation.
- `DataQualityStatus` and `Timeframe` enums mirrored in TypeScript with a
  parity test.
- **`harsh_quant_os.data`** — the provider-neutral `Bar` and `BarRequest`
  models and the two protocols. `Bar` prices are `Decimal` so the stored
  value is the value the provider sent; OHLC relationships are checked
  where the failure can still name the bar; `volume` is `None` when
  unreported rather than `0`; timestamps must be timezone-aware; the
  schema is closed and frozen. Failures are typed, and a `PartialData`
  carries both the requested and received counts so a short answer cannot
  be mistaken for a complete one.
- **The validation pipeline** (`harsh_quant_os.data.validation`) — five of
  the seven checks in section 3. `parse_rows` quarantines the whole batch
  on the first malformed row and names the field without echoing the
  value; `validate_bars` counts duplicates, records gaps as intervals,
  rejects out-of-order timestamps with a reason instead of sorting them,
  and flags outliers without adjusting them. It never edits a bar, never
  fills a gap and never reorders anything, and tests pin each of those
  absences.
- A test that parses every file under `src/` and fails if any imports a
  vendor SDK — principle 1, made executable rather than aspirational.

Not implemented: adapters, ingestion, storage manifests, the session
calendar and second-source cross-check, and the four interfaces in
section 2 without an implementation.

---

## 7. Phase 3 exit criteria

- Two paths into storage: historical backfill and incremental update.
- Full provenance on every stored dataset.
- Validation report per ingestion run, stored and queryable.
- Gaps reported as gaps; no invented values anywhere.
- A dataset can be re-ingested and produce an identical version.
