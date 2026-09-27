# @harsh-quant-os/shared

Runtime utilities shared by the web app, the API client and tooling.

## Rules

- Pure functions only: no network, no filesystem, no environment access, no
  secrets.
- Everything exported must have a deterministic unit test in `tests/unit`.
- Financial maths does **not** belong here - it lives in the Python quant
  packages, where it is covered by deterministic tests.

## Status

Phase 1 - application skeleton. The package contains:

- two small, tested numeric helpers (percentage change and safe division)
  that set the pattern for deterministic numeric helpers;
- `api-contracts.ts` - the runtime parsers `parseHealthResponse` and
  `parseReadyResponse` plus `API_PATHS`, the single definition of
  `/api/v1/health` and `/api/v1/ready` used by the API client and by the
  contract tests. A payload the API would not send is rejected here, before
  it can reach a component (see
  [ADR-0002](../../docs/decisions/ADR-0002-shared-contract-without-codegen.md)).
