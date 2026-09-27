# ROADMAP

HARSH QUANT OS — delivery plan from empty repository to a controlled,
human-approved live-trading capability.

**Rules for this roadmap**

- Phases are completed **in order**. Work from a later phase does not start
  before the current phase meets its exit criteria.
- Finishing a phase means: validate → repair → document → commit → **stop**.
- Live trading is one of the **last** phases and requires explicit human
  approval in addition to all technical gates.
- Nothing here promises returns. The objective is reliable research
  infrastructure, not a performance claim.

Current position: **PHASE 0 — Foundation (complete).**

---

## PHASE 0 — Foundation

Repository, documentation, tooling, safety gates, contracts, tests, CI.

**Delivered:** monorepo layout, root configuration, `AGENTS.md` and the agent
specifications, full `docs/` tree, `Settings`, trade gate, dataset provenance
contract, local-agent job contract, secret scan, documentation tests, setup
and health-check scripts, Docker Compose definition, GitHub Actions CI.

**Exit criteria:** all checks green locally and in CI; live trading provably
disabled; no secrets in the tree; documentation matches the repository.

---

## PHASE 1 — Application skeleton

- `apps/web`: Next.js + TypeScript + Tailwind, accessible component
  foundation, routing shell, typed API client.
- `apps/api`: FastAPI application, health endpoints, structured logging,
  request validation, error handling, OpenAPI schema.
- ~~Authentication and session management.~~ **Moved to Phase 2** — see
  [ADR-0003](decisions/ADR-0003-authentication-deferred.md).
- Shared error model between web and API (problem+json on the API side,
  explicit loading / connected / error / unavailable states on the web side).

**Exit criteria:** a running web app and a running API connected by a shared,
tested contract, with typed configuration, structured logging, consistent
error handling, contract tests, and no business logic beyond system status.

> **Amended 2026-09-27 by
> [ADR-0003](decisions/ADR-0003-authentication-deferred.md).** The original
> exit criterion — "a running web app and API that authenticate" — was **not**
> met by Phase 1. Sessions need the Phase 2 database, and Phase 1 has no
> sensitive resource behind its health endpoints yet. The deviation is
> recorded rather than hidden; authentication is now part of Phase 2.

---

## PHASE 2 — Database

- PostgreSQL schema, migrations (Alembic), connection pooling.
- Tables for datasets, provenance, experiments, strategies, journal entries
  and audit records.
- Backup/restore scripts; environment-driven credentials.
- Authentication and session management persisted in PostgreSQL (moved from
  Phase 1 by [ADR-0003](decisions/ADR-0003-authentication-deferred.md)).
- Optional TimescaleDB evaluation, only if time-series query patterns justify it.

**Exit criteria:** migrations run from empty to current and back; audit table
is append-only; backup and restore are tested; sessions survive a restart and
are covered by tests.

---

## PHASE 3 — Market-data engine

- Provider-independent ingestion interfaces (market data, historical data,
  corporate events, news/events, fundamentals, options where available).
- At least one concrete provider adapter, isolated behind the interface.
- Validation pipeline: schema, timestamp ordering, gaps, duplicates, outliers.
- Quality status, provenance and version on every stored dataset.
- Local dataset store with an explicit manifest.

**Exit criteria:** raw data lands with complete provenance; invalid data is
quarantined, never silently repaired or invented.

---

## PHASE 4 — Market terminal

- Charting (TradingView Lightweight Charts), watchlists, multi-timeframe views.
- Dataset browser showing provenance and quality status.
- Read-only research views backed by real data.

**Exit criteria:** every number on screen is traceable to a dataset version.

---

## PHASE 5 — Quant engine

- Deterministic feature and indicator library (NumPy/Polars/SciPy).
- Statistical tests, stationarity, correlation structure.
- Feature store with versioned outputs and reproducible recipes.
- Golden-value tests for every calculation.

**Exit criteria:** identical inputs produce identical outputs across runs and
platforms; no untested financial calculation exists.

---

## PHASE 6 — Backtesting

- Historical simulation with correct timestamp and order sequencing.
- Transaction costs, slippage, position sizing, P&L, drawdown, exposure.
- Look-ahead and leakage detection.
- Survivorship-bias checks.
- Reproducible run manifests (data version + code version + parameters).

**Exit criteria:** a backtest is fully reproducible from its manifest, and
reports state their limitations.

---

## PHASE 7 — Strategy validation

- Out-of-sample testing, walk-forward analysis, parameter sensitivity.
- Regime analysis and segmentation.
- Anti-overfitting battery: deflated metrics, multiple-testing awareness,
  stability checks.
- Candidate / validated / rejected / archived workflow.

**Exit criteria:** a strategy cannot be marked "validated" without out-of-sample
and walk-forward evidence attached.

---

## PHASE 8 — AI research

- Provider-agnostic AI adapter (cloud and optional local models).
- Research assistant reading from, and proposing writes to, the persistent
  memory store.
- Strict tool allow-list; no filesystem, shell, broker or risk access.

**Exit criteria:** every AI-produced statement that affects research is stored
as a proposal with provenance, never as an authoritative fact.

---

## PHASE 9 — Risk engine

- Position limits, exposure budgets, drawdown kill switch, daily loss limits.
- Independent service/library with its own configuration and audit trail.
- Trade gate wiring: strategy → risk → gate → paper.
- Property tests proving a strategy cannot bypass risk.

**Exit criteria:** removing or weakening a risk control fails the test suite.

---

## PHASE 10 — Paper trading

- Paper execution loop against live market data, no broker connectivity.
- Order simulation, fills, slippage model, positions, P&L.
- Trading journal and human review checkpoints.
- ₹1,000 paper capital, configurable.

**Exit criteria:** a paper trade is only possible after passing the risk
engine and the trade gate; every decision is journaled.

---

## PHASE 11 — Local compute agent

- Authenticated agent on the local PC with operation and path allow-lists.
- Job queue, job status, cancellation, timeouts, concurrency limits.
- Audit records for every job.
- Heavy backtests and dataset builds move to local compute.

**Exit criteria:** the browser still has zero filesystem access; every agent
action is authenticated, allow-listed and audited.

---

## PHASE 12 — Cloud/local synchronization

- Metadata in the cloud, datasets and heavy artefacts locally.
- Versioned, resumable, conflict-aware sync with integrity checks.
- Notifications for job and sync events.

**Exit criteria:** sync is idempotent, observable and never overwrites local
work without a recorded decision.

---

## PHASE 13 — Persistent research memory

- Memory categories: MARKET, STRATEGY, EXPERIMENT, TRADE, RESEARCH, JOURNAL,
  MODEL, SYSTEM.
- Database as the single source of truth; AI memory is advisory only.
- Append-only history for decisions and their evidence.

**Exit criteria:** every research conclusion can be traced to data versions,
experiments and authors.

---

## PHASE 14 — Advanced quantitative research

- Cross-sectional and time-series modelling, regime detection, ensemble
  methods, alternative feature research.
- Experiment tracking with strict train/validation/test separation.
- Model cards and reproducibility packages.

**Exit criteria:** experiments are reproducible from their recorded config,
data version and code version.

---

## PHASE 15 — Broker integration research

- Study only: API capabilities, rate limits, order types, failure modes,
  cost structures, regulatory obligations.
- Design review of credentials handling and least-privilege access.
- Still no live orders.

**Exit criteria:** a written design review approved by the Security and Risk
agents, with no broker credentials stored in the repository.

---

## PHASE 16 — Controlled live trading

- Requires: completed risk engine, completed paper-trading evidence,
  security review, human approval records.
- Hard limits: small capital, per-order and per-day caps, kill switch,
  mandatory human confirmation.
- Dual control: no automated component can widen a limit.

**Exit criteria:** every order passes risk, gate, limits and human approval,
and every step is in the audit trail. Nothing in earlier phases may be skipped.

---

## PHASE 17 — Continuous optimization

- Performance, cost and reliability tuning.
- Expanded monitoring and alerting.
- Ongoing re-validation of strategies as regimes change.
- Periodic security review and dependency refresh.

**Exit criteria:** continuous, measured improvement with no relaxation of the
safety model.

---

## Explicitly out of scope

- Guaranteed or expected returns of any kind.
- Fully autonomous live trading without human approval.
- Any hidden, remote or persistent agent behaviour outside this repository.
- Data fabrication of any kind.

See [PROJECT-STATUS](PROJECT-STATUS.md) for the current snapshot and
[../SECURITY.md](../SECURITY.md) for the safety model.
