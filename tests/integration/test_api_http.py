"""Integration: start the real API over TCP, call it, shut it down.

This is the "smallest reliable integration test" the brief asks for instead of
Playwright: a genuine HTTP round trip against a genuine uvicorn process, with
the same payload the web client parses. The browser-side half of the chain
(API client -> component -> DOM) is covered by
``tests/integration/api-web-flow.test.ts``.

The process itself is started by ``_http.running_api``, which both this module
and ``test_auth_http.py`` share.

Two readiness branches are covered here, because they are the two things that
can be wrong in opposite directions:

* ``test_ready_is_green_when_the_database_answers`` - needs the real
  PostgreSQL server, and says so out loud if it is not there.
* ``test_ready_is_red_when_the_database_cannot_be_reached`` - needs nothing,
  and proves that an unreachable database turns the probe into a 503 rather
  than a comfortable 200.
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest

from ._http import UNREACHABLE_DATABASE_URL, running_api


@pytest.mark.integration
def test_ready_is_green_when_the_database_answers(require_postgres: None) -> None:
    """The healthy branch, over real HTTP, against real PostgreSQL.

    ``require_postgres`` is the precondition: it prints why and skips when
    the server is absent, and fails when CI demands it be present.
    """
    _ = require_postgres

    with running_api() as base_url:
        health = httpx2.get(f"{base_url}/api/v1/health", timeout=5.0)
        assert health.status_code == 200
        payload: dict[str, Any] = health.json()
        assert payload["status"] == "ok"
        assert payload["service"] == "harsh-quant-os-api"
        assert payload["version"]

        # The unversioned alias must answer identically for probes.
        alias = httpx2.get(f"{base_url}/health", timeout=5.0)
        assert alias.status_code == 200
        assert alias.json() == payload

        ready = httpx2.get(f"{base_url}/api/v1/ready", timeout=5.0)
        assert ready.status_code == 200
        ready_payload: dict[str, Any] = ready.json()
        assert ready_payload["status"] == "ready"
        database = next(c for c in ready_payload["checks"] if c["name"] == "database")
        assert database["status"] == "ok"
        assert database["detail"] == "PostgreSQL answered a readiness round trip"

        # Structured errors still apply over real HTTP.
        missing = httpx2.get(f"{base_url}/no-such-path", timeout=5.0)
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["title"] == "Not Found"


@pytest.mark.integration
def test_ready_is_red_when_the_database_cannot_be_reached() -> None:
    """An unreachable database is a 503, reported as `failed`, not as healthy.

    Runs everywhere: the database URL is pointed at a closed port rather than
    at whatever happens to be installed, so this cannot pass by accident and
    cannot fail because Docker is off.
    """
    with running_api({"DATABASE_URL": UNREACHABLE_DATABASE_URL}) as base_url:
        # Liveness is unaffected: the process is up, it just cannot serve.
        health = httpx2.get(f"{base_url}/api/v1/health", timeout=5.0)
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        ready = httpx2.get(f"{base_url}/api/v1/ready", timeout=5.0)
        assert ready.status_code == 503
        ready_payload: dict[str, Any] = ready.json()
        assert ready_payload["status"] == "not_ready"

        database = next(c for c in ready_payload["checks"] if c["name"] == "database")
        assert database["status"] == "failed"
        assert database["status"] != "not_configured"
        assert database["detail"] == "PostgreSQL did not answer a readiness round trip"

        # Whatever went wrong stays on the server.
        body = ready.text.lower()
        for fragment in ("postgresql://", "asyncpg", "password", "traceback"):
            assert fragment not in body, f"readiness leaked {fragment!r}"
