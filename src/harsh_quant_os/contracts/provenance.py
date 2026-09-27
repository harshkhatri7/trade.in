"""Provider-independent data contracts.

Every dataset that enters the platform must carry provenance metadata so that
a result can always be traced back to: who supplied it, when it was ingested,
what timeframe it covers, and whether validation passed. Missing data is never
invented - a dataset without provenance is rejected, not filled in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataQualityStatus(StrEnum):
    """Validation outcome attached to every ingested dataset."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"


class Timeframe(StrEnum):
    """Standardised bar sizes. Provider-specific labels are normalised here."""

    TICK = "tick"
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MN1 = "1mo"


class DatasetProvenance(BaseModel):
    """Immutable provenance record for a stored dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, description="Provider identifier, e.g. 'provider_x'.")
    symbol: str = Field(min_length=1, description="Instrument identifier in provider-neutral form.")
    timestamp: datetime = Field(description="Period covered by the dataset (timezone aware).")
    ingested_at: datetime = Field(description="When the platform ingested the data.")
    timeframe: Timeframe
    quality_status: DataQualityStatus = DataQualityStatus.UNKNOWN
    provenance: str = Field(
        min_length=1,
        description="Lineage: raw artefact URI, ingestion run id or recipe identifier.",
    )
    version: str = Field(min_length=1, description="Dataset version, e.g. '2026.09.27.1'.")
    provider_dataset_id: str = Field(default="", description="Native id at the provider, if any.")

    @field_validator("timestamp", "ingested_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "datetime values must be timezone aware; naive timestamps are rejected"
            )
        return value

    @model_validator(mode="after")
    def _reject_incomplete_provenance(self) -> DatasetProvenance:
        """Reject records that cannot be trusted.

        Data cannot have been ingested before the event it describes existed;
        such a record indicates a clock or lineage error and must not enter
        the store (missing/incorrect data is never silently accepted).
        """
        if self.ingested_at < self.timestamp:
            raise ValueError(
                "ingested_at must not precede timestamp: "
                f"{self.ingested_at.isoformat()} < {self.timestamp.isoformat()}"
            )
        if self.quality_status is DataQualityStatus.INVALID:
            raise ValueError("datasets marked invalid must not be stored; quarantine them instead")
        return self

    @property
    def is_usable(self) -> bool:
        """A dataset is usable only after validation marks it valid."""
        return self.quality_status is DataQualityStatus.VALID


def utcnow() -> datetime:
    """Timezone-aware current time used across the platform."""
    return datetime.now(tz=UTC)
