"""Authentication: credentials, sessions and the service that runs them.

Split into three layers so that the security-critical pieces stay testable
without a database:

* :mod:`~harsh_quant_os.auth.hashing` - Argon2id, pure functions, no I/O;
* :mod:`~harsh_quant_os.auth.tokens` - token generation and keyed MAC, pure;
* :mod:`~harsh_quant_os.auth.service` - the application service that owns
  transactions, audit records and the failure taxonomy.

:class:`~harsh_quant_os.auth.errors.AuthError` and its subclasses are the
boundary this package raises. They deliberately do not import FastAPI: the
HTTP status mapping belongs to the API layer.
"""

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
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)
from harsh_quant_os.auth.service import (
    AuthenticatedContext,
    AuthService,
    LoginResult,
    normalize_email,
    validate_email,
)
from harsh_quant_os.auth.tokens import (
    generate_session_token,
    hash_session_token,
    is_plausible_session_token,
)

__all__ = [
    "AuthError",
    "AuthService",
    "AuthenticatedContext",
    "DatabaseUnavailable",
    "DuplicateUser",
    "InvalidCredentials",
    "LoginResult",
    "PasswordPolicyError",
    "SessionExpired",
    "SessionInvalid",
    "SessionRevoked",
    "generate_session_token",
    "hash_password",
    "hash_session_token",
    "is_plausible_session_token",
    "needs_rehash",
    "normalize_email",
    "validate_email",
    "validate_password_policy",
    "verify_password",
]
