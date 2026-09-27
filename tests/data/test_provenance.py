"""Dataset provenance contract tests (data architecture foundation)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts import DataQualityStatus, DatasetProvenance, Timeframe

_TS = datetime(2026, 9, 27, 9, 15, tzinfo=UTC)
_INGESTED = _TS + timedelta(minutes=2)


def _provenance(**overrides: object) -> DatasetProvenance:
    payload: dict[str, object] = {
        "source": "provider_x",
        "symbol": "RELIANCE",
        "timestamp": _TS,
        "ingested_at": _INGESTED,
        "timeframe": Timeframe.M5,
        "quality_status": DataQualityStatus.VALID,
        "provenance": "runs/2026-09-27T09-15-00/provider_x",
        "version": "2026.09.27.1",
    }
    payload.update(overrides)
    return DatasetProvenance(**payload)


@pytest.mark.unit
def test_valid_provenance_accepted() -> None:
    record = _provenance()

    assert record.is_usable is True
    assert record.timeframe is Timeframe.M5
    assert record.source == "provider_x"


@pytest.mark.unit
def test_naive_timestamps_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone aware"):
        _provenance(timestamp=datetime(2026, 9, 27, 9, 15))


@pytest.mark.unit
def test_ingestion_before_event_rejected() -> None:
    with pytest.raises(ValidationError, match="ingested_at must not precede"):
        _provenance(ingested_at=_TS - timedelta(seconds=1))


@pytest.mark.unit
def test_invalid_datasets_are_not_stored() -> None:
    with pytest.raises(ValidationError, match="marked invalid"):
        _provenance(quality_status=DataQualityStatus.INVALID)


@pytest.mark.unit
def test_unknown_quality_is_not_usable() -> None:
    record = _provenance(quality_status=DataQualityStatus.UNKNOWN)

    assert record.is_usable is False


@pytest.mark.unit
def test_empty_source_rejected() -> None:
    with pytest.raises(ValidationError):
        _provenance(source="")


@pytest.mark.unit
def test_record_is_immutable_and_closed() -> None:
    record = _provenance()

    with pytest.raises(ValidationError):
        record.source = "other"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        _provenance(unexpected_field="x")


@pytest.mark.unit
def test_all_timeframes_are_normalised() -> None:
    assert [tf.value for tf in Timeframe] == [
        "tick",
        "1m",
        "5m",
        "15m",
        "30m",
        "1h",
        "4h",
        "1d",
        "1w",
        "1mo",
    ]
