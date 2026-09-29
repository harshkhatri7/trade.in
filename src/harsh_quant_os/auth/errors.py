"""Authentication failures as a typed hierarchy.

Every error here means *the caller's credentials or session were not
accepted*. None of them carries a reason string that could distinguish
"no such account" from "wrong password" to a remote caller - that
distinction is the single most useful thing an attacker can learn from a
login form, so it stays out of the response and out of the exception
message. The detail a human needs is written to the audit trail instead,
where it belongs.

HTTP status mapping lives in the API layer (``hqos_api.core.errors``), not
here: this module must not import FastAPI.
"""

from __future__ import annotations


class AuthError(Exception):
    """Base class for every authentication failure."""


class InvalidCredentials(AuthError):
    """Login was refused.

    Deliberately one class for "unknown user", "wrong password" and
    "inactive account": collapsing them is what keeps the response identical
    across all three.
    """

    def __init__(self, reason: str = "invalid credentials") -> None:
        # ``reason`` is for the audit trail and server-side logs only; it is
        # never interpolated into an HTTP response.
        super().__init__("authentication failed")
        self.reason = reason


class SessionInvalid(AuthError):
    """No usable session: absent, malformed, tampered with, or unknown."""

    def __init__(self, reason: str = "invalid session") -> None:
        super().__init__("session is not valid")
        self.reason = reason


class SessionExpired(SessionInvalid):
    """The session's absolute deadline has passed."""

    def __init__(self) -> None:
        super().__init__(reason="session expired")


class SessionRevoked(SessionInvalid):
    """The session was ended by logout or an explicit revocation."""

    def __init__(self) -> None:
        super().__init__(reason="session revoked")


class DuplicateUser(AuthError):
    """An account with that address already exists."""

    def __init__(self) -> None:
        super().__init__("user already exists")


class PasswordPolicyError(AuthError):
    """A password offered at creation time does not meet the local policy."""

    def __init__(self, detail: str) -> None:
        super().__init__("password rejected by policy")
        self.detail = detail


class DatabaseUnavailable(AuthError):
    """The database could not be reached or failed mid-transaction.

    Raised only after the underlying driver error has been captured for the
    server-side log. The client receives a generic 503 problem document - the
    driver's message can contain the connection string and must not cross the
    boundary.
    """

    def __init__(self, error_type: str) -> None:
        super().__init__("database unavailable")
        self.error_type = error_type


__all__ = [
    "AuthError",
    "DatabaseUnavailable",
    "DuplicateUser",
    "InvalidCredentials",
    "PasswordPolicyError",
    "SessionExpired",
    "SessionInvalid",
    "SessionRevoked",
]
