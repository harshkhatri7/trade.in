"""System endpoints: liveness and readiness.

Both paths are served by the same router, mounted twice by the factory:

* ``/api/v1/health`` and ``/api/v1/ready`` - the versioned base URL fixed in
  docs/architecture/backend.md section 4. This is the contract the web client
  calls.
* ``/health`` and ``/ready`` - unversioned aliases for probes (Docker,
  process supervisors, load balancers) that should not have to know the API
  version. They return exactly the same payload.

Breaking changes move to ``/api/v2``; the aliases follow the current version.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.system import HealthResponse, ReadinessStatus, ReadyResponse
from hqos_api.services.system import build_health, build_ready

READY_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "description": "A required dependency is unavailable; see `checks` for the reason.",
        "model": ReadyResponse,
    }
}


def create_system_router(settings: Settings) -> APIRouter:
    """Build a router bound to one explicit ``Settings`` instance."""
    router = APIRouter(tags=["system"])

    @router.get(
        "/health",
        response_model=HealthResponse,
        summary="Liveness",
        description="Reports that the API process is up. Contains no dependency checks.",
    )
    async def health() -> HealthResponse:
        return build_health(settings)

    @router.get(
        "/ready",
        response_model=ReadyResponse,
        responses=READY_RESPONSES,
        summary="Readiness",
        description=(
            "Reports whether the API can serve normal requests. Returns 503 when a "
            "required dependency has failed. In Phase 1 no database exists, so the "
            "database check is reported as `not_configured` instead of `ok`."
        ),
    )
    async def ready(response: Response) -> ReadyResponse:
        payload = build_ready(settings)
        if payload.status is ReadinessStatus.NOT_READY:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return payload

    return router
