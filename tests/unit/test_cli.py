"""`hqos` must report observed state, never a claim.

Two commands exist (`version`, `status`). Both are checked for the exit code
they actually return, and `status` is checked for the property that matters
most in a terminal that people paste into issues: it names unresolved
secrets but never prints their values.
"""

from __future__ import annotations

import pytest

from harsh_quant_os.cli import main
from harsh_quant_os.config import Settings
from harsh_quant_os.version import DISPLAY_VERSION, PROJECT_NAME, __version__

SECRET_FIELD_NAMES = ("auth_secret_key", "database_password", "local_agent_token")


@pytest.mark.unit
def test_version_command_reports_the_real_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0

    out = capsys.readouterr().out
    assert out.strip() == f"{PROJECT_NAME} {__version__} (display {DISPLAY_VERSION})"
    assert DISPLAY_VERSION in out


@pytest.mark.security
def test_status_reports_safety_state_without_leaking_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings()
    assert main(["status"]) == 0
    out = capsys.readouterr().out

    assert "live_trading       : disabled (enforced at configuration load)" in out
    assert "broker             : " in out
    assert "placeholder secrets: " in out

    for name in SECRET_FIELD_NAMES:
        value = getattr(settings, name)
        # Only values long enough to be a credential are compared against the
        # output: a one-character placeholder would match by accident and make
        # the assertion meaningless rather than meaningful.
        if isinstance(value, str) and len(value) >= 8:
            assert value not in out


@pytest.mark.unit
def test_unknown_command_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["bogus"])

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


@pytest.mark.unit
def test_missing_command_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2
