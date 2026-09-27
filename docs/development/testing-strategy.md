# Testing strategy

Tests are the evidence that a claim about the code is true. A check that did
not run is reported as **not run** — never as passing.

---

## 1. Principles

1. **Deterministic financial tests.** Money and returns are computed with
   fixed inputs and expected values. No `assertAlmostEqual` by luck; exact
   where the arithmetic is exact, and explicitly tolerance-based where
   floating point requires it — with the tolerance justified in a comment.
2. **Fail-closed security tests.** Every safety control has a test that fails
   when the control is removed.
3. **No fabricated data.** Fixtures are clearly synthetic and labelled as
   such; they are never presented as market history.
4. **Every bug gets a regression test** that fails before the fix.
5. **`filterwarnings = ["error"]`** in pytest: a deprecation is a failure,
   not a nuisance.
6. **No deleted tests to make a build green.**

---

## 2. Test layout

```text
tests/
├── unit/          pure logic: config, gates, contracts, helpers
├── api/           FastAPI routes, error mapping, CORS, config, contract parity
├── web/           API client and component tests (Vitest + jsdom)
├── contracts/     shared contract fixture: system-status.json
├── integration/   real boundaries, two halves:
│                  ├── test_api_http.py       API process → real HTTP → assertions
│                  └── api-web-flow.test.tsx  API process → typed client → DOM
├── security/      secrets, live-trading gate, policy enforcement
├── data/          provenance, validation, dataset contracts
├── quant/         golden values, statistical behaviour (Phase 5+)
├── backtesting/   engine correctness, reproducibility (Phase 6+)
└── end-to-end/    full workflows in a browser (Phase 4+)
```

Markers are registered in `pyproject.toml`: `unit`, `integration`,
`security`, `quant`, `backtesting`, `e2e`, `slow`.

The TypeScript side of `tests/` is excluded from the root `tsconfig.json`
(the web app's config includes it instead) so `npm run typecheck` checks both
projects exactly once each.

A check that cannot run must say so: the TypeScript integration suite prints
the reason it skipped (no Python with FastAPI), and CI runs it in a job where
Python is installed, so it cannot skip there unnoticed.

---

## 3. What each layer uses

| Layer                    | Tool                  | Command                  |
| ------------------------ | --------------------- | ------------------------ |
| Python unit/integration  | pytest                | `npm run test:py`        |
| Python coverage          | pytest-cov            | `python -m pytest --cov` |
| TypeScript unit          | Vitest                | `npm run test`           |
| TypeScript components    | Vitest + jsdom + Testing Library | `npm run test`   |
| Integration (API → DOM)  | Vitest + a real API process | `npm run test:integration` |
| TypeScript coverage      | Vitest + v8 provider  | `npm run test:coverage`  |
| End-to-end browser       | Playwright (Phase 4+, not installed) | —          |
| Lint/format/type gates   | Ruff, mypy, ESLint, `tsc`, Prettier | `npm run check` |

Run everything: `npm run check` (format, lint, typecheck, Vitest, pytest).

---

## 4. Coverage expectations

Coverage is a floor, not a goal. Targets:

| Area                                | Floor |
| ----------------------------------- | ----- |
| Safety gates, risk, money maths     | 100 % of branches |
| Data validation and provenance      | 90 %   |
| Services and routers                | 80 %   |
| UI components                       | 70 %   |

A number with no test behind it is not covered, regardless of the report.

---

## 5. Financial test rules

- Use hand-computable fixtures: a five-bar series with known answers.
- Assert on money with exact decimal expectations, not eyeballed floats.
- Test the *edges*: zero denominators, empty series, single observations,
  gaps in data, market closures.
- Test timezone handling explicitly — a naive timestamp must be rejected.
- Property tests belong here: monotonicity of cumulative returns, ordering
  invariants, conservation of cash across a round trip.

---

## 6. Security test rules

A change to any of these areas must add or update a test:

- configuration safety validation;
- the trade gate;
- secrets handling;
- local-agent operation and path allow-lists;
- authorisation on an endpoint.

Current examples that already fail the build when weakened:
`tests/security/test_live_trading_disabled.py`,
`tests/security/test_no_secrets_committed.py`,
`tests/security/test_env_template.py`.

---

## 7. Documentation tests

`tests/unit/test_documentation.py` verifies:

- every required document exists;
- every agent `AGENT.md` has its required sections;
- relative Markdown links resolve;
- the roadmap contains PHASE 0 … PHASE 17 in order;
- project status matches the declared version, phase and capital;
- no document contains a blocked absolute claim about returns.

Documentation is treated as an artefact with tests, not as optional prose.

---

## 8. Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request, in four jobs:

1. **TypeScript** — install (npm, from the lockfile), format check
   (Prettier), lint (ESLint), type check (`tsc` for the root project and for
   `apps/web`), tests (Vitest), `next build`, dependency audit.
2. **Python** — install (`pip install -e ".[dev]"`), format check (Ruff
   format), lint (Ruff check), type check (`mypy` strict), tests (pytest,
   including the security and documentation suites), coverage report.
3. **Integration** — installs both toolchains and runs the integration
   suites for real: `npm run test:integration` (API process → typed client →
   DOM) and `pytest tests/integration` (API process over HTTP). This job
   exists so the TypeScript integration suite cannot skip for lack of Python
   and still report a green build.
4. **Repository policy** — `.env` must not be tracked, `LIVE_TRADING_ENABLED`
   must be false in the template, no unexpectedly large files.

CI never deploys, never places an order, and never has access to production
secrets.

---

## 9. What is explicitly not tested yet

Honest gaps, by phase: authentication and sessions (not implemented — Phase 2,
see [ADR-0003](../decisions/ADR-0003-authentication-deferred.md)), database
migrations (Phase 2), ingestion (Phase 3), UI end-to-end in a real browser
(Phase 4; Playwright is not installed), quant maths (Phase 5), backtest
engine (Phase 6), risk engine (Phase 9), local agent permissions (Phase 11),
sync (Phase 12).

What Phase 1 does cover: API routes and error mapping, the shared contract in
both directions, the typed client's failure modes, each rendered UI state,
and the full API → client → DOM chain against a live server.

See [../PROJECT-STATUS.md](../PROJECT-STATUS.md).
