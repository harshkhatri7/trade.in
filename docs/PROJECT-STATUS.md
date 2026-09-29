# PROJECT STATUS

| Field                | Value                                          |
| -------------------- | ---------------------------------------------- |
| **Project**          | HARSH QUANT OS                                 |
| **Version**          | 0.1.0-alpha                                    |
| **Current phase**    | 2 — Database and authentication (in progress)  |
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
| Database                    | PostgreSQL 16 via SQLAlchemy 2.0 (async) + Alembic; `users`, `sessions`, `audit_log` |
| Migrations                  | One revision (`930c38609bc3`); empty → head → empty is covered by a test |
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

- The Phase 2 schema domains beyond identity and audit: datasets and their
  provenance, experiments, strategies, journal entries
- Nightly scheduling of backups, and where backup output is stored off-machine
- Rate limiting and a per-request CSRF token
- Market-data ingestion and historical data — Phase 3
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

1. **Phase 2 is not finished.** Every exit criterion in
   [ROADMAP.md](ROADMAP.md) is now met — migrations from empty, an
   append-only audit table, tested backup and restore, and sessions that
   survive a restart — but the phase's schema deliverables (datasets,
   provenance, experiments, strategies, journal entries) do not exist yet.
   Do not describe Phase 2 as complete until they do.
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

**Finish Phase 2:** the remaining schema domains — datasets and their
provenance, experiments, strategies and journal entries — so the deliverables
listed in [ROADMAP.md](ROADMAP.md) match what the migrations actually create.
The exit criteria are met; the deliverables are not, and Phase 3 does not
start before both are.
