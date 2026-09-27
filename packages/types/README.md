# @harsh-quant-os/types

Shared TypeScript **type** definitions for HARSH QUANT OS.

## Rules

- This package contains types and constants only. No I/O, no network, no
  secrets, no business logic.
- Every type mirrors a Python contract in `src/harsh_quant_os/`. When the two
  drift, the Python contract wins and a test must be added here.
- Strict TypeScript is mandatory (`no-explicit-any` is an ESLint error).

## Status

Phase 1 - application skeleton. The package now carries:

- the foundation enums that mirror the Phase 0 Python contracts
  (`TradingMode`, `JobStatus`, `DataQualityStatus`, `Timeframe`,
  `MemoryCategory`);
- the Phase 1 system-status contract (`HealthResponse`, `ReadyResponse`,
  `ReadinessCheck`, `HealthStatus`, `ReadinessStatus`, `CheckStatus`,
  `ApiEnvironment`), mirroring
  `src/harsh_quant_os/contracts/system.py`.

Parity with Python is enforced in both directions:
`tests/unit/health-contract.test.ts` parses the Python source, and
`tests/api/test_contract_parity.py` parses this package's TypeScript. Richer
domain types arrive with the phases that define them.
