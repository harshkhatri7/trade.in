"""Cross-language contract parity for the dataset payloads.

The Python models are authoritative; ``packages/types/src/datasets.ts``
mirrors them for the browser. This test checks three things:

1. both sides accept the same fixture (``tests/contracts/datasets.json``);
2. both sides reject a payload that does not follow it;
3. the field names written in TypeScript are exactly the ones written in
   Python.

``tests/unit/datasets-contract.test.ts`` performs the same comparison in
the opposite direction, so the Python job and the TypeScript job each
fail when either side drifts.

About the fixture's values: the stored dataset, its version, its storage
path, the quality status, the row count, the source and the two bars are
read from the artefact an observed ``hqos data ingest`` run left in
``data/``; the acquisition timestamps and the second, pending dataset are
constructed to exercise the nullable fields the schema allows. Nothing
here is presented as a market observation beyond those two recorded bars.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts.datasets import (
    BarPoint,
    DatasetBarsResponse,
    DatasetDetailResponse,
    DatasetListResponse,
    DatasetSummary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "contracts" / "datasets.json"
TS_TYPES_PATH = REPO_ROOT / "packages" / "types" / "src" / "datasets.ts"
PY_CONTRACT_PATH = REPO_ROOT / "src" / "harsh_quant_os" / "contracts" / "datasets.py"


def _fixture() -> dict[str, Any]:
    data: Any = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "the shared fixture must be a JSON object"
    return data


def _read(path: Path) -> str:
    assert path.is_file(), f"missing source file: {path}"
    return path.read_text(encoding="utf-8")


def _ts_interface_fields(name: str) -> list[str]:
    source = _read(TS_TYPES_PATH)
    match = re.search(rf"export interface {name}\s*\{{(.*?)\}}", source, re.DOTALL)
    assert match, f"interface {name} not found in {TS_TYPES_PATH.name}"
    return re.findall(r"^\s*(\w+)\??:", match.group(1), re.MULTILINE)


def _class_body(pattern: str) -> str:
    source = _read(PY_CONTRACT_PATH)
    match = re.search(pattern, source, re.DOTALL)
    assert match, f"{pattern} not found in {PY_CONTRACT_PATH.name}"
    return match.group(1)


def _python_model_fields(name: str) -> list[str]:
    body = _class_body(rf"class {name}\(BaseModel\):(.*?)(?=\nclass |\Z)")
    return re.findall(r"^\s{4}(\w+)\s*:", body, re.MULTILINE)


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_list_model() -> None:
    payload = _fixture()["dataset_list"]

    validated = DatasetListResponse.model_validate(payload)
    assert validated.model_dump(mode="json") == payload
    # The pending entry is the schema's shape for a registered name that
    # has no artefact yet: every artefact-bound field is null, and null
    # means *not recorded* rather than zero.
    pending = validated.datasets[1]
    assert pending.version is None
    assert pending.row_count is None


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_detail_model() -> None:
    payload = _fixture()["dataset_detail"]

    validated = DatasetDetailResponse.model_validate(payload)
    assert validated.model_dump(mode="json") == payload
    assert len(validated.provenance) == 2, "history is append-only: both acquisitions survive"
    assert validated.dataset.version is not None
    assert validated.dataset.storage_path is not None
    assert validated.dataset.version in validated.dataset.storage_path


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_bars_model() -> None:
    payload = _fixture()["dataset_bars"]

    validated = DatasetBarsResponse.model_validate(payload)
    assert validated.model_dump(mode="json") == payload
    assert validated.has_more is True
    assert validated.next_cursor is not None


@pytest.mark.unit
def test_dataset_models_reject_payloads_that_do_not_follow_the_contract() -> None:
    summary = _fixture()["dataset_list"]["datasets"][0]

    with pytest.raises(ValidationError):
        DatasetSummary.model_validate({**summary, "unexpected": "value"})

    # Every field is required even when its value may be null: the key is
    # part of the contract, so a payload that omits it is not the payload
    # TypeScript declared either.
    for dropped in ("version", "quality_status", "updated_at"):
        missing = {key: value for key, value in summary.items() if key != dropped}
        with pytest.raises(ValidationError):
            DatasetSummary.model_validate(missing)

    with pytest.raises(ValidationError):
        DatasetSummary.model_validate({**summary, "quality_status": "verified"})

    with pytest.raises(ValidationError):
        DatasetSummary.model_validate({**summary, "timeframe": "1y"})


@pytest.mark.unit
def test_bars_reject_a_price_that_is_not_a_decimal() -> None:
    point = _fixture()["dataset_bars"]["bars"][0]

    for bad in ("not-a-price", "1,234.5", ""):
        with pytest.raises(ValidationError):
            BarPoint.model_validate({**point, "open": bad})


@pytest.mark.unit
def test_a_bars_page_must_describe_itself() -> None:
    """A page that contradicts itself is refused, not rendered.

    ``returned`` has to match the array beside it, and a page claiming
    more data has to carry the cursor that reaches it. TypeScript
    enforces both in ``parseDatasetBarsResponse``; this is the Python
    half of the same rule, so neither side can accept a payload the
    other refuses.
    """
    bars = _fixture()["dataset_bars"]

    with pytest.raises(ValidationError):
        DatasetBarsResponse.model_validate({**bars, "returned": 0})

    without_cursor = {**bars, "has_more": True, "next_cursor": None}
    with pytest.raises(ValidationError):
        DatasetBarsResponse.model_validate(without_cursor)

    # The end of the series is the other legal shape: nothing more, and
    # no cursor implying otherwise.
    at_the_end = {**bars, "has_more": False, "next_cursor": None}
    assert DatasetBarsResponse.model_validate(at_the_end).has_more is False


@pytest.mark.unit
def test_price_strings_survive_a_round_trip_untouched() -> None:
    """The digits written to disk are the digits that come back.

    This is the property the whole traceability claim rests on: a price is
    a ``Decimal`` in Python and a string in the browser, so neither side
    ever routes it through a binary float on the way to the screen.
    """
    point = _fixture()["dataset_bars"]["bars"][0]

    validated = BarPoint.model_validate(point)
    dumped = validated.model_dump(mode="json")

    assert dumped["open"] == point["open"] == "78563.0"
    assert dumped["volume"] == point["volume"] == "30.04552452"


@pytest.mark.unit
def test_typescript_interface_fields_match_the_python_models() -> None:
    for name in (
        "DatasetSummary",
        "DatasetProvenanceEntry",
        "DatasetListResponse",
        "DatasetDetailResponse",
        "BarPoint",
        "DatasetBarsResponse",
    ):
        assert _python_model_fields(name) == _ts_interface_fields(name), (
            f"{name} has drifted between src/harsh_quant_os/contracts/datasets.py "
            f"and packages/types/src/datasets.ts"
        )
