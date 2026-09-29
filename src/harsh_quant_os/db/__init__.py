"""PostgreSQL storage layer (Phase 2).

Importing this package registers every model with the declarative metadata,
which is what lets Alembic autogenerate compare a live database against the
code. The package deliberately re-exports only the pieces callers need:
engine construction, the session factory, the models and the base.
"""

from __future__ import annotations

from harsh_quant_os.db.backup import (
    BackupError,
    BackupManifest,
    TableBackup,
    export_database,
    import_database,
)
from harsh_quant_os.db.base import NAMING_CONVENTION, Base
from harsh_quant_os.db.engine import (
    build_engine,
    build_session_factory,
    dispose_engine,
    ping_database,
)
from harsh_quant_os.db.models import (
    AuditLog,
    Dataset,
    DatasetProvenance,
    Experiment,
    JournalEntry,
    Strategy,
    User,
    UserSession,
)

__all__ = [
    "NAMING_CONVENTION",
    "AuditLog",
    "BackupError",
    "BackupManifest",
    "Base",
    "Dataset",
    "DatasetProvenance",
    "Experiment",
    "JournalEntry",
    "Strategy",
    "TableBackup",
    "User",
    "UserSession",
    "build_engine",
    "build_session_factory",
    "dispose_engine",
    "export_database",
    "import_database",
    "ping_database",
]
