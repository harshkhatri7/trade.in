"""Shared fixtures for the API tests.

Settings are always constructed explicitly with ``_env_file=None`` so that a
developer's local ``.env`` can never change what the suite asserts. The app is
built through the same factory the process uses.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harsh_quant_os.config import Settings
from hqos_api.factory import create_app

# Loopback port with no listener: the connection is refused immediately, so a
# probe against it fails fast, offline, and identically on every machine. The
# unit suite runs without PostgreSQL, and it must say so rather than be handed
# a database it does not have.
_UNREACHABLE_DATABASE = "postgresql+asyncpg://unit_tests:unit_tests@127.0.0.1:5/unit_tests"


@pytest.fixture
def settings() -> Settings:
    """Deterministic test settings: no ``.env``, environment ``test``.

    ``database_url`` is deliberate rather than inherited from the default, so
    that the readiness endpoint's answer does not depend on whether something
    happens to be listening on 5432. The *healthy* database check is covered
    by ``tests/integration/test_api_http.py``, which runs against a real
    PostgreSQL server.
    """
    return Settings.load(
        _env_file=None,
        app_env="test",
        database_url=_UNREACHABLE_DATABASE,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
