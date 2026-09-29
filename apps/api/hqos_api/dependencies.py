"""FastAPI dependencies: how a router obtains its collaborators.

Everything a handler needs is resolved from ``app.state`` here rather than
imported as a module global. That keeps one owner for each piece of
long-lived state - the factory builds it and disposes it - and it means a
test can substitute a probe by replacing an attribute, without the
application growing a second construction path.

None of these functions performs business logic. They locate collaborators
and stop there; the decision-making lives in the application service.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.auth.errors import SessionInvalid
from harsh_quant_os.auth.service import AuthenticatedContext, AuthService
from hqos_api.cookies import SESSION_COOKIE_NAME

#: A readiness probe: returns whether PostgreSQL answered a round trip.
DatabasePing = Callable[[], Awaitable[bool]]


def request_id(request: Request) -> str | None:
    """The correlation id this request is being served under, if any.

    Passed into the audit trail so a refused login can be tied back to the
    server log line that recorded it.
    """
    value = getattr(request.state, "request_id", "")
    return str(value) if value else None


def get_database_ping(request: Request) -> DatabasePing:
    """Return the ping installed by the application factory.

    The cast is deliberate and visible: ``app.state`` is untyped because it
    is a bag of attributes, so the shape is asserted here, at the single
    place that reads it, rather than silently widening the return type.
    """
    return cast(DatabasePing, request.app.state.database_ping)


def get_auth_service(request: Request) -> AuthService:
    """Return the authentication service owned by this application."""
    return cast(AuthService, request.app.state.auth_service)


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the session maker installed by the application factory.

    Read-only handlers receive the real one: handing a reader a private
    factory would mean testing a wiring the process does not have. What
    makes these callers safe is that they only ever select.
    """
    return cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)


def get_store_root(request: Request) -> Path:
    """Return the dataset store this application reads artefacts from.

    Resolved per request rather than captured when the router is built,
    so a test can point one application at a store of its own without the
    reader knowing anything changed. The factory pins it to
    ``DEFAULT_STORE_ROOT``; there is no setting for it, because every
    entry point in this repository runs from the repository root and the
    directory is workspace state, not configuration.
    """
    return cast(Path, request.app.state.store_root)


async def get_auth_context(request: Request) -> AuthenticatedContext:
    """Resolve the session cookie into a live session, or fail.

    Raises :class:`~harsh_quant_os.auth.errors.SessionInvalid` and its
    subclasses when there is no usable session. The mapping from that
    exception to an HTTP 401 lives in ``hqos_api.core.errors`` so that no
    router invents its own answer.
    """
    service = get_auth_service(request)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        # An absent cookie is the ordinary state of a signed-out visitor,
        # not an attack: it is refused without writing an audit row.
        raise SessionInvalid(reason="no session cookie presented")
    return await service.authenticate(token, request_id=request_id(request))


__all__ = [
    "DatabasePing",
    "get_auth_context",
    "get_auth_service",
    "get_database_ping",
    "get_session_factory",
    "get_store_root",
    "request_id",
]
