"""The session cookie: one name, and the flags each response must set.

Why a cookie at all, rather than a token the browser holds: the session
credential is the one secret a page must present on every request, and a
value readable by JavaScript is a value any injected script can also read.
An ``HttpOnly`` cookie is invisible to the page, so an XSS bug cannot walk
away with a live session.

The flags are chosen rather than defaulted:

``httponly``
    not readable from script - see above.
``samesite="lax"``
    a cross-site ``POST`` does not carry the cookie, which is what makes a
    third-party form unable to submit a state-changing request as the
    signed-in user. ``strict`` would break legitimate inbound links (the
    first navigation from an external site arrives without the cookie);
    ``none`` would surrender the property entirely and require HTTPS.
``secure``
    set only in production, where the origin is HTTPS. Setting it in local
    development would make the cookie unsendable over plain ``http`` and
    break login without improving anything on a loopback interface.
``path="/"`
    one session covers the whole application.

The cookie is set on the login response and cleared on logout; reading it
back out is a separate concern and lives with the dependency that resolves
it to a session.
"""

from __future__ import annotations

from fastapi import Response

SESSION_COOKIE_NAME = "hqos_session"
SESSION_COOKIE_PATH = "/"


def set_session_cookie(
    response: Response,
    token: str,
    *,
    max_age_seconds: int,
    secure: bool,
) -> None:
    """Attach the session token to ``response`` as an ``HttpOnly`` cookie."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age_seconds,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    """Expire the session cookie.

    Every attribute must match the one used when the cookie was set, or the
    browser treats it as a different cookie and leaves the original in place.
    """
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


__all__ = [
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_PATH",
    "clear_session_cookie",
    "set_session_cookie",
]
