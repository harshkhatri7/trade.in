# System architecture

**Phase:** 0 — Foundation. This document describes the target architecture
and what exists today. Sections marked *not implemented* have no code yet.

---

## 1. Overview

```text
                     ┌──────────────────────────────┐
                     │  Browser (untrusted client)  │
                     └──────────────┬───────────────┘
                                    │ HTTPS, session
                     ┌──────────────▼───────────────┐
                     │  WEB  · apps/web (Next.js)   │
                     └──────────────┬───────────────┘
                                    │ REST / JSON
                     ┌──────────────▼───────────────┐
                     │  API  · apps/api (FastAPI)   │
                     │  auth · RBAC · validation    │
                     └───────┬──────────────┬───────┘
                             │              │
              ┌──────────────▼───┐          │  authenticated job
              │ APPLICATION      │          │  submission
              │ SERVICES         │          │
              │ orchestration,   │          │
              │ transactions,    │          │
              │ audit writing    │          │
              └───┬───────┬──┬───┘          │
                  │       │  │              │
        ┌─────────▼──┐ ┌──▼──▼────────┐ ┌───▼────────────────┐
        │  DOMAIN    │ │ QUANT · RISK │ │ JOB QUEUE          │
        │  pure      │ │ · BACKTEST   │ │ id, status, limits │
        │  logic     │ │ libraries    │ └───┬────────────────┘
        └─────┬──────┘ └──────┬───────┘     │
              │               │      ┌──────▼─────────────────┐
        ┌─────▼───────────────▼──┐   │ LOCAL AGENT (your PC)  │
        │ STORAGE                │   │ auth · allow-lists     │
        │ PostgreSQL (truth)     │   │ jobs · audit · limits  │
        │ local dataset store    │   └──────┬─────────────────┘
        └────────────────────────┘          │
                                    ┌───────▼────────────────┐
                                    │ LOCAL COMPUTE          │
                                    │ backtests, datasets,   │
                                    │ ML experiments, models │
                                    └────────────────────────┘
```

---

## 2. Component inventory

| Component        | Path                  | Language / stack            | Phase | State          |
| ---------------- | --------------------- | --------------------------- | ----- | -------------- |
| Web UI           | `apps/web`            | Next.js, TypeScript, Tailwind | 1   | Not implemented |
| API              | `apps/api`            | Python, FastAPI, Pydantic   | 1     | Not implemented |
| Foundation       | `src/harsh_quant_os`  | Python 3.12                 | 0     | **Implemented** |
| Database         | PostgreSQL            | SQLAlchemy, Alembic         | 2     | Not implemented |
| Data platform    | `packages/data`       | Python                      | 3     | Not implemented |
| Quant engine     | `packages/quant`      | NumPy, Polars, SciPy        | 5     | Not implemented |
| Backtesting      | `packages/backtesting`| Python                      | 6     | Not implemented |
| Risk engine      | `packages/risk`       | Python                      | 9     | Not implemented |
| Local agent      | `apps/local-agent`    | Python                      | 11    | Not implemented |
| Shared TS types  | `packages/types`      | TypeScript                  | 0     | **Implemented** |
| Shared TS utils  | `packages/shared`     | TypeScript                  | 0     | **Implemented** |

---

## 3. Request paths

### 3.1 Read path (UI → data)

```text
Browser → API (authenticate) → Application service (authorise, audit)
        → Query repository → PostgreSQL → DTO → UI
```

### 3.2 Research path (strategy → order decision)

```text
DATA → VALIDATION → FEATURE ENGINEERING → STRATEGY → SIGNAL
     → RISK ENGINE → TRADE GATE → PAPER TRADING → HUMAN APPROVAL
                                                          ↓
                                              (future) LIVE EXECUTION
```

The last step is not implemented and is not reachable in this repository
before Phase 16 with explicit approval. See
[risk engine](risk-engine.md) and [backtesting](backtesting.md).

### 3.3 Local compute path

```text
Browser → API (authenticate, authorise) → Job queue (id, limits)
        → LOCAL AGENT (verify token, verify operation, verify path allow-list)
        → run under timeout + concurrency limit → audit record → status
```

The browser **never** receives a filesystem handle, a shell, or a direct
network route to the local machine. See [local agent](local-agent.md).

---

## 4. Cross-cutting rules

| Rule                        | Enforcement                                            |
| --------------------------- | ------------------------------------------------------ |
| One configuration object    | `harsh_quant_os.config.Settings`                      |
| No global mutable state     | Explicit dependency injection, no module-level singletons |
| Typed boundaries            | Pydantic models at API edge, TS types at UI edge       |
| Determinism in finance      | Golden tests; no wall-clock or random values in maths  |
| Append-only audit           | Audit table has no UPDATE/DELETE path in application code |
| Fail closed                 | Missing permission, missing data or failed check ⇒ reject |
| Provider independence       | Adapters implement interfaces; domain never imports a vendor |

---

## 5. Deployment shape

**Development** (Phase 0, today):

- Everything runs on the local Windows machine.
- `.venv` for Python, npm workspaces for TypeScript.
- PostgreSQL optional via `docker compose up -d postgres`.

**Target** (Phases 1–17):

| Tier        | Contents                                   | Where          |
| ----------- | ------------------------------------------ | -------------- |
| Cloud       | Web, API, auth, database, light jobs, metadata, notifications | Cloud |
| Local PC    | Heavy backtests, large datasets, ML experiments, local models, research, training | Local |
| Bridge      | Local agent (allow-listed job execution)   | Local, reached by API |

Sync details: [synchronization](synchronization.md).

---

## 6. What Phase 0 actually provides

Implemented and tested:

- `Settings` with safety validation ([backend](backend.md)).
- Trade gate: `resolve_trading_mode`, `evaluate_trade_gate`,
  `assert_live_trading_blocked` ([risk engine](risk-engine.md)).
- Dataset provenance contract ([data platform](data-platform.md)).
- Local-agent job contract with an operation allow-list
  ([local agent](local-agent.md)).
- Memory categories ([database](database.md)).
- Cross-language type parity enforced by tests.

Not implemented: everything else on this page. See
[../PROJECT-STATUS.md](../PROJECT-STATUS.md).

---

## 7. Related documents

[Frontend](frontend.md) · [Backend](backend.md) · [Database](database.md) ·
[Data platform](data-platform.md) · [Quant engine](quant-engine.md) ·
[Backtesting](backtesting.md) · [Risk engine](risk-engine.md) ·
[AI system](ai-system.md) · [Local agent](local-agent.md) ·
[Synchronization](synchronization.md) · [ADR-0001](../decisions/ADR-0001-initial-architecture.md)
