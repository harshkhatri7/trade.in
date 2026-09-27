"""Cross-language contract parity for the system status payloads.

The Python models are authoritative; ``packages/types/src/system.ts`` mirrors
them for the browser. This test checks three things:

1. both sides accept the same fixture (``tests/contracts/system-status.json``);
2. both sides reject a payload that does not follow it;
3. the field names and enum values written in TypeScript are exactly the ones
   written in Python.

``tests/unit/health-contract.test.ts`` performs the same comparison in the
opposite direction, so the Python job and the TypeScript job each fail when
either side drifts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from harsh_quant_os.contracts.system import (
    ApiEnvironment,
    CheckStatus,
    HealthResponse,
    HealthStatus,
    ReadinessCheck,
    ReadinessStatus,
    ReadyResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "contracts" / "system-status.json"
TS_TYPES_PATH = REPO_ROOT / "packages" / "types" / "src" / "system.ts"
PY_CONTRACT_PATH = REPO_ROOT / "src" / "harsh_quant_os" / "contracts" / "system.py"


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


def _ts_union_values(name: str) -> list[str]:
    source = _read(TS_TYPES_PATH)
    match = re.search(rf"export type {name}\s*=\s*([^;]+);", source, re.DOTALL)
    assert match, f"type alias {name} not found in {TS_TYPES_PATH.name}"
    return re.findall(r"'([^']+)'", match.group(1))


def _class_body(pattern: str) -> str:
    source = _read(PY_CONTRACT_PATH)
    match = re.search(pattern, source, re.DOTALL)
    assert match, f"{pattern} not found in {PY_CONTRACT_PATH.name}"
    return match.group(1)


def _python_enum_values(name: str) -> list[str]:
    body = _class_body(rf"class {name}\(StrEnum\):(.*?)(?=\nclass |\Z)")
    return re.findall(r'=\s*"([^"]+)"', body)


def _python_model_fields(name: str) -> list[str]:
    body = _class_body(rf"class {name}\(BaseModel\):(.*?)(?=\nclass |\Z)")
    return re.findall(r"^\s{4}(\w+)\s*:", body, re.MULTILINE)


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_health_model() -> None:
    payload = _fixture()["health"]

    assert HealthResponse.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_ready_model() -> None:
    payload = _fixture()["ready"]

    validated = ReadyResponse.model_validate(payload)
    assert validated.model_dump(mode="json") == payload
    assert validated.checks
    for check in validated.checks:
        assert isinstance(check, ReadinessCheck)


@pytest.mark.unit
def test_health_model_rejects_a_payload_that_does_not_follow_the_contract() -> None:
    payload = _fixture()["health"]

    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**payload, "unexpected": "value"})

    missing = {key: value for key, value in payload.items() if key != "version"}
    with pytest.raises(ValidationError):
        HealthResponse.model_validate(missing)

    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**payload, "status": "healthy"})


@pytest.mark.unit
def test_typescript_interface_fields_match_the_python_models() -> None:
    assert _python_model_fields("HealthResponse") == _ts_interface_fields("HealthResponse")
    assert _python_model_fields("ReadinessCheck") == _ts_interface_fields("ReadinessCheck")
    assert _python_model_fields("ReadyResponse") == _ts_interface_fields("ReadyResponse")


@pytest.mark.unit
def test_typescript_unions_match_the_python_enums() -> None:
    assert _python_enum_values("HealthStatus") == _ts_union_values("HealthStatus")
    assert _python_enum_values("ReadinessStatus") == _ts_union_values("ReadinessStatus")
    assert _python_enum_values("CheckStatus") == _ts_union_values("CheckStatus")
    assert _python_enum_values("ApiEnvironment") == _ts_union_values("ApiEnvironment")


@pytest.mark.unit
def test_enums_expose_the_values_the_api_actually_serves() -> None:
    assert [value.value for value in HealthStatus] == ["ok"]
    assert [value.value for value in ReadinessStatus] == ["ready", "not_ready"]
    assert [value.value for value in CheckStatus] == ["ok", "not_configured", "failed"]
    assert [value.value for value in ApiEnvironment] == [
        "development",
        "test",
        "staging",
        "production",
    ]
