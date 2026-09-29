"""Authentication application service.

Layering: this module sits between the HTTP routers and the storage layer, so
it may import SQLAlchemy models (the pure domain underneath it - hashing and
tokens - may not import anything from either side).

Three rules shape everything below.

**The service owns its transactions.** Each public method opens a session from
the factory, decides the commit boundary and closes it. A router never calls
``commit``; if it did, "the audit record and the state change are one
transaction" would depend on whichever handler forgot.

**Failure reasons are recorded, not returned.** ``InvalidCredentials`` carries
a ``reason`` that goes to the audit trail and the server log. The HTTP
response is the same for every reason, so a caller cannot use the difference
between "unknown account" and "wrong password" to enumerate accounts.

**Unknown accounts cost the same as wrong passwords.** ``burn_password_check``
runs the same Argon2 work when no user matches, because a login endpoint that
answers in 2 ms for an unknown address and 110 ms for a wrong password is a
user-enumeration oracle wearing a login form.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.audit import AuditEventType, AuditOutcome
from harsh_quant_os.auth.errors import (
    AuthError,
    DatabaseUnavailable,
    DuplicateUser,
    InvalidCredentials,
    PasswordPolicyError,
    SessionExpired,
    SessionInvalid,
    SessionRevoked,
)
from harsh_quant_os.auth.hashing import (
    MAX_PASSWORD_LENGTH,
    burn_password_check,
    hash_password,
    validate_password_policy,
    verify_password,
)
from harsh_quant_os.auth.tokens import (
    generate_session_token,
    hash_session_token,
    is_plausible_session_token,
)
from harsh_quant_os.contracts.provenance import utcnow
from harsh_quant_os.db.models import AuditLog, User, UserSession

logger = logging.getLogger(__name__)

#: RFC 5321 practical limit on an address length.
MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class LoginResult:
    """What a successful login produced.

    ``token`` is the one and only time the raw session token exists outside
    the caller's request; the caller must place it in the session cookie and
    drop it. It is never logged, never stored and never returned in JSON.
    """

    user: User
    session: UserSession
    token: str


@dataclass(frozen=True, slots=True)
class AuthenticatedContext:
    """A caller proven to hold a live session."""

    user: User
    session: UserSession


def normalize_email(email: str) -> str:
    """Canonical form of an address: trimmed and lower-cased.

    Applied everywhere before the value touches the database, which is what
    makes ``users``' ``email = lower(email)`` check satisfiable rather than a
    trap, and what stops ``Ada@Example.com`` and ``ada@example.com`` from
    becoming two accounts.
    """
    return email.strip().lower()


def validate_email(email: str) -> None:
    """Lightweight address sanity check.

    Deliberately not a full RFC 5322 parser: those are large, and a regex
    that claims to validate addresses is usually wrong in one direction or
    the other. This only rejects the cases that would corrupt storage -
    blank, whitespace, no separator, or longer than RFC 5321 allows.
    """
    value = normalize_email(email)
    if not value or len(value) > MAX_EMAIL_LENGTH:
        raise PasswordPolicyError("email address is missing or too long")
    if any(char.isspace() for char in value):
        raise PasswordPolicyError("email address must not contain whitespace")
    local, separator, domain = value.partition("@")
    if not separator or not local or not domain or "." not in domain:
        raise PasswordPolicyError("email address must look like name@example.com")


class AuthService:
    """Login, logout and session validation against PostgreSQL."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        secret_key: str,
        session_ttl: timedelta,
    ) -> None:
        if not secret_key:
            raise ValueError("secret_key is required")
        if session_ttl.total_seconds() <= 0:
            raise ValueError("session_ttl must be positive")
        self._session_factory = session_factory
        self._secret_key = secret_key
        self._session_ttl = session_ttl

    # -- public API -------------------------------------------------------

    async def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
        is_superuser: bool = False,
        request_id: str | None = None,
    ) -> User:
        """Create an account, or raise :class:`DuplicateUser`.

        There is no self-service registration endpoint in Phase 2: an account
        is created out of band (``hqos user create``) so that a private
        research platform never exposes an open sign-up surface to the
        network. This method is the single place that mints credentials.
        """
        validate_email(email)
        validate_password_policy(password)
        normalized = normalize_email(email)
        digest = hash_password(password)

        async with self._session_factory() as session:
            try:
                user = User(
                    email=normalized,
                    password_hash=digest,
                    display_name=display_name.strip() if display_name else None,
                    is_superuser=is_superuser,
                )
                session.add(user)
                await session.flush()
                await self._record(
                    session,
                    event=AuditEventType.USER_CREATED,
                    outcome=AuditOutcome.SUCCESS,
                    actor=user,
                    email=normalized,
                    request_id=request_id,
                    detail="account created",
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.warning("auth.user_exists email=%s", normalized)
                raise DuplicateUser from None
            except AuthError:
                await session.rollback()
                raise
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                await session.rollback()
                raise self._database_failure("create_user", exc) from exc
        return user

    async def login(
        self,
        *,
        email: str,
        password: str,
        request_id: str | None = None,
    ) -> LoginResult:
        """Authenticate and open a session.

        Every refusal raises :class:`InvalidCredentials`, which the API layer
        turns into one indistinguishable 401. The specific reason is written
        to ``audit_log`` before the exception is raised.
        """
        normalized = normalize_email(email) if isinstance(email, str) else ""

        async with self._session_factory() as session:
            try:
                result = await self._attempt_login(session, normalized, password, request_id)
                # `_attempt_login` only flushes: without a commit here the new
                # session row and its audit row are rolled back by the context
                # manager as it closes, and the token just minted would resolve
                # to nothing - a login that "succeeded" but could never be used.
                # Both outcomes of a login are durable by design: the success
                # above, the refusal below.
                await session.commit()
                return result
            except InvalidCredentials:
                # `_attempt_login` staged the audit row for this refusal in
                # the same session. Commit it: the refusal must be durable
                # even though the login was not. Nothing else can be pending,
                # because a login makes no state change before it succeeds.
                await session.commit()
                raise
            except AuthError:
                await session.rollback()
                raise
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                await session.rollback()
                raise self._database_failure("login", exc) from exc

    async def authenticate(
        self,
        token: str | None,
        *,
        request_id: str | None = None,
    ) -> AuthenticatedContext:
        """Resolve a presented token to a live session, or refuse.

        Covers every way a token can be unusable: absent, malformed,
        tampered with (so it matches no row), expired, revoked, or belonging
        to a deactivated account. Each produces a distinct internal reason
        and the same external 401.
        """
        if not token:
            raise SessionInvalid(reason="no session presented")
        if not is_plausible_session_token(token):
            # Shape check first: a malformed cookie must not cost a query.
            raise SessionInvalid(reason="malformed session token")

        token_hash = hash_session_token(token, self._secret_key)
        async with self._session_factory() as session:
            try:
                return await self._resolve_session(session, token_hash, request_id)
            except SessionInvalid:
                # `_resolve_session` staged the rejection audit row; keep it.
                await session.commit()
                raise
            except AuthError:
                await session.rollback()
                raise
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                await session.rollback()
                raise self._database_failure("authenticate", exc) from exc

    async def logout(
        self,
        token: str | None,
        *,
        request_id: str | None = None,
    ) -> None:
        """Revoke the session behind ``token``.

        Repeating the call is **not** idempotent success: after the first
        logout the token no longer resolves to a usable session, so the second
        attempt raises :class:`SessionRevoked` exactly like any other request
        with a dead session. That is the honest answer - the session really is
        gone - and it keeps "revoked sessions are rejected" true without a
        special case.
        """
        if not token or not is_plausible_session_token(token):
            raise SessionInvalid(reason="malformed session token")

        token_hash = hash_session_token(token, self._secret_key)
        async with self._session_factory() as session:
            try:
                row = await session.scalar(
                    select(UserSession).where(UserSession.token_hash == token_hash)
                )
                if row is None:
                    raise SessionInvalid(reason="no such session")
                if row.revoked_at is not None:
                    await self._record(
                        session,
                        event=AuditEventType.SESSION_REJECTED,
                        outcome=AuditOutcome.FAILURE,
                        session_id=row.id,
                        request_id=request_id,
                        detail="logout on an already revoked session",
                    )
                    raise SessionRevoked()

                user = await session.get(User, row.user_id)
                now = utcnow()
                row.revoked_at = now
                row.revoked_reason = "logout"
                await session.flush()
                await self._record(
                    session,
                    event=AuditEventType.LOGOUT_SUCCEEDED,
                    outcome=AuditOutcome.SUCCESS,
                    actor=user,
                    email=user.email if user else None,
                    session_id=row.id,
                    request_id=request_id,
                    detail="session revoked by logout",
                )
                await session.commit()
            except AuthError:
                # Either the audit row above must be kept (rejection path) or
                # there is nothing worth keeping (pre-audit failure). In both
                # cases the transaction holds only what we meant to write.
                await session.commit()
                raise
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                await session.rollback()
                raise self._database_failure("logout", exc) from exc

    async def revoke_session(
        self,
        session_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> bool:
        """Revoke a session by id. Returns ``True`` when something changed.

        Exists so that revocation has one implementation regardless of what
        triggers it; an unknown id or an already-revoked session returns
        ``False`` rather than raising, because the caller's intent (this
        session must be dead) is already satisfied.
        """
        async with self._session_factory() as session:
            try:
                row = await session.get(UserSession, session_id)
                if row is None:
                    return False
                if row.revoked_at is not None:
                    return False
                user = await session.get(User, row.user_id)
                row.revoked_at = utcnow()
                row.revoked_reason = reason
                await session.flush()
                await self._record(
                    session,
                    event=AuditEventType.SESSION_REVOKED,
                    outcome=AuditOutcome.SUCCESS,
                    actor=user,
                    email=user.email if user else None,
                    session_id=row.id,
                    request_id=request_id,
                    detail=reason,
                )
                await session.commit()
                return True
            except AuthError:
                await session.rollback()
                raise
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                await session.rollback()
                raise self._database_failure("revoke_session", exc) from exc

    # -- internals --------------------------------------------------------

    async def _attempt_login(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        request_id: str | None,
    ) -> LoginResult:
        too_long = not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH
        if too_long:
            await self._record(
                session,
                event=AuditEventType.LOGIN_FAILED,
                outcome=AuditOutcome.FAILURE,
                email=email or None,
                request_id=request_id,
                detail="password length outside accepted bounds",
            )
            raise InvalidCredentials(reason="password length")

        user = await session.scalar(select(User).where(User.email == email))

        if user is None:
            # Same work as a real verification, so timing cannot distinguish
            # "no such account" from "wrong password".
            burn_password_check(password)
            await self._record(
                session,
                event=AuditEventType.LOGIN_FAILED,
                outcome=AuditOutcome.FAILURE,
                email=email or None,
                request_id=request_id,
                detail="no account for the submitted address",
            )
            raise InvalidCredentials(reason="unknown account")

        if not user.is_active:
            # Still spend the verification: an inactive account is an
            # equally unhelpful answer, and short-circuiting it would leak.
            verify_password(user.password_hash, password)
            await self._record(
                session,
                event=AuditEventType.LOGIN_FAILED,
                outcome=AuditOutcome.FAILURE,
                actor=user,
                email=user.email,
                request_id=request_id,
                detail="account is deactivated",
            )
            raise InvalidCredentials(reason="inactive account")

        if not verify_password(user.password_hash, password):
            await self._record(
                session,
                event=AuditEventType.LOGIN_FAILED,
                outcome=AuditOutcome.FAILURE,
                actor=user,
                email=user.email,
                request_id=request_id,
                detail="password did not match",
            )
            raise InvalidCredentials(reason="password mismatch")

        token = generate_session_token()
        row = UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token, self._secret_key),
            expires_at=utcnow() + self._session_ttl,
        )
        session.add(row)
        await session.flush()
        await self._record(
            session,
            event=AuditEventType.LOGIN_SUCCEEDED,
            outcome=AuditOutcome.SUCCESS,
            actor=user,
            email=user.email,
            session_id=row.id,
            request_id=request_id,
            detail="session opened",
        )
        return LoginResult(user=user, session=row, token=token)

    async def _resolve_session(
        self,
        session: AsyncSession,
        token_hash: str,
        request_id: str | None,
    ) -> AuthenticatedContext:
        row = await session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        if row is None:
            # Presented, plausible, and matches nothing: a tampered token, or
            # one made stale by rotating AUTH_SECRET_KEY.
            await self._record(
                session,
                event=AuditEventType.SESSION_REJECTED,
                outcome=AuditOutcome.FAILURE,
                request_id=request_id,
                detail="no session matches the presented token",
            )
            raise SessionInvalid(reason="no matching session")

        if row.revoked_at is not None:
            await self._record(
                session,
                event=AuditEventType.SESSION_REJECTED,
                outcome=AuditOutcome.FAILURE,
                session_id=row.id,
                request_id=request_id,
                detail="session was revoked",
            )
            raise SessionRevoked()

        if row.expires_at <= utcnow():
            await self._record(
                session,
                event=AuditEventType.SESSION_REJECTED,
                outcome=AuditOutcome.FAILURE,
                session_id=row.id,
                request_id=request_id,
                detail="session past its expiry",
            )
            raise SessionExpired()

        user = await session.get(User, row.user_id)
        if user is None or not user.is_active:
            # The session outlived its account, or the account was disabled
            # after login. Either way the session stops working.
            await self._record(
                session,
                event=AuditEventType.SESSION_REJECTED,
                outcome=AuditOutcome.FAILURE,
                session_id=row.id,
                request_id=request_id,
                detail="session owner missing or deactivated",
            )
            raise SessionInvalid(reason="session owner is not usable")

        return AuthenticatedContext(user=user, session=row)

    async def _record(
        self,
        session: AsyncSession,
        *,
        event: AuditEventType,
        outcome: AuditOutcome,
        actor: User | None = None,
        email: str | None = None,
        session_id: uuid.UUID | None = None,
        detail: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Stage one audit row in the caller's transaction.

        Staged rather than committed here on purpose: backend.md rule 4
        requires the audit record and the state change to land in the *same*
        transaction, so this method never commits. The caller decides.
        """
        session.add(
            AuditLog(
                event_type=event.value,
                outcome=outcome.value,
                actor_user_id=actor.id if actor is not None else None,
                actor_email=email.lower() if isinstance(email, str) else None,
                session_id=session_id,
                detail=detail,
                request_id=request_id,
            )
        )
        await session.flush()

    @staticmethod
    def _database_failure(operation: str, exc: BaseException) -> DatabaseUnavailable:
        """Log the failure type internally and build the client-safe error.

        Only the exception's *type* is logged. A SQLAlchemy message can embed
        the connection string, which embeds the password, so the message is
        never written and never raised across the HTTP boundary.
        """
        logger.error(
            "auth.database_failure operation=%s error_type=%s",
            operation,
            type(exc).__name__,
        )
        return DatabaseUnavailable(type(exc).__name__)


__all__ = [
    "MAX_EMAIL_LENGTH",
    "AuthService",
    "AuthenticatedContext",
    "LoginResult",
    "normalize_email",
    "validate_email",
]
