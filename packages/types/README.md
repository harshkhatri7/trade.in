# @harsh-quant-os/types

Shared TypeScript **type** definitions for HARSH QUANT OS.

## Rules

- This package contains types and constants only. No I/O, no network, no
  secrets, no business logic.
- Every type mirrors a Python contract in `src/harsh_quant_os/`. When the two
  drift, the Python contract wins and a test must be added here.
- Strict TypeScript is mandatory (`no-explicit-any` is an ESLint error).

## Status

Phase 0 - foundation. The enums below mirror the Phase 0 Python contracts
(`TradingMode`, `JobStatus`, `DataQualityStatus`, `Timeframe`,
`MemoryCategory`). Richer domain types arrive with the phases that define them.
