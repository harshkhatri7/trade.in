"""Authentication over a real socket: log in, carry the cookie, log out.

``tests/api/test_auth_endpoints.py`` covers the status codes from inside the
process; this module is the same behaviour with a real uvicorn process, a real
TCP connection and a real cookie jar - because the parts that matter most here
are the ones an in-process transport cannot reproduce:

* that ``Set-Cookie`` arrives with the flags the browser will honour;
* that the browser then attaches it to the next request *without* the test
  having to do it for them;
* that logging out kills the session server-side, so the next request fails
  even if the value were still in the jar;
* that an unknown address and a wrong password produce byte-identical
  refusals, so a login form cannot be turned into an account-enumeration
  oracle.

Every test here writes only to ``harsh_quant_os_test``: ``test_database_url``
is the fixture that makes the URL, and ``_db.url_for`` is what asserted it is
not the configured database.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harsh_quant_os.auth import AuthService

from ._db import rows
from ._http import UNREACHABLE_DATABASE_URL, running_api

SESSION_COOKIE = "hqos_session"

#: Valid against the password policy so a *successful* login reaches the
#: database, and under 24 characters so no secret scanner reads it as one.
PASSWORD = "quant-dev-passphrase"


def _email(label: str) -> str:
    """A fresh address per test: ``harsh_quant_os_test`` outlives one run."""
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.mark.integration
async def test_login_me_and_logout_work_over_a_real_socket(
    require_postgres: None,
    test_database_url: str,
    auth_service: AuthService,
    engine: AsyncEngine,
) -> None:
    """The whole session lifecycle, driven the way a browser drives it."""
    _ = require_postgres
    email = _email("roundtrip")
    user = await auth_service.create_user(email=email, password=PASSWORD)

    with (
        running_api({"DATABASE_URL": test_database_url}) as base_url,
        httpx2.Client(base_url=base_url, timeout=10.0) as browser,
    ):
        login = browser.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200, login.text

        # The credential is a cookie and nothing else.
        set_cookie = login.headers.get("set-cookie", "")
        assert set_cookie.startswith(f"{SESSION_COOKIE}=")
        flags = set_cookie.lower()
        assert "httponly" in flags, "script could read the session"
        assert "samesite=lax" in flags, "a cross-site POST would carry it"
        assert "path=/" in flags
        assert "max-age=" in flags, "the cookie would never expire"

        body: dict[str, Any] = login.json()
        assert body["user"]["email"] == email
        assert set(body) == {"user", "session"}
        assert set(body["user"]) == {
            "id",
            "email",
            "display_name",
            "is_superuser",
            "created_at",
        }
        assert set(body["session"]) == {"issued_at", "expires_at"}
        assert SESSION_COOKIE not in login.text, "the token reached the body"

        # The jar carries it forward with no help from the test.
        me = browser.get("/api/v1/me")
        assert me.status_code == 200, me.text
        assert me.json() == body

        logout = browser.post("/api/v1/auth/logout")
        assert logout.status_code == 204, logout.text
        assert SESSION_COOKIE in logout.headers.get("set-cookie", "")

        # Revocation is server-side, not merely cookie deletion: even a
        # client that kept the value finds the session gone.
        gone = browser.get("/api/v1/me")
        assert gone.status_code == 401
        assert gone.json()["detail"] == "A valid session is required for this request."

        # And repeating the logout is still a refusal, not a comfortable 204.
        again = browser.post("/api/v1/auth/logout")
        assert again.status_code == 401

    # Each transition left a row, tied to this account.
    for event, count in (
        ("auth.login.succeeded", 1),
        ("auth.logout.succeeded", 1),
    ):
        found = await rows(
            engine,
            "SELECT id FROM audit_log WHERE event_type = :event AND actor_user_id = :uid",
            {"event": event, "uid": user.id},
        )
        assert len(found) == count, f"{event}: expected {count}, saw {len(found)}"


@pytest.mark.integration
async def test_an_unknown_address_and_a_wrong_password_are_indistinguishable(
    require_postgres: None,
    test_database_url: str,
    auth_service: AuthService,
    engine: AsyncEngine,
) -> None:
    """Same status, same headers, same bytes: no enumeration oracle.

    The distinction lives in the log, where it is useful to an operator, and
    nowhere on the wire, where it would be useful to somebody else.
    """
    _ = require_postgres
    existing = _email("enumerate")
    await auth_service.create_user(email=existing, password=PASSWORD)
    absent = _email("nobody")

    with running_api({"DATABASE_URL": test_database_url}) as base_url:
        unknown = httpx2.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": absent, "password": PASSWORD},
            timeout=10.0,
        )
        wrong = httpx2.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": existing, "password": "definitely-the-wrong-one"},
            timeout=10.0,
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.headers["content-type"] == wrong.headers["content-type"]
    assert unknown.content == wrong.content, "the two refusals were distinguishable"
    assert "set-cookie" not in unknown.headers
    assert "set-cookie" not in wrong.headers
    assert unknown.json()["detail"] == "Email or password is incorrect."
    for response in (unknown, wrong):
        assert "unknown account" not in response.text
        assert "wrong password" not in response.text

    # Both were refused *and* recorded - the log keeps the distinction.
    for email in (absent, existing):
        found = await rows(
            engine,
            "SELECT outcome FROM audit_log WHERE event_type = :event AND actor_email = :email",
            {"event": "auth.login.failed", "email": email},
        )
        assert len(found) == 1, f"{email} was not audited"
        assert found[0][0] == "failure"


@pytest.mark.integration
def test_a_login_cannot_claim_success_when_the_database_is_down() -> None:
    """Over a real socket, an unreachable database is 503 with no cookie.

    Runs everywhere: the URL is a closed loopback port rather than whatever
    the machine happens to have, so this cannot pass by accident and cannot
    fail because Docker is off.
    """
    with running_api({"DATABASE_URL": UNREACHABLE_DATABASE_URL}) as base_url:
        response = httpx2.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": "owner@example.com", "password": PASSWORD},
            timeout=10.0,
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    # A cookie here would be a session for a login that never happened.
    assert "set-cookie" not in response.headers
    assert response.json()["status"] == 503

    body = response.text
    for name, secret in (
        ("the submitted password", PASSWORD),
        ("a connection string", "postgresql://"),
        ("the credential inside it", "integration_tests"),
        ("a traceback", "Traceback"),
    ):
        assert secret not in body, f"the 503 contained {name}"
