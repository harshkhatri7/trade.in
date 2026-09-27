# HARSH QUANT OS

**Version:** 0.1.0-alpha · **Phase:** 1 — Application skeleton · **Live trading:** DISABLED

A private quantitative trading **research** and **analysis** platform.

HARSH QUANT OS is being built to ingest and validate market data, run
reproducible quantitative research, test strategies honestly, and operate a
paper-trading loop with strict risk control.

> **This is not a money-making promise.** Nothing in this repository guarantees
> profit. Backtests describe the past, not the future. Trading involves risk
> of loss. Live trading is **not implemented** and will remain disabled until a
> dedicated, separately reviewed phase is completed and explicitly approved.

---

## Current state (Phase 1)

Phase 0 delivered the **development foundation**: repository layout,
documentation, tooling, safety gates, contracts, tests and CI. Phase 1 adds
the **application skeleton**: a FastAPI service and a Next.js shell joined by
a typed, tested contract. There is no dashboard, no market data, no strategy,
no signal, no backtest engine and no trading.

| Subsystem        | Status                               |
| ---------------- | ------------------------------------ |
| Repository/Git   | Initialized (`main`)                 |
| API              | `/api/v1/health`, `/api/v1/ready`    |
| Web shell        | Next.js app showing the live API response |
| Contract         | Python ⇄ TypeScript, parity tested   |
| Authentication   | Not implemented (Phase 2, ADR-0003)  |
| Documentation    | Complete for Phases 0–1              |
| Type checking    | Strict TypeScript + strict mypy      |
| Lint/format      | Ruff (Python), ESLint + Prettier     |
| Tests            | pytest + Vitest, all passing         |
| Safety gates     | Implemented and tested               |
| Database         | Not implemented (Phase 2)            |
| Market data      | Not implemented (Phase 3)            |
| Quant engine     | Not implemented (Phase 5)            |
| Backtesting      | Not implemented (Phase 6)            |
| Paper trading    | Not implemented (Phase 10)           |
| Broker           | Not connected                        |
| Live trading     | Disabled — unreachable by config     |

The authoritative status file is [docs/PROJECT-STATUS.md](docs/PROJECT-STATUS.md).
The plan is [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Repository layout

```text
harsh-quant-os/
├── apps/                 # Deployable services (web, api, local-agent)
├── packages/             # Shared libraries (types, shared, quant, risk, ...)
├── src/harsh_quant_os/   # Python foundation package (config, safety, contracts)
├── agents/               # AI agent specifications (10 agents, AGENT.md each)
├── docs/                 # Architecture, development, security, ops, research
├── research/             # Experiments, hypotheses, reports, notebooks
├── strategies/           # candidates / validated / rejected / archived
├── data/                 # raw / clean / features / exports / cache (not committed)
├── tests/                # unit, integration, security, data, quant, backtesting, e2e
├── scripts/              # setup, development, data, maintenance
└── infrastructure/       # docker, database, deployment, monitoring
```

Directories that hold results (`data/`, `research/`, `strategies/validated/`)
keep their `.gitkeep` placeholders but never their contents — datasets and
outputs are local artefacts, not source code.

---

## Tech stack

| Layer            | Choice                                     | Why                                                          |
| ---------------- | ------------------------------------------ | ------------------------------------------------------------ |
| Web UI           | Next.js + TypeScript + Tailwind CSS        | App Router, strict typing, accessible component architecture |
| API              | Python + FastAPI + Pydantic                | Async, typed request/response models, OpenAPI for free       |
| Database         | PostgreSQL                                 | Relational integrity for research records and audit trails   |
| Quant            | NumPy, Polars/Pandas, SciPy, scikit-learn, statsmodels | Standard numerical stack; Polars for fast columnar work |
| Charts           | TradingView Lightweight Charts             | Purpose-built for financial series, permissive license       |
| Local agent      | Python                                     | Same language as the API, easy to audit                      |
| Containers       | Docker (optional)                          | Reproducible PostgreSQL for development                      |
| Version control  | Git + GitHub (private)                     | History, review, CI                                          |
| AI               | Provider-agnostic adapter, local optional  | No vendor lock-in; local models remain optional              |

Every dependency must have a written reason. Popularity is not a reason.

---

## Quick start

Prerequisites: **Git**, **Node.js ≥ 20.11**, **Python 3.12+**. Docker is
optional (needed only for PostgreSQL).

```powershell
# 1. Verify your machine
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1

# 2. One-shot setup: directories, virtualenv, dependencies, validation
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\setup.ps1

# 3. Configure your local environment
#    Creates .env from the template if it is missing, generates local-only
#    secrets (never printed), and covers both loopback origins for CORS.
npm run env:provision

# 4. Run every check
npm run check
```

`.env` is git-ignored and is never written by an agent: run the provisioning
step yourself, and re-run it with `-Force` to rotate the generated values.

Run the application (Phase 1: API + web):

```powershell
npm run dev        # API on http://127.0.0.1:8000 + web on http://127.0.0.1:3000
npm run api        # API only
npm run web        # web only
npm run build:web  # production build of the web app
```

Ports, CORS origins and the browser's API URL come from `.env`
(`API_HOST`, `API_PORT`, `WEB_HOST`, `WEB_PORT`, `API_ALLOWED_ORIGINS`,
`NEXT_PUBLIC_API_BASE_URL`). The page displays the live `/health` response —
no status, version or environment value on screen is hard-coded.

If the status panel shows **DISCONNECTED**, either the API is not running or
the origin you opened the page from is missing from `API_ALLOWED_ORIGINS`;
the browser refuses the call and the panel says so. `npm run dev` prints a
warning naming the exact value to add, and `npm run env:provision` puts both
loopback origins in the allow-list.

Individual checks:

```powershell
npm run format:check      # Prettier
npm run lint              # ESLint
npm run typecheck         # tsc --noEmit (strict) for root and apps/web
npm run test              # Vitest (unit, web and integration suites)
npm run test:integration  # integration suite only
npm run test:py           # pytest
npm run health            # environment health report (real results only)
```

Python-only equivalents (no npm):

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

---

## Architecture in one paragraph

The browser talks to the **API**, never to your filesystem. The API calls
**application services**, which call the **domain**, which uses the **quant**,
**risk** and **backtesting** libraries, all backed by **PostgreSQL**. Heavy or
local-only work is submitted as an authenticated, allow-listed **job** to a
separate **local agent** running on your PC; the agent enforces path
allow-lists, resource limits, cancellation and audit logging. Full detail lives
in [ARCHITECTURE.md](ARCHITECTURE.md) and
[docs/architecture/system-architecture.md](docs/architecture/system-architecture.md).

---

## Safety model (summary)

- Live trading is **disabled** and cannot be enabled by configuration:
  `Settings` rejects `LIVE_TRADING_ENABLED=true` at load time.
- A strategy may **request** a trade. The **risk engine** may reject it. A
  strategy can never override the risk engine.
- The trade gate refuses any `live` request outright.
- Secrets live only in `.env` (git-ignored). `.env.example` holds placeholders.
- The AI layer has no broker credentials, no unrestricted filesystem or shell
  access, and no ability to bypass risk controls or alter audit history.

Details: [SECURITY.md](SECURITY.md).

---

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/development/definition-of-done.md](docs/development/definition-of-done.md).
All AI agents must obey [AGENTS.md](AGENTS.md) without exception.

## License

Private, unpublished project. All rights reserved.
