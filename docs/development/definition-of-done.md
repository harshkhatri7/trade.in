# Definition of done

A task is done when **every** box below is checked. Partial completion is
reported as partial — never as done.

---

## 1. Global checklist

### Scope

- [ ] Belongs to the **current roadmap phase** (see [../ROADMAP.md](../ROADMAP.md)).
- [ ] Touches only **permitted directories** for the acting agent
      (see [agent workflow](agent-workflow.md)).
- [ ] Does not start the next phase.

### Correctness

- [ ] `npm run format:check` passes.
- [ ] `npm run lint` passes.
- [ ] `npm run typecheck` passes.
- [ ] `npm run test` passes (Vitest).
- [ ] `npm run test:py` passes (pytest, including security tests).
- [ ] `ruff check .` and `mypy` report no new findings.
- [ ] When the change touches line endings, `.gitattributes`, generated
      files or the repository layout, `npm run check` also passes in a
      **fresh clone** — a working tree can be right and a clone wrong.
- [ ] New behaviour has tests; fixed bugs have regression tests.
- [ ] Financial calculations have deterministic expected-value tests.

### Safety

- [ ] Live trading remains disabled and unreachable.
- [ ] The risk engine remains independent of strategy logic; no bypass added.
- [ ] No broker SDK, endpoint or credential introduced.
- [ ] No secret, token, password or personal data added to any tracked file.
- [ ] Audit records remain append-only.
- [ ] No destructive operation performed on the workspace or history.

### Honesty

- [ ] No fabricated data, metrics, results or screenshots.
- [ ] Nothing claimed as passing unless the command was actually run and its
      real output observed.
- [ ] Failures, gaps and unfinished items are listed explicitly.
- [ ] No absolute claim about returns or risk anywhere in the change.

### Documentation

- [ ] `docs/` updated in the same change as the behaviour.
- [ ] Changelog updated for operator-visible changes.
- [ ] [PROJECT-STATUS](../PROJECT-STATUS.md) updated if the status changed.
- [ ] All relative documentation links still resolve.

### Version control

- [ ] Conventional commit message.
- [ ] No unrelated files, no generated artefacts, no datasets.
- [ ] Committed only after the gate passed.

---

## 2. Phase completion is bigger

Finishing a **phase** additionally requires:

- [ ] Every exit criterion in the roadmap for that phase is verified.
- [ ] CI is green on the phase's merge commit.
- [ ] Security-relevant changes reviewed by the Security agent.
- [ ] ADR written if an architectural decision was taken.
- [ ] `CHANGELOG.md` and `docs/PROJECT-STATUS.md` reflect reality.
- [ ] A short report of what was validated, what failed, what remains.
- [ ] **Stop.** Report and wait for direction before beginning the next phase.

---

## 3. What "done" does not mean

- "It compiles" is not done; it means it compiles.
- "Tests pass" is only meaningful if the tests are real and were run.
- "Looks right" is not verification for anything numeric.
- "It works on my machine" is a note, not evidence — say which checks ran.
- Documentation that describes an intention is not documentation; it belongs
  in the roadmap instead.

---

## 4. Reporting template

Use this when handing a task back:

```text
TASK      <what was asked>
PHASE     <roadmap phase>
CHANGED   <files/areas>
VALIDATED <commands run and their real results>
FAILED    <what failed and why — or "none">
OPEN      <unresolved items — or "none">
SAFETY    <live trading disabled? risk independent? secrets clean?>
NEXT      <exactly one recommended next task>
```
