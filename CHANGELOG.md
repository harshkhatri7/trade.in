# Changelog

All notable changes to HARSH QUANT OS are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). The display
version `0.1.0-alpha` corresponds to PEP 440 `0.1.0a0`.

---

## [Unreleased]

### Phase 3 — market-data engine (complete)

#### Added

- **Provider-neutral market-data interfaces** `src/harsh_quant_os/data/`
  — `Bar` and `BarRequest` with `Decimal` prices (the stored value is the
  value the provider sent), timezone-aware timestamps, OHLC relationships
  checked where the failure can still name the bar, and a closed, frozen
  schema. `volume` is `None` when a provider reported none, never `0`:
  zero is a claim that nothing traded.
- **Typed provider failures** — `RateLimited` (carrying `retry_after`),
  `AuthenticationFailed`, `PartialData` (carrying both the requested and
  received counts, so a short answer cannot be mistaken for a complete
  one), `UnsupportedRange`, `ProviderUnavailable` and
  `InvalidProviderPayload`, all catchable through `MarketDataError`.
- **The validation pipeline** `harsh_quant_os.data.validation` — five of
  the seven checks in `data-platform.md` section 3, and an honest note in
  the report for the two that have no implementation yet. `parse_rows`
  quarantines the whole batch on the first malformed row rather than
  dropping the rows around it, naming the field without echoing the value
  (this message goes into a log). `validate_bars` counts duplicates —
  flagging separately those whose values disagreed with the bar kept, and
  making the batch `suspect` when they did — records gaps as explicit
  intervals with the count of bars that were missing, rejects
  out-of-order timestamps with a reason instead of sorting them, and
  flags outliers by modified z-score while leaving them exactly as they
  arrived. Nothing is reordered, filled, clamped or otherwise repaired,
  and tests pin each of those absences rather than only pinning the
  behaviour that is present.
- **A local dataset store with an explicit manifest**
  `harsh_quant_os.data.store` and `harsh_quant_os.data.manifest`.
  Artefacts land in `data/raw/`, `data/clean/` or `data/quarantine/`, in
  directories named by the SHA-256 of their own contents — so no write can
  overwrite an earlier artefact, re-ingesting identical bars is idempotent,
  and "raw is immutable" is a property of the layout rather than a
  convention somebody has to keep. Writes are atomic: content goes to a
  temporary file and is moved into place, so a file that exists is a file
  that finished. Validation's verdict is authoritative — an invalid batch
  raises `StoreRefused` rather than being stored, and the only path that
  writes it anywhere is `quarantine_batch`, which does not touch `clean/`.
  The manifest is one `datasets` row per logical name carrying quality
  status, instrument, timeframe, version and storage path, upserted on the
  name so a re-ingest updates it instead of creating a second dataset,
  with an append-only provenance row appended per acquisition. A new
  migration adds those five columns with three check constraints: the
  status must be one the contract defines, the timeframe must be
  provider-neutral, and `version` and `storage_path` are both set or both
  absent — a half-written manifest is refused rather than discovered later.
- **A test that fails the build if anything under `src/` imports a vendor
  SDK.** Provider independence is the sort of rule that erodes one
  convenient import at a time; parsing every file turns it into something
  a red build can contradict.
- **A transport and one concrete adapter** — `HttpTransport` with a
  stdlib-only `UrllibTransport`: a status code is returned rather than
  raised, because telling a wrong symbol from wrong credentials is the
  adapter's judgement rather than a socket's, and a request that never
  got an answer becomes `ProviderUnavailable`. Behind it,
  `KrakenProvider` for Kraken's public OHLC feed, chosen because it needs
  no key — so the class of bug that writes a secret into a log is
  structurally impossible here — and because prices arrive as decimal
  strings, so nothing is rounded on the way in before anyone has decided
  that rounding is acceptable. It pages without sorting, drops the
  not-yet-committed candle by arithmetic rather than by position, drops
  the repeat a page boundary creates while leaving a duplicate the
  provider itself sent for validation to count, and maps only the two
  error responses actually observed against the live endpoint; anything
  else Kraken says goes out through the base class carrying the
  provider's own words. `RAISED_ERRORS` and `NOT_RAISED_ERRORS` enumerate
  what it can and cannot raise, and a test asserts the pair covers every
  failure the package declares. An opt-in live test composes the whole
  path and skips visibly when it is not asked for.
- **The ingestion job** `hqos data ingest` — fetch, validate, write the
  artefacts, register the manifest row, in that order, with the database
  proved reachable before the network is used so that an unusable
  database costs one refused connection rather than a fetch nothing can
  record. An invalid batch exits 1 with a quarantine record and no
  manifest row; a successful one prints counts, quality status, version
  and paths — never a price, because an ingest summary copied anywhere
  must not read as a result.

#### Not yet delivered

A second provider; scheduled or resumable ingestion (the operator names
every window, and nothing resumes from the last stored bar); the full
validation report of a *successful* run, of which only the status, reasons
and notes reach the manifest; the session-calendar and second-source
cross-checks; and the corporate-actions, news, fundamentals and options
interfaces.

### Phase 2 — database and authentication (complete)

#### Added

- **PostgreSQL persistence** `src/harsh_quant_os/db/` — SQLAlchemy 2.0 async
  engine, session factory, and the `users` / `sessions` / `audit_log` /
  `datasets` / `dataset_provenance` / `strategies` / `experiments` /
  `journal_entries` models.
- **Migrations** `alembic/` + `alembic.ini` — two revisions (`930c38609bc3`,
  then `3842df3d0db8`) build the whole schema from empty; `alembic/env.py`
  prefers `HQOS_DATABASE_URL` and otherwise reads `Settings`.
- **Append-only audit log** — an append-only trigger plus a `CHECK`
  constraint on `event_type`; the application cannot rewrite history even if
  a caller tries.
- **Authentication** `src/harsh_quant_os/auth/` — Argon2id password hashing,
  session tokens stored as an HMAC-SHA256 digest, and `POST
  /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/me`. There is
  no open registration: accounts come from `hqos user create`.
- **`hqos user create` CLI** — reads the password from `--password-stdin` or
  a TTY prompt, refuses a placeholder, and never echoes a credential.
- **`npm run db:migrate` / `npm run db:downgrade`** — Alembic through
  `scripts/data/migrate.ps1`, with `://...@` redacted from everything it
  prints.
- **`HQOS_REQUIRE_POSTGRES=1`** — turns "the database was not there" from a
  skip into a failure; the CI integration job sets it alongside a PostgreSQL
  service.
- Contract parity for the auth context across Python, TypeScript and a shared
  fixture.
- **Backup and restore** `src/harsh_quant_os/db/backup.py` — every table in a
  single transaction using PostgreSQL's binary COPY, with the Alembic
  revision recorded in `manifest.json`. A restore into a database at a
  different revision, into populated data, or from a directory without a
  manifest is refused rather than attempted, and identity sequences are
  re-aimed so the first insert after a restore cannot collide.
- **`hqos db backup` and `hqos db restore`** — the runnable form of the same
  module. Both report only what they observed (table names, row counts, the
  schema revision); a connection failure is reported by error type, never by
  the driver's own message, because that message embeds the connection
  string.
- **The Phase 2 research schema** (revision `3842df3d0db8`) — `datasets`,
  `dataset_provenance`, `strategies`, `experiments` and `journal_entries`,
  the schema domains ROADMAP.md asks for. Provenance is append-only at the
  database, like `audit_log`; deleting a dataset that has recorded origin or
  a strategy that has experiments is refused rather than cascaded, so
  research lineage cannot be destroyed by one delete; `metrics` defaults to
  `{}`, which means nothing has been measured. Structured payloads are
  `jsonb` rather than a guessed column set, because the strategy and
  experiment formats belong to modules that do not exist yet.
- **Migration and schema tests** — five in
  `tests/integration/test_migrations.py`: build from empty, roll back,
  rebuild; every refusal provoked and observed (privilege error `42501` for
  append-only, check violation `23514` for an unknown status or a finish
  without a start, foreign-key violations for the restricted deletes); plus
  assertions that no column anywhere stores a naive timestamp or an
  approximate-numeric value.

#### Fixed

- `login()` committed nothing on success, so the caller's context manager
  rolled back the brand-new session row and a "successful" login could never
  authenticate. Both the success and the refusal path now commit.

#### Not yet delivered

Nightly backup scheduling, rate limiting, a per-request CSRF token, and the
TimescaleDB evaluation that ROADMAP.md makes optional and conditional on
measured query patterns. The Phase 2 research tables exist but have **no
writer** — they are a schema, not a feature.

### Phase 1 — Application skeleton

Phase 1 — A real request path, nothing more: browser →
HTTP → FastAPI → settings → health response, with the contract proved on
both sides.

#### Added

- **API service** `apps/api` — FastAPI application with `GET /api/v1/health`
  and `GET /api/v1/ready` (aliases at `/health` and `/ready`), served from
  typed Pydantic models in `harsh_quant_os.contracts.system`; structured
  logging with request ids, RFC 7807 problem+json error handling, CORS from
  configuration, OpenAPI disabled in production. `/ready` reported
  `database: not_configured` because Phase 1 had no database.
- **Web application** `apps/web` — Next.js 16 + React 19 + Tailwind CSS 4
  shell: dark, responsive, accessible (landmarks, skip link, reduced-motion),
  showing the phase and the **live** `/health` response. No charts, no market
  numbers, no P&L, no fabricated status.
- **Typed API client** (`apps/web/src/api-client`) — the only place the app
  performs HTTP. Request state is a closed union: `loading`, `connected`,
  `error`, `unavailable`; network failures are reported, never hidden.
- **Shared system contract** — `src/harsh_quant_os/contracts/system.py`,
  mirrored by `packages/types/src/system.ts` with runtime parsers in
  `packages/shared/src/api-contracts.ts`, and a common fixture in
  `tests/contracts/system-status.json`. Parity is checked in **both**
  directions (TypeScript parses the Python source and vice versa) instead of
  code generation — see ADR-0002.
- **Integration tests** — `tests/integration/test_api_http.py` starts a real
  uvicorn process and asserts over real HTTP; `tests/integration/api-web-flow.test.tsx`
  runs the same process through the real client into a rendered DOM. It
  skips with a printed reason when Python with FastAPI is absent, and CI has
  a dedicated job so it cannot skip there unnoticed.
- **Tests** — pytest 69 passed, Vitest 47 passed: endpoint schema and
  status codes, versioning aliases, CORS and configuration, error shape,
  contract parity, client failure modes, one test per rendered UI state.
- **Developer commands** — `npm run dev` (API + web), `npm run api`,
  `npm run web`, `npm run build:web`, `npm run test:integration`;
  `start-dev.ps1` reads host and port from `.env`.
- **CI** — `next build` in the TypeScript job and a new integration job that
  installs both toolchains.
- **Decisions** — ADR-0002 (shared contract without codegen), ADR-0003
  (authentication deferred to Phase 2), with the matching roadmap amendment.

#### Changed

- `.env.example` — CORS allow-list default widened to both localhost origins,
  plus `NEXT_PUBLIC_API_BASE_URL`; documented what each key controls.
- `npm run typecheck` now checks the root project **and** `apps/web`.
- ESLint ignores are anchored correctly (`**/.next/**`), so generated Next.js
  output is never linted.
- `next.config.ts` sets `agentRules: false`: Next does not write
  `AGENTS.md`/`CLAUDE.md` into a tree whose documentation is machine-tested.

#### Security

- CORS is an explicit allow-list from `API_ALLOWED_ORIGINS`; `Settings`
  rejects a wildcard outside `development`/`test` (test enforced).
- The API binds to `127.0.0.1` by default and exposes only read-only
  endpoints; no state-changing route exists.

#### Known limitations

- **No authentication.** Roadmap Phase 1 originally required it; ADR-0003
  records the deviation and moves it to Phase 2, together with the roadmap
  change. The mitigations listed there are not a substitute for it.
- No database, no market data, no charts, no strategies, no backtests, no
  paper trading, no AI — Phase 2 onward.
- Playwright is not installed; browser-level end-to-end tests start in
  Phase 4.

---

## [0.1.0-alpha] — 2026-09-27

Phase 0 — Foundation. Repository initialised; no application behaviour yet.

### Added

- **Repository foundation** — `main` branch, `.gitignore`, `.gitattributes`,
  `.editorconfig`, npm workspaces, root `pyproject.toml`.
- **Python foundation package** `src/harsh_quant_os`:
  - `config.Settings` — typed environment configuration with safety
    validation; rejects `LIVE_TRADING_ENABLED=true` and placeholder secrets
    outside development/test.
  - `safety.gates` — `TradingMode`, `resolve_trading_mode`,
    `evaluate_trade_gate`, `assert_live_trading_blocked`; live execution
    raises unconditionally.
  - `contracts.provenance` — provider-independent dataset provenance record
    (source, symbol, timestamp, ingestion time, timeframe, quality, lineage,
    version) with timezone and lineage validation.
  - `contracts.jobs` — local-agent job contract with an explicit operation
    allow-list.
  - `memory.MemoryCategory` — the eight persistent memory partitions.
  - `cli` — `hqos version` and `hqos status` reporting real environment state.
- **TypeScript foundation** — `@harsh-quant-os/types` (domain types mirroring
  the Python contracts) and `@harsh-quant-os/shared` (deterministic numeric
  helpers), both strictly typed.
- **Tooling** — Ruff (lint + format), mypy strict with the Pydantic plugin,
  pytest, ESLint 10 flat config, Prettier, Vitest 5, strict `tsconfig`.
- **Tests** — 57 tests across unit, data, security and documentation
  categories (pytest: 38 passed, 1 skipped; Vitest: 19 passed), including a
  working-tree secret scan, live-trading gate tests, cross-language contract
  parity, and documentation link/structure validation.
- **Documentation** — README, AGENTS, ARCHITECTURE, SECURITY, CONTRIBUTING,
  the full `docs/` tree (architecture, development, security, operations,
  research), ADR-0001, roadmap and project status.
- **Agent specifications** — `AGENT.md` for each of the ten planned agents.
- **Automation** — setup script, health check, project validation, database
  helpers and maintenance scripts (PowerShell, Windows).
- **Infrastructure** — development `docker-compose.yml` (PostgreSQL, optional
  Redis) and GitHub Actions CI.

### Security

- Secrets are confined to `.env` (git-ignored); `.env.example` holds
  placeholders only, verified by test.
- Live trading is unreachable by configuration; verified by test.
- Risk engine is architecturally separate from strategy logic.

### Known limitations

- No application code yet: `apps/web`, `apps/api` and `apps/local-agent`
  are placeholders for Phase 1 and Phase 11.
- No database, no market data, no quant engine, no backtester, no paper
  trading, no AI assistant.
- Docker is not installed on the development machine, so PostgreSQL
  provisioning is untested here; `health-check` reports it honestly.
