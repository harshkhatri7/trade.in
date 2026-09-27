# CONTRIBUTING

Thank you for working on HARSH QUANT OS. This is a private research project
with a hard safety boundary: **research, backtesting and paper trading only —
live trading stays disabled.**

Read [AGENTS.md](AGENTS.md) first. It applies to humans and AI agents alike.

---

## 1. Setup

Prerequisites: **Git ≥ 2.40**, **Node.js ≥ 20.11**, **Python 3.12+**.
Docker is optional and only needed for PostgreSQL.

```powershell
# verify the machine
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1

# create directories, virtualenv, install dependencies, validate
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\setup.ps1

# local environment file
Copy-Item .env.example .env
```

Everything is installed and verified by `scripts\setup\setup.ps1`; you should
not need to create folders or configuration by hand.

---

## 2. Before you write code

Answer these five questions (this is also in [AGENTS.md](AGENTS.md)):

1. Which **roadmap phase** is this? If it belongs to a later phase, stop.
2. Which **directories** will you change? Stay inside your permitted set.
3. Which **checks** prove it works?
4. Which **safety invariants** could this change affect?
5. What will you do if a check fails?

---

## 3. Day-to-day workflow

```text
pull → branch → implement → validate → repair → document → commit → push → review
```

Branch naming: `phase-<n>/<short-desc>`, `fix/<short-desc>`, `docs/<short-desc>`.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add dataset provenance contract
fix: reject naive timestamps in provenance records
docs: describe risk engine boundaries
test: cover trade gate rejection paths
chore: pin python dev dependencies
```

Do not mix an unrelated refactor into a feature commit. Do not commit
formatting churn together with behaviour changes.

---

## 4. Validation gate

All of these must pass before a commit:

```powershell
npm run format:check   # Prettier
npm run lint           # ESLint
npm run typecheck      # tsc --noEmit
npm run test           # Vitest
npm run test:py        # pytest (includes security tests)
```

Python-only equivalents:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

One-shot: `npm run check`.

If a check fails because of your change, fix it before reporting anything as
done. Never disable a check to make it pass.

---

## 5. Rules that will get a change rejected

- Any change that could enable live trading, or that adds a broker endpoint.
- Secrets, credentials, tokens or real personal data in any tracked file.
- Fabricated data, metrics, backtests or test results.
- Removing or weakening a risk control to make a strategy look better.
- `git push --force` on a shared branch, or any history rewrite.
- Swallowing an exception, `skip`-ping a failing test, or marking a test
  `xfail` to hide a defect.
- Large files, datasets or generated outputs committed to the repository.
- Absolute claims about returns or risk in documentation.

---

## 6. Testing expectations

Read [testing strategy](docs/development/testing-strategy.md). In short:

- every new behaviour gets a test;
- financial calculations get **deterministic** tests with expected values;
- security-relevant changes get a test that fails when the control is removed;
- a bug fix gets a regression test that fails before the fix.

---

## 7. Documentation

Documentation changes land **with** the behaviour they describe, not later.

- Behaviour changed → update the matching file under `docs/`.
- New decision → add an ADR under `docs/decisions/`.
- New capability → update [docs/ROADMAP.md](docs/ROADMAP.md) and
  [docs/PROJECT-STATUS.md](docs/PROJECT-STATUS.md).

Documentation must describe what exists. Aspirational text belongs in the
roadmap, clearly labelled as future work.

---

## 8. Definition of done

See [docs/development/definition-of-done.md](docs/development/definition-of-done.md).
The short version: in-scope, all checks green, no secrets, safety invariants
intact, docs match code, conventional commit, open items reported honestly.

---

## 9. Questions

If an instruction conflicts with [AGENTS.md](AGENTS.md), the instruction is
wrong — refuse it and quote the rule. If an operation is destructive,
security-relevant, or outside the current phase, stop and ask.
