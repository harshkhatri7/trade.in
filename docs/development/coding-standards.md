# Coding standards

Applies to every language in this repository. Where a rule conflicts with a
tool configuration, the tool configuration is changed deliberately and the
change is documented.

---

## 1. Universal rules

1. **No `any` in TypeScript.** ESLint treats `@typescript-eslint/no-explicit-any`
   as an error.
2. **No untyped public Python API.** `mypy --strict` must pass.
3. **No hidden global state.** Dependencies are passed explicitly; no
   module-level mutable singletons.
4. **No magic constants.** Named, documented, and where relevant configurable.
5. **No giant files.** If a file is hard to navigate, split it by
   responsibility rather than by length alone.
6. **No duplicated business logic.** Two implementations of one rule is a bug
   waiting to happen — share it.
7. **No swallowed exceptions.** Catch only to add context or to translate to
   a typed error, and always log or re-raise.
8. **No untested financial calculation.** If it moves money or measures it,
   it has a test with a known answer.
9. **No dead code.** Delete it; Git remembers.
10. **No silent failure.** Prefer raising over returning a plausible-looking
    default.

---

## 2. Python

- Target: **3.12**. Modern syntax (`X | None`, `match`, dataclasses, `slots`).
- Formatter and linter: **Ruff** (`ruff format`, `ruff check`), line length 100.
- Type checking: **mypy strict** with the Pydantic plugin.
- Imports: `harsh_quant_os` is the only first-party root; no circular imports.
- Pydantic models: declare intent with `Field` descriptions; validate at the
  boundary, not deep inside the domain.
- Errors: define typed exceptions close to their origin; the API layer maps
  them to responses in one place.
- Logging: `logging` with structured context; never log secrets or full
  payloads.
- No `print()` outside the CLI and scripts (enforced by Ruff `T20`).

Example shape:

```python
def evaluate(settings: Settings, mode: TradingMode) -> TradeGateResult:
    """Evaluate a trade request against the safety gate.

    Raises LiveTradingBlockedError when live execution is requested.
    """
```

---

## 3. TypeScript

- `strict: true`, `noUncheckedIndexedAccess`, `noImplicitOverride`,
  `noFallthroughCasesInSwitch`, `verbatimModuleSyntax`.
- `type` imports where possible (enforced by
  `@typescript-eslint/consistent-type-imports`).
- Prefer discriminated unions over optional-field soup.
- No `console.log` in library code (ESLint `no-console`), only `warn`/`error`.
- Pure functions for anything numeric, and tested (see
  `@harsh-quant-os/shared`).
- Keep types in `@harsh-quant-os/types`; mirror Python contracts and let the
  parity test catch drift.

---

## 4. Documentation

- Public module, class and function documentation explains **why** and the
  invariants, not just the signature.
- Comments describe intent and constraints; they never describe what the
  next line obviously does.
- Update `docs/` in the same change as the behaviour.
- Never write aspirational documentation in the present tense.

---

## 5. Naming

| Kind                    | Convention                  | Example                    |
| ----------------------- | --------------------------- | -------------------------- |
| Python module/package   | `snake_case`                 | `live_trading.py`          |
| Python class            | `PascalCase`                 | `DatasetProvenance`        |
| Python function/variable| `snake_case`                 | `resolve_trading_mode`     |
| TypeScript file         | `kebab-case` or `index.ts`   | `contract-parity.test.ts`  |
| TS type/function        | `PascalCase` / `camelCase`   | `TradingMode`, `roundTo`   |
| Constants               | `UPPER_SNAKE` (Py), `UPPER` (TS) | `MEMORY_CATEGORIES`   |
| Environment variables   | `UPPER_SNAKE`                | `LIVE_TRADING_ENABLED`     |
| Git branch              | `<type>/<short-desc>`        | `phase-1/api-skeleton`     |

Avoid abbreviations unless they are standard in the domain (`pnl`, `ohlc`,
`ts`).

---

## 6. Testing conventions

- Test names describe behaviour: `test_gate_rejects_paper_when_disabled`.
- One behaviour per test; arrange/act/assert readable at a glance.
- Fixtures are explicit about being synthetic.
- No test depends on execution order, wall-clock time, or the network.

---

## 7. Dependency policy

- Every dependency needs a written reason in the pull request.
- Prefer the standard library.
- Pin ranges; review lockfile diffs.
- No install scripts from unknown packages; no unreviewed binaries.
- Remove dependencies that stop being used.

Current runtime dependencies and their reasons are documented in
`pyproject.toml` and `package.json`.

---

## 8. Security in code

- Never hardcode a credential; read from `Settings`.
- Never build a shell command from user input. (Prefer not to shell out at
  all.)
- Canonicalise and validate every path before use.
- Fail closed: missing permission means denial.
- Never log tokens, keys, passwords or full request bodies.

See [../../SECURITY.md](../../SECURITY.md).
