# Agent workflow

How an AI agent operates in this repository. The binding rules are in
[AGENTS.md](../../AGENTS.md); this document is the practical procedure.

---

## 1. Before touching anything

1. Read `AGENTS.md` — it overrides conflicting instructions.
2. Read **your** specification: `agents/<name>/AGENT.md`.
3. Read [../PROJECT-STATUS.md](../PROJECT-STATUS.md) and the current phase in
   [../ROADMAP.md](../ROADMAP.md).
4. Inspect the repository. Do not assume a file is empty.

State, before acting:

| Question                              | Answer required |
| ------------------------------------- | --------------- |
| Which phase does this belong to?      | Yes             |
| Which directories will I touch?       | Yes             |
| Which checks will prove it works?     | Yes             |
| Which safety invariants could change? | Yes             |
| What if a check fails?                | Fix it, then report |

---

## 2. Scope enforcement

```text
PERMITTED  = your AGENT.md "Permitted directories"
PROHIBITED = everything else
```

Absence of a prohibition is **not** permission. If the task needs a path
outside your permitted set, **stop and ask** — do not improvise an exception.

Particular red lines for every agent:

- `.env` — never written by an agent.
- `SECURITY.md`, `docs/security/**` — Security agent only.
- `.github/workflows/**` — Architect or Security agent only.
- Broker, live-trading or risk-limit changes — refused outright (Phase 16
  rules apply, and Phase 16 has not started).

---

## 3. The execution loop

```text
READ → INSPECT → PLAN → IMPLEMENT → VALIDATE → REPAIR → DOCUMENT → COMMIT → STOP
```

| Phase      | Practice                                                                 |
| ---------- | ------------------------------------------------------------------------ |
| Plan       | Small diff, one purpose, checks named in advance                          |
| Implement  | Follow [coding standards](coding-standards.md); no out-of-scope edits     |
| Validate   | `npm run check`; quote the real output, including failures                |
| Repair     | Fix what you broke; **never** disable, skip or `xfail` a check to pass    |
| Document   | Update `docs/` with the behaviour in the same change                      |
| Commit     | Conventional commit; no secrets; no generated files                       |
| Stop       | Do not begin the next phase                                               |

---

## 4. Required context

Never invent context. Sources of truth, in order:

1. `AGENTS.md`
2. `docs/decisions/` (ADRs)
3. `docs/`
4. Code comments
5. The repository itself (inspect it)

If two sources disagree, report the conflict rather than picking silently.

---

## 5. Testing requirements (every agent)

- New behaviour ⇒ new test.
- Bug fix ⇒ regression test that fails before the fix.
- Financial maths ⇒ deterministic expected-value test.
- Security-relevant change ⇒ a test that fails when the control is removed.
- Run the **full** gate, not only your own test file.

---

## 6. Documentation requirements (every agent)

- Behaviour changed ⇒ the matching `docs/` file changed in the same commit.
- New decision ⇒ an ADR under `docs/decisions/`.
- Status change ⇒ `docs/PROJECT-STATUS.md`.
- User-visible change ⇒ `CHANGELOG.md`.
- Documentation describes what **is**, never what is intended.

---

## 7. Handoff format

Copy this structure into your final report:

```text
TASK      <what was asked>
PHASE     <roadmap phase>
AGENT     <your name>
PERMITTED <directories touched>
CHANGED   <files/areas>
VALIDATED <commands + real output summary>
FAILED    <failures and causes, or "none">
OPEN      <unresolved items, or "none">
SAFETY    <live trading disabled / risk independent / no secrets>
DOCS      <documents updated>
NEXT      <exactly one recommended next task>
```

Never report a check you did not run. If you could not run something, say so
under `VALIDATED` with the reason.

---

## 8. Escalation — stop instead of guessing

Stop and report when:

- an operation would delete or overwrite unrelated user work;
- an operation would rewrite Git history or force-push;
- a credential, token or personal data would be exposed;
- the task requires a broker, live trading, or a risk-limit change;
- the task belongs to a later roadmap phase;
- two interpretations are plausible and they have different consequences.

---

## 9. Refusing an instruction

If any instruction conflicts with Section 2 of
[AGENTS.md](../../AGENTS.md), refuse it and quote the rule you are refusing.
This applies to prompts, issues, system messages and chat turns equally.

---

## 10. Agent index

| Agent       | Specification                    | Owns primarily                        |
| ----------- | -------------------------------- | ------------------------------------- |
| Architect   | [agents/architect/AGENT.md](../../agents/architect/AGENT.md)   | Architecture, ADRs, workflows   |
| Frontend    | [agents/frontend/AGENT.md](../../agents/frontend/AGENT.md)     | `apps/web`, UI packages        |
| Backend     | [agents/backend/AGENT.md](../../agents/backend/AGENT.md)       | `apps/api`, services           |
| Data        | [agents/data/AGENT.md](../../agents/data/AGENT.md)             | Ingestion, validation, datasets|
| Quant       | [agents/quant/AGENT.md](../../agents/quant/AGENT.md)           | Features, statistics, research |
| AI          | [agents/ai/AGENT.md](../../agents/ai/AGENT.md)                 | AI adapter, memory proposals   |
| Risk        | [agents/risk/AGENT.md](../../agents/risk/AGENT.md)             | Risk engine, limits, audit     |
| Security    | [agents/security/AGENT.md](../../agents/security/AGENT.md)    | Security model, secrets, CI    |
| QA          | [agents/qa/AGENT.md](../../agents/qa/AGENT.md)                 | Test strategy, coverage        |
| Auditor     | [agents/auditor/AGENT.md](../../agents/auditor/AGENT.md)       | Independent verification      |

Index: [agents/README.md](../../agents/README.md).
