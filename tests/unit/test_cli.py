"""`hqos` must report observed state, never a claim.

The commands that exist (`version`, `status`, `user create`, `db backup`,
`db restore`, `data ingest`) are each checked for the exit code they actually
return, and `status` is checked for the property that matters most in a
terminal that people paste into issues: it names unresolved secrets but never
prints their values.

`user create` and `db backup` are held to the same standard from the other
side: what they were given must not appear in anything they write, on any
path — including the paths where they fail. `data ingest` is checked from
both directions: it must refuse a malformed window before it spends a
network call or a database connection on it, and its success summary must
describe the store rather than print a price.
"""

from __future__ import annotations

import io
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from harsh_quant_os import cli
from harsh_quant_os.cli import _quarantine_summary, main
from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.provenance import Timeframe
from harsh_quant_os.data import Bar, quarantine_batch, validate_bars
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


# -- `data ingest` ----------------------------------------------------------


def _ingest_args(*extra: str) -> list[str]:
    """A well-formed ingest command, with the given additions appended."""
    return [
        "data",
        "ingest",
        "--symbol",
        "XBTUSD",
        "--timeframe",
        "1h",
        "--start",
        "2026-01-01T00:00:00+00:00",
        *extra,
    ]


def _sample_bars(timeframe: Timeframe = Timeframe.M1) -> list[Bar]:
    """Two synthetic bars — a formatter's fixture, never a price claim.

    Nothing here is a market or a result; the values exist only so the
    summary can be read for what it does and does not print. The
    timeframe is a parameter because validation refuses a batch whose
    bars disagree with the timeframe it was asked about — which is the
    right behaviour, and would otherwise refuse this fixture.
    """
    return [
        Bar(
            symbol="XBTUSD",
            timeframe=timeframe,
            timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.50"),
            volume=Decimal("10.00"),
        ),
        Bar(
            symbol="XBTUSD",
            timeframe=timeframe,
            timestamp=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            open=Decimal("100.50"),
            high=Decimal("102.00"),
            low=Decimal("100.00"),
            close=Decimal("101.25"),
            volume=Decimal("12.50"),
        ),
    ]


#: Prices from the fixture above. None may ever appear in CLI output:
#: what this command reports is the state of the store, not a number
#: somebody could copy into a claim.
FIXTURE_PRICES = ("100.00", "101.00", "99.00", "100.50", "102.00", "101.25")


@pytest.mark.unit
def test_ingest_documents_the_window_it_reads(capsys: pytest.CaptureFixture[str]) -> None:
    """The operator must be able to see the flags without reading the source."""
    with pytest.raises(SystemExit) as exit_info:
        main(["data", "ingest", "--help"])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--provider", "--symbol", "--timeframe", "--start", "--end", "--limit", "--store"):
        assert flag in out, f"{flag} was not documented"
    for name in ("kraken", "yahoo"):
        assert name in out, f"the {name} feed was not named in --provider's help"


@pytest.mark.unit
def test_data_without_a_subcommand_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """`hqos data` alone must not guess at what to fetch."""
    with pytest.raises(SystemExit) as exit_info:
        main(["data"])

    assert exit_info.value.code == 2
    assert "required" in capsys.readouterr().err


@pytest.mark.unit
def test_ingest_rejects_a_timeframe_the_provider_does_not_have(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A timeframe is chosen from a list, so a typo is caught at the prompt."""
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "data",
                "ingest",
                "--symbol",
                "XBTUSD",
                "--timeframe",
                "7m",
                "--start",
                "2026-01-01T00:00:00+00:00",
            ]
        )

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "1h" in err, "the refusal did not list what is supported"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ("yesterday", "is not an ISO 8601 instant"),
        ("2026-01-01T00:00:00", "no UTC offset"),
    ],
)
def test_ingest_refuses_a_window_it_cannot_interpret(
    start: str, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A window with no offset would mean local time, and be wrong by hours.

    Refused before configuration, the database or the network is touched,
    so the operator's typo costs a message and nothing else.
    """
    assert (
        main(["data", "ingest", "--symbol", "XBTUSD", "--timeframe", "1h", "--start", start]) == 1
    )

    err = capsys.readouterr().err
    assert expected in err
    assert "--start" in err


@pytest.mark.unit
def test_ingest_refuses_a_window_that_runs_backwards(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(_ingest_args("--end", "2025-12-31T00:00:00+00:00")) == 1
    assert "--end is not after --start" in capsys.readouterr().err


@pytest.mark.unit
def test_ingest_refuses_a_limit_of_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_ingest_args("--limit", "0")) == 1
    assert "--limit" in capsys.readouterr().err


@pytest.mark.unit
def test_ingest_refuses_a_still_placeholder_database_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unprovisioned machine is told what to run, not shown a fetch."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://harsh_quant_os:replace-with-a-dev-password@127.0.0.1:5432/harsh_quant_os",
    )
    monkeypatch.setenv("DATABASE_PASSWORD", "replace-with-a-dev-password")

    assert main(_ingest_args()) == 1

    err = capsys.readouterr().err
    assert "placeholder" in err
    assert "env:provision" in err


@pytest.mark.security
def test_ingest_checks_the_database_before_it_spends_a_network_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manifest must be writable before anything is fetched.

    Proved by making the provider impossible to construct: were the order
    the other way round, this test would fail with the provider's own
    complaint instead of the database's — and the fetch would already
    have happened by then.
    """
    _point_the_database_nowhere(monkeypatch)

    class _NeverConstructed:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("the provider was built before the database was checked")

    monkeypatch.setattr(cli, "KrakenProvider", _NeverConstructed)

    assert main(_ingest_args()) == 1

    captured = capsys.readouterr()
    assert "did not accept the connection" in captured.err
    assert "npm run db:start" in captured.err

    for name, secret in (
        ("a connection string", "postgresql://"),
        ("the credential in the connection string", "cli_tests"),
        ("the password from the environment", NON_PLACEHOLDER_PASSWORD),
    ):
        assert secret not in captured.out + captured.err, f"output contained {name}"


async def _async_nothing(*args: object, **kwargs: object) -> None:
    """Stands in for engine, session-factory and ping work."""


async def _fake_register(session_factory: object, stored: object) -> uuid.UUID:
    """Returns an id, which is all the summary asks of registration."""
    return uuid.UUID(int=4242)


@pytest.mark.unit
def test_ingest_reports_a_successful_run_without_printing_a_price(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The whole success path, with the network and the database stubbed.

    Stubs rather than a live run, so this is a test of what the command
    *does* — the order of its steps, the artefacts it leaves, the exit
    code it returns — and not of whether a provider or a container
    happened to be reachable at that moment.
    """
    bars = _sample_bars(Timeframe.H1)

    class _StubProvider:
        source = "https://example.invalid/0/public"

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def fetch_bars(self, request: object) -> list[Bar]:
            return list(bars)

    monkeypatch.setattr(cli, "KrakenProvider", _StubProvider)
    monkeypatch.setattr(cli, "_confirm_database_is_there", _async_nothing)
    monkeypatch.setattr(cli, "build_engine", lambda url: object())
    monkeypatch.setattr(cli, "dispose_engine", _async_nothing)
    monkeypatch.setattr(cli, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(cli, "register_dataset", _fake_register)
    monkeypatch.setenv("DATABASE_PASSWORD", NON_PLACEHOLDER_PASSWORD)

    assert main(_ingest_args("--store", str(tmp_path), "--name", "cli.ingest.probe")) == 0

    out = capsys.readouterr().out
    assert out.startswith("ingested")
    assert "quality status" in out
    assert "manifest id" in out
    assert str(uuid.UUID(int=4242)) in out
    assert "rows stored" in out

    for price in FIXTURE_PRICES:
        assert price not in out, "the ingest summary printed a price"

    # What it says it wrote, it wrote.
    assert (tmp_path / "clean" / "cli.ingest.probe").is_dir()
    assert (tmp_path / "raw" / "cli.ingest.probe").is_dir()


@pytest.mark.unit
def test_ingest_rejects_a_provider_it_does_not_have(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider is chosen from a list, so a typo is caught at the prompt
    rather than as a fetch against a feed that was never configured.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "data",
                "ingest",
                "--provider",
                "poloniex",
                "--symbol",
                "XBTUSD",
                "--timeframe",
                "1h",
                "--start",
                "2026-01-01T00:00:00+00:00",
            ]
        )

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "yahoo" in err, "the refusal did not list what is supported"
    assert "kraken" in err, "the refusal did not list what is supported"


@pytest.mark.unit
def test_the_provider_flag_selects_the_feed_and_names_the_dataset(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--provider yahoo`` constructs the other adapter, and the default
    dataset name carries the provider so two feeds of one symbol can
    never overwrite each other.
    """
    bars = _sample_bars(Timeframe.H1)

    class _StubYahoo:
        source = "https://query1.finance.yahoo.com/v8/finance/chart"

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def fetch_bars(self, request: object) -> list[Bar]:
            return list(bars)

    monkeypatch.setattr(cli, "YahooProvider", _StubYahoo)
    monkeypatch.setattr(cli, "_confirm_database_is_there", _async_nothing)
    monkeypatch.setattr(cli, "build_engine", lambda url: object())
    monkeypatch.setattr(cli, "dispose_engine", _async_nothing)
    monkeypatch.setattr(cli, "build_session_factory", lambda engine: object())
    monkeypatch.setattr(cli, "register_dataset", _fake_register)
    monkeypatch.setenv("DATABASE_PASSWORD", NON_PLACEHOLDER_PASSWORD)

    assert main(_ingest_args("--provider", "yahoo", "--store", str(tmp_path))) == 0

    out = capsys.readouterr().out
    assert out.startswith("ingested")
    # No --name given: <provider>.<symbol>.<timeframe> from the flags.
    assert (tmp_path / "clean" / "yahoo.xbtusd.1h").is_dir(), "the default name ignored --provider"
    assert (tmp_path / "raw" / "yahoo.xbtusd.1h").is_dir()


@pytest.mark.unit
def test_the_quarantine_summary_calls_a_refusal_a_refusal(
    tmp_path: Path,
) -> None:
    """A refused batch must never read as an empty success."""
    backwards = sorted(_sample_bars(), key=lambda bar: bar.timestamp, reverse=True)
    report = validate_bars(backwards, timeframe=Timeframe.M1)
    assert report.reasons, "the fixture was not actually refused"

    record = quarantine_batch(
        tmp_path,
        name="cli.refused.probe",
        source="https://example.invalid/0/public",
        raw_bars=backwards,
        report=report,
    )

    summary = _quarantine_summary(record, store_root=tmp_path)

    assert summary.startswith("batch refused")
    assert "not written; a refused batch is not a dataset" in summary
    assert "quality status" in summary
    assert record.payload_path in summary

    for price in FIXTURE_PRICES:
        assert price not in summary, "the quarantine summary printed a price"


# -- `strategy` -------------------------------------------------------------


@pytest.mark.unit
def test_promote_documents_the_gate_it_enforces(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["strategy", "promote", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "walk-forward" in out
    assert "someone other than the author" in out


@pytest.mark.unit
def test_strategy_workflow_promotes_only_with_the_section_3_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = str(tmp_path)

    assert (
        main(
            [
                "strategy",
                "register",
                "--slug",
                "band-v2",
                "--hypothesis",
                "enter on a 1% band, exit on a 0.5% retrace",
                "--author",
                "quant",
                "--run-id",
                "run-0001",
                "--run-detail",
                "exploratory run on the pinned 1m dataset",
                "--strategies-dir",
                root,
            ]
        )
        == 0
    )
    assert "registered: band-v2 -> candidates" in capsys.readouterr().out

    # Too early: refused, with the gaps named on stderr.
    assert (
        main(
            [
                "strategy",
                "promote",
                "--slug",
                "band-v2",
                "--actor",
                "auditor",
                "--strategies-dir",
                root,
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "cannot be marked validated" in err
    assert "walk_forward" in err

    for kind in ("held_out", "walk_forward", "sensitivity", "critique"):
        assert (
            main(
                [
                    "strategy",
                    "evidence",
                    "--slug",
                    "band-v2",
                    "--kind",
                    kind,
                    "--reference",
                    f"ref-{kind}",
                    "--detail",
                    f"the recorded {kind} entry",
                    "--recorded-by",
                    "auditor",
                    "--strategies-dir",
                    root,
                ]
            )
            == 0
        )
    capsys.readouterr()

    assert (
        main(
            [
                "strategy",
                "promote",
                "--slug",
                "band-v2",
                "--actor",
                "auditor",
                "--strategies-dir",
                root,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "promoted: band-v2 -> validated" in out
    assert "Phase 10 plus human approval" in out

    # The file moved with the stage.
    assert (tmp_path / "validated" / "band-v2.json").is_file()
    assert not (tmp_path / "candidates" / "band-v2.json").exists()

    assert main(["strategy", "show", "--strategies-dir", root]) == 0
    out = capsys.readouterr().out
    assert "validated/band-v2" in out
    assert "missing for validated: none" in out
    assert "unregistered -> candidates" in out
    assert "candidates -> validated" in out


@pytest.mark.unit
def test_strategy_reject_requires_and_then_keeps_its_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = str(tmp_path)
    assert (
        main(
            [
                "strategy",
                "register",
                "--slug",
                "quiet-market",
                "--hypothesis",
                "entries only in high-volume sessions",
                "--author",
                "quant",
                "--run-id",
                "run-0002",
                "--run-detail",
                "exploratory run with two trades",
                "--strategies-dir",
                root,
            ]
        )
        == 0
    )
    capsys.readouterr()

    # An empty reason never reaches the file.
    assert (
        main(
            [
                "strategy",
                "reject",
                "--slug",
                "quiet-market",
                "--actor",
                "quant",
                "--reason",
                " ",
                "--strategies-dir",
                root,
            ]
        )
        == 1
    )
    assert "keeps its reason" in capsys.readouterr().err

    assert (
        main(
            [
                "strategy",
                "reject",
                "--slug",
                "quiet-market",
                "--actor",
                "quant",
                "--reason",
                "two trades in the sample, nothing to judge",
                "--strategies-dir",
                root,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "rejected: quiet-market" in out
    assert "reason kept: two trades in the sample, nothing to judge" in out


@pytest.mark.unit
def test_strategy_show_on_an_empty_directory_says_so(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["strategy", "show", "--strategies-dir", str(tmp_path)]) == 0
    assert "no promotion records" in capsys.readouterr().out


@pytest.mark.unit
def test_strategy_without_a_subcommand_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["strategy"])

    assert excinfo.value.code == 2
    assert "required" in capsys.readouterr().err
