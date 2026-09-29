"""phase 3 dataset manifest: quality status, version and storage location

Revision ID: 7c4d9e2a15b3
Revises: 3842df3d0db8
Create Date: 2026-09-29 12:04:11.355902

ROADMAP phase 3 requires quality status, provenance and version on every
stored dataset. Provenance already has its own append-only table from
phase 2; this revision adds the other three facts to ``datasets``, where
the store can write them in the same transaction as the row itself.

The three check constraints are the substance of the change:

* ``quality_status`` may only hold a value the shared contract recognises,
  so a typo cannot become a fourth, undiscoverable state;
* ``timeframe`` may only hold a provider-neutral value, or NULL for a
  logical dataset that holds no series;
* ``version`` and ``storage_path`` are both set or both absent, so no row
  can name a version with nowhere to read it, or point at a file with no
  way to say which version it is.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c4d9e2a15b3"
down_revision: str | None = "3842df3d0db8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.add_column("datasets", sa.Column("instrument", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("timeframe", sa.Text(), nullable=True))
    op.add_column(
        "datasets",
        sa.Column(
            "quality_status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
    )
    op.add_column("datasets", sa.Column("version", sa.Text(), nullable=True))
    op.add_column("datasets", sa.Column("storage_path", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_datasets_quality_status",
        "datasets",
        "quality_status IN ('unknown', 'pending', 'valid', 'suspect', 'invalid')",
    )
    op.create_check_constraint(
        "ck_datasets_timeframe",
        "datasets",
        "timeframe IS NULL OR timeframe IN "
        "('tick', '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo')",
    )
    op.create_check_constraint(
        "ck_datasets_version_and_storage",
        "datasets",
        "(version IS NULL) = (storage_path IS NULL)",
    )
    op.create_index(
        op.f("ix_datasets_quality_status"),
        "datasets",
        ["quality_status"],
        unique=False,
    )


def downgrade() -> None:
    """Reverse this revision."""
    op.drop_index(op.f("ix_datasets_quality_status"), table_name="datasets")
    op.drop_constraint("ck_datasets_version_and_storage", "datasets", type_="check")
    op.drop_constraint("ck_datasets_timeframe", "datasets", type_="check")
    op.drop_constraint("ck_datasets_quality_status", "datasets", type_="check")
    op.drop_column("datasets", "storage_path")
    op.drop_column("datasets", "version")
    op.drop_column("datasets", "quality_status")
    op.drop_column("datasets", "timeframe")
    op.drop_column("datasets", "instrument")
