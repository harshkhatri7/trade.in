"""Phase 2 persistence models: identity, sessions and the audit trail.

Design notes that a reader of the DDL alone would not see:

* **Every timestamp is ``timestamptz``.** ``docs/architecture/database.md``
  section 4 requires UTC storage; a naive ``timestamp`` would silently let the
  server's local time leak into session expiry, which is exactly how a session
  ends up expiring at the wrong moment on a machine in another zone.
* **The audit trail has no foreign keys, on purpose.** A foreign key with
  ``ON DELETE CASCADE`` would make PostgreSQL *edit* an audit row when the
  actor is removed, and ``ON DELETE RESTRICT`` would make the actor
  undeletable forever. Both contradict "audit is immutable". Instead the
  actor's id and email are **snapshotted** as plain columns, so audit rows
  outlive the actors they describe. This is the deliberate ``ON DELETE``
  policy for this table, recorded here and in database.md.
* **Append-only is enforced by the database, not by the application.** The
  migration installs a ``BEFORE UPDATE OR DELETE`` trigger that raises. A
  well-behaved service is not a guarantee; the database is. The trigger is
  what makes "the application role cannot modify audit rows" a statement that
  can be executed rather than merely asserted.
* **Money never appears here.** When a table does hold money it uses
  ``numeric(20, 6)`` per database.md section 4 - never ``float8``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from harsh_quant_os.audit import event_type_check_sql, outcome_check_sql
from harsh_quant_os.contracts.provenance import utcnow
from harsh_quant_os.db.base import Base

# Every timestamp is produced by the *application* clock, not by PostgreSQL's
# `now()`, while still declaring `server_default` as a fallback for raw SQL.
# Two reasons, both concrete:
#
# 1. A `server_default` is not read back into the ORM after INSERT, so a model
#    that only declares one would hand `None` to any caller reading the value
#    it just wrote - including `/me`, which returns `users.created_at`.
# 2. Session expiry is decided by `utcnow()` in the service. Mixing an
#    application clock for expiry with a database clock for `created_at`
#    would put two clocks in one row; one clock cannot disagree with itself.


class User(Base):
    """An account. Stored credentials are Argon2id hashes, never plaintext."""

    __tablename__ = "users"
    __table_args__ = (
        # Emails are normalised to lower case before they reach this table;
        # the CHECK is the backstop that makes "the same address twice" a
        # database error rather than two accounts that only look different.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("length(password_hash) > 0", name="password_hash_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    #: Normalised (lower-cased, stripped) address. Unique by construction.
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Argon2id encoded hash, self-describing so parameters can be upgraded.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    #: Single-operator platform: a superuser owns the installation.
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
    )


class UserSession(Base):
    """A server-side session.

    The raw token is never stored. What lands in ``token_hash`` is
    ``HMAC-SHA256(AUTH_SECRET_KEY, token)``, so possession of the database
    alone neither reveals a usable token nor lets a caller mint one: the lookup
    key is derived from a secret the database does not hold. Rotating
    ``AUTH_SECRET_KEY`` therefore invalidates every session at once.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: 64 hex characters - HMAC-SHA256 output. Unique, so a token maps to
    #: exactly one row and replay of a revoked token cannot match a new one.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    #: Absolute expiry. An absolute deadline is chosen over a sliding idle
    #: timeout because it is unambiguous to test and cannot be extended by
    #: continued use. Computed from ``utcnow()`` - the same clock the
    #: validator compares against, so the two cannot disagree.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: Set by logout or by an explicit revocation. Never cleared.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Why it was revoked, e.g. ``logout``. Never carries a secret.
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    """Append-only record of security-relevant events.

    See the module docstring: no foreign keys, snapshotted actor identity,
    and immutability enforced by a database trigger installed in the initial
    migration.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(event_type_check_sql(), name="event_type"),
        CheckConstraint(outcome_check_sql(), name="outcome"),
        CheckConstraint(
            "actor_email IS NULL OR actor_email = lower(actor_email)",
            name="actor_email_lowercase",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
        index=True,
    )
    #: One of ``AuditEventType``'s values; the CHECK is generated from it.
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    #: Snapshot, deliberately not a foreign key - see the module docstring.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Snapshot of the session the event belongs to. No foreign key: a
    #: session row is deleted by cascade, and cascade would mutate audit.
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    #: Free-text context. Writers must never place a password, token or
    #: hash here - ``detail`` is a human-readable reason, nothing more.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Correlates with the ``X-Request-ID`` of the request, when there was one.
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["AuditLog", "User", "UserSession"]
