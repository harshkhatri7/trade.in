"""System status contract shared by the API and the web client.

The API serves these models; the browser validates every payload against the
TypeScript mirror in ``@harsh-quant-os/types`` before it is rendered. Drift
between the two sides is caught by tests, not by review:

- ``tests/api/test_contract_parity.py`` compares the Python field names and
  enums with the TypeScript source and with the shared fixture;
- ``tests/unit/health-contract.test.ts`` performs the same comparison in the
  opposite direction;
- both sides validate ``tests/contracts/system-status.json``.

Readiness semantics (Phase 1)
-----------------------------
``/ready`` answers exactly one question: *can this process serve requests?*

It does **not** claim that PostgreSQL is healthy, because no database exists
before Phase 2. The database check therefore reports ``not_configured`` — an
honest state, not a pass. When the storage layer lands in Phase 2 the check
becomes required, and a missing database will flip the endpoint to ``503``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ApiEnvironment(StrEnum):
    """Deployment environment the process was configured with."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class HealthStatus(StrEnum):
    """``/health`` answers only that the process is serving requests."""

    OK = "ok"


class ReadinessStatus(StrEnum):
    """Aggregate readiness of the service."""

    READY = "ready"
    NOT_READY = "not_ready"


class CheckStatus(StrEnum):
    """State of a single readiness dependency."""

    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


class ReadinessCheck(BaseModel):
    """One named dependency and why it is or is not available."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Stable machine name, e.g. 'database'.")
    status: CheckStatus
    detail: str = Field(min_length=1, description="Human-readable reason; never a secret.")


class HealthResponse(BaseModel):
    """Liveness payload: the process is up and identifies itself."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: HealthStatus
    service: str
    version: str
    environment: ApiEnvironment


class ReadyResponse(BaseModel):
    """Readiness payload: aggregate state plus every individual check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReadinessStatus
    service: str
    version: str
    environment: ApiEnvironment
    checks: list[ReadinessCheck]
