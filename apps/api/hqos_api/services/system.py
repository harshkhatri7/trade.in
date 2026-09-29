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


def build_readiness_checks(*, database_reachable: bool) -> list[ReadinessCheck]:
    """Every dependency readiness depends on, with an honest state.

    Two dependencies now exist. ``database`` reports what a round trip
    actually returned: ``ok`` when PostgreSQL answered, ``failed`` when it did
    not. It is never reported as healthy because a connection *should* work,
    and ``not_configured`` is no longer produced - the application now has a
    database, so claiming it is not part of readiness would be false.
    """
    return [
        ReadinessCheck(
            name=API_CHECK,
            status=CheckStatus.OK,
            detail="application started and accepting HTTP requests",
        ),
        ReadinessCheck(
            name=DATABASE_CHECK,
            status=CheckStatus.OK if database_reachable else CheckStatus.FAILED,
            detail=(
                "PostgreSQL answered a readiness round trip"
                if database_reachable
                else "PostgreSQL did not answer a readiness round trip"
            ),
        ),
    ]


def build_ready(settings: Settings, *, database_reachable: bool) -> ReadyResponse:
    """Readiness payload: ``ready`` only when no required check has failed.

    ``database_reachable`` is an *observation* passed in by the caller, not
    something this pure function decides - that keeps it testable without a
    database and keeps the ping in the HTTP layer where I/O belongs.
    """
    checks = build_readiness_checks(database_reachable=database_reachable)
    required_ok = all(check.status is not CheckStatus.FAILED for check in checks)
    return ReadyResponse(
        status=ReadinessStatus.READY if required_ok else ReadinessStatus.NOT_READY,
        service=service_name(settings),
        version=settings.app_version,
        environment=ApiEnvironment(settings.app_env),
        checks=checks,
    )
