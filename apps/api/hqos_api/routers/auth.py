"""Authentication endpoints: login, logout, and "who am I".

Three routes, mounted by the factory at ``/api/v1``:

============================  ==========================================
``POST /api/v1/auth/login``    verify credentials, set the session cookie
``POST /api/v1/auth/logout``   revoke the session, clear the cookie
``GET  /api/v1/me``            resolve the cookie to the current account
============================  ==========================================

This layer parses, delegates and maps - it never decides. Every judgement
about whether credentials are good or a session is live happens in
:class:`~harsh_quant_os.auth.service.AuthService`; every judgement about
which status code that implies happens once, in ``hqos_api.core.errors``.

Two properties are visible from the outside and are asserted by tests:

* **login answers identically for an unknown address and a wrong password.**
  Both are ``401`` with the same body, because a login form that distinguishes
  them is an account-enumeration oracle.
* **the session token appears only in ``Set-Cookie``.** No JSON payload on
  any route contains it, so nothing a browser renders can expose it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.auth import (
    AuthContextResponse,
    LoginRequest,
    SessionProfile,
    UserProfile,
)
from harsh_quant_os.db.models import User, UserSession
from hqos_api.cookies import SESSION_COOKIE_NAME, clear_session_cookie, set_session_cookie
from hqos_api.dependencies import get_auth_context, get_auth_service, request_id

_PROBLEM = "application/problem+json"

_LOGIN_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": (
            "Credentials were not accepted. The response is identical for an "
            "unknown address and for a wrong password, so it cannot be used "
            "to discover which accounts exist."
        ),
        "content": {_PROBLEM: {"schema": {"type": "object"}}},
    }
}

_AUTH_REQUIRED: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "description": (
            "No usable session: the cookie is missing, malformed, expired or "
            "revoked. One response covers all four."
        ),
        "content": {_PROBLEM: {"schema": {"type": "object"}}},
    }
}


def _context(user: User, session: UserSession) -> AuthContextResponse:
    """Project a resolved account and session onto the shared contract."""
    return AuthContextResponse(
        user=UserProfile(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_superuser=user.is_superuser,
            created_at=user.created_at,
        ),
        session=SessionProfile(
            issued_at=session.created_at,
            expires_at=session.expires_at,
        ),
    )


def create_auth_router(settings: Settings) -> APIRouter:
    """Build a router bound to one explicit ``Settings`` instance."""
    router = APIRouter(tags=["auth"])

    @router.post(
        "/auth/login",
        response_model=AuthContextResponse,
        responses=_LOGIN_RESPONSES,
        summary="Open a session",
        description=(
            "Verifies the submitted credentials and, on success, attaches the "
            "`HttpOnly` session cookie to this response. The body is the same "
            "shape `/me` returns so the client validates one contract either "
            "way. The session token itself is never part of the body."
        ),
    )
    async def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> AuthContextResponse:
        result = await get_auth_service(request).login(
            email=payload.email,
            password=payload.password,
            request_id=request_id(request),
        )
        set_session_cookie(
            response,
            result.token,
            max_age_seconds=settings.auth_token_expiry_minutes * 60,
            # False outside production so that login works over plain http on
            # the loopback development origin; True in production, where the
            # origin is HTTPS and a cookie without it would be refused.
            secure=settings.is_production,
        )
        return _context(result.user, result.session)

    @router.post(
        "/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=_AUTH_REQUIRED,
        summary="Close the session",
        description=(
            "Revokes the session behind the cookie and clears it. Revocation "
            "is recorded server-side, so the token stops working immediately "
            "and does not merely stop being displayed. Calling this again "
            "afterwards returns 401: by then the session really is gone, and "
            "saying otherwise would be false."
        ),
    )
    async def logout(request: Request, response: Response) -> None:
        await get_auth_service(request).logout(
            request.cookies.get(SESSION_COOKIE_NAME),
            request_id=request_id(request),
        )
        clear_session_cookie(response, secure=settings.is_production)

    @router.get(
        "/me",
        response_model=AuthContextResponse,
        responses=_AUTH_REQUIRED,
        summary="Current account",
        description=(
            "Resolves the session cookie to the signed-in account. Returns 401 "
            "with a problem document when there is no usable session."
        ),
    )
    async def me(
        request: Request,
    ) -> AuthContextResponse:
        context = await get_auth_context(request)
        return _context(context.user, context.session)

    return router


__all__ = ["create_auth_router"]
