# PROJECT STATUS

| Field                | Value                                          |
| -------------------- | ---------------------------------------------- |
| **Project**          | HARSH QUANT OS                                 |
| **Version**          | 0.1.0-alpha                                    |
| **Current phase**    | 3 — Market-data engine (in progress)          |
| **Live trading**     | **DISABLED**                                   |
| **Broker**           | **NOT CONNECTED**                              |
| **Paper trading**    | NOT IMPLEMENTED                                |
| **Capital (paper)**  | ₹1,000                                         |
| **Primary objective**| Build reliable research infrastructure         |
| **Last updated**     | 2026-09-29                                     |

> This file states only what is true right now. It is validated by
> `tests/unit/test_documentation.py`, and it must be updated in the same
> change that alters the state it describes.

---

## 1. What exists today

| Area                        | State                                                        |
| --------------------------- | ------------------------------------------------------------ |
| Git repository              | Initialized, branch `main`, no remote configured             |
| Repository layout           | `apps/`, `packages/`, `src/`, `agents/`, `docs/`, `tests/`, `scripts/`, `infrastructure/` |
| Documentation               | Complete for Phases 0–2 (architecture, development, security, operations, research, ADRs) |
| Database                    | PostgreSQL 16 via SQLAlchemy 2.0 (async) + Alembic; `users`, `sessions`, `audit_log`, `datasets`, `dataset_provenance`, `strategies`, `experiments`, `journal_entries` |
| Migrations                  | Two revisions (`930c38609bc3` → `3842df3d0db8`); empty → head → empty is covered by a test |
| Backup and restore          | `harsh_quant_os.db.backup` — binary COPY with the schema revision in the manifest; round trip proved by a test |
| Authentication              | `AuthService`: Argon2id, sessions in PostgreSQL, `hqos_session` cookie |
| Audit log                   | Append-only by trigger and `CHECK` constraint; every login outcome recorded |
| Web application             | `apps/web` — Next.js 16 + React 19 + Tailwind 4 shell         |
| API service                 | `apps/api` — FastAPI: health, readiness, login, logout, `/me`  |
| API client                  | Typed client in `apps/web/src/api-client` with explicit loading / connected / error / unavailable states |
| Shared contract             | Python models, TypeScript mirrors and fixtures, checked in both directions (system status and auth context) |
| Configuration               | Typed `Settings` with safety validation (single source for env) |
| Safety gates                | Implemented and covered by tests                             |
| Data contracts              | Provenance record, job contract, memory categories, system status |
| Market-data interfaces      | `harsh_quant_os.data` — provider-neutral `Bar`/`BarRequest`, `HistoricalDataProvider` and `MarketDataProvider`, typed provider failures; a test fails the build if anything under `src/` imports a vendor SDK |
| Validation pipeline         | `harsh_quant_os.data.validation` — schema quarantine, timestamp ordering, duplicates, gaps, outliers; session calendar and second-source cross-check not implemented |
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
- Market-data **adapters, ingestion and storage manifests** — Phase 3.
  Interfaces and validation exist; nothing fetches or stores anything yet,
  and no provider has been called. The session-calendar and second-source
  cross-checks have no implementation either.
- Market terminal and charts — Phase 4
- Quant / feature engine — Phase 5
- Backtesting engine — Phase 6
- Strategy validation and walk-forward testing — Phase 7
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

There is no dashboard, no chart, no market number, no signal, no backtest and
no trading of any kind in the interface. The only value the web app displays
comes from a validated `/health` response.

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

---

## 6. Next step

**Phase 3 is under way, on instruction.** Phase 2 was closed, validated and
committed; the phase-boundary stop was then lifted by the human, so Phase 3
(Market-data engine) began with the provider-independent interface layer.

Next, in [ROADMAP.md](ROADMAP.md) order: a local dataset store with an
explicit manifest, then one concrete provider adapter behind the
interface. Phase 3's exit criteria — raw data lands with complete
provenance, and invalid data is quarantined rather than silently repaired
or invented — are **not** met yet: validation now exists, but nothing has
been ingested, so no data has landed anywhere.

Carried forward, none of it Phase 3: nightly backup scheduling and where
backups live off-machine; rate limiting and a per-request CSRF token; and
the human-supplied `local_agent_token`.
