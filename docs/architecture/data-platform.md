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
| Cross-check      | Optional second source; disagreement ⇒ `suspect`          | **Not implemented** — two providers now exist (Kraken, Yahoo), but each series is still fetched from one source, and cross-provider symbol unification is deliberately absent, so nothing yet has two answers to compare |

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
skeleton while excluding contents. The manifest lives in PostgreSQL — the
`datasets` row for the logical name, plus an append-only
`dataset_provenance` row per acquisition — and maps logical dataset names
to physical files and versions. `raw/`, `clean/` and `quarantine/` are
written by `harsh_quant_os.data.store`; `features/`, `exports/` and
`cache/` are not implemented.

---

## 5. Timeframes

Provider labels are normalised into the `Timeframe` enum implemented in
`harsh_quant_os.contracts.provenance`:

`tick`, `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, `1mo`.

Timestamps are timezone-aware; storage is UTC; session times are resolved
using the instrument's exchange calendar, never the machine's local clock.

---

## 6. Current state (Phase 3 — interfaces, validation, storage, ingestion)

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
- **The local dataset store** (`harsh_quant_os.data.store`) — `raw/`,
  `clean/` and `quarantine/` under `data/`. Directories are
  content-addressed by SHA-256, so no write can overwrite an earlier
  artefact and re-ingesting identical bars is idempotent rather than
  duplicating them. Writes go to a temporary file and are moved into
  place, so a file that exists is a file that finished. Validation's
  verdict is authoritative: an invalid batch raises `StoreRefused` instead
  of being stored, and the only path that writes it anywhere is
  `quarantine_batch`, which does not touch `clean/` or `raw/`.
- **The manifest** (`harsh_quant_os.data.manifest`) — one `datasets` row
  per logical name carrying quality status, instrument, timeframe, version
  and storage path, upserted on the name so a re-ingest updates it rather
  than creating a second dataset, with an append-only provenance row
  appended for every acquisition. Registration happens after the files are
  on disk, because a manifest row pointing at a file that was never
  written is worse than no row.
- **The transport** (`harsh_quant_os.data.transport`) — an `HttpTransport`
  protocol and a stdlib-only `UrllibTransport`. A status code is returned
  rather than raised, because telling a wrong symbol from wrong
  credentials is the adapter's judgement and not a socket's; a request
  that never got an answer becomes `ProviderUnavailable`. Verified against
  a loopback HTTP server, not against a mock.
- **Two concrete adapters** behind the interface
  (`harsh_quant_os.data.adapters`) —
  - `…adapters.kraken` — Kraken's public OHLC feed, chosen because it
    needs no key (so the class of bug that writes a secret into a log is
    structurally impossible here) and quotes prices as decimal strings (so
    nothing is rounded before anyone has decided that rounding is
    acceptable). It pages without sorting, drops the not-yet-committed
    candle by arithmetic rather than by position, drops the repeat a page
    boundary creates while leaving a duplicate the provider itself sent
    for validation to count, and maps only the two error responses
    actually observed — anything else goes out through the base class
    carrying the provider's own words. What it can and cannot raise is
    enumerated in `RAISED_ERRORS`/`NOT_RAISED_ERRORS` and asserted to
    cover every failure the package declares.
  - `…adapters.yahoo` — Yahoo Finance's chart endpoint, also keyless, and
    the one keyless source found that carries Indian exchange symbols:
    NSE (`^NSEI`, `RELIANCE.NS`, `TCS.NS`) and BSE (`^BSESN`,
    `TCS.BO`).
    Its `interval` mapping was checked against the live service for every
    timeframe it claims (`dataGranularity` echoes the request, `4h`
    included); JSON numbers are parsed with `parse_float=Decimal` so no
    float detour rounds a price on the way in; an all-null row — a real
    shape of this feed — is skipped as an absence while a partially null
    row is refused rather than filled; and because this feed was observed
    *silently clipping* a 400-day hourly request to the ~90 days it still
    holds, it measures where the returned series begins and raises
    `PartialData` on a dominant head shortfall — the one failure Kraken
    never raises, asserted both ways. It was also seen to emit its
    in-progress session marker *out of order* — a flat row stamped at
    request time, dropped between two older bars in a `1h` series — so
    the batch is refused for non-increasing timestamps and quarantined;
    bounding the window to finished sessions is what makes such a
    request ingestable, and no timestamp is ever sorted or rewritten to
    get past that check. It satisfies only
    `HistoricalDataProvider`: a keyless feed offers no honest enumeration
    of its universe, so `symbols` is deliberately absent.
- **The ingestion job** (`hqos data ingest` in
  `harsh_quant_os.cli`) — fetch, validate, write the artefacts, register
  the manifest row, in that order, with the database proved reachable
  *before* the network is used so an unusable database costs one refused
  connection rather than a fetch that cannot be recorded. Validation is
  authoritative: an invalid batch exits 1 with a quarantine record and no
  manifest row, and the summary it prints describes the store — counts,
  status, version, paths — and never a price.
- A test that parses every file under `src/` and fails if any imports a
  vendor SDK — principle 1, made executable rather than aspirational.

Not implemented: any scheduled or resumable ingestion (the operator names
the window); the session calendar and second-source cross-check; and the
four interfaces in section 2 without an implementation. Whether data has
landed is workspace state rather than a property of a fresh checkout —
`data/` is not committed — so the evidence for that lives in
`docs/PROJECT-STATUS.md`, which records what was observed and when.

---

## 7. Phase 3 exit criteria

The ROADMAP's own wording is the binding one: *raw data lands with
complete provenance; invalid data is quarantined, never silently repaired
or invented.* That has been observed end to end — a real fetch of 649
hourly candles, validated, stored, registered with a checksum and a
source, with 28 outlier bars flagged and reported as found rather than
adjusted (recorded in `docs/PROJECT-STATUS.md`).

The five criteria below are the stricter set this document set itself.
Two are only partly met, and are named as such rather than rounded up:

| # | Criterion | State | Evidence or gap |
| - | --------- | ----- | --------------- |
| 1 | Two paths into storage: historical backfill and incremental update | **Partly met** | `hqos data ingest --start … [--end …]` fetches any window, so a backfill and a later append are both one command. Nothing yet reads the manifest to resume from the last stored bar, so the incremental boundary is the operator's to supply, and no run is scheduled. |
| 2 | Full provenance on every stored dataset | Met | Each registered dataset carries instrument, timeframe, quality status, version and storage path on its `datasets` row, plus an append-only `dataset_provenance` row with source, SHA-256 checksum, row count and acquisition time. |
| 3 | Validation report per ingestion run, stored and queryable | **Partly met** | Quality status, reasons and notes are queryable from the manifest, and the full report is written to disk beside a *refused* batch. A successful run does not persist its report. |
| 4 | Gaps reported as gaps; no invented values anywhere | Met | `validate_bars` records gap intervals and never fills them; outliers are reported, never adjusted; the store refuses an invalid batch instead of repairing it. |
| 5 | A dataset can be re-ingested and produce an identical version | Met | The store is content-addressed by the SHA-256 of the clean artefact, and a file already holding that content is reused rather than rewritten. |
