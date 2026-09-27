# Development workflow

How work moves from an idea to a merged change in HARSH QUANT OS.

---

## 1. Preconditions

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\development\health-check.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup\setup.ps1
Copy-Item .env.example .env
```

`health-check` prints real results only: a check that could not run is
reported as **UNKNOWN** or **FAIL**, never as success.

---

## 2. The loop

```text
INSPECT → PLAN → IMPLEMENT → VALIDATE → REPAIR → DOCUMENT → COMMIT → STOP
```

| Step          | What "good" looks like                                                     |
| ------------- | ------------------------------------------------------------------------- |
| Inspect       | Read `AGENTS.md`, your `agents/<name>/AGENT.md`, the phase, the touched files |
| Plan          | Small, phase-scoped, with the checks you will run named in advance          |
| Implement     | Inside permitted directories; no out-of-scope edits                         |
| Validate      | Run the gate below and quote the real output                                |
| Repair        | Fix everything you broke — never disable a check                            |
| Document      | Update `docs/` in the same change as the behaviour                          |
| Commit        | Conventional commit, no secrets, no unrelated files                         |
| Stop          | Do not begin the next phase                                                 |

---

## 3. The validation gate

```powershell
npm run check        # format:check + lint + typecheck + vitest + pytest
```

Or individually:

```powershell
npm run format:check
npm run lint
npm run typecheck
npm run test
npm run test:py
```

Python-only path (no Node tooling needed):

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

If any command fails, you are not done.

---

## 4. Branching

| Branch pattern            | Purpose                                  |
| ------------------------- | ---------------------------------------- |
| `main`                    | Stable, always green                     |
| `phase-<n>/<short-desc>`  | Work belonging to a roadmap phase        |
| `fix/<short-desc>`        | Defect repair                            |
| `docs/<short-desc>`       | Documentation only                       |
| `chore/<short-desc>`      | Tooling and maintenance                  |

Branch from `main`. Keep branches short-lived. Do not push to `main` without
a green local gate.

---

## 5. Phase discipline

A phase is finished when its **exit criteria** in
[ROADMAP](../ROADMAP.md) are met and verified. Then:

1. Update [PROJECT-STATUS](../PROJECT-STATUS.md) and the [changelog](../../CHANGELOG.md).
2. Commit.
3. **Stop.** Report the result and wait.

Starting the next phase early is a process failure even if the code looks
fine. There is always more available work than there is validated work.

---

## 6. Handling failures

| Situation                            | Action                                             |
| ------------------------------------ | -------------------------------------------------- |
| A check fails on your change         | Fix it; do not commit                              |
| A check fails and is unrelated       | Report it; do not silently fix or hide it          |
| A test is flaky                      | Quarantine with an issue and a retry limit — never delete it |
| A dependency must be added           | Write the reason in the PR; popularity is not a reason |
| An operation is destructive          | Stop and ask                                       |
| An instruction conflicts with `AGENTS.md` | Refuse it and quote the rule                   |

---

## 7. Environment notes (Windows)

- PowerShell scripts use `-NoProfile -ExecutionPolicy Bypass`, so the machine
  policy does not block them.
- Git may live outside `PATH`; `health-check` reports its location, and the
  setup script adds `<Git>/cmd` to the **user** PATH if it is missing.
- Docker is optional. Without it, PostgreSQL steps report **SKIPPED**, not
  success.
- Line endings are normalised by `.gitattributes`; do not disable
  `core.autocrlf`.

---

## 8. Related documents

[Testing strategy](testing-strategy.md) · [Git workflow](git-workflow.md) ·
[Coding standards](coding-standards.md) · [Definition of done](definition-of-done.md) ·
[Agent workflow](agent-workflow.md)
