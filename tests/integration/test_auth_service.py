"""The authentication failure matrix, exercised against real PostgreSQL.

Every branch in ``harsh_quant_os.auth.service`` is driven here, because the
interesting behaviour of that module only exists once a row is really read
and really written: an audit record that "would have been" staged is not
evidence of anything.

Four properties are asserted repeatedly because they are the ones that would
be expensive to get wrong:

* **Every login refusal is the same from outside.** Unknown address, wrong
  password, deactivated account and oversized input all raise the same class
  with the same message, and the differing internal reason never appears in
  that message.
* **The token exists only in memory and in the cookie.** The database holds
  an HMAC, never the token; no JSON payload carries it.
* **Refusals that never reach the database leave no trace** - a malformed
  cookie is answered without a query, so junk cannot make PostgreSQL work.
* **Nothing sensitive reaches the log.** Password, token, secret key and
  connection string are all checked against the records every authentication
  path produces - including the database-failure log line, which is written
  exactly where the driver's password-bearing message would otherwise go.

Tables are not truncated between tests: each test mints a fresh address, so
the suite never needs to delete audit rows it just proved were append-only.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from harsh_quant_os.auth import AuthService
from harsh_quant_os.auth.errors import (
    DatabaseUnavailable,
    DuplicateUser,
    InvalidCredentials,
    PasswordPolicyError,
    SessionExpired,
    SessionInvalid,
    SessionRevoked,
)
from harsh_quant_os.auth.tokens import is_plausible_session_token
from harsh_quant_os.config import Settings
from harsh_quant_os.db import build_engine, build_session_factory, dispose_engine

from ._db import rows

pytestmark = pytest.mark.integration

#: Deliberately under 24 characters: the repository's no-secrets scanner
#: flags any `password = "<24+ chars>"` assignment, and a throwaway account
#: for a test must not look like a credential worth protecting.
PASSWORD = "quant-dev-passphrase"

#: Nothing listens here, so a connection is refused immediately.
UNREACHABLE_DATABASE = "postgresql+asyncpg://integration:integration@127.0.0.1:5/integration"


def _email(label: str) -> str:
    """A fresh address for one test.

    Unique per call rather than per test name so that re-running a single
    test, or running them in a random order, does not collide with rows a
    previous run left behind - the suite has no truncation step by design.
    """
    return f"{label}-{uuid.uuid4().hex[:12]}@example.com"


async def _account(auth_service: AuthService, label: str) -> str:
    """Create an account and return its address."""
    email = _email(label)
    await auth_service.create_user(email=email, password=PASSWORD)
    return email


async def _audit(engine: AsyncEngine, *, email: str | None = None) -> list[tuple[object, ...]]:
    """Audit rows, as ``(event, outcome, detail)``, newest last."""
    if email is None:
        statement = "SELECT event_type, outcome, detail FROM audit_log ORDER BY id"
        params: dict[str, object] = {}
    else:
        statement = (
            "SELECT event_type, outcome, detail FROM audit_log "
            "WHERE actor_email = :email ORDER BY id"
        )
        params = {"email": email}
    return await rows(engine, statement, params)


# -- creating accounts -----------------------------------------------------


async def test_create_user_stores_a_hash_and_records_it(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("created")
    user = await auth_service.create_user(email=email, password=PASSWORD, display_name="Ada")

    (stored,) = (
        await rows(engine, "SELECT password_hash FROM users WHERE id = :id", {"id": user.id})
    )[0]
    assert stored != PASSWORD
    assert stored.startswith("$argon2id$"), "the stored credential is not an Argon2id hash"
    assert PASSWORD not in stored, "the password appears verbatim in storage"

    assert await _audit(engine, email=email) == [("user.created", "success", "account created")]


async def test_the_same_address_cannot_be_created_twice(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("duplicate")
    await auth_service.create_user(email=email, password=PASSWORD)

    with pytest.raises(DuplicateUser):
        await auth_service.create_user(email=email, password=PASSWORD)

    (count,) = (
        await rows(engine, "SELECT count(*) FROM users WHERE email = :email", {"email": email})
    )[0]
    assert count == 1, "a duplicate insert was not refused"


async def test_address_case_and_padding_are_the_same_account(auth_service: AuthService) -> None:
    email = _email("cased")
    await auth_service.create_user(email=email.upper(), password=PASSWORD)

    with pytest.raises(DuplicateUser):
        await auth_service.create_user(email=f"   {email}   ", password=PASSWORD)


@pytest.mark.parametrize(
    "password",
    [
        "too-short",
        " " * 12,
        "x" * 4096,
    ],
)
async def test_passwords_the_policy_refuses(auth_service: AuthService, password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        await auth_service.create_user(email=_email("policy"), password=password)


@pytest.mark.parametrize(
    "email_value",
    [
        "",
        "not-an-email",
        "a@b",
        "a b@example.com",
        "x" * 300 + "@example.com",
    ],
)
async def test_addresses_the_policy_refuses(auth_service: AuthService, email_value: str) -> None:
    with pytest.raises(PasswordPolicyError):
        await auth_service.create_user(email=email_value, password=PASSWORD)


# -- logging in ------------------------------------------------------------


async def test_login_issues_a_token_that_is_never_stored(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("login")
    await auth_service.create_user(email=email, password=PASSWORD)

    result = await auth_service.login(email=email, password=PASSWORD, request_id="req-login")
    assert result.user.email == email
    assert is_plausible_session_token(result.token)

    stored = await rows(
        engine, "SELECT token_hash FROM sessions WHERE user_id = :id", {"id": result.user.id}
    )
    assert len(stored) == 1
    token_hash = str(stored[0][0])
    assert token_hash != result.token
    assert len(token_hash) == 64, "the stored value is not the SHA-256 MAC the design specifies"
    assert result.token not in token_hash

    assert ("auth.login.succeeded", "success", "session opened") in await _audit(
        engine, email=email
    )


async def test_a_second_login_opens_a_second_session(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("twice")
    await auth_service.create_user(email=email, password=PASSWORD)

    first = await auth_service.login(email=email, password=PASSWORD)
    second = await auth_service.login(email=email, password=PASSWORD)

    assert first.token != second.token
    (count,) = (
        await rows(
            engine, "SELECT count(*) FROM sessions WHERE user_id = :id", {"id": first.user.id}
        )
    )[0]
    assert count == 2


async def test_unknown_address_and_wrong_password_are_indistinguishable(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    """The pair of answers must be byte-identical, or the form enumerates."""
    email = _email("wrong")
    ghost = _email("nobody")
    await auth_service.create_user(email=email, password=PASSWORD)

    with pytest.raises(InvalidCredentials) as wrong:
        await auth_service.login(email=email, password=PASSWORD + "x")
    with pytest.raises(InvalidCredentials) as unknown:
        await auth_service.login(email=ghost, password=PASSWORD)

    assert type(wrong.value) is type(unknown.value) is InvalidCredentials
    assert str(wrong.value) == str(unknown.value)
    for failure in (wrong.value, unknown.value):
        assert failure.reason not in str(failure), "the internal reason leaked into the message"

    # ...while both remain distinguishable where it belongs: the audit trail.
    real_details = {str(row[2]) for row in await _audit(engine, email=email)}
    ghost_details = {str(row[2]) for row in await _audit(engine, email=ghost)}
    assert "password did not match" in real_details
    assert "no account for the submitted address" in ghost_details


async def test_a_deactivated_account_cannot_log_in(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("inactive")
    user = await auth_service.create_user(email=email, password=PASSWORD)
    await rows(engine, "UPDATE users SET is_active = false WHERE id = :id", {"id": user.id})

    with pytest.raises(InvalidCredentials) as failure:
        await auth_service.login(email=email, password=PASSWORD)
    assert failure.value.reason == "inactive account"
    assert str(failure.value) == "authentication failed"

    details = {str(row[2]) for row in await _audit(engine, email=email)}
    assert "account is deactivated" in details


async def test_an_oversized_password_is_refused_before_it_is_hashed(
    auth_service: AuthService,
) -> None:
    email = _email("oversized")
    await auth_service.create_user(email=email, password=PASSWORD)

    with pytest.raises(InvalidCredentials) as failure:
        await auth_service.login(email=email, password="x" * 4096)
    assert failure.value.reason == "password length"


async def test_an_unknown_account_still_spends_the_hashing_work(
    auth_service: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unknown-user branch must burn time rather than skip it.

    The spy calls the real implementation, so this proves the branch ran
    without replacing the cost with something cheaper than production pays.
    """
    import harsh_quant_os.auth.service as service_module
    from harsh_quant_os.auth.hashing import burn_password_check as real_burn

    burned: list[str] = []

    def spy(password: str) -> None:
        burned.append("burned")
        real_burn(password)

    monkeypatch.setattr(service_module, "burn_password_check", spy)

    with pytest.raises(InvalidCredentials):
        await auth_service.login(email=_email("ghost"), password=PASSWORD)
    assert burned == ["burned"], "an unknown account did not spend verification work"

    email = _email("real")
    await auth_service.create_user(email=email, password=PASSWORD)
    with pytest.raises(InvalidCredentials):
        await auth_service.login(email=email, password=PASSWORD + "x")
    assert burned == ["burned"], "the wrong-password path must verify, not burn"


# -- holding a session -----------------------------------------------------


async def test_a_live_token_resolves_to_its_own_account(auth_service: AuthService) -> None:
    alice = await _account(auth_service, "alice")
    bob = await _account(auth_service, "bob")

    alice_session = await auth_service.login(email=alice, password=PASSWORD)
    bob_session = await auth_service.login(email=bob, password=PASSWORD)

    resolved = await auth_service.authenticate(alice_session.token)
    assert resolved.user.email == alice
    assert resolved.user.id != bob_session.user.id


async def test_an_absent_token_is_refused_without_touching_the_database(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    before = len(await _audit(engine))

    with pytest.raises(SessionInvalid) as failure:
        await auth_service.authenticate(None)
    assert failure.value.reason == "no session presented"
    assert str(failure.value) == "session is not valid"

    assert len(await _audit(engine)) == before, "a missing cookie cost a database write"


@pytest.mark.parametrize(
    "junk",
    [
        "short",
        "has.dots.in.it.and.plenty.of.characters",
        "plus+signs+are+not+in+the+urlsafe+alphabet",
        " " * 60,
        "é" * 40,
    ],
)
async def test_a_malformed_token_is_refused_without_a_query(
    auth_service: AuthService, engine: AsyncEngine, junk: str
) -> None:
    before = len(await _audit(engine))

    with pytest.raises(SessionInvalid) as failure:
        await auth_service.authenticate(junk)
    assert failure.value.reason == "malformed session token"

    assert len(await _audit(engine)) == before, "junk cookies made PostgreSQL do work"


async def test_a_tampered_token_is_refused_and_recorded(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("tamper")
    await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    replacement = "A" if result.token[-1] != "A" else "B"
    tampered = result.token[:-1] + replacement
    assert is_plausible_session_token(tampered), "the test must tamper within the accepted shape"

    with pytest.raises(SessionInvalid) as failure:
        await auth_service.authenticate(tampered)
    assert failure.value.reason == "no matching session"

    details = {str(row[2]) for row in await _audit(engine)}
    assert "no session matches the presented token" in details


async def test_an_expired_session_is_refused(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("expired")
    await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    await rows(
        engine,
        "UPDATE sessions SET expires_at = now() - interval '1 hour' WHERE user_id = :id",
        {"id": result.user.id},
    )

    with pytest.raises(SessionExpired):
        await auth_service.authenticate(result.token)


async def test_a_revoked_session_is_refused(auth_service: AuthService) -> None:
    email = _email("revoked")
    await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    assert await auth_service.revoke_session(result.session.id, reason="operator revoked") is True

    with pytest.raises(SessionRevoked):
        await auth_service.authenticate(result.token)
    assert await auth_service.revoke_session(result.session.id, reason="again") is False


async def test_a_session_stops_working_when_its_account_is_deactivated(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    """Disabling an account must kill the sessions it already opened."""
    email = _email("orphan")
    user = await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    await rows(engine, "UPDATE users SET is_active = false WHERE id = :id", {"id": user.id})

    with pytest.raises(SessionInvalid) as failure:
        await auth_service.authenticate(result.token)
    assert failure.value.reason == "session owner is not usable"


async def test_revoking_an_unknown_session_is_not_an_error(auth_service: AuthService) -> None:
    assert await auth_service.revoke_session(uuid.uuid4(), reason="nothing to revoke") is False


# -- logging out -----------------------------------------------------------


async def test_logout_revokes_the_session_immediately(
    auth_service: AuthService, engine: AsyncEngine
) -> None:
    email = _email("logout")
    await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    await auth_service.logout(result.token, request_id="req-logout")

    (row,) = await rows(
        engine,
        "SELECT revoked_at, revoked_reason FROM sessions WHERE user_id = :id",
        {"id": result.user.id},
    )
    assert row[1] == "logout"

    with pytest.raises(SessionRevoked):
        await auth_service.authenticate(result.token)
    assert ("auth.logout.succeeded", "success", "session revoked by logout") in await _audit(
        engine, email=email
    )


async def test_logging_out_twice_is_a_refusal_not_a_second_success(
    auth_service: AuthService,
) -> None:
    email = _email("twice-out")
    await auth_service.create_user(email=email, password=PASSWORD)
    result = await auth_service.login(email=email, password=PASSWORD)

    await auth_service.logout(result.token)
    with pytest.raises(SessionRevoked):
        await auth_service.logout(result.token)


@pytest.mark.parametrize("token", [None, "", "not-a-session-token"])
async def test_logout_without_a_usable_session_is_refused(
    auth_service: AuthService, token: str | None
) -> None:
    with pytest.raises(SessionInvalid):
        await auth_service.logout(token)


# -- infrastructure failures ------------------------------------------------


def test_an_unreachable_database_is_reported_as_unavailable(
    live_settings: Settings,
) -> None:
    """A down server is a typed 503, never a stack trace and never a lie.

    Runs without PostgreSQL at all: the URL points at a closed loopback
    port, so this cannot pass because a database happened to be up.
    """

    async def _attempt() -> DatabaseUnavailable:
        engine = build_engine(UNREACHABLE_DATABASE)
        try:
            service = AuthService(
                session_factory=build_session_factory(engine),
                secret_key=live_settings.auth_secret_key,
                session_ttl=timedelta(minutes=live_settings.auth_token_expiry_minutes),
            )
            try:
                await service.login(email=_email("unreachable"), password=PASSWORD)
            except DatabaseUnavailable as failure:
                return failure
            raise AssertionError("login succeeded against a database that is not there")
        finally:
            await dispose_engine(engine)

    failure = asyncio.run(_attempt())

    assert failure.error_type, "the failure type is what the server logs"
    # The driver's message would carry the connection string, and with it the
    # password; only the type name may cross the boundary.
    assert "postgresql" not in str(failure).lower()
    assert "password" not in str(failure).lower()
    assert PASSWORD not in str(failure)


# -- logging ---------------------------------------------------------------


async def test_nothing_sensitive_reaches_the_log_on_any_auth_path(
    auth_service: AuthService, live_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Drive every code path that has a log line, and read what came out.

    A happy-path login writes nothing at all, so a test that only did that
    would assert against an empty transcript and prove nothing. The records
    the authentication stack does emit are the ones that could leak:

    * ``auth.user_exists`` - a warning carrying the submitted address;
    * ``auth.database_failure`` - written precisely where the SQLAlchemy
      message would otherwise go, and that message embeds the connection
      string and with it the password;
    * ``api.login_refused`` - the internal reason that must never reach the
      client, asserted from the HTTP side in ``tests/api/test_auth_endpoints``.
    """
    email = _email("quiet")
    await auth_service.create_user(email=email, password=PASSWORD)

    with caplog.at_level(logging.DEBUG):
        result = await auth_service.login(email=email, password=PASSWORD, request_id="req-quiet")
        await auth_service.authenticate(result.token)
        await auth_service.logout(result.token)

        with pytest.raises(DuplicateUser):
            await auth_service.create_user(email=email, password=PASSWORD)

        async def _against_a_missing_database() -> None:
            engine = build_engine(UNREACHABLE_DATABASE)
            try:
                service = AuthService(
                    session_factory=build_session_factory(engine),
                    secret_key=live_settings.auth_secret_key,
                    session_ttl=timedelta(minutes=live_settings.auth_token_expiry_minutes),
                )
                await service.login(email=email, password=PASSWORD)
            finally:
                await dispose_engine(engine)

        with pytest.raises(DatabaseUnavailable):
            await _against_a_missing_database()

    messages = [record.getMessage() for record in caplog.records]
    assert messages, "the test proved nothing if nothing was logged"
    assert any("auth.user_exists" in message for message in messages)
    assert any("auth.database_failure" in message for message in messages)

    transcript = " ".join(messages)
    for name, secret in (
        ("password", PASSWORD),
        ("session token", result.token),
        ("AUTH_SECRET_KEY", live_settings.auth_secret_key),
        ("database password", live_settings.database_password),
    ):
        assert secret not in transcript, f"a log record contained the {name}"
    assert "postgresql://" not in transcript, "a connection string reached the log"
