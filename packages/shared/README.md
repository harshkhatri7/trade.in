# @harsh-quant-os/shared

Runtime utilities shared by the web app, the API client and tooling.

## Rules

- Pure functions only: no network, no filesystem, no environment access, no
  secrets.
- Everything exported must have a deterministic unit test in `tests/unit`.
- Financial maths does **not** belong here - it lives in the Python quant
  packages, where it is covered by deterministic tests.

## Status

Phase 0 - foundation with two small, tested helpers (percentage change and
safe division) that set the pattern for deterministic numeric helpers.
