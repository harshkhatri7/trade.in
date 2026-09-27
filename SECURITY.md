# SECURITY

**Status:** Phase 0 — Foundation. **Live trading:** DISABLED. **Broker:** not
connected.

Security in HARSH QUANT OS is about two things: protecting credentials and
infrastructure, and protecting the researcher from their own system doing
something irreversible with money.

---

## 1. Security principles

1. **Deny by default.** Anything not explicitly allowed is refused — paths,
   operations, network targets, trade modes.
2. **Least privilege.** Each component, agent and AI tool gets the smallest
   access that lets it do its job.
3. **Separation of duties.** Strategy proposes, risk disposes, gate authorises,
   human approves. No single component holds all four.
4. **No secrets in the repository.** Ever, in any file, including tests and
   documentation.
5. **Append-only audit.** Audit records are written, never edited or deleted
   by application code.
6. **Fail closed.** When a check cannot run, the answer is "no", not "yes".

---

## 2. Trading safety (the core control)

| Control                                    | Where enforced                              | Status    |
| ------------------------------------------ | ------------------------------------------- | --------- |
| `LIVE_TRADING_ENABLED=true` is rejected    | `Settings` model validator, at load time    | Enforced  |
| Live trade requests raise                  | `harsh_quant_os.safety.gates`               | Enforced  |
| Paper mode must be explicitly enabled      | `Settings.paper_trading_enabled`            | Enforced  |
| Strategy cannot override risk              | Architectural: risk is a separate layer     | Enforced  |
| Broker SDK / endpoints                     | Not present in the codebase                 | Enforced  |
| Human approval before any live order       | Phase 16 requirement                        | Not built |

Enforcement is verified by `tests/security/test_live_trading_disabled.py`, so
removing the guard breaks the build.

---

## 3. Secrets management

- `.env` is git-ignored; `.env.example` holds placeholders only.
- Secrets are read through the typed `Settings` object, never `os.environ`
  scattered through the codebase.
- Placeholder values are detected (`missing_secrets()`) and rejected outside
  `development`/`test`.
- AI providers, data providers and notification channels each get their own
  key so they can be rotated independently.
- See [secrets management](docs/security/secrets-management.md).

---

## 4. The AI layer may not

- read or write arbitrary parts of the filesystem;
- run arbitrary shell commands;
- make unrestricted network calls;
- see broker credentials (it must never have them);
- bypass, weaken or reconfigure the risk engine;
- modify, truncate or delete audit history;
- change any setting that would enable live trading.

Local AI stays optional. A cloud model and a local model are both reached
through the same provider-agnostic adapter with the same restrictions.
See [AI system](docs/architecture/ai-system.md).

---

## 5. The local agent

The local agent is the only component with access to the researcher's PC, and
it is deliberately narrow:

- shared-token authentication plus explicit job authorisation;
- an **operation allow-list** (an unknown operation is rejected outright);
- a **path allow-list** per job — no roots means no access at all;
- job IDs, status transitions, timeouts, concurrency limits and cancellation;
- structured logs and append-only audit records;
- no shell execution, ever.

See [local agent security](docs/security/local-agent-security.md).

---

## 6. Dependency and supply-chain hygiene

- `npm audit` and `pip` come from a lockfile-protected install; CI fails on
  known vulnerabilities.
- Install scripts are reviewed; unknown executables are not downloaded.
- Development dependencies are pinned to ranges recorded in
  `package.json` / `pyproject.toml`.
- Docker images are pinned by tag in [infrastructure/docker](infrastructure/docker).

---

## 7. Automated verification

| Check                                                | Command                        |
| ---------------------------------------------------- | ------------------------------ |
| Secret scan of the working tree                      | `npm run test:py` (security)   |
| `.env.example` placeholder validation                | `npm run test:py` (security)   |
| Live-trading gate tests                              | `npm run test:py` (security)   |
| Documentation policy (no absolute return claims)     | `npm run test:py` (unit)       |
| Git-ignore coverage for secrets                      | `npm run test:py` (security)   |

These run in CI on every push; a regression turns the pipeline red.

---

## 8. Reporting a vulnerability

Do **not** open a public issue. Contact the repository owner directly with:

1. the affected file or endpoint;
2. a minimal reproduction;
3. the impact you believe it has;
4. any suggested fix.

You will get an acknowledgement, an honest assessment, and a fix before any
public disclosure.

---

## 9. Known gaps at Phase 0

- No authentication exists yet (Phase 1); there is no running API.
- No rate limiting, CSRF or session management yet (Phase 1).
- No database encryption at rest yet (Phase 2).
- No runtime audit store yet; gate decisions are tested but not persisted
  (Phase 9/10).
- No broker integration — by design, until Phase 15/16.

These are phase-scheduled, not oversights. See
[docs/ROADMAP.md](docs/ROADMAP.md) and
[threat model](docs/security/threat-model.md).
