"""Structured errors: every failure crosses the boundary as problem+json."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from harsh_quant_os.config import Settings
from hqos_api.core.errors import PROBLEM_MEDIA_TYPE
from hqos_api.factory import create_app

PROBLEM_KEYS = {"type", "title", "status", "detail", "instance"}


@pytest.fixture
def validation_client(settings: Settings) -> Iterator[TestClient]:
    """An app with one deliberately invalidatable route.

    The probe exists only in this test module: Phase 1 has no endpoint that
    accepts input, so the validation handler would otherwise be unreachable.
    """
    app = create_app(settings)

    @app.get("/_probe")
    async def probe(limit: int = Query(default=1, ge=10)) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def failure_client(settings: Settings) -> Iterator[TestClient]:
    """An app with a route that raises, to reach the catch-all handler."""
    app = create_app(settings)

    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("internal detail that must never cross the boundary")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_unknown_path_returns_problem_json(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload: dict[str, Any] = response.json()
    assert PROBLEM_KEYS.issubset(payload)
    assert payload["title"] == "Not Found"
    assert payload["instance"] == "/does-not-exist"


def test_wrong_method_returns_problem_json_with_allow_header(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert "GET" in response.headers["allow"]
    assert response.json()["title"] == "Method Not Allowed"


def test_validation_failure_reports_fields_without_echoing_input(
    validation_client: TestClient,
) -> None:
    response = validation_client.get("/_probe", params={"limit": 5})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert PROBLEM_KEYS.issubset(payload)
    errors = payload["errors"]
    assert errors, "field-level messages are required"
    assert {"loc", "msg", "type"}.issubset(errors[0])
    # The submitted value must not be reflected: a client may have posted a
    # credential in a field that failed validation.
    assert "input" not in errors[0]


def test_valid_request_passes_the_validation_handler(validation_client: TestClient) -> None:
    response = validation_client.get("/_probe", params={"limit": 50})

    assert response.status_code == 200
    assert response.json() == {"limit": 50}


def test_unhandled_exception_returns_a_generic_500(failure_client: TestClient) -> None:
    response = failure_client.get("/_boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload = response.json()
    assert payload["title"] == "Internal Server Error"
    assert "internal detail" not in payload["detail"]
    assert "RuntimeError" not in payload["detail"]


def test_health_is_still_reachable_on_the_failure_app(failure_client: TestClient) -> None:
    assert failure_client.get("/health").status_code == 200
