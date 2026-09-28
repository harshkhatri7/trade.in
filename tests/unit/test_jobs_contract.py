"""Local-agent job contract: the allowlist is the whole security boundary.

`allowed_roots` is what stops a job from touching anything outside the
directories it was granted. A blank entry would be an empty path that a
prefix check could walk straight past, so the validator that rejects blank
entries is pinned here instead of being trusted on reading. Payloads are fed
through `model_validate`, because that is how untrusted input arrives.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts.jobs import JobOperation, JobStatus, LocalAgentJob


def _valid_payload() -> dict[str, object]:
    """A payload that is accepted as-is, for tests that change one field."""
    return {"operation": JobOperation.DATASET_SCAN, "requested_by": "researcher"}


@pytest.mark.unit
def test_empty_root_entry_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        LocalAgentJob.model_validate({**_valid_payload(), "allowed_roots": ("",)})


@pytest.mark.unit
def test_blank_root_entry_is_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        LocalAgentJob.model_validate({**_valid_payload(), "allowed_roots": ("   ",)})


@pytest.mark.unit
def test_one_bad_root_rejects_the_whole_job() -> None:
    with pytest.raises(ValidationError, match="allowed_roots"):
        LocalAgentJob.model_validate(
            {**_valid_payload(), "allowed_roots": ("C:/data", "", "C:/research")}
        )


@pytest.mark.unit
def test_valid_roots_are_kept_as_given() -> None:
    job = LocalAgentJob.model_validate(
        {**_valid_payload(), "allowed_roots": ["C:/data", "C:/research"]}
    )

    assert job.allowed_roots == ("C:/data", "C:/research")


@pytest.mark.unit
def test_no_roots_means_nothing_is_accessible() -> None:
    job = LocalAgentJob.model_validate(_valid_payload())

    assert job.allowed_roots == ()


@pytest.mark.unit
def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LocalAgentJob.model_validate({**_valid_payload(), "operation": "filesystem.read"})


@pytest.mark.unit
def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        LocalAgentJob.model_validate({**_valid_payload(), "unexpected": 1})


@pytest.mark.unit
def test_anonymous_principal_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LocalAgentJob.model_validate({**_valid_payload(), "requested_by": ""})


@pytest.mark.unit
def test_timeout_must_be_at_least_one_second() -> None:
    with pytest.raises(ValidationError):
        LocalAgentJob.model_validate({**_valid_payload(), "timeout_seconds": 0})


@pytest.mark.unit
def test_defaults_describe_a_queued_job() -> None:
    job = LocalAgentJob.model_validate(_valid_payload())

    assert job.status is JobStatus.QUEUED
    assert job.timeout_seconds == 3600
    assert job.error == ""
    assert job.started_at is None
    assert job.finished_at is None
    assert job.created_at.tzinfo is not None  # every timestamp is timezone-aware


@pytest.mark.unit
def test_job_ids_are_unique() -> None:
    ids = {LocalAgentJob.model_validate(_valid_payload()).job_id for _ in range(50)}

    assert len(ids) == 50


@pytest.mark.unit
def test_terminal_state_is_only_reached_by_finished_jobs() -> None:
    expected = {
        JobStatus.QUEUED: False,
        JobStatus.RUNNING: False,
        JobStatus.SUCCEEDED: True,
        JobStatus.FAILED: True,
        JobStatus.CANCELLED: True,
    }
    observed = {
        status: LocalAgentJob.model_validate({**_valid_payload(), "status": status}).is_terminal
        for status in JobStatus
    }

    assert observed == expected


@pytest.mark.unit
def test_job_is_immutable_once_created() -> None:
    job = LocalAgentJob.model_validate(_valid_payload())

    with pytest.raises(ValueError):  # pydantic's ValidationError subclasses ValueError
        job.status = JobStatus.RUNNING  # type: ignore[misc]
