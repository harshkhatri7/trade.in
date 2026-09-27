"""`/health` and `/ready`: payload, version, aliases and headers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.system import HealthResponse, ReadyResponse
from harsh_quant_os.version import DISPLAY_VERSION

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


def test_ready_returns_200_and_reports_checks(client: TestClient) -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    payload = response.json()
    assert ReadyResponse.model_validate(payload).model_dump(mode="json") == payload
    assert payload["status"] == "ready"


def test_ready_does_not_pretend_the_database_is_healthy(client: TestClient) -> None:
    """Phase 1 has no database: the check must say so, not report `ok`."""
    payload = client.get("/ready").json()
    checks = {check["name"]: check for check in payload["checks"]}

    assert "database" in checks
    assert checks["database"]["status"] == "not_configured"
    assert checks["database"]["status"] != "ok"
    assert "Phase 2" in checks["database"]["detail"]
    assert checks["api"]["status"] == "ok"


def test_every_openapi_path_is_documented(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    for expected in ("/api/v1/health", "/api/v1/ready", "/health", "/ready"):
        assert expected in paths, f"{expected} missing from the OpenAPI schema"


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get(VERSIONED)

    assert response.headers.get("X-Request-ID")


def test_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get(VERSIONED, headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"
