"""Audit vocabulary: what an audit record is called and how it ended.

Deliberately pure - an ``enum.StrEnum`` with no I/O and no framework import -
so that the storage layer, the application services and the tests can all
reference the same strings without any of them importing each other.

Two properties matter more than the vocabulary itself:

* the set of event types is **closed**. ``audit_log.event_type`` carries a
  database ``CHECK`` over exactly these values, so a typo cannot become an
  audit record that no report can find. Widening the set is a reviewed
  migration, not an edit.
* an audit row is a statement of **what happened**, never of what might
  happen. A failure is recorded with ``outcome = failure``; a failure is
  never written as a success.
"""

from __future__ import annotations

from enum import StrEnum


class AuditOutcome(StrEnum):
    """How the audited attempt ended."""

    SUCCESS = "success"
    FAILURE = "failure"


class AuditEventType(StrEnum):
    """Closed set of audited event types (mirrored by the ``audit_log`` CHECK)."""

    USER_CREATED = "user.created"
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    LOGOUT_SUCCEEDED = "auth.logout.succeeded"
    SESSION_REVOKED = "auth.session.revoked"
    SESSION_REJECTED = "auth.session.rejected"


#: The SQL fragment the migration installs as a CHECK constraint. Generated
#: from the enum so the database and the code cannot drift apart silently.
def event_type_check_sql() -> str:
    """Return the ``CHECK`` predicate covering every :class:`AuditEventType`."""
    values = ", ".join(f"'{event.value}'" for event in AuditEventType)
    return f"event_type IN ({values})"


def outcome_check_sql() -> str:
    """Return the ``CHECK`` predicate covering every :class:`AuditOutcome`."""
    values = ", ".join(f"'{outcome.value}'" for outcome in AuditOutcome)
    return f"outcome IN ({values})"


__all__ = [
    "AuditEventType",
    "AuditOutcome",
    "event_type_check_sql",
    "outcome_check_sql",
]
