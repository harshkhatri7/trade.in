"""Opaque session tokens: generation, and the key used to look one up.

A session token is a bearer credential - whoever holds it *is* the session -
so three properties matter:

1. **Unpredictable.** 256 bits from ``secrets`` (a CSPRNG), not ``random``,
   which is predictable from its observable state.
2. **Never stored.** The database keeps ``HMAC-SHA256(AUTH_SECRET_KEY, token)``.
   Because the token has 256 bits of entropy, the stored value cannot be
   inverted by brute force; and because the MAC is keyed, an attacker with a
   database dump still cannot forge a lookup value for a token they choose.
   Rotating ``AUTH_SECRET_KEY`` therefore invalidates every session at once -
   a useful property during an incident, and the reason the key exists.
3. **Cheaply rejectable.** ``is_plausible_session_token`` lets the request
   path refuse garbage before it opens a database round trip, so a malformed
   cookie cannot make PostgreSQL do work.

Authentication itself looks rows up by the *computed* MAC rather than by
comparing digests in Python: there is no constant-time comparison helper here
because none is needed, and shipping an unused one would be dead code rather
than a security property.

This module has no I/O and no framework import.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

#: 32 bytes of entropy; ``token_urlsafe`` encodes this to 43 characters.
SESSION_TOKEN_BYTES = 32

#: Accepted shape of a presented token. The alphabet is exactly the
#: urlsafe-base64 alphabet, so anything carrying ``.``, spaces, ``+``, ``/``
#: or a non-ASCII character is rejected before a query is built from it.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")


def generate_session_token() -> str:
    """Return a fresh, cryptographically random session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def is_plausible_session_token(token: str) -> bool:
    """Return ``True`` when ``token`` could have been issued by this system.

    This is a shape check, not an authenticity check: a well-formed token
    still has to match a live row. It exists so malformed input never reaches
    the database.
    """
    return isinstance(token, str) and _TOKEN_PATTERN.match(token) is not None


def hash_session_token(token: str, secret_key: str) -> str:
    """Return the hex ``HMAC-SHA256`` of ``token`` keyed by ``secret_key``.

    The output is 64 hex characters, which is what the ``sessions.token_hash``
    column holds.

    Raises ``ValueError`` for a missing key: an HMAC under an empty key would
    still produce a plausible-looking digest while providing no protection
    against forging, so it fails loudly instead of silently working.
    """
    if not secret_key:
        raise ValueError("secret_key is required to key the session MAC")
    return hmac.new(
        secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


__all__ = [
    "SESSION_TOKEN_BYTES",
    "generate_session_token",
    "hash_session_token",
    "is_plausible_session_token",
]
