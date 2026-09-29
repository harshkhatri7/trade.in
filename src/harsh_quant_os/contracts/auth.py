"""Authentication contract shared by the API and the web client.

The Python models here are authoritative; ``packages/types/src/auth.ts``
mirrors them for the browser, and drift is caught by tests rather than by
review:

- ``tests/api/test_auth_contract_parity.py`` compares field names and the
  shared fixture against the TypeScript source;
- ``tests/unit/auth-contract.test.ts`` performs the same comparison in the
  opposite direction.

Two deliberate omissions are part of the contract:

* **No token field.** The session token travels only in an ``HttpOnly``
  cookie, so no JSON payload - not login, not ``/me`` - can carry it. A
  browser-side JavaScript read of the token would make it reachable by any
  injected script; keeping it out of JSON means there is nothing to read.
* **No session id.** Knowing a session's id grants nothing (the cookie is
  what grants), and publishing an internal handle into every response buys
  an attacker a correlation key for no user-visible benefit.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    """The authenticated account, as login and ``/me`` report it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID = Field(description="Stable account identifier.")
    email: str = Field(description="Normalised (lower-cased) address.")
    display_name: str | None = Field(
        default=None, description="Optional display name; `null` when unset."
    )
    is_superuser: bool = Field(
        description="True for the account that owns this private installation."
    )
    created_at: datetime = Field(description="Account creation time, timezone-aware.")


class SessionProfile(BaseModel):
    """Lifetime of the session that authorised the current request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issued_at: datetime = Field(description="When the session was opened.")
    expires_at: datetime = Field(
        description="Absolute deadline after which the session stops working."
    )


class AuthContextResponse(BaseModel):
    """Answer to "who am I, and how long may I stay?".

    Served by both ``POST /api/v1/auth/login`` and ``GET /api/v1/me`` so the
    client has exactly one shape to validate regardless of how the context
    was obtained.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user: UserProfile
    session: SessionProfile


class LoginRequest(BaseModel):
    """Credentials posted to ``POST /api/v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    # Bounded so that an oversized body is rejected before it can reach the
    # password hasher; Argon2's cost is independent of input length, but the
    # memory to hold the input is not.
    password: str = Field(min_length=1, max_length=1024)


__all__ = [
    "AuthContextResponse",
    "LoginRequest",
    "SessionProfile",
    "UserProfile",
]
