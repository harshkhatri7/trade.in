"""`hqos` must report observed state, never a claim.

Three commands exist (`version`, `status`, `user create`). Each is checked for
the exit code it actually returns, and `status` is checked for the property
that matters most in a terminal that people paste into issues: it names
unresolved secrets but never prints their values.

`user create` is held to the same standard from the other side: the password
it was given must not appear in anything it writes, on any path - including
the paths where it fails.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from harsh_quant_os.cli import main
from harsh_quant_os.config import Settings
from harsh_quant_os.version import DISPLAY_VERSION, PROJECT_NAME, __version__

SECRET_FIELD_NAMES = ("auth_secret_key", "database_password", "local_agent_token")

#: A password that never reaches a database in these tests. Short enough to
#: satisfy no scanner that looks for a credential-shaped assignment.
TEST_PASSWORD = "cli-test-pass"

#: Nothing listens on port 5, so a connection is refused immediately.
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://cli_tests:cli_tests@127.0.0.1:5/cli_tests"

#: Configured so `Settings.is_placeholder("database_password")` is False and
#: the command gets as far as opening a connection. Overrides `.env`, which
#: pydantic-settings ranks below a real environment variable.
NON_PLACEHOLDER_PASSWORD = "a-local-password-that-is-not-a-placeholder"


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


# -- `user create` ----------------------------------------------------------


def _point_the_database_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings that pass the placeholder check and then refuse to connect.

    Overrides ``.env`` on both counts, so these tests behave the same on a
    machine that has never been provisioned and on one that has - and so that
    no test can reach the development database even by accident.
    """
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DATABASE_URL)
    monkeypatch.setenv("DATABASE_PASSWORD", NON_PLACEHOLDER_PASSWORD)


def _feed_password(monkeypatch: pytest.MonkeyPatch, text: str = TEST_PASSWORD + "\n") -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


@pytest.mark.unit
def test_create_documents_the_channel_it_reads_the_password_from(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["user", "create", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--email" in out
    assert "--password-stdin" in out
    assert "--superuser" in out


@pytest.mark.unit
def test_user_without_a_subcommand_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["user"])

    assert excinfo.value.code == 2
    assert "required" in capsys.readouterr().err


@pytest.mark.security
def test_create_without_a_terminal_refuses_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No TTY means no prompt is possible, and guessing would be worse."""
    _point_the_database_nowhere(monkeypatch)
    # A password is sitting on stdin, but without --password-stdin the command
    # would have to prompt for it, and there is nobody there to answer.
    _feed_password(monkeypatch)

    assert main(["user", "create", "--email", "owner@example.com"]) == 1

    err = capsys.readouterr().err
    assert "--password-stdin" in err
    assert TEST_PASSWORD not in err


@pytest.mark.security
def test_create_with_an_empty_stdin_reports_that_nothing_was_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _point_the_database_nowhere(monkeypatch)
    _feed_password(monkeypatch, "")

    assert main(["user", "create", "--email", "owner@example.com", "--password-stdin"]) == 1

    err = capsys.readouterr().err
    assert "no password was read" in err
    assert TEST_PASSWORD not in err


@pytest.mark.security
def test_create_reports_a_database_it_cannot_reach_without_leaking_the_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure a server would log must not become a line the CLI prints.

    The driver's own message embeds the connection string, and the connection
    string embeds the password - so only the error's *type* may be shown.
    """
    _point_the_database_nowhere(monkeypatch)
    _feed_password(monkeypatch)

    assert main(["user", "create", "--email", "owner@example.com", "--password-stdin"]) == 1

    captured = capsys.readouterr()
    assert "did not accept the connection" in captured.err
    assert "npm run db:start" in captured.err

    for name, secret in (
        ("the password", TEST_PASSWORD),
        ("a connection string", "postgresql://"),
        ("the credential in the connection string", "cli_tests"),
    ):
        assert secret not in captured.out + captured.err, f"output contained {name}"


@pytest.mark.security
def test_create_refuses_a_bad_address_without_printing_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal message describes the rule, never the value that broke it."""
    _point_the_database_nowhere(monkeypatch)
    _feed_password(monkeypatch)

    assert main(["user", "create", "--email", "not-an-address", "--password-stdin"]) == 1

    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "name@example.com" in captured.err
    assert TEST_PASSWORD not in captured.out + captured.err


@pytest.mark.unit
def test_create_refuses_a_still_placeholder_database_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unprovisioned machine gets told what to run, not a connection error."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://harsh_quant_os:replace-with-a-dev-password@127.0.0.1:5432/harsh_quant_os",
    )
    monkeypatch.setenv("DATABASE_PASSWORD", "replace-with-a-dev-password")
    _feed_password(monkeypatch)

    assert main(["user", "create", "--email", "owner@example.com", "--password-stdin"]) == 1

    err = capsys.readouterr().err
    assert "placeholder" in err
    assert "env:provision" in err
    assert TEST_PASSWORD not in err


@pytest.mark.unit
def test_backup_documents_where_it_writes(capsys: pytest.CaptureFixture[str]) -> None:
    """The operator must be able to see the flags without reading the source."""
    with pytest.raises(SystemExit) as exit_info:
        main(["db", "backup", "--help"])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "--output" in out
    assert "--overwrite" in out


@pytest.mark.unit
def test_restore_documents_the_switch_that_discards_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The flag that destroys existing rows is the one worth spelling out."""
    with pytest.raises(SystemExit) as exit_info:
        main(["db", "restore", "--help"])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "--replace-existing" in out
    assert "--source" in out


@pytest.mark.unit
def test_db_without_a_subcommand_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """`hqos db` alone must not guess at whether to back up or to restore."""
    with pytest.raises(SystemExit) as exit_info:
        main(["db"])

    assert exit_info.value.code == 2
    assert "required" in capsys.readouterr().err


@pytest.mark.security
def test_backup_reports_a_database_it_cannot_reach_without_leaking_the_dsn(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A refused socket is reported by type, never by the message underneath.

    The underlying message is where a connection string would appear; the
    error class is all an operator needs to know where to look.
    """
    _point_the_database_nowhere(monkeypatch)

    destination = tmp_path / "unreachable-backup"
    assert main(["db", "backup", "--output", str(destination)]) == 1

    captured = capsys.readouterr()
    assert "did not accept the connection" in captured.err
    assert "npm run db:start" in captured.err
    assert "ConnectionRefusedError" in captured.err

    for name, secret in (
        ("a connection string", "postgresql://"),
        ("the credential in the connection string", "cli_tests"),
        ("the password from the environment", NON_PLACEHOLDER_PASSWORD),
    ):
        assert secret not in captured.out + captured.err, f"output contained {name}"


@pytest.mark.unit
def test_restore_refuses_a_directory_that_is_not_a_backup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The manifest is checked before a connection is ever opened, and said so."""
    _point_the_database_nowhere(monkeypatch)

    assert main(["db", "restore", "--source", str(tmp_path / "nope")]) == 1

    err = capsys.readouterr().err
    assert "error:" in err
    assert "manifest.json" in err
    assert "postgresql://" not in err
