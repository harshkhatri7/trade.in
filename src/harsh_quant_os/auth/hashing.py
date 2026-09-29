"""Argon2id password hashing.

`docs/architecture/backend.md` section 6 fixes the algorithm family:
**Argon2id or bcrypt, never reversible**. Argon2id is chosen because it is
memory-hard, so an attacker with a GPU cannot trade memory for speed the way
they can against PBKDF2 or bcrypt.

The parameters below are **measured, not guessed**: on the development
machine (AMD Ryzen 5 6600H, Windows 11) ``m=45056 KiB / t=3 / p=1`` costs
~110 ms per hash and ~110 ms per verification. That is 2.3x the memory and
1.5x the work of the Argon2id minimum in the OWASP Password Storage Cheat
Sheet (m=19456 KiB, t=2, p=1), while staying cheap enough that the test
suite, which creates real accounts, does not become slow. ``p=1`` rather
than the library's default ``p=4``: four lanes oversubscribe a laptop that
runs the suite and the API at the same time, and buy nothing an attacker
feels.

The encoded hash is self-describing - ``$argon2id$v=19$m=...,t=...,p=...``
- so parameters can be raised later and ``needs_rehash`` can tell an old
hash from a current one. Raising them is a code change plus a rehash on next
login, not a migration.

**Nothing in this module logs, formats or returns a password.** The only
value that ever leaves it is an encoded hash.
"""

from __future__ import annotations

import logging

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from argon2.low_level import Type

from harsh_quant_os.auth.errors import PasswordPolicyError

logger = logging.getLogger(__name__)

#: Minimum length. Length beats composition rules: NIST SP 800-63B advises
#: allowing long passphrases and explicitly discourages "one upper, one
#: digit, one symbol" rules, which mostly produce ``Password1!``.
MIN_PASSWORD_LENGTH = 12

#: Upper bound so an attacker cannot hand the hasher an unbounded input.
#: Enforced on login too, where it is rejected as an ordinary bad credential
#: rather than as a policy violation - a policy message on login would tell a
#: caller something about an account they have not proven access to.
MAX_PASSWORD_LENGTH = 1024

ARGON2_TIME_COST = 3
ARGON2_MEMORY_KIB = 45056
ARGON2_PARALLELISM = 1
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16


def build_hasher() -> PasswordHasher:
    """Construct a hasher with the parameters documented above.

    Built per call rather than stored at module scope: the object holds no
    reusable state worth keeping, and a module-level instance would be
    hidden global configuration that a test cannot replace.
    """
    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LENGTH,
        salt_len=ARGON2_SALT_LENGTH,
        type=Type.ID,
    )


def validate_password_policy(password: str) -> None:
    """Apply the **creation-time** password policy.

    Raises :class:`PasswordPolicyError` with a reason suitable for the person
    choosing the password. This runs only when a credential is being created;
    it is never called during login, because rejecting an existing password
    on login would both lock users out and leak the stored policy.
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be text")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    if not password.strip():
        raise PasswordPolicyError("password must not be only whitespace")


def hash_password(password: str) -> str:
    """Return the Argon2id encoded hash of ``password``.

    Raises on genuine hashing failure so that a caller never stores a
    credential it did not actually hash.
    """
    return build_hasher().hash(password)


def verify_password(encoded: str, password: str) -> bool:
    """Return ``True`` only when ``password`` matches ``encoded``.

    Never raises. A corrupt or truncated stored hash is reported as "does not
    match" rather than as a 500: the row is unusable, the login must fail, and
    the driver of that conclusion is not a server error. ``InvalidHashError``
    derives from ``ValueError`` rather than ``Argon2Error`` in argon2-cffi,
    which is why both are caught here.
    """
    if not encoded or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return bool(build_hasher().verify(encoded, password))
    except (Argon2Error, ValueError, TypeError):
        # Logged by type name only. The hash itself can encode a password
        # the user chose, and the password obviously must not appear.
        # TypeError is included so the "never raises" promise holds even if
        # an untyped caller hands something that is not a string.
        logger.warning("password.verify could not be evaluated")
        return False


def needs_rehash(encoded: str) -> bool:
    """Return ``True`` when ``encoded`` was produced with weaker parameters."""
    try:
        return bool(build_hasher().check_needs_rehash(encoded))
    except (Argon2Error, ValueError):
        # An unparseable hash is by definition not a current-format hash.
        return True


def burn_password_check(password: str) -> None:
    """Spend the same work as a verification, for an account that does not exist.

    Login must not answer faster for an unknown address than for a wrong
    password - the difference is exactly the signal a credential-stuffing
    run is looking for. Hashing the offered password and discarding the
    result costs about the same as verifying a real one (~110 ms), so the
    unknown-user path and the wrong-password path take the same time.

    Errors are swallowed: this work exists only to consume time, and its
    failure must not turn an ordinary 401 into a 500.
    """
    try:
        hash_password(password)
    except (Argon2Error, ValueError, TypeError):
        logger.warning("password.burn could not be evaluated")


__all__ = [
    "ARGON2_HASH_LENGTH",
    "ARGON2_MEMORY_KIB",
    "ARGON2_PARALLELISM",
    "ARGON2_SALT_LENGTH",
    "ARGON2_TIME_COST",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "build_hasher",
    "burn_password_check",
    "hash_password",
    "needs_rehash",
    "validate_password_policy",
    "verify_password",
]
