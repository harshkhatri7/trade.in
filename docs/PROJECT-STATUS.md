# PROJECT STATUS

| Field                | Value                                          |
| -------------------- | ---------------------------------------------- |
| **Project**          | HARSH QUANT OS                                 |
| **Version**          | 0.1.0-alpha                                    |
| **Current phase**    | 1 — Application skeleton                       |
| **Live trading**     | **DISABLED**                                   |
| **Broker**           | **NOT CONNECTED**                              |
| **Paper trading**    | NOT IMPLEMENTED                                |
| **Capital (paper)**  | ₹1,000                                         |
| **Primary objective**| Build reliable research infrastructure         |
| **Last updated**     | 2026-09-27                                     |

> This file states only what is true right now. It is validated by
> `tests/unit/test_documentation.py`, and it must be updated in the same
> change that alters the state it describes.

---

## 1. What exists today

| Area                        | State                                                        |
| --------------------------- | ------------------------------------------------------------ |
| Git repository              | Initialized, branch `main`, no remote configured             |
| Repository layout           | `apps/`, `packages/`, `src/`, `agents/`, `docs/`, `tests/`, `scripts/`, `infrastructure/` |
| Documentation               | Complete for Phases 0–1 (architecture, development, security, operations, research, ADRs) |
| Web application             | `apps/web` — Next.js 16 + React 19 + Tailwind 4 shell         |
| API service                 | `apps/api` — FastAPI, `/api/v1/health` and `/api/v1/ready`    |
| API client                  | Typed client in `apps/web/src/api-client` with explicit loading / connected / error / unavailable states |
| Shared contract             | Python models, TypeScript mirrors and a fixture, checked in both directions |
| Configuration               | Typed `Settings` with safety validation (single source for env) |
| Safety gates                | Implemented and covered by tests                             |
| Data contracts              | Provenance record, job contract, memory categories, system status |
| Type checking               | Strict TypeScript (`tsc --noEmit` for root **and** `apps/web`), strict mypy + Pydantic plugin |
| Lint / format               | Ruff, ESLint 10 flat config, Prettier                        |
| Tests                       | pytest + Vitest, including contract parity, integration (real HTTP and API → client → DOM), security and documentation suites |
| CI                          | GitHub Actions: TypeScript, Python, integration, repository policy |
| Local environment scripts   | setup, health check, validation, dev launcher, database helpers |

### Running it

```powershell
npm run dev     # API + web, ports read from .env
npm run check   # format:check + lint + typecheck + vitest + pytest
npm run health  # environment health report (real results only)
```

### Endpoints that exist

| Endpoint                  | Purpose                                                        |
| ------------------------- | -------------------------------------------------------------- |
| `GET /api/v1/health`      | Process liveness, version and environment (also at `/health`)  |
| `GET /api/v1/ready`       | Readiness with explicit checks (also at `/ready`)              |

`/ready` reports `database: not_configured`. Phase 1 has no database and the
API does not pretend otherwise.

---

## 2. What does **not** exist yet

Nothing below is implemented. Any document or screen claiming otherwise is a
defect.

- Authentication and sessions — Phase 2 (deferred from Phase 1, ADR-0003)
- Database schema and migrations — Phase 2
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
no trading of any kind in the Phase 1 interface. The only value the web app
displays comes from a validated `/health` response.

---

## 3. Environment observed at Phase 0 and verified again in Phase 1

| Tool            | Observed                                             |
| --------------- | ---------------------------------------------------- |
| OS              | Windows 11 (NT 10.0.26200), x64                      |
| CPU / RAM       | AMD Ryzen 5 6600H, 16 GB                             |
| Node.js         | v24.20.0                                             |
| npm             | 11.19.0                                              |
| Python          | 3.12.10 (3.13 also installed)                        |
| pip             | 26.2.1 (inside `.venv`)                              |
| Git             | 2.55.0 at `D:\Git` — added to the user PATH          |
| Docker          | **Not installed** (optional; PostgreSQL not provisioned locally) |

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
| API authentication                          | **Not implemented** — Phase 2, see ADR-0003           |
| API network exposure                        | Binds to `127.0.0.1` by default; CORS is an allow-list |
| State-changing API endpoints                | None (Phase 1 is read-only)                          |

---

## 5. Open items at the end of Phase 1

1. **Authentication is missing.** Roadmap Phase 1 originally required it;
   [ADR-0003](decisions/ADR-0003-authentication-deferred.md) moves it to
   Phase 2 because sessions need the Phase 2 database. Until then the API has
   no authentication. Mitigations (localhost bind, CORS allow-list, no
   sensitive or write endpoints) are listed in that ADR and are not a
   substitute for it.
2. Git identity is a local placeholder (`Harsh Quant OS
   <owner@harsh-quant-os.local>`). Set your real identity before pushing:
   `git config user.name "..."` and `git config user.email "..."`.
3. No Git remote exists. Adding GitHub is a manual step — nothing is pushed
   automatically.
4. Docker is not installed, so `docker compose up postgres` has not been
   exercised on this machine. Install Docker Desktop (or Podman) if you want
   a local PostgreSQL for Phase 2.
5. The TypeScript integration test needs Python with FastAPI installed; it
   skips with a printed reason when they are absent (CI runs it in a job
   that installs them, so it cannot skip there silently).

---

## 6. Next step

**One task only:** Phase 2 — database (PostgreSQL schema, migrations,
environment-driven credentials) together with the authentication and session
work deferred by ADR-0003. Do not start Phase 3 until Phase 2 meets its exit
criteria.

See [ROADMAP.md](ROADMAP.md).
