"""CORS and application configuration.

CORS is development-only and origin-driven: ``API_ALLOWED_ORIGINS`` supplies
the list, a wildcard is rejected outside local development by ``Settings``,
and the pre-flight methods are limited to the verbs the API actually serves.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harsh_quant_os.config import Settings, SettingsError
from hqos_api.factory import create_app

ALLOWED_ORIGIN = "http://localhost:3000"
OTHER_ORIGIN = "https://attacker.example"

_PRODUCTION_SECRETS: dict[str, str] = {
    "auth_secret_key": "a" * 48,
    "database_password": "b" * 32,
    "local_agent_token": "c" * 40,
}


def production_settings(**overrides: object) -> Settings:
    """A loadable production configuration with real-looking secrets."""
    return Settings.load(
        _env_file=None,
        app_env="production",
        **_PRODUCTION_SECRETS,
        **overrides,
    )


@pytest.fixture
def cors_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_allowed_origin_receives_cors_headers(cors_client: TestClient) -> None:
    response = cors_client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_preflight_is_answered_for_an_allowed_origin(cors_client: TestClient) -> None:
    response = cors_client.options(
        "/api/v1/health",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "GET" in response.headers["access-control-allow-methods"]


def test_disallowed_origin_gets_no_cors_headers(cors_client: TestClient) -> None:
    response = cors_client.get("/health", headers={"Origin": OTHER_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_only_served_methods_are_allowed_in_preflight(cors_client: TestClient) -> None:
    response = cors_client.options(
        "/api/v1/ready",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "DELETE"},
    )

    # The API never serves DELETE, so the pre-flight must not be granted.
    assert response.status_code == 400
    assert "method" in response.text.lower()
    assert "DELETE" not in response.headers.get("access-control-allow-methods", "")


def test_production_configuration_is_served_without_interactive_docs() -> None:
    app = create_app(production_settings())

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    # The API itself must still work.
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_development_keeps_docs_and_wildcard_only_when_configured() -> None:
    settings = Settings.load(_env_file=None, app_env="development", api_allowed_origins="*")
    app = create_app(settings)

    assert app.docs_url == "/docs"
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": OTHER_ORIGIN})

    assert response.headers["access-control-allow-origin"] == OTHER_ORIGIN


def test_settings_reject_wildcard_cors_outside_development() -> None:
    with pytest.raises(SettingsError, match="API_ALLOWED_ORIGINS"):
        Settings.load(
            _env_file=None,
            app_env="production",
            api_allowed_origins="*",
            **_PRODUCTION_SECRETS,
        )


def test_factory_uses_the_origins_from_settings() -> None:
    settings = Settings.load(
        _env_file=None,
        app_env="test",
        api_allowed_origins="http://localhost:4000 , http://127.0.0.1:4000",
    )
    app: FastAPI = create_app(settings)

    cors = next(
        m for m in app.user_middleware if getattr(m.cls, "__name__", "") == "CORSMiddleware"
    )
    assert cors.kwargs["allow_origins"] == ["http://localhost:4000", "http://127.0.0.1:4000"]
    # POST joins the allowlist because authentication is state-changing: a
    # browser must be able to preflight a login. The verbs stay enumerated -
    # no wildcard - so a future "allow everything" edit has to happen here,
    # in front of a test that says so.
    assert cors.kwargs["allow_methods"] == ["GET", "POST", "HEAD", "OPTIONS"]
