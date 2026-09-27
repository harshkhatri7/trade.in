"""Local-agent job contract.

The local agent is the controlled bridge between the cloud tier and the
researcher's PC. It never exposes a filesystem or a shell to the browser: the
API submits a *job* (operation + explicit allowlisted roots), the agent
executes it under resource limits, and every job leaves an audit record.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from harsh_quant_os.contracts.provenance import utcnow


class JobStatus(StrEnum):
    """Lifecycle of a local-agent job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobOperation(StrEnum):
    """Operations the agent is allowed to perform.

    The list is an allowlist, not a menu: anything absent from this enum is
    rejected. New operations are added through a reviewed code change, never
    through a request payload.
    """

    DATASET_SCAN = "dataset.scan"
    DATASET_BUILD_FEATURES = "dataset.build_features"
    BACKTEST_RUN = "backtest.run"
    MODEL_TRAIN = "model.train"


class LocalAgentJob(BaseModel):
    """Immutable description plus mutable lifecycle fields of one job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID = Field(default_factory=uuid4)
    operation: JobOperation
    requested_by: str = Field(min_length=1, description="Authenticated principal, never anonymous.")
    allowed_roots: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Absolute directories the job may touch; empty means nothing is accessible.",
    )
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timeout_seconds: int = Field(default=3600, ge=1)
    error: str = ""

    @field_validator("allowed_roots")
    @classmethod
    def _normalise_roots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for root in value:
            if not root.strip():
                raise ValueError("allowed_roots entries must be non-empty absolute paths")
        return value

    @property
    def is_terminal(self) -> bool:
        return self.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
