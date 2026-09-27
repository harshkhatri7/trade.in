# Changelog

All notable changes to HARSH QUANT OS are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). The display
version `0.1.0-alpha` corresponds to PEP 440 `0.1.0a0`.

---

## [Unreleased]

_Nothing yet._

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
