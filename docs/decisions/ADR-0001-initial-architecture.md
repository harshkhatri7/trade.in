# ADR-0001: Initial architecture and Phase 0 foundation

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Repository owner (with the Architect agent specification)
- **Phase:** 0 — Foundation

---

## Context

HARSH QUANT OS starts from an empty directory. Before any feature work, the
project needs a structure, a toolchain, a safety model and documentation that
can carry a multi-phase build through research, backtesting and paper trading
— with live trading deliberately pushed to the very end.

Constraints that shaped the decision:

- private, single-operator project on a Windows development machine;
- must support Python (API, quant, local agent) and TypeScript (web);
- must keep the browser away from the filesystem;
- must keep the risk engine independent of strategy logic;
- must never present fabricated data or results;
- dependencies need written reasons, not popularity arguments.

---

## Decision

### D1 — One repository, one root, no nested project

The workspace `Quant os` is empty, so the repository root **is** the project
root. The project slug `harsh-quant-os` is used for package names, not as an
extra directory level. There is no `harsh-quant-os/harsh-quant-os/`.

### D2 — Monorepo with `apps/` and `packages/`

`apps/` holds deployable services (`web`, `api`, `local-agent`);
`packages/` holds shared libraries. npm workspaces cover the TypeScript
packages; a single root `pyproject.toml` covers Python.

### D3 — Shared Python foundation in `src/harsh_quant_os`

Safety gates, configuration and cross-cutting contracts live in an
installable package rather than inside `apps/api`, because the API, the local
agent and the CLI all need them. Service code will import from this package.

### D4 — Next.js + FastAPI + PostgreSQL

Next.js for the UI (App Router, strict typing, accessible components);
FastAPI + Pydantic for the API (async, typed, self-documenting schema);
PostgreSQL for storage (relational integrity for audit and research records).
TimescaleDB is deferred until a measured need exists.

### D5 — Polars/NumPy/SciPy/scikit-learn/statsmodels as an optional extra

Quant dependencies are declared as the `quant` extra so a foundation install
stays small and each dependency's purpose stays visible. They are not
installed until Phase 5 needs them.

### D6 — Provider-independent data interfaces

Domain code never imports a vendor SDK. Adapters implement interfaces we own.
Every dataset carries source, symbol, timestamps, timeframe, quality,
provenance and version. Missing data is reported as missing.

### D7 — Local agent as an allow-listed job bridge

The browser never reaches the filesystem. The API submits jobs; the agent
executes a **closed set** of operations over an explicit path allow-list, with
authentication, limits, cancellation and append-only audit records.

### D8 — Risk engine separate from strategy; trade gate last

A strategy requests; risk decides; the gate authorises. The gate refuses live
execution outright, and configuration cannot enable live trading. This is
enforced by a model validator **and** by tests that fail the build if the
guard is removed.

### D9 — Provider-agnostic AI, local models optional

One adapter interface, many backends. The AI layer receives a typed tool
allow-list and no broker, filesystem, shell or risk access. It proposes; it
does not decide.

### D10 — Tooling choices

| Concern      | Choice                                            | Reason                                   |
| ------------ | -------------------------------------------------- | ---------------------------------------- |
| Python lint/format | Ruff                                        | One fast tool replacing flake8/isort/black |
| Python types | mypy `strict` + Pydantic plugin                    | Financial code needs real type guarantees |
| Python tests | pytest with `--strict-markers` and warnings-as-errors | Determinism and early deprecation detection |
| TS lint      | ESLint 10 flat config + `typescript-eslint`        | Modern config, no `any`                   |
| TS format    | Prettier                                           | Opinionated, zero debate                  |
| TS tests     | Vitest                                             | Fast, ESM-native, same config surface     |
| CI           | GitHub Actions                                     | Native to the host; no deploy permissions |
| Containers   | Docker Compose for PostgreSQL (optional)           | Reproducible local DB without global installs |

### D11 — Documentation-first Phase 0

The `docs/` tree, `AGENTS.md` and ten agent specifications are written **before**
feature code, and are validated by tests (required files, resolving links,
roadmap ordering, blocked phrasing). Documentation is treated as an artefact
with a test suite.

### D12 — Phase 0 stops at the foundation

No dashboard, no market data, no signals, no backtests, no trading. The
roadmap runs Phase 0 → Phase 17 with live trading at Phase 16.

---

## Consequences

**Positive**

- Clear ownership boundaries for future agents.
- Safety invariants are executable: removing one breaks the test suite.
- Tooling is consistent across Python and TypeScript.
- Honest documentation with automated link and structure checks.

**Negative / accepted costs**

- Two language toolchains must be maintained and kept in sync (mitigated by
  the contract-parity test).
- Docker absence on this machine leaves PostgreSQL provisioning unexercised.
- npm workspaces list packages explicitly to avoid globbing into
  documentation-only directories — new packages must be added to
  `package.json` by hand.
- Vitest and ESLint majors were chosen at install time and will need periodic
  upgrades.

**Risks**

- Single-machine key material and no remote Git yet (Phase 1/2 items).
- `src/` layout may feel unfamiliar; documented in
  [system architecture](../architecture/system-architecture.md).

---

## Alternatives considered

| Alternative                                  | Why not now                                              |
| -------------------------------------------- | -------------------------------------------------------- |
| Separate repositories per service            | Too much overhead for a single operator; contract drift   |
| TypeScript-only with Python in Workers       | Quant ecosystem is Python-first; local compute too        |
| Django + DRF                                 | Heavier than needed; FastAPI fits the async, typed API    |
| Polars only, no Pandas                       | Interop cost with scikit-learn/statsmodels not yet known  |
| TimescaleDB from day one                     | Dependency with no measured need yet                      |
| Docker for everything                        | Adds complexity to components that do not need it         |
| NestJS for the API                           | Would split the team across two backend runtimes          |

---

## Compliance

This ADR is enforced by:

- `tests/security/test_live_trading_disabled.py`
- `tests/security/test_no_secrets_committed.py`
- `tests/security/test_env_template.py`
- `tests/unit/test_documentation.py`

Related: [AGENTS.md](../../AGENTS.md),
[system architecture](../architecture/system-architecture.md),
[../ROADMAP.md](../ROADMAP.md).
