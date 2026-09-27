# ADR-0002: Shared Python/TypeScript contract without code generation

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Repository owner (with the Backend and Frontend agent specifications)
- **Phase:** 1 — Application skeleton

---

## Context

Phase 1 introduces the first payload that both languages must agree on:
`GET /health` and `GET /ready` are produced by FastAPI/Pydantic and consumed
by the TypeScript API client in `apps/web`.

Two failure modes have to be prevented:

- **Silent drift.** The API renames a field; the web app compiles; the page
  quietly shows `undefined`. Nothing fails until someone looks at the screen.
- **Toolchain weight.** An OpenAPI generator (or a schema-first code
  generator) adds a generated-code step, a commit that nobody reviews, a
  regeneration command that people forget, and a second build system for a
  payload that currently has four fields.

The payload surface at this point is small (one health object, one readiness
object with a list of checks) and is expected to stay small until the API has
real resources to describe.

---

## Decision

### D1 — The contract has one fixture and two mirrors

- `tests/contracts/system-status.json` is the documented, human-readable
  contract. It holds an example health payload and an example readiness
  payload with their exact shapes.
- `src/harsh_quant_os/contracts/system.py` holds the authoritative Python
  models (`HealthResponse`, `ReadyResponse`, `ReadinessCheck`, and their
  status enums). FastAPI serves these models directly; there is no untyped
  `dict` in any response.
- `packages/types/src/system.ts` mirrors the same fields as TypeScript types,
  and `packages/shared/src/api-contracts.ts` re-validates them at runtime with
  `parseHealthResponse` / `parseReadyResponse`.

### D2 — Parity is proved in both directions, in the test suites that already exist

- `tests/unit/health-contract.test.ts` parses the **Python** source and the
  fixture with the TypeScript parsers, and asserts they accept the same
  payloads and reject the same invalid ones.
- `tests/api/test_contract_parity.py` parses the **TypeScript** source with
  the Python models and asserts field and enum parity.

A change to either side that the other side does not make breaks one of these
tests. Both directions are tested because a one-directional check only proves
that the side you happened to edit is self-consistent.

### D3 — No code generation in Phase 1

Generation is deferred until a payload surface exists that is larger than a
human can keep in their head (real resources, pagination, request bodies). At
that point the decision is revisited with a measured need, following the same
rule as TimescaleDB in ADR-0001: adopt when a need is observed, not before.

### D4 — Versioning: one canonical prefix, one unversioned alias

`GET /api/v1/health` and `GET /api/v1/ready` are canonical. The same router
is also mounted at `/health` and `/ready` so that probes, scripts and the
health check do not need to know the version. Both paths serve the identical
response; there is a single implementation. Breaking changes will be served
under `/api/v2`, not by mutating `/api/v1`.

---

## Consequences

**Positive**

- Contract drift fails CI rather than rendering `undefined` in the UI.
- No generated files in the tree; every line of the contract was written and
  reviewed by a person.
- Existing toolchains keep working: pytest for the Python half, Vitest for
  the TypeScript half, no extra runner.

**Negative / accepted costs**

- Two mirrored definitions must be edited together. This is deliberate: the
  parity tests make the second edit mandatory instead of implicit.
- The parity tests parse source with regular expressions. They are precise
  about field names and enum values but are not a general type checker; a
  field whose *type* changes without a rename would need a stricter check
  later.
- Revisit D3 when the payload surface grows, or the regex approach becomes
  the weaker of the two checks.

**Risks**

- A contributor could weaken a parity test instead of updating both sides.
  That is a review failure, not a tooling failure; the tests are listed below
  so their purpose stays visible.

---

## Alternatives considered

| Alternative                                | Why not now                                                                 |
| ------------------------------------------ | --------------------------------------------------------------------------- |
| OpenAPI codegen (`openapi-typescript`, etc.) | Adds a generator, a regeneration step and generated files for four fields |
| JSON Schema as the single source           | Another schema language plus a runtime validator in Python and TypeScript   |
| One-way check (TS mirrors Python only)     | Proves nothing about the mirror; drift in the mirror goes unnoticed         |
| Handshake tests only (HTTP round trip)     | Catches shape changes at runtime but not type/enum intent, and needs a live server |
| GraphQL / RPC layer                        | Far beyond a health endpoint; new dependency with no measured need          |

---

## Compliance

This ADR is enforced by:

- `tests/unit/health-contract.test.ts` (parses the Python source and fixture)
- `tests/api/test_contract_parity.py` (parses the TypeScript source)
- `tests/api/test_system_endpoints.py` (response schema and status codes)
- `tests/integration/test_api_http.py` (real HTTP against a live server)
- `tests/integration/api-web-flow.test.tsx` (API → client → DOM)

Related: [ADR-0001](ADR-0001-initial-architecture.md),
[ADR-0003](ADR-0003-authentication-deferred.md),
[backend architecture](../architecture/backend.md),
[testing strategy](../development/testing-strategy.md).
