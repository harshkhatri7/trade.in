"""Pure builders that turn configuration into response payloads.

Keeping them out of the routers means the contract can be unit-tested without
HTTP, and no FastAPI import is needed to reason about what the service reports.
"""

from __future__ import annotations

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.system import (
    ApiEnvironment,
    CheckStatus,
    HealthResponse,
    HealthStatus,
    ReadinessCheck,
    ReadinessStatus,
    ReadyResponse,
)

DATABASE_CHECK = "database"
API_CHECK = "api"


def service_name(settings: Settings) -> str:
    """Public service identifier, derived from configuration."""
    return f"{settings.app_name}-api"


def build_health(settings: Settings) -> HealthResponse:
    """Liveness payload: the process is up and identifies itself."""
    return HealthResponse(
        status=HealthStatus.OK,
        service=service_name(settings),
        version=settings.app_version,
        environment=ApiEnvironment(settings.app_env),
    )


def build_readiness_checks() -> list[ReadinessCheck]:
    """Every dependency readiness depends on, with an honest state.

    Phase 1 has exactly one dependency - the process itself. The database is
    listed as ``not_configured`` rather than omitted or reported healthy, so
    that a caller can see what has *not* been verified.
    """
    return [
        ReadinessCheck(
            name=API_CHECK,
            status=CheckStatus.OK,
            detail="application started and accepting HTTP requests",
        ),
        ReadinessCheck(
            name=DATABASE_CHECK,
            status=CheckStatus.NOT_CONFIGURED,
            detail=(
                "not part of Phase 1; PostgreSQL arrives in Phase 2, "
                "so readiness does not depend on it"
            ),
        ),
    ]


def build_ready(settings: Settings) -> ReadyResponse:
    """Readiness payload: ``ready`` only when no required check has failed."""
    checks = build_readiness_checks()
    required_ok = all(check.status is not CheckStatus.FAILED for check in checks)
    return ReadyResponse(
        status=ReadinessStatus.READY if required_ok else ReadinessStatus.NOT_READY,
        service=service_name(settings),
        version=settings.app_version,
        environment=ApiEnvironment(settings.app_env),
        checks=checks,
    )
