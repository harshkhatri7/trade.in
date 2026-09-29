"""Phase 2 persistence models: identity, sessions, audit, and research.

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

The research tables (``datasets``, ``dataset_provenance``, ``strategies``,
``experiments``, ``journal_entries``) exist in Phase 2 although nothing
writes to them yet, because ROADMAP.md lists them as Phase 2 deliverables.
They are deliberately **narrow**:

* Structured payloads are ``jsonb``, not a guessed column set. What a
  strategy's specification contains belongs to the strategy module that
  does not exist yet; a column set invented now would be wrong quietly and
  expensive to migrate.
* ``metrics`` defaults to ``{}`` and means *nothing has been measured*. An
  empty object is the honest default - there is no result to record until a
  backtest produces one, and a schema that shipped sample numbers would be
  indistinguishable from a run that produced them.
* Provenance is **append-only**, enforced by the same kind of trigger as
  ``audit_log``: a record of where data came from that can be edited is not
  a record of where data came from.
* Deleting a dataset or strategy is refused (``ON DELETE RESTRICT``) while
  it still has provenance, experiments or notes attached. Those are archived
  with ``archived_at`` instead, so research lineage cannot be destroyed by a
  single cascade.
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
from sqlalchemy.dialects.postgresql import JSONB
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


class Dataset(Base):
    """A named source of research data.

    Holds no "where it came from": that is per acquisition and belongs to
    :class:`DatasetProvenance`, which records it in a row that cannot later
    change its mind.
    """

    __tablename__ = "datasets"
    __table_args__ = (CheckConstraint("length(name) > 0", name="name_present"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``ON DELETE SET NULL``: the record outlives its author instead of
    #: making the author undeletable forever.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Datasets are archived, never dropped, while provenance exists - the
    #: provenance foreign key is ``RESTRICT`` for exactly that reason.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class DatasetProvenance(Base):
    """One acquisition of a dataset: where it came from, and what arrived.

    Append-only. A provenance record that can be edited is not provenance,
    so the migration gives this table the same kind of ``BEFORE UPDATE OR
    DELETE`` trigger ``audit_log`` has. Corrections are made by appending a
    new row, which is also what actually happened.

    ``ON DELETE RESTRICT`` on ``dataset_id``: a dataset with recorded
    origin cannot be removed by a cascade.
    """

    __tablename__ = "dataset_provenance"
    __table_args__ = (CheckConstraint("length(source) > 0", name="source_present"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: When the data was obtained, which may be long before the row was
    #: written - a backfilled acquisition is recorded with its real date.
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    #: URL, provider name or internal path. Never a credential: sources are
    #: public endpoints or local paths, never a signed or keyed address.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 of the payload as received, when one was computed. NULL means
    #: "not checked", not "matched".
    checksum_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Rows obtained, or NULL when it was not counted. Never estimated.
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    license: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )


class Strategy(Base):
    """A named strategy definition.

    ``spec`` is ``jsonb`` rather than a column set because its shape belongs
    to the strategy module, which does not exist yet. Writing that column
    set now would mean guessing at a contract and baking the guess into
    constraints.
    """

    __tablename__ = "strategies"
    __table_args__ = (CheckConstraint("length(name) > 0", name="name_present"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The definition itself. ``{}`` means "not specified yet".
    spec: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Retired rather than deleted - experiments may still reference it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class Experiment(Base):
    """A run: what was tried, against what, and what came out.

    ``metrics`` defaults to ``{}``, which means *nothing has been measured*.
    That distinction is the whole reason the default is an empty object
    rather than any number: a schema that shipped sample metrics would be
    indistinguishable from a run that produced them.

    Deleting a strategy or dataset that has experiments is refused
    (``RESTRICT``), so results cannot be orphaned by a cascade.
    """

    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("length(name) > 0", name="name_present"),
        CheckConstraint(
            "status IN ('planned', 'running', 'completed', 'failed')",
            name="status_known",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NOT NULL",
            name="finished_requires_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Nullable: an experiment may be defined before the strategy it runs is
    #: recorded. NULL means "not linked", never "no strategy involved".
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("strategies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    parameters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'planned'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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


class JournalEntry(Base):
    """A piece of written research memory.

    Editable, unlike provenance: notes are corrected as understanding
    changes, and ``updated_at`` records that they were. The link to an
    experiment is ``SET NULL`` rather than ``RESTRICT`` so a written note is
    never destroyed along with the run it was about.
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("length(title) > 0", name="title_present"),
        CheckConstraint("length(body) > 0", name="body_present"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("experiments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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


__all__ = [
    "AuditLog",
    "Dataset",
    "DatasetProvenance",
    "Experiment",
    "JournalEntry",
    "Strategy",
    "User",
    "UserSession",
]
