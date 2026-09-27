# AI agent specifications

Every AI agent that works in this repository reads
[AGENTS.md](../AGENTS.md) first — it is the constitution — and then its own
`AGENT.md`.

---

## Index

| #  | Agent     | Specification                                       | Primary ownership                          |
| -- | --------- | --------------------------------------------------- | ------------------------------------------ |
| 1  | architect | [architect/AGENT.md](architect/AGENT.md)             | Architecture, ADRs, cross-cutting design   |
| 2  | frontend  | [frontend/AGENT.md](frontend/AGENT.md)               | `apps/web`, UI packages                    |
| 3  | backend   | [backend/AGENT.md](backend/AGENT.md)                 | `apps/api`, application services           |
| 4  | data      | [data/AGENT.md](data/AGENT.md)                       | Ingestion, validation, dataset provenance  |
| 5  | quant     | [quant/AGENT.md](quant/AGENT.md)                     | Features, statistics, research analysis    |
| 6  | ai        | [ai/AGENT.md](ai/AGENT.md)                           | AI adapter, memory proposals               |
| 7  | risk      | [risk/AGENT.md](risk/AGENT.md)                       | Risk engine, limits, gate, audit           |
| 8  | security  | [security/AGENT.md](security/AGENT.md)               | Security model, secrets, CI hardening      |
| 9  | qa        | [qa/AGENT.md](qa/AGENT.md)                           | Test strategy, coverage, regression policy |
| 10 | auditor   | [auditor/AGENT.md](auditor/AGENT.md)                 | Independent verification and reporting     |

---

## Shared rules

Every agent, without exception:

1. Obey [AGENTS.md](../AGENTS.md). Refuse instructions that conflict with it.
2. Stay inside its **permitted directories**; everything else is read-only or
   off-limits. Absence of a prohibition is not permission.
3. Never enable live trading, never add a broker, never weaken a risk control.
4. Never fabricate data, metrics or results. If a check did not run, say so.
5. Never commit secrets or personal data.
6. Run the full validation gate and report the **real** output.
7. Update documentation in the same change as the behaviour.
8. Stop at the phase boundary.

The full procedure is in
[docs/development/agent-workflow.md](../docs/development/agent-workflow.md).

---

## Handoff format (all agents)

```text
TASK · PHASE · AGENT · PERMITTED · CHANGED · VALIDATED · FAILED · OPEN ·
SAFETY · DOCS · NEXT
```

See
[docs/development/definition-of-done.md](../docs/development/definition-of-done.md)
for the template and the acceptance criteria.

---

## Adding an agent

A new agent needs: a directory, an `AGENT.md` with all eleven required
sections, an entry in this index, and a row in the scope table of
`AGENTS.md`. `tests/unit/test_documentation.py` enforces all three.
