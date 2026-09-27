# ADR-0003: Authentication deferred from Phase 1 to Phase 2

- **Status:** Accepted (records a deviation from the original roadmap)
- **Date:** 2026-09-27
- **Deciders:** Repository owner
- **Phase:** 1 — Application skeleton

---

## Context

[ROADMAP.md](../ROADMAP.md) listed, under Phase 1:

> - Authentication and session management.

with the exit criterion *"a running web app and API that authenticate"*. The
same phase also promised the application skeleton: the Next.js shell, the
typed API client, the FastAPI application, health endpoints, structured
logging, request validation and error handling.

While implementing Phase 1 it became clear that these two threads do not fit
together honestly:

1. **Sessions need somewhere to live.** A session that survives a restart
   needs storage. The only storage approved for this project is PostgreSQL,
   which arrives in Phase 2. Building a file-backed or in-memory session
   store now would produce code that is deliberately thrown away in the very
   next phase, while introducing credential handling, cookie flags, CSRF and
   password hashing before the audit table they are supposed to be recorded
   in exists.
2. **There is nothing to protect yet.** Phase 1 exposes two endpoints that
   report version, environment and readiness. No dataset, no research record,
   no account, no order — none of it exists. Adding an authentication layer
   in front of a health check would create the appearance of security without
   a resource being secured.
3. **Phase 1's contract work is the real dependency.** The web app and the
   API must first agree on a payload shape and report their connection state
   truthfully. That is the piece every later phase (including
   authentication) builds on.

Per `AGENTS.md` §8, a conflict between an implemented phase and the roadmap
is escalated rather than silently resolved. This ADR is that escalation.

---

## Decision

### D1 — Authentication and session management move to Phase 2

Phase 2 becomes: database, migrations, **and** authentication/sessions
persisted in that database. The roadmap is amended in the same change as this
ADR; the phase numbering does not change.

### D2 — Phase 1 is restated around what it actually delivers

Phase 1 exit criteria become: a running web app and a running API connected
by a shared, tested contract, with typed configuration, structured logging,
consistent error handling, and no business logic beyond system status. The
deferral above is the single documented deviation from the original Phase 1
text.

### D3 — The gap is reported, not hidden

Until Phase 2 lands, the API has **no authentication**. This is stated in
`docs/PROJECT-STATUS.md` and in the Phase 1 status report for this change. It
is not described as "handled", "optional" or "coming soon" in code comments.

### D4 — Mitigations that exist today are configuration, not auth

While the gap exists:

- the API binds to `127.0.0.1` by default (`API_HOST`), so it is not
  reachable from another machine unless configuration deliberately changes
  that;
- CORS is an explicit allow-list from `API_ALLOWED_ORIGINS`; a wildcard is
  rejected outside `development`/`test` by `Settings`;
- there is no sensitive data behind the endpoints yet;
- no state-changing endpoint exists at all — Phase 1 is read-only.

These reduce exposure. They are **not** a substitute for authentication and
must not be described as one.

---

## Consequences

**Positive**

- No throwaway session store, and no credential handling before the audit
  trail it depends on exists.
- Phase 2 becomes one coherent unit: persistence plus the sessions that need
  it, tested together.

**Negative / accepted costs**

- The original Phase 1 exit criterion "a running web app and API that
  authenticate" is **not met by Phase 1**. This ADR records the deviation
  explicitly instead of quietly redefining the phase.
- Any endpoint added between now and Phase 2 is unauthenticated. Mitigated
  by D4 and by the fact that no sensitive or state-changing endpoint exists.

**Risks**

- Normalisation of scope slippage: mitigated by requiring the roadmap,
  status file and this ADR to be updated in the same change, all of which are
  checked by `tests/unit/test_documentation.py`.

---

## Alternatives considered

| Alternative                                            | Why not                                                                    |
| ------------------------------------------------------ | -------------------------------------------------------------------------- |
| Keep auth in Phase 1 with file-backed sessions         | Duplicated, throwaway persistence; cred handling without audit records      |
| Static bearer token in `.env`                          | A shared secret that looks like authentication but rotates nowhere and protects one operator talking to himself |
| Reorder: auth before the database                      | Sessions then need a second storage decision, and the roadmap's Phase 2 would lose its storage owner |
| Skip authentication entirely                           | Rejected: Phase 16 cannot exist without it; it is deferred, not removed     |
| Ship Phase 1 without recording the deviation           | Rejected by `AGENTS.md` §8 — report the conflict, do not conceal it         |

---

## Compliance

This ADR is enforced by:

- `docs/ROADMAP.md` (Phase 1 and Phase 2 amended in the same change)
- `docs/PROJECT-STATUS.md` (states the phase and the authentication gap)
- `tests/unit/test_documentation.py` (status file must state the current
  phase, live-trading state and capital)

Related: [ADR-0001](ADR-0001-initial-architecture.md),
[ADR-0002](ADR-0002-shared-contract-without-codegen.md),
[../ROADMAP.md](../ROADMAP.md),
[backend architecture](../architecture/backend.md).
