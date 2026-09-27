# AI system architecture

**Phase:** 0 — Foundation. **No AI component is implemented.** The AI research
assistant is Phase 8; this document fixes the constraints it must operate
under.

---

## 1. Position of AI in the system

AI is an **assistant to research**, never an authority. It may:

- read data the operator is allowed to read;
- summarise, compare, critique and suggest;
- propose hypotheses, experiment configurations and journal entries;
- answer questions about stored results.

It may **never**:

- execute trades or place orders;
- access broker credentials (none exist in this repository);
- access the risk engine's configuration or attempt to bypass a control;
- read or write arbitrary filesystem paths;
- run arbitrary shell commands;
- make unrestricted network calls;
- modify or delete audit history;
- change anything that would enable live trading;
- present a proposal as an established fact.

---

## 2. Provider-agnostic design

```text
                ┌──────────────────────────┐
                │  AI adapter interface    │
                │  complete(request) →     │
                │  structured response     │
                └────────────┬─────────────┘
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   cloud provider A    cloud provider B    local model (optional)
   (API key from env)  (API key from env)  (runs on local PC)
```

- One interface, many backends; swapping providers is configuration.
- Local AI is **optional**: the product must work with it disabled.
- Prompts, model ids, temperature and limits come from `Settings`.
- No provider receives secrets, credentials or data the operator has not
  explicitly selected for that request.

---

## 3. Tool allow-list

The assistant reaches the rest of the system only through named, typed tools
declared by the application:

| Tool (planned)              | Reads                    | Writes                     |
| --------------------------- | ------------------------ | -------------------------- |
| `query_datasets`            | dataset metadata         | —                          |
| `query_experiments`         | experiment records       | —                          |
| `propose_hypothesis`        | —                        | `research` memory (pending)|
| `propose_experiment`        | —                        | experiment draft (pending) |
| `add_journal_entry`         | —                        | journal (attributed)       |
| `explain_backtest`          | a stored run + manifest   | —                          |

Anything not on this list does not exist as far as the model is concerned.

Rules for every tool:

1. **Typed inputs and outputs** — Pydantic models, no free-form strings.
2. **Authenticated principal** — every call is attributed to a user.
3. **Authorisation** — checked by the API, not by the prompt.
4. **Read-only by default** — writes create *pending* entries requiring human
   confirmation.
5. **Audited** — prompt hash, tool name, arguments, result status, latency.
6. **Bounded** — timeouts, token limits, and call-rate limits.

---

## 4. Memory and truth

Persistent memory categories (already defined in
`harsh_quant_os.memory.MemoryCategory`):

`market`, `strategy`, `experiment`, `trade`, `research`, `journal`,
`model`, `system`.

- **The database is the source of truth.** Conversational context is
  disposable and must never be the only record of a decision.
- Anything the assistant contributes is stored with provenance: author,
  timestamp, source conversation id, and the evidence it referenced.
- The assistant may propose a memory entry; a human (or a reviewed automated
  rule) promotes it.

---

## 5. Local AI

- Optional, off by default (`AI_LOCAL_ENABLED=false`).
- Runs on the local PC through the same job/allow-list mechanism as other
  local compute ([local agent](local-agent.md)).
- Model weights and downloads are the operator's choice; nothing is fetched
  silently.
- Local inference is never a hard requirement for the platform to function.

---

## 6. Evaluation and honesty

- Model outputs that affect research are stored as **proposals**, not facts.
- Generated numbers must reference the query or artifact they came from; the
  system never accepts a figure the model produced without a source.
- Prompt-injection defences: model output is data, never instructions to the
  host application.
- Failure handling: a provider timeout or malformed response surfaces as an
  error, never as a fabricated answer.

---

## 7. Current state and exit criteria

**Phase 0:** no AI code, no provider SDK, no key in the repository.
`AI_API_KEY` in `.env.example` is an empty placeholder.

**Phase 8 exit criteria:**

- Adapter works with at least one cloud provider and, optionally, one local
  model, selected by configuration.
- Tool allow-list enforced in code and covered by security tests.
- Every AI contribution stored as a proposal with provenance.
- Audit records for all model calls.
- Security agent review completed and recorded.
