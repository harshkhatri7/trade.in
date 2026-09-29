"""`/health` and `/ready`: payload, version, aliases and headers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.system import HealthResponse, ReadyResponse
from harsh_quant_os.version import DISPLAY_VERSION
from hqos_api.services.system import build_ready

VERSIONED = "/api/v1/health"
UNVERSIONED = "/health"


def test_health_returns_200(client: TestClient) -> None:
    response = client.get(VERSIONED)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_health_schema_matches_the_contract(client: TestClient, settings: Settings) -> None:
    payload = client.get(VERSIONED).json()

    assert set(payload) == {"status", "service", "version", "environment"}
    # Round-trip through the same model FastAPI serialises with.
    assert HealthResponse.model_validate(payload).model_dump(mode="json") == payload
    assert payload["status"] == "ok"
    assert payload["service"] == "harsh-quant-os-api"
    assert payload["environment"] == "test"
    assert payload["version"] == settings.app_version


def test_health_version_is_the_project_version(settings: Settings) -> None:
    """The default in Settings must stay aligned with the package version."""
    assert settings.app_version == DISPLAY_VERSION


def test_versioned_and_unversioned_aliases_are_identical(client: TestClient) -> None:
    versioned = client.get(VERSIONED)
    unversioned = client.get(UNVERSIONED)

    assert versioned.status_code == unversioned.status_code == 200
    assert versioned.json() == unversioned.json()


def test_ready_returns_503_when_the_database_round_trip_fails(
    client: TestClient, settings: Settings
) -> None:
    """No reachable database means readiness, not a pass.

    The unit settings point at a closed port, so the round trip really is
    attempted and really does fail - there is no stub anywhere in this test.
    The endpoint must therefore answer 503 with a payload that still
    validates against the contract, because a readiness probe that returns
    200 while a required dependency is down is worse than no probe.
    """
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    payload = response.json()
    assert ReadyResponse.model_validate(payload).model_dump(mode="json") == payload
    assert payload["status"] == "not_ready"
    assert payload["service"] == "harsh-quant-os-api"
    assert payload["environment"] == "test"
    assert payload["version"] == settings.app_version


def test_ready_reports_a_database_check_it_cannot_pass(client: TestClient) -> None:
    """The check is named, stated `failed`, and never claimed healthy."""
    payload = client.get("/ready").json()
    checks = {check["name"]: check for check in payload["checks"]}

    assert set(checks) == {"api", "database"}
    assert checks["api"]["status"] == "ok"
    assert checks["database"]["status"] == "failed"
    assert checks["database"]["status"] != "ok"
    # Phase 2 has a database, so `not_configured` would be a false statement
    # about what was probed - distinct from `failed`, which says it was.
    assert checks["database"]["status"] != "not_configured"


def test_ready_failure_does_not_leak_connection_details(client: TestClient) -> None:
    """A failed probe reports a sentence, never a DSN, credential or traceback."""
    response = client.get("/ready")
    checks = {check["name"]: check for check in response.json()["checks"]}

    assert checks["database"]["detail"] == "PostgreSQL did not answer a readiness round trip"
    body = response.text.lower()
    for fragment in ("postgresql://", "asyncpg", "password", "unit_tests", "traceback", 'file "'):
        assert fragment not in body, f"readiness leaked {fragment!r}"


def test_ready_payload_says_ready_when_the_database_answers(settings: Settings) -> None:
    """The other half of the builder, in its own right.

    ``build_ready`` takes the result of a round trip it did not perform, so
    both of its branches are checked here as a pure function. That the real
    round trip returns ``True`` against PostgreSQL is asserted separately, in
    ``tests/integration/test_api_http.py``.
    """
    payload = build_ready(settings, database_reachable=True)

    assert payload.status.value == "ready"
    checks = {check.name: check for check in payload.checks}
    assert checks["database"].status.value == "ok"
    assert checks["api"].status.value == "ok"


def test_every_openapi_path_is_documented(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    for expected in (
        "/api/v1/health",
        "/api/v1/ready",
        "/health",
        "/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/me",
    ):
        assert expected in paths, f"{expected} missing from the OpenAPI schema"

    # Probes get an unversioned alias; authentication does not. A load
    # balancer has no business reaching a login form, and a second route
    # means a second place for a security behaviour to drift out of sync.
    for unexpected in ("/auth/login", "/auth/logout", "/me"):
        assert unexpected not in paths, f"{unexpected} must not exist unversioned"


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get(VERSIONED)

    assert response.headers.get("X-Request-ID")


def test_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get(VERSIONED, headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"
