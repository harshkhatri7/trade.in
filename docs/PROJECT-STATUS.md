# PROJECT STATUS

| Field                | Value                                          |
| -------------------- | ---------------------------------------------- |
| **Project**          | HARSH QUANT OS                                 |
| **Version**          | 0.1.0-alpha                                    |
| **Current phase**    | 7 — Strategy validation (in progress)      |
| **Live trading**     | **DISABLED**                                   |
| **Broker**           | **NOT CONNECTED**                              |
| **Paper trading**    | NOT IMPLEMENTED                                |
| **Capital (paper)**  | ₹1,000                                         |
| **Primary objective**| Build reliable research infrastructure         |
| **Last updated**     | 2026-09-30                                     |

> This file states only what is true right now. It is validated by
> `tests/unit/test_documentation.py`, and it must be updated in the same
> change that alters the state it describes.

---

## 1. What exists today

| Area                        | State                                                        |
| --------------------------- | ------------------------------------------------------------ |
| Git repository              | Initialized, branch `main`, no remote configured             |
| Repository layout           | `apps/`, `packages/`, `src/`, `agents/`, `docs/`, `tests/`, `scripts/`, `infrastructure/` |
| Documentation               | Complete for Phases 0–6 and Phase 7 increment 1 (architecture, development, security, operations, research, ADRs) |
| Database                    | PostgreSQL 16 via SQLAlchemy 2.0 (async) + Alembic; `users`, `sessions`, `audit_log`, `datasets`, `dataset_provenance`, `strategies`, `experiments`, `journal_entries` |
| Migrations                  | Three revisions (`930c38609bc3` → `3842df3d0db8` → `7c4d9e2a15b3`); empty → head → empty is covered by a test |
| Backup and restore          | `harsh_quant_os.db.backup` — binary COPY with the schema revision in the manifest; round trip proved by a test |
| Authentication              | `AuthService`: Argon2id, sessions in PostgreSQL, `hqos_session` cookie |
| Audit log                   | Append-only by trigger and `CHECK` constraint; every login outcome recorded |
| Web application             | `apps/web` — Next.js 16 + React 19 + Tailwind 4: home page with system status, `/datasets` browser with provenance         |
| API service                 | `apps/api` — FastAPI: health, readiness, login, logout, `/me`, and read-only dataset reads (directory, detail, stored bars)  |
| API client                  | Typed client in `apps/web/src/api-client` with explicit loading / connected / error / unavailable states |
| Shared contract             | Python models, TypeScript mirrors and fixtures, checked in both directions (system status, auth context and dataset reads) |
| Configuration               | Typed `Settings` with safety validation (single source for env) |
| Safety gates                | Implemented and covered by tests                             |
| Data contracts              | Provenance record, job contract, memory categories, system status |
| Market-data interfaces      | `harsh_quant_os.data` — provider-neutral `Bar`/`BarRequest`, `HistoricalDataProvider` and `MarketDataProvider`, typed provider failures; a test fails the build if anything under `src/` imports a vendor SDK |
| Validation pipeline         | `harsh_quant_os.data.validation` — schema quarantine, timestamp ordering, duplicates, gaps, outliers; session calendar and second-source cross-check not implemented |
| Dataset store + manifest    | `data/raw`, `data/clean`, `data/quarantine` written content-addressed and atomically; `datasets` carries quality status, version and storage path with three check constraints; provenance appended per acquisition |
| Market-data adapter         | `KrakenProvider` — Kraken's public OHLC feed behind `HttpTransport` (stdlib client, no key, prices as decimal strings); paging, an unfinished candle and both observed error responses are handled explicitly, and an opt-in live test composes the whole path |
| Ingestion job               | `hqos data ingest` — fetch → validate → store → register in one command; refuses (exit 1) and quarantines a batch validation rejects; database proved reachable before any network call |
| Backtesting engine          | `harsh_quant_os.backtesting` — deterministic next-bar-open engine with `Decimal` money and golden money-path tests, the §3 run manifest with byte-identical re-execution, the §4 metric set with assumptions attached, window-coverage checks, and the §6 report (limitations first); every simulated order passes `ConfiguredRiskEvaluator`. Phase 7 increment 1 adds chronological train/held-out splitting with an append-only held-out-once access ledger (`validation.py`) and rolling/expanding walk-forward windows with the aggregated out-of-sample track (`walkforward.py`) |
| Type checking               | Strict TypeScript (`tsc --noEmit` for root **and** `apps/web`), strict mypy + Pydantic plugin over `src`, `tests`, `apps/api`, `alembic` |
| Lint / format               | Ruff, ESLint 10 flat config, Prettier                        |
| Tests                       | pytest + Vitest, including contract parity, integration (real HTTP, real API process, API → client → DOM), security and documentation suites |
| CI                          | GitHub Actions: TypeScript, Python, integration (with a PostgreSQL service and `HQOS_REQUIRE_POSTGRES=1`), repository policy |
| Local environment scripts   | setup, environment provisioning, health check, validation, dev launcher, database helpers (start, migrate, reset, backup, restore) |

### Running it

```powershell
npm run dev        # API + web, ports read from .env
npm run check      # format:check + lint + typecheck + vitest + pytest
npm run health     # environment health report (real results only)
npm run db:migrate # apply Alembic migrations (redacted output)

hqos db backup  --output data/backups/2026-09-29 # every table, one transaction
hqos db restore --source data/backups/2026-09-29 # refuses a populated target

hqos data ingest --symbol XBTUSD --timeframe 1h `
  --start 2026-09-01T00:00:00+00:00 --end 2026-09-28T00:00:00+00:00

hqos backtest report --dataset kraken.xbtusd.1m `
  --entry-above 84000 --exit-below 83000 # report -> research/reports/ (Git-ignored)
```

`data/` is ignored by Git in its entirety, so a backup written beneath it is
never committed.

### Endpoints that exist

| Endpoint                  | Purpose                                                        |
| ------------------------- | -------------------------------------------------------------- |
| `GET /api/v1/health`      | Process liveness, version and environment (also at `/health`)  |
| `GET /api/v1/ready`       | Readiness with explicit checks (also at `/ready`)              |
| `POST /api/v1/auth/login` | Open a session; sets the `hqos_session` cookie                 |
| `POST /api/v1/auth/logout`| Revoke the current session (`204`)                             |
| `GET /api/v1/me`          | The authenticated account and its session                      |
| `GET /api/v1/datasets`    | Every dataset with provenance, quality status and version      |
| `GET /api/v1/datasets/{name}` | One dataset and its append-only acquisition history      |
| `GET /api/v1/datasets/{name}/bars` | One cursor page of stored bars, tagged with its version |

The three dataset routes are `GET`-only and unauthenticated by design
(`docs/architecture/backend.md` §4 and §6): they expose public market data
and where it came from, not an account, a session, a strategy, a position
or an order. The loopback bind and the CORS allow-list are what keep them
local. A timestamp with no UTC offset and an inverted window are refused
with `422`; an unknown name is `404`; a manifest row whose artefact cannot
be read is `409`, never a shorter series than the manifest claims.

`/ready` performs a real round trip to PostgreSQL and reports `database: ok`
or `database: failed`; a failed check answers `503`. `not_configured` is no
longer emitted for the database — the application has one, so saying it does
not would be false.

There is **no open registration**: accounts are created out of band with
`hqos user create`.

---

## 2. What does **not** exist yet

Nothing below is implemented. Any document or screen claiming otherwise is a
defect.

- Nightly scheduling of backups, and where backup output is stored off-machine
- Rate limiting and a per-request CSRF token
- Market-data **ingestion, scheduled and resumable** — Phase 3's adapter,
  validation, store, manifest and the `hqos data ingest` command all
  exist and have been exercised against a live public provider, but no
  run is scheduled, nothing resumes from the last stored bar (the
  operator names the window), and only one provider is implemented. A
  second provider, the session-calendar check and the second-source
  cross-check have no implementation either, and the full validation
  report of a *successful* run is not persisted — only the status,
  reasons and notes on the manifest row.
- Market terminal **UI** — Phase 4, in progress. The read-only dataset API,
  the `/datasets` browser page (directory, quality status, provenance
  panel), the stored-bars chart with its table, the persisted watchlist and
  the multi-timeframe view all exist; increments 1–4 are delivered and
  observed in a real browser.
- Quant / feature engine — Phase 5, complete. The indicator library,
  the statistical tests (stationarity, autocorrelation, correlation),
  the leakage-controlled transforms, versioned feature recipes and the
  on-disk feature store all exist with golden tests; the Phase 5 exit
  criteria are assessed met below. Distribution fitting and
  resampling/session alignment remain not implemented.
- Backtesting engine — Phase 6, complete. The deterministic engine,
  the configured risk evaluator on every simulated order, the §3 run
  manifest with byte-identical reproduction, the §4 metric set and the
  §6 report all exist with golden tests; the Phase 6 exit criteria are
  assessed met below. Regime-split results and parameter-sensitivity
  surfaces remain not implemented (Phase 7).
- Strategy validation and walk-forward testing — Phase 7, in progress.
  Increment 1 (chronological splits, the held-out-once access ledger,
  train-slice selection recording every variant, walk-forward windows
  with the documented aggregation and tamper-checked JSON evidence)
  exists with golden tests; parameter sensitivity, regime splits,
  deflated metrics, benchmark/shuffled-signal nulls and the promotion
  workflow remain not implemented.
- AI research assistant — Phase 8
- Risk engine — Phase 9
- Paper trading — Phase 10
- Local compute agent — Phase 11
- Cloud/local synchronization — Phase 12
- Persistent research memory — Phase 13
- Advanced quantitative research — Phase 14
- Broker integration research — Phase 15
- Controlled live trading — Phase 16
- Continuous optimization — Phase 17

There is no dashboard, no signal, no backtest and no trading of any kind
in the interface. Every value the web app displays comes from a validated
API response — health, dataset metadata, provenance or stored bars — and
nothing on screen is hard-coded.

---

## 3. Environment observed at Phase 0 and verified again in Phase 2

| Tool            | Observed                                             |
| --------------- | ---------------------------------------------------- |
| OS              | Windows 11 (NT 10.0.26200), x64                      |
| CPU / RAM       | AMD Ryzen 5 6600H, 16 GB                             |
| Node.js         | v24.20.0                                             |
| npm             | 11.19.0                                              |
| Python          | 3.12.10 (3.13 also installed)                        |
| pip             | 26.2.1 (inside `.venv`)                              |
| Git             | 2.55.0 at `D:\Git` — added to the user PATH          |
| Docker          | Docker Desktop 29.8.0 + Compose v5.5.1 running; `postgres` container healthy on `127.0.0.1:5432` |

`scripts\development\health-check.ps1` re-checks all of this at run time and
prints actual results.

---

## 4. Safety state

| Control                                     | State                                                |
| ------------------------------------------- | ---------------------------------------------------- |
| `LIVE_TRADING_ENABLED`                      | Rejected at configuration load                       |
| Trade gate refuses `live` requests          | Enforced + tested                                    |
| Paper mode requires explicit enablement     | Enforced + tested                                    |
| Broker SDK / endpoints in the codebase      | None                                                 |
| Risk engine independent of strategy logic   | Enforced by architecture                             |
| Secrets in the repository                   | None found by the secret scan                        |
| AI access to filesystem / shell / broker    | Not granted                                          |
| API authentication                          | **Implemented** — session cookie over PostgreSQL; no open registration |
| Rate limiting / per-request CSRF token      | **Not implemented** — recorded gap, see `docs/architecture/backend.md` §6 |
| API network exposure                        | Binds to `127.0.0.1` by default; CORS is an allow-list |
| State-changing API endpoints                | Login and logout only (a session, never a position)   |
| Live trading                                | Not implemented; cannot be enabled by configuration   |

---

## 5. Open items carried forward

1. **Phase 2 is finished against [ROADMAP.md](ROADMAP.md).** Every exit
   criterion is met and every non-optional deliverable exists, including the
   schema domains (datasets, provenance, experiments, strategies, journal
   entries). Two Phase 2 items remain honestly open rather than claimed:
   **TimescaleDB has not been evaluated** — the roadmap makes it conditional
   on measured query patterns and none exist yet — and **the new tables have
   no writer**. They are a schema, not a feature: nothing inserts into them,
   so no screen, API or document may imply otherwise.
2. **No per-request CSRF token.** The session cookie is `SameSite=Lax`, the
   API binds to loopback and CORS is an allow-list; that is the current
   mitigation, not a substitute for a token. The limitation is documented in
   `docs/architecture/backend.md`.
3. Git identity is configured locally as a personal name and email rather
   than the Phase 0 placeholder. Check it is the identity you want before a
   remote exists: `git config user.name` and `git config user.email`.
4. No Git remote exists. Adding GitHub is a manual step — nothing is pushed
   automatically.
5. The TypeScript integration test needs Python with FastAPI installed; it
   skips with a printed reason when they are absent (the CI integration job
   installs them and sets `HQOS_REQUIRE_POSTGRES=1`, so a database test that
   cannot run fails there rather than skipping).
6. `.env` is provisioned except for `local_agent_token`, which is reserved
   for the human to supply (AGENTS.md section 3).
7. **Phase 3's two stricter self-imposed criteria are only partly met**
   (`docs/architecture/data-platform.md` §7): no run is scheduled and
   nothing resumes from the last stored bar, so the operator names every
   window; and the full validation report of a *successful* run is not
   written to disk — only the status, reasons and notes on the manifest
   row. The ROADMAP's own Phase 3 exit criteria are met; these two are
   recorded here rather than rounded up.
8. **The dataset read endpoints are served without authentication.** This
   is the §6 rule applied deliberately — market data and its provenance
   name no account — not a control that failed. What stands behind it
   today is the `127.0.0.1` bind, the CORS allow-list and `GET`-only
   routes. The condition under which it must be revisited is publishing
   research data beyond loopback; `docs/architecture/backend.md` §4
   records that authentication would be the first change.

---

## 6. Next step

**Phase 3 (Market-data engine) has delivered its ROADMAP exit criteria.**
The last undelivered bullet — a concrete provider adapter — landed as
`KrakenProvider` behind `HttpTransport`, and the command that ties the
pieces together landed as `hqos data ingest`.

Observed on 2026-09-29 against Kraken's live public endpoint, with the
repository at the commit being documented:

- `hqos data ingest --symbol XBTUSD --timeframe 1h --start
  2026-09-01T00:00:00+00:00 --end 2026-09-28T00:00:00+00:00` exited 0;
- 649 candles received, 649 stored, 0 duplicates, 0 gaps;
- quality status `suspect`, because 28 bars were flagged as outliers —
  reported as found, not adjusted;
- artefacts written under `data/clean/kraken.xbtusd.1h/<sha256>/` and
  read back digit for digit;
- one `datasets` row and one append-only `dataset_provenance` row, the
  latter carrying source `https://api.kraken.com/0/public`, the SHA-256
  checksum, the row count and the acquisition time.

That is the ROADMAP's wording observed rather than asserted: **raw data
lands with complete provenance**, and **invalid data is quarantined,
never silently repaired or invented**. The live check is opt-in
(`HQOS_LIVE_PROVIDER_TESTS=1`) and skips — visibly, as a skip — when it
is not asked for.

Not started as of Phase 3's close: Phase 4. Phase 3 stopped there, and the
next phase began only on the human's instruction, exactly as Phase 2's did.

**Phase 4 (Market terminal) is in progress.** Increment 1 — the read-only
dataset API — is delivered and observed on 2026-09-29 against the
repository at the commit being documented:

- `GET /api/v1/datasets`, `GET /api/v1/datasets/{name}` and
  `GET /api/v1/datasets/{name}/bars` over a real uvicorn process and the
  real PostgreSQL test database, reading a store written by
  `store_batch` and registered by `register_dataset`;
- the directory answer carried the observed dataset's version, its
  `suspect` quality status, its source and its row count; the detail
  answer carried the acquisition history newest first with the SHA-256
  checksum; the bars answer returned `78563.0` and `30.04552452`
  digit for digit, `limit=1` paging through the cursor without overlap,
  and an empty window answering `returned: 0` rather than an error;
- refusals observed with their statuses: unknown name `404`, artefact
  removed from `data/` `409`, timestamp without an offset `422`,
  inverted window `422`, and a dataset name containing a separator
  reachable both raw and percent-encoded;
- the same contracts mirrored in TypeScript and checked against one
  shared fixture (`tests/contracts/datasets.json`) in both directions;
- battery: `pytest` 297 passed + 1 skipped (the opt-in live provider
  test, visible as a skip), `ruff check` clean, `ruff format --check`
  clean over 140 files, `mypy` clean over 95 files, prettier, eslint and
  `tsc` clean, vitest 87 passed.

**Increment 2 — the `/datasets` browser page — is delivered and observed**
on 2026-09-29 with the repository at this commit:

- `apps/web/src/app/datasets/page.tsx` plus
  `components/dataset-browser.tsx`: a directory table (instrument,
  timeframe, quality status, row count, shortened version, acquisition
  time) and, on selection, a provenance panel showing the full SHA-256,
  storage path and the append-only acquisition history — including the
  outlier note validation recorded, shown as written;
- typed client methods `getDatasets`, `getDataset` and `getDatasetBars`
  over the same parsers Python asserts: the dataset name is encoded as
  one path component (a name containing `/` round-trips), and only the
  bars parameters actually supplied are written into the query string;
- four request states on both panels — loading / connected / error /
  unavailable, plus `idle` before any selection — rendered from the shared
  fixture `tests/contracts/datasets.json`, which carries real recorded
  metadata rather than invented samples;
- a `null` field renders as `—`, never `0`; the full version is on screen
  beside the detail panel's figures; failure messages reach the screen
  unchanged; `npm run build:web` produced a production build of both
  routes;
- battery after the change: `pytest` 297 passed + 1 skipped, `ruff check`
  clean, `ruff format --check` clean (140 files), `mypy` clean (95
  files), prettier, eslint and `tsc` clean, vitest **109 passed** (was
  103 — +5 bars-panel tests, +1 contract-guard test), `npm run
  build:web` prerendered `/`, `/_not-found` and `/datasets`.
  
**Increment 4 — watchlist & multi-timeframe — is delivered and observed**
on 2026-09-30 with the repository at this commit:

- `features/datasets/use-watchlist.ts`: a localStorage-persisted watchlist
  hook (`useWatchlist`) that stores followed dataset names across reloads;
  corrupt JSON, non-arrays and non-string entries are treated as an empty
  list instead of throwing into a render; SSR-safe (initial state `null`,
  then hydrated); `toggle` adds or removes a name — deduplicated, in
  insertion order — and reads storage itself when state has not hydrated
  yet, so a click before hydration cannot wipe a stored list; a quota
  failure keeps the in-memory list working instead of crashing.
- `components/dataset-watchlist.tsx`: a panel rendered in a two-column
  grid with the multi-timeframe view, between the directory and the detail
  panel. Followed datasets render with their stored metadata (instrument,
  timeframe, row count, shortened version — `—` for anything never
  recorded, never `0`); a followed name the directory no longer carries is
  kept, marked "(not in directory)", and can still be removed; clicking a
  row's name opens the same detail panel as a directory row and marks the
  open dataset with `aria-current`. The panel renders the directory's
  request state with the app-wide wording (`request-state.ts`), so it
  never claims CONNECTED while the directory is loading or failed.
- `components/dataset-multi-timeframe.tsx`: groups the directory by
  instrument (first-appearance order) and renders **every** canonical
  timeframe chip in `TIMEFRAMES` order (`tick | 1m | 5m | 15m | 30m | 1h |
  4h | 1d | 1w | 1mo`). A chip is a button (`View {tf} of {instrument}`)
  exactly where a stored dataset matches, and opens that dataset by its
  real name; every other chip is a dashed, non-interactive span with an
  sr-only "(not stored)" — the grid shows what is missing without
  pretending it can be opened. Datasets that lack the instrument and/or
  timeframe needed for the grid are named in a footnote rather than
  dropped. Grouping is one top-level memo — no hooks inside render loops.
- `apps/web/src/components/dataset-browser.tsx`: renders both panels
  (sharing one `useWatchlist()` call, so the directory's "Follow" toggles
  and the watchlist panel always agree), and each directory row carries a
  Follow toggle with `aria-pressed` and accessible name
  `Follow {dataset}`.
- `tests/web/dataset-bars.test.tsx`: the chart's `setData` assertion now
  waits with `waitFor` instead of racing the passive effect it asserts —
  the same arguments, previously observed to flake on a cold worker start.
- observed in a real browser against real uvicorn + the dev database with
  three ingested datasets (`kraken.xbtusd.1m` 661 rows, `kraken.xbtusd.1h`
  649 rows, `kraken.xbtusd.1d` 28 rows): Follow flipped `aria-pressed` and
  the watchlist gained the row; after a reload the entry persisted; the
  watchlist's name button opened the detail panel with the 200-bar chart
  and the full SHA-256 on screen; the `1d` chip switched the detail panel
  to `kraken.xbtusd.1d` and its real 28 bars loaded; Unfollow returned the
  empty state, reset the directory toggle to `aria-pressed="false"`, and
  wrote `[]` to storage; the page console held 0 errors and 0 warnings;
- accessibility on `/datasets`: axe-core (wcag2a/aa, wcag21a/aa,
  best-practice) **0 violations, 44 checks passed** after fixing a real
  finding this increment introduced — `opacity-60` on the "not stored"
  chips dropped their contrast to 3.48:1, so the class was removed (the
  dashed border already signals absence); 4 contrast nodes were reported
  `incomplete` (bordered elements axe cannot decide) and were verified by
  token math instead: `#9aa7b8` on `#0a0c10` = 8.0:1 and on `#11151c` =
  7.5:1, both above 4.5:1; Lighthouse on `/datasets`: accessibility,
  best-practices and SEO **1.0 each with zero failures**;
- battery after the change: `pytest` 297 passed + 1 skipped, `ruff check`
  clean, `ruff format --check` clean (140 files), `mypy` clean (95
  files), prettier, eslint and `tsc` clean, vitest **132 passed** (was
  109 — +7 watchlist panel, +6 multi-timeframe panel, +8 hook, +2 browser
  integration), `npm run build:web` compiled successfully.

**Increment 3 — the stored-bars chart — is delivered and observed** on
2026-09-29 with the repository at this commit:

- `apps/web/src/components/dataset-bars.tsx`: a candlestick chart
  (TradingView Lightweight Charts 5.2.1, reason recorded in
  `docs/architecture/frontend.md` §1) of one explicit window —
  `GET /api/v1/datasets/{name}/bars?limit=200` — inside the detail panel,
  with the full artefact version printed above the figure, the
  instrument/timeframe/quality metadata line, and the `has_more` note
  stated out loud when the window is a page of a longer series;
- chart and table read one payload: prices become numbers only for the
  chart's geometry, while the table prints the stored decimal strings
  verbatim (`78563.0`, `30.04552452`); a null volume renders `—`, never
  `0`;
- observed in a real browser against a real uvicorn process and the dev
  database: `GET .../bars?limit=200` answered `200`, the chart painted
  non-blank pixels on its seven canvases, the table rendered 200 rows of
  exact strings, the full SHA-256 was on screen above the figure, the
  page console was empty, and no element overflowed the viewport;
  a screenshot was captured;
- accessibility verified with axe-core on the open panel after two real
  findings were fixed: the chart container is a labelled
  `role="figure"` (the library renders its TradingView attribution link
  inside, and `img` is a leaf role), and the scrollable table wrapper is
  a named focusable region — result **0 violations, 45 checks passed**;
  Lighthouse on `/datasets` scored accessibility, best-practices and SEO
  **1.0 each with zero failures**;
- the contract is the chart's guard: a bar timestamp that does not parse
  is rejected by `parseBarPoint` before any chart could read it, asserted
  in the client tests;
- battery after the change: `pytest` 297 passed + 1 skipped, `ruff check`
  clean, `ruff format --check` clean (140 files), `mypy` clean (95
  files), prettier, eslint and `tsc` clean, vitest **109 passed** (was
  103 — +5 bars-panel tests, +1 contract-guard test), `npm run
  build:web` prerendered `/`, `/_not-found` and `/datasets`;
- dependencies: `lightweight-charts@^5.2.1` and its `fancy-canvas@2.1.0`
  transitive pinned into `apps/web/package.json`; the lockfile diff was
  reviewed (registry.npmjs.org URLs, integrity hashes, Apache-2.0 and
  MIT, 0 vulnerabilities).

The ROADMAP's Phase 4 exit criterion — every number on screen traceable
to a dataset version — was **recorded as unassessed** while the watchlist
and multi-timeframe views the phase specifies did not exist, because a
phase exit criterion is not judged on partial evidence. That evidence is
no longer partial: with increments 1–4 all delivered, the criterion is
assessed **on the full set of screens the phase specified** and is
**met**, recorded 2026-09-30:

- the directory table renders each row count beside that dataset's
  version column;
- the detail panel prints the full SHA-256 above every figure;
- the chart prints the version of the payload it draws directly above
  itself, and its table restates that payload's exact values;
- the watchlist prints each followed dataset's row count and version
  prefix on the same row, with the full version in the cell's `title`;
- the multi-timeframe panel carries no dataset-derived numbers at all —
  only timeframe labels and dataset identities.

Counts that are local interface state (how many datasets are listed, how
many are followed) are counts of what the UI itself holds, not values
read from a dataset, and are excluded from this criterion on the same
basis as in increments 1–3. The phase boundary itself follows AGENTS.md
§2.9: Phase 4 stops here, and the next phase began only on the owner's
explicit in-conversation instruction to continue through the roadmap —
that instruction conflicts with §2.9's stop-at-boundary rule, and the
conflict is disclosed in the session report rather than silently
resolved.

**Phase 5 (Quant engine) is in progress.** Increment 1 — the indicator
library — is delivered and validated on 2026-09-30:

- `src/harsh_quant_os/quant/` with `series.py` (the shared input
  boundary: an empty, non-1-D or non-finite series, and an invalid or
  over-long window, raise `InvalidSeries` before any window rolls) and
  `indicators/` (`sma`, `ema`, `rolling_std`, `rolling_zscore`,
  `bollinger_bands`, `rolling_vwap`, `rsi`, `macd`) — every formula
  written out in its module docstring, every window right-aligned;
- `tests/quant/test_indicators.py`: 46 tests — golden values hand-derived
  inside the test file (EMA as exact fractions `5/3, 23/9, 95/27, 365/81`,
  RSI's Wilder recursion worked through fraction by fraction, population
  variances, VWAP arithmetic), an independent window-loop cross-check, and
  for every function the three mechanical properties quant-engine.md
  requires: appending a future bar changes no earlier output (no
  look-ahead), two calls are bit-identical (determinism), and the input
  array is never mutated;
- the `quant` extra (numpy, pandas, polars, scipy, scikit-learn,
  statsmodels — already declared in `pyproject.toml` with a written reason
  for each) is now installed in `.venv`;
- battery: `pytest` 343 passed + 1 skipped (was 297 — +46 quant),
  `ruff check` clean, `ruff format --check` clean, `mypy` clean over 101
  source files (was 95);
- not started within Phase 5: `stats/`, `transforms/`, `recipes/`,
  `registry/`, the leakage split/label helpers, and the benchmark.

**Increment 2 — statistical properties — is delivered and validated on
2026-09-30:**

- `src/harsh_quant_os/quant/stats/`: `adf_stationarity` (the augmented
  Dickey-Fuller unit-root test returning statistic, p-value, sample
  sizes, alpha, the rejection flag and the critical values in one typed
  result — the p-value is statsmodels' MacKinnon approximation,
  `result_object=False` is passed explicitly so a 0.16 default change
  cannot move the contract, and the `stationary` flag is exactly
  `p_value < alpha`), `acf` (the biased `1/n` autocorrelation estimator
  with `acf[0] = 1`, lags capped below the series length, constant
  series refusing instead of returning `NaN`) and `correlation_matrix`
  (Pearson over equally long columns; constant columns and unequal
  lengths refuse with the column named; a single column returns
  `[[1.0]]`, not a bare scalar);
- `tests/quant/test_stats.py`: 40 tests. The ADF statistic is
  cross-checked against an OLS t-statistic computed **from scratch in
  the test** (design matrix, least squares, RSS, standard error —
  statsmodels not involved in the expectation); the behavioural fixtures
  are a written-out Park-Miller LCG, observed rejecting the unit-root
  null at p < 0.01 as raw noise and not rejecting at 5% as its
  cumulative sum, asserted as thresholds rather than pinned library
  output; `acf` and the correlation matrix are compared against values
  worked out by hand in the test from the documented formulas;
- `pyproject.toml`: the `quant` extra's `statsmodels` floor moves to
  `>=0.15.0` (the `result_object` keyword this code passes was introduced
  there) and a mypy override records that statsmodels ships no
  `py.typed`, with the boundary validation this module performs instead;
- battery: `pytest` **383 passed** + 1 skipped (was 297 at Phase 4's
  close — +86 quant tests), `ruff check` clean, `ruff format --check`
  clean, `mypy` clean over 106 source files (was 95).
- not started within Phase 5: `transforms/`, `recipes/`, `registry/`,
  the leakage split/label helpers, and the benchmark.

**Increment 3 — transforms and the leakage controls — is delivered and
validated on 2026-09-30:**

- `src/harsh_quant_os/quant/transforms/`:
  - `returns.py` — `simple_returns` and `log_returns`, aligned with the
    input (position 0 NaN, documented), strictly positive prices and
    nonzero denominators enforced by refusal; `forward_return`, a
    **label** whose last `horizon` positions are NaN because those
    outcomes have not happened yet — an unobservable label is NaN,
    never guessed;
  - `lag.py` — one-directional shifting (`out[i] = values[i-periods]`);
    a negative shift would read the future and is refused **by name**,
    and a zero shift is refused because a no-op must not stand in for a
    real one;
  - `scaling.py` — `StandardScaler`, a frozen fit/transform: `fit`
    computes from exactly the values passed and records how many it
    saw (`n`), and `transform` only applies the stored statistics, so
    transforming future data cannot re-centre it;
  - `splits.py` — `chronological_split`, time-ordered only (no shuffle
    exists that could put a future row in training), cut validated to
    leave both sides non-empty, disjointness re-asserted before
    returning; `assert_disjoint`, public for caller-built index sets,
    names the first shared index;
- `tests/quant/test_transforms.py`: 46 tests — golden values worked out
  by hand (dyadic returns `[0.5, -0.5, 1.0]`, `-0.25/0.0` two-bar
  labels, mean 3 / variance 2 scaler, cut-at-8 split), and the §4
  leakage properties asserted mechanically: lag direction, fit-sample
  statistics (with a full-sample fit shown to differ), splits checked
  with NumPy rather than the helper under test (disjoint, complete,
  `max(train) < min(test)`), and a forward label that never revises a
  previously computable value when data is appended;
- battery: `pytest` **429 passed** + 1 skipped (was 383 at increment 2 —
  +46 transforms), `ruff check` clean, `ruff format --check` clean
  (157 files), `mypy` clean over 112 source files (was 106);
- not started within Phase 5: `recipes/`, `registry/`, resampling and
  session alignment, and the benchmark.

**Increment 4 — recipes, registry and the measured benchmark — is
delivered and validated on 2026-09-30:**

- `src/harsh_quant_os/quant/recipes/`: `recipe.py` (`DatasetRef`
  pinning one dataset by name **and** content-addressed SHA-256;
  `FeatureSpec` validated at construction against the closed op list;
  `FeatureRecipe` with schema version, exactly one pinned input, an
  execution-ordered feature list and a `nan_policy` sentence recorded
  verbatim; canonical sorted-key JSON so the recipe's SHA-256 identity
  does not depend on construction order, with `from_json` refusing
  unknown and missing fields), `ops.py` (the closed whitelist `sma`,
  `ema`, `rolling_std`, `rolling_zscore`, `rsi`, `log_returns`,
  `simple_returns`, `lag` — each a golden-tested primitive; no `eval`,
  no dynamic import, an unknown op fails with the known names listed),
  `bars.py` (`BarBatch` validated at construction; `load_bar_batch`
  re-hashes the clean artefact against its content-addressed directory
  and refuses a mismatch, requires an explicit version when several
  exist, and refuses missing volume with a count instead of filling
  it), and `execute.py` (validate → compare the name/version pin
  against the batch with both sides named → run in declaration order
  where a source is an input column or an earlier feature; forward
  references are unrepresentable, and a chained source carrying
  warm-up NaN is refused by feature name rather than computed
  through);
- `src/harsh_quant_os/quant/registry/`: `FeatureStore` — entries keyed
  by recipe hash holding `recipe.json`, `values.npy`, `times.npy` and
  `meta.json` (dataset identity, shape, per-column NaN counts, SHA-256
  over canonical little-endian bytes of both artefacts). `meta.json`
  is written last: its presence is the completion marker, an
  interrupted save is refused by name and repaired by a re-save, and
  re-saving a complete entry compares checksums — a determinism
  violation is an error for both sides, never an overwrite. `verify`
  cross-checks the record against the recipe; `load_recipe` re-hashes
  the file, so an edited recipe no longer hashes to its directory;
- `tests/quant/test_recipes.py` (47) + `test_registry.py` (16): the
  canonical JSON is asserted against a string written out byte for byte
  with its SHA-256 recomputed independently; execution is
  bit-identical and leaves inputs untouched; the version pin names
  both sides on mismatch; reproduce-twice **through disk** is
  bit-identical; tampered recipe/matrix/meta, incomplete entries,
  wrong-recipe matrices, determinism violations and path escapes are
  all refused with the reason. Every store fixture is written into
  `tmp_path` — the suite never reads or writes `data/`;
- `scripts/quant/benchmark_features.py`: measures execution on the real
  661-row `kraken.xbtusd.1m` store through the same `load_bar_batch`
  path research uses and checks each timed run against the cold run by
  SHA-256 over canonical bytes (exit 1 if any run differed — the
  harness reported its own first bug rather than passing quietly).
  Measured on this machine (Python 3.12.10, numpy 2.5.3, Windows 11),
  9 features, 126 NaN cells: cold 2.766 ms; 50 timed runs min 1.235 /
  median 1.847 / max 4.528 ms; **50/50 runs SHA-256-identical** to the
  cold run. Dataset version `0a7dd69ff1c4…e29b0`, recipe hash
  `b38da597c454…e48e`, matrix hash `0a6138722513…1a45`. Timings are
  observations that vary run to run; rerun the script to measure
  again — the reproduction count is what the harness asserts;
- filed entries land in `data/features/` (git-ignored local research
  state, alongside `clean/` and `raw/`);
- battery: `pytest` **492 passed** + 1 skipped (was 429 at increment 3
  — +63 recipe/registry tests), `ruff check` clean, `ruff format
  --check` clean (167 files), `mypy` clean over 121 source files (was
  112);
- not started within Phase 5: resampling/session-alignment helpers,
  §4's timestamped `label_time >= info_time` label assertion, and
  distribution fitting (named in quant-engine.md §1's responsibility
  list but not an exit criterion in §7 — recorded as a gap, not
  dropped).

**Phase 5 exit criteria (quant-engine.md §7) — assessed 2026-09-30:**

- Indicator library with golden tests and documented formulas —
  **met**: 46 golden/property tests in `test_indicators.py`, every
  formula written out in its module docstring.
- Reproducible feature recipes with recorded versions — **met**:
  increments 4 pin input dataset versions, hash the canonical recipe,
  and reproduce the matrix bit-identically through disk (16 registry +
  47 recipe tests, plus the benchmark's 50/50 checksum reproduction).
- Leakage property tests passing — **met**: asserted mechanically in
  `test_transforms.py` (46) and the recipe pin/refusal tests. §4's
  scaling, shifting and split-disjointness rows are covered directly;
  the label row is covered only by `forward_return`'s unobservable-tail
  NaN — the timestamped `label_time >= info_time` helper itself remains
  not implemented and is listed above.
- Benchmark data documented; performance measured, not assumed —
  **met**: the numbers above came from running the script; they are
  recorded with their machine context and the command that reproduces
  them, and no number in this document was written without a run.
- `ruff`, `mypy --strict` and the full test suite green — **met**:
  492 passed + 1 skipped; ruff check, ruff format and mypy clean.

**Phase 6 (Backtesting engine) is complete.** Increments 1–4 are
delivered and validated on 2026-09-30:

- **Increment 1 — deterministic engine core** (`engine.py`,
  `strategy.py`, `costs.py`, `data.py`, `safety/risk.py`): the
  documented intrabar rule (a fill pending at the next bar's open ±
  slippage, marked at the close, decided after the mark), `Decimal`
  money end to end with an engine-end identity check
  (`equity == capital + realised − commission + unrealised` within
  1e-12), a bounded `HistoryView` that raises `IndexError` past the
  current bar, a `CausalityViolation` asserted per fill, average-cost
  ledger accounting (crossings realise the closed portion, then re-open
  the remainder at the fill price), a final-bar order expiring
  structurally before risk evaluation, and `OrderStatus` limited to
  FILLED / EXPIRED / REJECTED. The money path is worked out by hand in
  `tests/backtesting/test_engine.py`.
- **Increment 2 — configured risk for every simulated order**: the
  constructor runs the live-trading assertion first; limits are exact
  decimals; only risk-increasing orders are checked (reducing orders
  are never blocked); daily loss is tracked per UTC date from first
  evaluation; unparseable limits refuse with a reason; invalid limits
  raise at construction; the engine passes the position into
  evaluation.
- **Increment 3 — manifest, metrics, byte-identical reproduction**
  (`manifest.py`, `metrics.py`): the §3 manifest with a content-hash
  `run_id` and no wall clock anywhere, the git SHA read from
  `git rev-parse HEAD`, three artefact hashes compared on
  re-execution with `ReproductionMismatch` when one moves, and the §4
  metric set with its assumptions attached — annualisation from actual
  elapsed time so gaps cannot inflate a rate, and undefined figures
  rendering `None` with the reason instead of a plausible number.
  While writing the real-data report, a defect was found and fixed:
  the git-SHA reader validated against 64-hex only, so every real
  40-character `rev-parse` answer was rejected and `null` recorded
  forever — now both real forms are accepted, with a regression test
  that feeds git's own output shapes through.
- **Increment 4 — report, coverage, real-data run** (`report.py`,
  `reference.py`, `window_coverage`, `hqos backtest report`): the §6
  report with limitations first, the manifest attached, assumptions
  separated from measured results, the standard caveat, conditional
  language and a deterministic Wilson interval for the hit rate (the
  engine consumes no randomness, so no bootstrap is run — stated as a
  limitation); window-coverage checks that count missing bars and
  never interpolate them (a timeframe with no fixed length says so
  rather than guessing a month); cost sensitivity at 0.5x/1x/2x with
  a fresh risk evaluator per run; and the CLI command that ties it
  together. Two reports were generated from the real
  `kraken.xbtusd.1m` store (661 bars, coverage complete — 0 missing,
  0 irregular — dataset version `0a7dd69ff1c4…e29b0`) into
  `research/reports/`, which is Git-ignored: simulated results are
  never committed.
- battery: `pytest` **585 passed** + 1 skipped (was 492 at Phase 5's
  close — +93: the 84-test backtesting suite plus the 9 risk-evaluator
  security tests), `ruff check` clean, `ruff format --check` clean
  (186 files), `mypy` clean over 140 source files (was 121),
  prettier, eslint and `tsc` clean, vitest **132 passed** (no web
  changes this phase).
- not started within Phase 6: nothing from backtesting.md §8's exit
  criteria; out-of-sample splitting, walk-forward and regime splits
  are Phase 7's.

**Phase 6 exit criteria (backtesting.md §8) — assessed 2026-09-30:**

- Deterministic engine with golden-value tests — **met**:
  `tests/backtesting/test_engine.py` restates the money path in
  `Decimal` by hand; the suite reproduces it digit for digit.
- Costs, slippage and sizing are explicit inputs, recorded in the
  manifest — **met**: `bps_commission` / `fixed_bps_slippage` are
  closed sets; an unknown model is refused with "refusing to guess".
- Manifest-based reproducibility test passes — **met**:
  `test_manifest.py` stores a manifest as JSON, re-executes it and
  compares orders, equity and whole-result hashes; the reproduction
  is byte-identical and a moved hash raises `ReproductionMismatch`.
- Look-ahead and leakage checks run automatically — **met**: a
  `CausalityViolation` per fill, `HistoryView` bounded to the current
  bar, datasets loaded only by pinned, re-hashed version (Phase 5's
  split-disjointness and fit-scope assertions cover the feature side).
- Reports include assumptions and limitations — **met**: `report.py`
  puts limitations first and separates assumptions from measured
  results; `test_report.py` asserts the ordering, the caveat, the
  conditional language and the absence of every `FORBIDDEN_CLAIMS`
  phrase.
- Risk evaluation is invoked in the simulated path — **met**: every
  simulated order passes `ConfiguredRiskEvaluator` before it may
  fill.

**Phase 7 (Strategy validation) is in progress.** Increment 1 — data
separation and walk-forward — is delivered and validated on
2026-09-30:

- **Increment 1 — splits, the held-out-once ledger, walk-forward**
  (`validation.py`, `walkforward.py`): a chronological train/held-out
  cut that refuses overlap (the held-out suffix must start strictly
  after every training bar — never shuffled); an append-only
  `AccessLedger` whose second held-out touch raises instead of being
  logged, because a test set consulted twice has become training
  data; `evaluate_held_out` verifying the data handed in really is
  the split's pinned slice (same artefact, same span) before running,
  and returning the §3 manifest with the §4 numbers plus the updated
  ledger; `select_on_train` running every declared candidate with a
  fresh strategy instance and a fresh risk evaluator under an
  explicitly named objective, recording every variant, score and
  manifest so the multiple-testing count is visible, with ties
  resolved to the first declared candidate and recorded as ties.
  `walk_forward` generates rolling (or expanding) windows in which
  each test slice starts exactly where its own training ends, runs
  every window as an independent simulation (fresh capital, fresh
  strategy, fresh evaluator), and aggregates the test segments by
  compounding each segment's net return as if the full capital were
  re-deployed (`product(1 + r) − 1`, exact in `Decimal`) beside
  pooled trade counts, positive/negative/flat window counts and the
  variants-tried total — the surface, not the optimum. The summary
  is canonical JSON with every run's manifest embedded; loading
  refuses wrong `kind`, unknown version, edited honesty notes, any
  manifest whose `run_id` no longer matches its payload, and any
  aggregate that does not follow from the windows it summarises.
  Golden traces are hand-computed in the tests: the held-out run
  ends at `995.399998` with net `-0.004600002` (cross-checked
  against capital + realised − commission = 1000 − 4.4 − 0.200002),
  and the walk-forward's window 0 selects the trader at 1004 vs
  1000 while window 1 selects hold at 1000 vs 996, track
  compounding to `-0.002` with hit rate `None` (no completed round
  trips — never a plausible zero).
- battery: `pytest` **612 passed** + 1 skipped (was 585 at Phase 6's
  close — +27: 14 split/ledger/selection tests plus 13
  walk-forward/JSON-evidence tests), `ruff check` clean, `ruff
  format --check` clean (190 files), `mypy` clean over 144 source
  files (was 140), prettier, eslint and `tsc` clean, vitest **132
  passed** (no web changes this increment).
- not started within Phase 7: parameter sensitivity, regime splits,
  deflated/multiple-testing headline adjustment, benchmark and
  shuffled-signal nulls, and the candidate / validated / rejected /
  archived promotion workflow with its product rule (no `validated`
  without out-of-sample and walk-forward evidence attached).

Not started as of Phase 7 increment 1: the rest of Phase 7 (above),
then Phase 8 (AI research).

Carried forward, none of it Phase 6: nightly backup scheduling and where
backups live off-machine; rate limiting and a per-request CSRF token; and
the human-supplied `local_agent_token`.
