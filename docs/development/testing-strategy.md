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
├── integration/   component interactions (Phase 1+)
├── security/      secrets, live-trading gate, policy enforcement
├── data/          provenance, validation, dataset contracts
├── quant/         golden values, statistical behaviour (Phase 5+)
├── backtesting/   engine correctness, reproducibility (Phase 6+)
└── end-to-end/    full workflows in a browser (Phase 4+)
```

Markers are registered in `pyproject.toml`: `unit`, `integration`,
`security`, `quant`, `backtesting`, `e2e`, `slow`.

---

## 3. What each layer uses

| Layer                    | Tool                  | Command                  |
| ------------------------ | --------------------- | ------------------------ |
| Python unit/integration  | pytest                | `npm run test:py`        |
| Python coverage          | pytest-cov            | `python -m pytest --cov` |
| TypeScript unit          | Vitest                | `npm run test`           |
| TypeScript coverage      | Vitest + v8 provider  | `npm run test:coverage`  |
| End-to-end browser       | Playwright (Phase 4+) | —                        |
| Lint/format/type gates   | Ruff, mypy, ESLint, `tsc`, Prettier | `npm run check` |

Run everything: `npm run check`.

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

`.github/workflows/ci.yml` runs on every push and pull request:

1. install (npm + pip, from lockfiles);
2. format check (Prettier, Ruff);
3. lint (ESLint, Ruff);
4. type check (`tsc`, `mypy`);
5. tests (Vitest, pytest, including the secret scan);
6. build/import check.

CI never deploys and never has access to production secrets.

---

## 9. What is explicitly not tested yet

Honest gaps, by phase: API routes and auth (Phase 1), database migrations
(Phase 2), ingestion (Phase 3), UI end-to-end (Phase 4), quant maths
(Phase 5), backtest engine (Phase 6), risk engine (Phase 9), local agent
permissions (Phase 11), sync (Phase 12).

See [../PROJECT-STATUS.md](../PROJECT-STATUS.md).
