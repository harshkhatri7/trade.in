"""Authentication at the HTTP boundary, without a database.

``settings`` points at a loopback port with no listener, so the paths asserted
here are the two kinds that need no PostgreSQL:

* the ones that are refused *before* any query runs - a missing or malformed
  cookie, a body that fails validation;
* the one where the connection being refused **is** the subject, because
  "the database is down" must be distinguishable at the boundary from "your
  credentials were wrong". Reporting the second would be a lie, and reporting
  the first as a success would be a worse one.

The full round trip - create an account, log in, carry the cookie, read
``/me``, log out - needs a real server and lives in
``tests/integration/test_auth_http.py``. The failure taxonomy of the service
itself is covered in ``tests/integration/test_auth_service.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from httpx2 import Response

from harsh_quant_os.auth.errors import InvalidCredentials
from harsh_quant_os.config import Settings
from hqos_api.cookies import SESSION_COOKIE_NAME
from hqos_api.factory import create_app

PROBLEM_MEDIA_TYPE = "application/problem+json"

#: Long enough to pass ``is_plausible_session_token`` (40-128 URL-safe
#: characters), so the service proceeds to look it up - and then cannot.
PLAUSIBLE_BUT_UNKNOWN_TOKEN = "a" * 43

#: Short enough to be refused as implausible, which happens before any query.
MALFORMED_TOKEN = "not-a-token"

#: Valid against the password policy, so Pydantic accepts it and the request
#: reaches the database. Under 24 characters so no secret scanner mistakes it
#: for a real credential.
FORM_PASSWORD = "a-form-only-password"

#: One character past ``LoginRequest``'s bound, so the body is rejected by
#: validation and the refusal has a credential in it to leak.
OVERSIZED_PASSWORD = "x" * 1025


def _assert_problem(response: Response, expected_status: int) -> dict[str, Any]:
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    payload: dict[str, Any] = response.json()
    assert {"type", "title", "status", "detail", "instance"}.issubset(payload)
    assert payload["status"] == expected_status
    return payload


def _present_cookie(client: TestClient, token: str) -> None:
    """Put the session cookie on the client rather than on one request.

    Per-request ``cookies=`` is deprecated, and ``filterwarnings = error``
    turns that deprecation into a failure - which is the right outcome: the
    warning says the assertion is being written against an API on its way
    out. Setting it on the client also mirrors the browser, where the cookie
    belongs to the client and is attached to every subsequent request.
    """
    client.cookies.set(SESSION_COOKIE_NAME, token)


# -- refusal before any query ----------------------------------------------


@pytest.mark.unit
def test_me_without_a_cookie_is_unauthorized(client: TestClient) -> None:
    payload = _assert_problem(client.get("/api/v1/me"), 401)

    assert payload["instance"] == "/api/v1/me"
    assert payload["detail"] == "A valid session is required for this request."


@pytest.mark.unit
def test_me_with_a_malformed_cookie_is_unauthorized_and_explains_nothing(
    client: TestClient,
) -> None:
    """Missing, malformed, expired and revoked share one answer on purpose.

    Which of those happened tells a caller who presented a token how that
    token relates to a real session - information they did not have before
    they asked.
    """
    _present_cookie(client, MALFORMED_TOKEN)
    response = client.get("/api/v1/me")

    payload = _assert_problem(response, 401)
    for word in ("expired", "revoked", "malformed", "unknown", "tampered"):
        assert word not in payload["detail"].lower()


@pytest.mark.unit
def test_logout_without_a_cookie_is_unauthorized(client: TestClient) -> None:
    payload = _assert_problem(client.post("/api/v1/auth/logout"), 401)

    assert payload["detail"] == "A valid session is required for this request."


@pytest.mark.unit
def test_logout_of_an_implausible_cookie_never_reaches_the_database(
    client: TestClient,
) -> None:
    """A syntactically impossible token is refused by inspection alone.

    Exercised here rather than assumed: the test above only proves the
    *absent* cookie path skips the database, and a garbage cookie is the
    shape an attacker actually sends.
    """
    _present_cookie(client, MALFORMED_TOKEN)
    response = client.post("/api/v1/auth/logout")

    _assert_problem(response, 401)


# -- the database being down is its own answer ------------------------------


@pytest.mark.unit
def test_login_reports_an_unreachable_database_as_service_unavailable(
    client: TestClient,
) -> None:
    """503, not 401: the credentials were never evaluated.

    A 401 here would tell a user their password is wrong when we do not know
    it, and a 200 would be a session that does not exist.
    """
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": FORM_PASSWORD},
    )

    payload = _assert_problem(response, 503)
    assert payload["detail"] == (
        "The service is temporarily unavailable. Please try again shortly."
    )

    body = response.text
    for name, secret in (
        ("the submitted password", FORM_PASSWORD),
        ("a connection string", "postgresql://"),
        ("the credential inside it", "unit_tests"),
    ):
        assert secret not in body, f"the 503 body contained {name}"

    # Nothing beyond the problem document: no session, no account, no
    # internals dressed up as a response the client could act on.
    assert set(payload) <= {"type", "title", "status", "detail", "instance"}


@pytest.mark.unit
def test_me_reports_an_unreachable_database_instead_of_claiming_unauthorized(
    client: TestClient,
) -> None:
    """A live-looking token cannot be checked, so the answer must be 503.

    Saying 401 here would report a conclusion - "this session is no good" -
    that was never reached.
    """
    _present_cookie(client, PLAUSIBLE_BUT_UNKNOWN_TOKEN)
    response = client.get("/api/v1/me")

    _assert_problem(response, 503)


@pytest.mark.unit
def test_logout_reports_an_unreachable_database_instead_of_claiming_success(
    client: TestClient,
) -> None:
    """The session was not revoked, so 204 would be false and 401 a guess."""
    _present_cookie(client, PLAUSIBLE_BUT_UNKNOWN_TOKEN)
    response = client.post("/api/v1/auth/logout")

    _assert_problem(response, 503)


# -- validation refuses before the service is called ------------------------


@pytest.mark.unit
def test_a_login_body_is_never_echoed_back_when_it_fails_validation(
    client: TestClient,
) -> None:
    """A validation error about a credential must not print the credential."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": OVERSIZED_PASSWORD},
    )

    payload = _assert_problem(response, 422)
    assert payload["detail"] == "One or more fields in the request failed validation."
    assert OVERSIZED_PASSWORD not in response.text
    assert "input" not in payload["errors"][0], "the submitted value was reflected"


@pytest.mark.unit
def test_login_refuses_a_body_that_introduces_a_token_field(client: TestClient) -> None:
    """The contract has no token field, so a body carrying one is rejected.

    The session token lives only in the ``HttpOnly`` cookie. A route that
    quietly accepted one would rebuild, over JSON, exactly the exposure the
    cookie exists to avoid.
    """
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.com",
            "password": FORM_PASSWORD,
            "token": "b" * 43,
        },
    )

    payload = _assert_problem(response, 422)
    assert "token" in str(payload["errors"])
    assert "b" * 43 not in response.text


@pytest.mark.unit
def test_login_refuses_a_body_that_introduces_a_session_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": FORM_PASSWORD, "session_id": "1"},
    )

    payload = _assert_problem(response, 422)
    assert "session_id" in str(payload["errors"])


# -- indistinguishability ---------------------------------------------------


@pytest.fixture
def refusal_client(settings: Settings) -> Iterator[TestClient]:
    """An app with one route that fails with a reason the caller chooses.

    The reason on :class:`InvalidCredentials` is server-side vocabulary: it
    distinguishes "no such account" from "wrong password" in the log, and must
    never reach the client. A probe is the only way to show that from outside,
    because the real login path withholds it before it ever gets here - and
    with no database, it does not get here at all.
    """
    app = create_app(settings)

    @app.post("/_refuse")
    async def refuse(request: Request) -> None:
        raise InvalidCredentials(reason=request.query_params.get("reason", "unknown"))

    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
def test_a_refusal_says_the_same_thing_whatever_the_internal_reason(
    refusal_client: TestClient,
) -> None:
    """Identical status, identical body: no enumeration oracle at the boundary."""
    unknown = refusal_client.post("/_refuse", params={"reason": "unknown account"})
    wrong = refusal_client.post("/_refuse", params={"reason": "wrong password"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.content == wrong.content, "the two refusals were distinguishable"

    body = unknown.text
    for leaked in ("unknown account", "wrong password", "reason"):
        assert leaked not in body, f"the internal {leaked!r} reached the client"


# -- what is mounted, and what the contract promises ------------------------


@pytest.mark.unit
def test_unversioned_auth_aliases_do_not_exist(client: TestClient) -> None:
    """Only ``/api/v1`` serves auth; a second spelling is a second contract."""
    for path in ("/auth/login", "/auth/logout", "/me"):
        response = client.request("POST" if "login" in path else "GET", path)

        assert response.status_code == 404, f"{path} should not be routed"
        assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)


@pytest.mark.unit
def test_the_documented_auth_payloads_carry_no_token_or_session_id(
    client: TestClient,
) -> None:
    """The omissions are in the published contract, not only in the models."""
    schema = client.get("/openapi.json").json()
    schemas: dict[str, Any] = schema["components"]["schemas"]

    assert set(schemas["AuthContextResponse"]["properties"]) == {"user", "session"}
    assert set(schemas["UserProfile"]["properties"]) == {
        "id",
        "email",
        "display_name",
        "is_superuser",
        "created_at",
    }
    assert set(schemas["SessionProfile"]["properties"]) == {"issued_at", "expires_at"}
    assert set(schemas["LoginRequest"]["properties"]) == {"email", "password"}

    for name in ("AuthContextResponse", "UserProfile", "SessionProfile", "LoginRequest"):
        published = set(schemas[name].get("properties", {}))
        assert "token" not in published, name
        assert "session_id" not in published, name
        assert "session_token" not in published, name


@pytest.mark.unit
def test_the_login_route_sets_no_cookie_when_it_cannot_log_anyone_in(
    client: TestClient,
) -> None:
    """A 503 must not carry a ``Set-Cookie`` the browser would keep."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": FORM_PASSWORD},
    )

    assert response.status_code == 503
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
