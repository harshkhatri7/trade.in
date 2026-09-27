# ARCHITECTURE

**HARSH QUANT OS** — architectural overview for the whole platform.
Detailed, subsystem-level documents live under
[docs/architecture/](docs/architecture/system-architecture.md).

---

## 1. Design goals

| Goal                    | How the architecture delivers it                                           |
| ----------------------- | -------------------------------------------------------------------------- |
| Research first          | Every subsystem exists to support honest research; nothing exists to trade  |
| Safety by construction  | Live trading is unreachable; risk controls are a separate, higher layer    |
| Reproducibility         | Datasets carry provenance and versions; experiments are recorded, not remembered |
| Provider independence   | Data access goes through interfaces, never a vendor SDK in domain code     |
| Local/cloud separation  | Heavy work runs on the local PC through an allow-listed job bridge          |
| Auditability            | Append-only audit records for jobs, gate decisions and configuration       |
| Replaceability          | Thin layers, explicit contracts, no hidden global state                    |

---

## 2. Layering

```text
┌─────────────────────────────────────────────────────────────┐
│  WEB UI  (Next.js + TypeScript + Tailwind)                  │
│  display only — no filesystem, no broker, no direct DB      │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS + session auth
┌───────────────────────────▼─────────────────────────────────┐
│  API  (FastAPI + Pydantic)                                  │
│  authentication · authorization · validation · rate limits  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  APPLICATION SERVICES                                       │
│  orchestration · transactions · audit records · job intake  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  DOMAIN (pure logic, no I/O)                                │
│  instruments · orders · positions · experiments · journals  │
└───────┬───────────────┬───────────────┬─────────────────────┘
        │               │               │
┌───────▼─────┐ ┌───────▼─────┐ ┌───────▼──────────┐
│ QUANT       │ │ RISK ENGINE │ │ BACKTESTING      │
│ features,   │ │ independent │ │ simulation,      │
│ statistics  │ │ veto power  │ │ walk-forward     │
└───────┬─────┘ └───────┬─────┘ └───────┬──────────┘
        └───────────────┼───────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│  DATA / STORAGE LAYER                                       │
│  PostgreSQL (source of truth) · local dataset store         │
└─────────────────────────────────────────────────────────────┘
```

A second, narrower path:

```text
WEB / API ──► authenticated job queue ──► LOCAL AGENT ──► local compute
                                                      (backtests, datasets,
                                                       local models)
```

Full detail: [system architecture](docs/architecture/system-architecture.md).

---

## 3. Non-negotiable boundaries

1. **The browser never touches the PC filesystem.** The web tier talks to the
   API; only the API talks to the local agent; the local agent only touches
   explicitly allow-listed paths.
2. **The risk engine is independent of strategy logic.** A strategy emits a
   request. The risk engine evaluates it with its own rules, budgets and kill
   switches. There is no code path from a strategy to an approved order that
   bypasses risk.
3. **The trade gate is the last authority.** Even a risk-approved request
   fails if the gate is not in an allowed mode. Live mode is refused outright.
   See [risk engine](docs/architecture/risk-engine.md).
4. **The database is the source of truth.** AI conversational memory may
   propose; it may never be authoritative for project state.
5. **Providers are behind interfaces.** Domain code never imports a vendor
   SDK. See [data platform](docs/architecture/data-platform.md).
6. **A backtest is evidence, never proof.** No report, UI string or document
   may present it as a promise. See
   [backtesting methodology](docs/research/backtesting-methodology.md).

---

## 4. Repository map

| Path                         | Responsibility                                                  |
| ---------------------------- | ---------------------------------------------------------------- |
| `apps/web`                   | Next.js front end (Phase 1)                                     |
| `apps/api`                   | FastAPI service entrypoint (Phase 1)                            |
| `apps/local-agent`           | Local compute bridge (Phase 11)                                 |
| `src/harsh_quant_os`         | Shared Python foundation: config, safety gates, contracts       |
| `packages/types`             | Shared TypeScript types mirroring Python contracts              |
| `packages/shared`            | Pure, tested TypeScript helpers                                 |
| `packages/data`              | Data-access libraries (Phase 3)                                 |
| `packages/quant`             | Feature and statistics libraries (Phase 5)                      |
| `packages/risk`              | Risk library (Phase 9)                                          |
| `packages/backtesting`       | Backtest library (Phase 6)                                      |
| `agents/`                    | AI agent specifications, one `AGENT.md` each                    |
| `docs/`                      | Architecture, development, security, operations, research, ADRs |
| `research/`                  | Experiments, hypotheses, reports, notebooks                     |
| `strategies/`                | Candidates, validated, rejected, archived                       |
| `data/`                      | Local datasets (never committed)                                |
| `tests/`                     | Mirrors the above, plus security and end-to-end                 |
| `scripts/`                   | Setup, development, data, maintenance                           |
| `infrastructure/`            | Docker, database, deployment, monitoring                        |

### Where shared Python code lives

Phase 0 puts the cross-cutting foundation in `src/harsh_quant_os/` rather than
inside `apps/api`, because the safety gates and contracts are needed by the
API, the local agent and the CLI alike. Service-specific code belongs to the
service; shared contracts belong to the foundation package. This is recorded
in [ADR-0001](docs/decisions/ADR-0001-initial-architecture.md).

---

## 5. Execution and trust boundaries

| Boundary                 | Crossing mechanism                              | Enforced by                                  |
| ------------------------ | ----------------------------------------------- | -------------------------------------------- |
| Browser → API            | HTTPS, session/JWT, RBAC                        | `apps/api` middleware (Phase 1)              |
| API → Database           | Connection string from environment, least privilege | `Settings` + migrations (Phase 2)         |
| API → Local agent        | mTLS/token, job payloads, operation allow-list  | Local agent auth + allow-lists (Phase 11)    |
| Local agent → filesystem | Path allow-list, per-job roots, no shell        | Agent sandbox (Phase 11)                     |
| Strategy → Order         | Signal → risk evaluation → trade gate           | Risk engine + `harsh_quant_os.safety.gates`  |
| Any component → broker   | Not implemented                                 | Blocked by policy and by configuration       |
| AI → anything            | Tool allow-list, no secrets, no risk bypass     | [AI system](docs/architecture/ai-system.md)  |

---

## 6. Cross-cutting concerns

- **Configuration** — one typed `Settings` object, loaded from the
  environment. Placeholders are rejected outside development/test.
- **Logging** — structured, level-controlled, never logging secrets.
- **Audit** — append-only records for gate decisions, job lifecycle and
  configuration changes.
- **Testing** — deterministic financial tests, security tests that fail the
  build when a safety invariant breaks. See
  [testing strategy](docs/development/testing-strategy.md).
- **Errors** — typed exceptions with user-safe messages; no swallowed
  failures.

---

## 7. Documentation index

- [Front end](docs/architecture/frontend.md) ·
  [Backend](docs/architecture/backend.md) ·
  [Database](docs/architecture/database.md)
- [Data platform](docs/architecture/data-platform.md) ·
  [Quant engine](docs/architecture/quant-engine.md) ·
  [Backtesting](docs/architecture/backtesting.md)
- [Risk engine](docs/architecture/risk-engine.md) ·
  [AI system](docs/architecture/ai-system.md) ·
  [Local agent](docs/architecture/local-agent.md) ·
  [Synchronization](docs/architecture/synchronization.md)
- [Roadmap](docs/ROADMAP.md) · [Project status](docs/PROJECT-STATUS.md) ·
  [Security](SECURITY.md) · [Agent constitution](AGENTS.md)
