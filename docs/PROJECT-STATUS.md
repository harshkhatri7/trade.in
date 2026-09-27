# PROJECT STATUS

| Field                | Value                                          |
| -------------------- | ---------------------------------------------- |
| **Project**          | HARSH QUANT OS                                 |
| **Version**          | 0.1.0-alpha                                    |
| **Current phase**    | 0 — Foundation                                 |
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
| Documentation               | Complete for Phase 0 (architecture, development, security, operations, research, ADR) |
| Configuration               | Typed `Settings` with safety validation                      |
| Safety gates                | Implemented and covered by tests                             |
| Data contracts              | Provenance record, job contract, memory categories           |
| Type checking               | Strict TypeScript (`tsc --noEmit`), strict mypy + Pydantic plugin |
| Lint / format               | Ruff, ESLint 10 flat config, Prettier                        |
| Tests                       | pytest + Vitest, including security and documentation suites |
| CI                          | GitHub Actions workflow defined                              |
| Local environment scripts   | setup, health check, validation, database helpers            |

---

## 2. What does **not** exist yet

Nothing below is implemented. Any document or screen claiming otherwise is a
defect.

- Web application (`apps/web`) — Phase 1
- API service (`apps/api`) — Phase 1
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

---

## 3. Environment observed at Phase 0

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

| Control                                     | State        |
| ------------------------------------------- | ------------ |
| `LIVE_TRADING_ENABLED`                      | Rejected at configuration load |
| Trade gate refuses `live` requests          | Enforced + tested |
| Paper mode requires explicit enablement     | Enforced + tested |
| Broker SDK / endpoints in the codebase      | None          |
| Risk engine independent of strategy logic   | Enforced by architecture |
| Secrets in the repository                   | None found by the secret scan |
| AI access to filesystem / shell / broker    | Not granted   |

---

## 5. Open items at the end of Phase 0

1. Git identity is a local placeholder (`Harsh Quant OS
   <owner@harsh-quant-os.local>`). Set your real identity before pushing:
   `git config user.name "..."` and `git config user.email "..."`.
2. No Git remote exists. Adding GitHub is a manual step — nothing is pushed
   automatically.
3. Docker is not installed, so `docker compose up postgres` has not been
   exercised on this machine. Install Docker Desktop (or Podman) if you want a
   local PostgreSQL for Phase 2.
4. `.env` has not been created. Run `Copy-Item .env.example .env` and fill in
   real values when a subsystem needs them.

---

## 6. Next step

**One task only:** Phase 1 — application skeleton
(`apps/api` FastAPI health endpoint + `apps/web` Next.js shell + contract
tests). Do not start Phase 2 until Phase 1 meets its exit criteria.

See [ROADMAP.md](ROADMAP.md).
