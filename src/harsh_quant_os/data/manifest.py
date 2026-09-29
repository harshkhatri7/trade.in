"""Recording where a stored dataset lives.

The files under ``data/`` answer *what the data is*. This module answers
*where it is, which version it is, and what validation thought of it* —
the manifest that data-platform.md section 4 says lives in PostgreSQL.

Three rules govern it:

1. **Register only what the store has already written.** A manifest row
   pointing at a file that was never created is worse than no row,
   because everything downstream believes it. Files first, row second.

2. **Upsert on the dataset name, never append.** ``datasets.name`` is
   unique, so a re-ingest of the same logical dataset updates one row
   rather than leaving two rows both claiming to be that dataset. The
   ``INSERT ... ON CONFLICT`` form does this in one statement, so two
   concurrent registrations of the same name cannot both win.

3. **Every registration appends a provenance row.** ``dataset_provenance``
   is append-only at the database, so each acquisition leaves a record
   that a later write cannot quietly revise — which is what makes "this is
   where it came from, and this is when" worth storing at all.

This module is deliberately *not* re-exported from ``harsh_quant_os.data``:
it needs SQLAlchemy, which is an optional ``storage`` extra, and importing
that package must not require it. The store and the interfaces remain
usable without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.data.store import StoredDataset
from harsh_quant_os.db.models import Dataset, DatasetProvenance

__all__ = ["dataset_by_name", "register_dataset"]


def _describe(reasons: Sequence[str], notes: Sequence[str]) -> str | None:
    """One line carrying both what validation found and what it could not.

    Both belong in the same place: a dataset whose caveats were dropped at
    the door would read better than it deserves to, and a later reader
    should not have to find a separate report to learn that outliers were
    never judged.
    """
    parts = [*reasons, *(f"not checked: {note}" for note in notes)]
    return "; ".join(parts) if parts else None


async def register_dataset(
    session_factory: async_sessionmaker[AsyncSession],
    stored: StoredDataset,
) -> uuid.UUID:
    """Write the manifest row for a batch the store has already written.

    Returns the dataset's id, which is what provenance and everything
    downstream refer to.
    """
    async with session_factory() as session:
        upsert = (
            pg_insert(Dataset)
            .values(
                name=stored.name,
                instrument=stored.instrument,
                timeframe=stored.timeframe.value,
                quality_status=stored.quality_status.value,
                version=stored.version,
                storage_path=stored.clean_path,
            )
            .on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "instrument": stored.instrument,
                    "timeframe": stored.timeframe.value,
                    "quality_status": stored.quality_status.value,
                    "version": stored.version,
                    "storage_path": stored.clean_path,
                    "updated_at": func.now(),
                },
            )
            .returning(Dataset.id)
        )
        dataset_id = await session.scalar(upsert)
        if not isinstance(dataset_id, uuid.UUID):
            # Unreachable while PostgreSQL behaves: RETURNING on an upsert
            # against a table with a primary key always yields a row. It is
            # checked rather than asserted because silently continuing with
            # a missing id would attach provenance to nothing at all.
            raise RuntimeError("registering a dataset returned no id")

        session.add(
            DatasetProvenance(
                dataset_id=dataset_id,
                acquired_at=datetime.now(tz=UTC),
                source=stored.source,
                checksum_sha256=stored.raw_sha256,
                row_count=stored.row_count,
                notes=_describe(stored.reasons, stored.notes),
            )
        )
        await session.commit()
        return dataset_id


async def dataset_by_name(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
) -> Dataset | None:
    """Read one manifest row back by its logical name.

    Kept here rather than inlined in a test so that the shape the rest of
    the platform depends on has one definition.
    """
    async with session_factory() as session:
        return await session.scalar(select(Dataset).where(Dataset.name == name))
