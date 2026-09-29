"""Cross-language contract parity for the authentication payloads.

The Python models in ``src/harsh_quant_os/contracts/auth.py`` are
authoritative; ``packages/types/src/auth.ts`` mirrors them for the browser.
This test checks four things:

1. both sides accept the shared fixture (``tests/contracts/auth-context.json``);
2. both sides reject a payload that does not follow it;
3. the field names written in TypeScript are exactly the ones written in
   Python, for every model in the contract;
4. no payload in the contract can carry a session token or a session id -
   the omission is deliberate and this is what makes it enforced rather than
   merely intended.

``tests/unit/auth-contract.test.ts`` performs the same comparison in the
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

from harsh_quant_os.contracts.auth import (
    AuthContextResponse,
    LoginRequest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "contracts" / "auth-context.json"
TS_TYPES_PATH = REPO_ROOT / "packages" / "types" / "src" / "auth.ts"
PY_CONTRACT_PATH = REPO_ROOT / "src" / "harsh_quant_os" / "contracts" / "auth.py"

#: Every model in the contract, in declaration order.
MODELS = ("UserProfile", "SessionProfile", "AuthContextResponse", "LoginRequest")


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


def _python_model_fields(name: str) -> list[str]:
    source = _read(PY_CONTRACT_PATH)
    match = re.search(rf"class {name}\(BaseModel\):(.*?)(?=\nclass |\Z)", source, re.DOTALL)
    assert match, f"class {name} not found in {PY_CONTRACT_PATH.name}"
    return re.findall(r"^\s{4}(\w+)\s*:", match.group(1), re.MULTILINE)


# -- the fixture -----------------------------------------------------------


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_auth_context_model() -> None:
    payload = _fixture()["auth_context"]

    validated = AuthContextResponse.model_validate(payload)
    assert validated.model_dump(mode="json") == payload


@pytest.mark.unit
def test_fixture_is_accepted_by_the_python_login_request_model() -> None:
    payload = _fixture()["login_request"]

    assert LoginRequest.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.unit
def test_auth_context_rejects_a_payload_that_does_not_follow_the_contract() -> None:
    payload = _fixture()["auth_context"]

    with pytest.raises(ValidationError):
        AuthContextResponse.model_validate({**payload, "unexpected": "value"})

    with pytest.raises(ValidationError):
        AuthContextResponse.model_validate({"user": payload["user"]})

    with pytest.raises(ValidationError):
        AuthContextResponse.model_validate({"user": None, "session": payload["session"]})


@pytest.mark.unit
def test_login_request_bounds_and_rejects_the_same_values_as_the_api() -> None:
    """The bounds that protect the hasher exist on both sides of the wire."""
    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"email": "", "password": "x"})

    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"email": "a" * 255, "password": "x"})

    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"email": "a@example.com", "password": ""})

    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"email": "a@example.com", "password": "x" * 1025})

    # An unknown field is refused rather than ignored, so a mistyped key in a
    # caller cannot be silently dropped.
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {"email": "a@example.com", "password": "x", "remember_me": True}
        )


# -- parity between the two languages --------------------------------------


@pytest.mark.unit
def test_typescript_interface_fields_match_the_python_models() -> None:
    for name in MODELS:
        assert _python_model_fields(name) == _ts_interface_fields(name), name


@pytest.mark.unit
def test_python_models_declare_exactly_the_fields_the_fixture_carries() -> None:
    """A field added on one side but not the other shows up here first."""
    context = _fixture()["auth_context"]
    assert _python_model_fields("UserProfile") == list(context["user"])
    assert _python_model_fields("SessionProfile") == list(context["session"])
    assert _python_model_fields("AuthContextResponse") == list(context)
    assert _python_model_fields("LoginRequest") == list(_fixture()["login_request"])


@pytest.mark.unit
def test_no_auth_payload_can_carry_a_token_or_a_session_id() -> None:
    """The two deliberate omissions, asserted rather than assumed.

    The session token lives only in an ``HttpOnly`` cookie; a session id in
    the JSON would hand out an internal handle for nothing. Both mirrors are
    checked, because the guarantee holds only while *neither* side can
    introduce the field.
    """
    for name in MODELS:
        fields = _python_model_fields(name)
        for forbidden in ("token", "session_id", "session_token"):
            assert forbidden not in fields, f"{name} in Python grew a {forbidden} field"
            assert forbidden not in _ts_interface_fields(name), f"{name} in TypeScript grew one"

    def _all_keys(value: Any) -> list[str]:
        """Every key name anywhere in the fixture, at any depth."""
        if isinstance(value, dict):
            found: list[str] = []
            for key, item in value.items():
                found.append(key)
                found.extend(_all_keys(item))
            return found
        if isinstance(value, list):
            return [key for item in value for key in _all_keys(item)]
        return []

    present = _all_keys(_fixture())
    for forbidden in ("token", "session_id", "session_token"):
        assert forbidden not in present, f"the shared fixture carries a {forbidden}"


@pytest.mark.unit
def test_the_typescript_source_declares_no_token_field_at_all() -> None:
    source = _read(TS_TYPES_PATH).lower()
    for forbidden in ("token:", "session_id:", "sessiontoken"):
        assert forbidden not in source, f"{TS_TYPES_PATH.name} mentions {forbidden}"
