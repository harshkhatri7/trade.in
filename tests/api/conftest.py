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


@pytest.fixture
def settings() -> Settings:
    """Deterministic test settings: no ``.env``, environment ``test``."""
    return Settings.load(_env_file=None, app_env="test")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
