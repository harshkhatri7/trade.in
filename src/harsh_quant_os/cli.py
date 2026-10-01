"""Command line entry point (``hqos``).

Only reports real state - it never claims success it did not observe.

There is no sign-up endpoint in Phase 2: accounts are minted here, out of
band, so a private research platform never exposes an open registration
surface to the network. Everything this file prints is either public
configuration or something it just observed being created - never a password,
never a token, never a connection string.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import platform
import shutil
import socket
import sys
import uuid
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from harsh_quant_os.auth import AuthService
from harsh_quant_os.auth.errors import DatabaseUnavailable, DuplicateUser, PasswordPolicyError
from harsh_quant_os.backtesting import (
    BacktestConfig,
    BacktestError,
    BpsCommission,
    CloseThreshold,
    FixedBpsSlippage,
    build_manifest,
    build_report,
    compute_metrics,
    cost_sensitivity,
    load_backtest_data,
    parse_decimal,
    promotion,
    run_backtest,
    window_coverage,
)
from harsh_quant_os.config import Settings, SettingsError
from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data import (
    DEFAULT_STORE_ROOT,
    BarRequest,
    KrakenProvider,
    MarketDataError,
    QuarantineRecord,
    StoredDataset,
    StoreRefused,
    UrllibTransport,
    ValidationReport,
    quarantine_batch,
    store_batch,
    validate_bars,
)
from harsh_quant_os.data.manifest import register_dataset
from harsh_quant_os.db import (
    BackupError,
    BackupManifest,
    build_engine,
    build_session_factory,
    dispose_engine,
    export_database,
    import_database,
)
from harsh_quant_os.db.models import User
from harsh_quant_os.quant.recipes.recipe import RecipeError
from harsh_quant_os.safety import (
    ConfiguredRiskEvaluator,
    TradingGateError,
    resolve_trading_mode,
)
from harsh_quant_os.version import DISPLAY_VERSION, PROJECT_NAME, __version__

#: Where ``hqos backtest report`` writes when ``--out`` is omitted.
#: Git-ignored: a simulated result is an artefact of a run, not
#: repository content (reports are never committed).
DEFAULT_REPORT_ROOT = Path(__file__).resolve().parents[2] / "research" / "reports"


class _CliError(Exception):
    """A failure worth exiting over, whose message is safe to print.

    Raised instead of printing directly so that every command funnels its
    errors through one place - and so that a test can assert on the message
    without also asserting on formatting.
    """


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hqos",
        description=f"{PROJECT_NAME} command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Print the project version.")
    subparsers.add_parser("status", help="Print the real environment and safety status.")

    user = subparsers.add_parser(
        "user",
        help="Manage local accounts (Phase 2 has no sign-up endpoint).",
    )
    user_commands = user.add_subparsers(dest="user_command", required=True)
    create = user_commands.add_parser(
        "create",
        help="Create an account, then report what was actually created.",
    )
    create.add_argument("--email", required=True, help="Address for the new account.")
    create.add_argument("--display-name", default=None, help="Optional name to show.")
    create.add_argument(
        "--superuser",
        action="store_true",
        help="Grant the owner flag for this private installation.",
    )
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from standard input instead of prompting for it.",
    )

    database = subparsers.add_parser(
        "db",
        help="Back up and restore the metadata database.",
    )
    database_commands = database.add_subparsers(dest="db_command", required=True)

    backup = database_commands.add_parser(
        "backup",
        help="Write every table to a directory, then report what was written.",
    )
    backup.add_argument("--output", required=True, help="Directory to write the backup into.")
    backup.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace a backup already present in that directory.",
    )

    restore = database_commands.add_parser(
        "restore",
        help="Load a backup into the configured database.",
    )
    restore.add_argument("--source", required=True, help="Directory holding the backup.")
    restore.add_argument(
        "--replace-existing",
        action="store_true",
        help="Discard rows already in the target database.",
    )

    data = subparsers.add_parser(
        "data",
        help="Fetch, validate and store market data for research.",
    )
    data_commands = data.add_subparsers(dest="data_command", required=True)

    ingest = data_commands.add_parser(
        "ingest",
        help=(
            "Fetch real candles, validate them, write the artefacts and "
            "register the manifest row. Exits 1 and quarantines the batch "
            "when validation refuses it."
        ),
    )
    ingest.add_argument(
        "--symbol",
        required=True,
        help="The provider's own spelling of the instrument, e.g. XBTUSD.",
    )
    ingest.add_argument(
        "--timeframe",
        required=True,
        choices=[value.value for value in Timeframe],
        help="Bar size, in the provider's vocabulary.",
    )
    ingest.add_argument(
        "--start",
        required=True,
        help="Instant to fetch from, ISO 8601, carrying its offset (e.g. ...+00:00).",
    )
    ingest.add_argument(
        "--end",
        default=None,
        help="Instant to stop at, ISO 8601 with its offset. Optional.",
    )
    ingest.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many bars. Optional.",
    )
    ingest.add_argument(
        "--name",
        default=None,
        help="Dataset name. Defaults to kraken.<symbol>.<timeframe>.",
    )
    ingest.add_argument(
        "--store",
        default=str(DEFAULT_STORE_ROOT),
        help=f"Directory to write the dataset into (default: {DEFAULT_STORE_ROOT}).",
    )

    backtest = subparsers.add_parser(
        "backtest",
        help="Run a historical simulation and write an honest report.",
    )
    backtest_commands = backtest.add_subparsers(dest="backtest_command", required=True)

    report = backtest_commands.add_parser(
        "report",
        help=(
            "Run the harness's reference strategy over a stored dataset and "
            "write a markdown report: limitations first, manifest attached, "
            "assumptions separated from measured results. The report file is "
            "a simulated result and is written outside version control."
        ),
    )
    report.add_argument(
        "--dataset",
        required=True,
        help="Stored dataset name, e.g. kraken.xbtusd.1m.",
    )
    report.add_argument(
        "--version",
        default=None,
        help="Pinned dataset version (SHA-256). Defaults to the only stored version.",
    )
    report.add_argument(
        "--store",
        default=str(DEFAULT_STORE_ROOT),
        help=f"Data root holding clean/ (default: {DEFAULT_STORE_ROOT}).",
    )
    report.add_argument(
        "--out",
        default=None,
        help=(
            "Report file to write. Defaults to "
            "research/reports/backtest-<dataset>-<run id>.md in the repository."
        ),
    )
    report.add_argument(
        "--target-qty",
        default="0.01",
        help="Position size while the rule holds, exact decimal (default 0.01).",
    )
    report.add_argument(
        "--entry-above",
        default="0",
        help=(
            "Enter while close >= this exact decimal; 'always' enters "
            "unconditionally (default 0, which holds on any non-negative "
            "price)."
        ),
    )
    report.add_argument(
        "--exit-below",
        default=None,
        help=(
            "Return to flat while close <= this exact decimal; omit to never "
            "exit. Requires --entry-above as a real band, because an 'always' "
            "entry could never exit."
        ),
    )
    report.add_argument(
        "--capital",
        default="1000",
        help="Starting capital, exact decimal (default 1000).",
    )
    report.add_argument(
        "--rate-bps",
        default="5",
        help="Commission in basis points, exact decimal (default 5).",
    )
    report.add_argument(
        "--fixed-fee",
        default="0",
        help="Fixed commission per fill, exact decimal (default 0).",
    )
    report.add_argument(
        "--slippage-bps",
        default="10",
        help="Slippage in basis points, exact decimal (default 10).",
    )

    strategy = subparsers.add_parser(
        "strategy",
        help=(
            "Move a strategy through candidates / validated / rejected / "
            "archived with evidence attached. 'validated' is refused without "
            "the section 3 evidence, and there is no live stage."
        ),
    )
    strategy_commands = strategy.add_subparsers(dest="strategy_command", required=True)

    def _add_record_arguments(command: argparse.ArgumentParser) -> None:
        """The slug and directory every strategy command shares."""
        command.add_argument(
            "--slug",
            required=True,
            help=(
                "Record identity: lowercase letters, digits and single "
                "hyphens; it becomes the file name."
            ),
        )
        command.add_argument(
            "--strategies-dir",
            default="strategies",
            help="Directory holding the four stage folders (default: strategies).",
        )

    register = strategy_commands.add_parser(
        "register",
        help="Register a hypothesis with its one exploratory run into candidates/.",
    )
    _add_record_arguments(register)
    register.add_argument(
        "--hypothesis",
        required=True,
        help="The registered hypothesis being tested.",
    )
    register.add_argument(
        "--author",
        required=True,
        help="Who is accountable for the candidate.",
    )
    register.add_argument(
        "--run-id",
        required=True,
        help=(
            "Run id of the one exploratory run (the run's artefacts stay "
            "outside version control; this names them)."
        ),
    )
    register.add_argument(
        "--run-detail",
        required=True,
        help="What that exploratory run was.",
    )

    evidence = strategy_commands.add_parser(
        "evidence",
        help=("Append one recorded evidence entry; entries are append-only and one per kind."),
    )
    _add_record_arguments(evidence)
    evidence.add_argument(
        "--kind",
        required=True,
        choices=list(promotion.EVIDENCE_KINDS),
        help="Which recorded kind.",
    )
    evidence.add_argument(
        "--reference",
        required=True,
        help="How to find the artefact (run id, manifest hash, critique id).",
    )
    evidence.add_argument(
        "--detail",
        required=True,
        help="What this entry was, in words.",
    )
    evidence.add_argument(
        "--recorded-by",
        required=True,
        help="Who recorded it; a critique must differ from the candidate's --author.",
    )

    promote_help = (
        "Promote a candidate to validated; refused unless held-out, "
        "walk-forward, sensitivity and critique are all recorded and the "
        "critique was recorded by someone other than the author."
    )
    promote = strategy_commands.add_parser(
        "promote",
        help=promote_help,
        description=promote_help,
    )
    _add_record_arguments(promote)
    promote.add_argument("--actor", required=True, help="Who is promoting.")
    promote.add_argument(
        "--reason",
        default=None,
        help="Why; defaults to naming the section 3 gates it passed.",
    )

    reject = strategy_commands.add_parser(
        "reject",
        help="Reject a candidate, keeping its reason beside the record (section 2.9).",
    )
    _add_record_arguments(reject)
    reject.add_argument("--actor", required=True, help="Who is rejecting.")
    reject.add_argument(
        "--reason",
        required=True,
        help="Why it is rejected; required, and kept with the record.",
    )

    archive = strategy_commands.add_parser(
        "archive",
        help="Archive a candidate or validated strategy with its reason.",
    )
    _add_record_arguments(archive)
    archive.add_argument("--actor", required=True, help="Who is archiving.")
    archive.add_argument(
        "--reason",
        required=True,
        help="Why it was closed; required, and kept with the record.",
    )

    show = strategy_commands.add_parser(
        "show",
        help="Show one record, or every record across the four stages.",
    )
    show.add_argument(
        "--slug",
        default=None,
        help="Show only this record; omit to list every record.",
    )
    show.add_argument(
        "--strategies-dir",
        default="strategies",
        help="Directory holding the four stage folders (default: strategies).",
    )
    return parser


def _version_text() -> str:
    return f"{PROJECT_NAME} {__version__} (display {DISPLAY_VERSION})"


def _status_text(settings: Settings) -> str:
    docker = shutil.which("docker")
    lines = [
        f"project            : {PROJECT_NAME} {__version__}",
        f"python             : {platform.python_version()}",
        f"platform           : {platform.platform()}",
        f"app_env            : {settings.app_env}",
        f"trading_mode       : {resolve_trading_mode(settings).value}",
        "live_trading       : disabled (enforced at configuration load)",
        f"broker             : {'configured' if settings.broker_provider else 'not connected'}",
        f"paper_capital      : {settings.paper_capital_amount:.2f} {settings.paper_capital_currency}",
        f"local_agent        : {'enabled' if settings.local_agent_enabled else 'disabled'}",
        f"docker             : {'available' if docker else 'not installed (Docker is optional)'}",
    ]
    unresolved = settings.missing_secrets()
    lines.append("placeholder secrets: " + (", ".join(unresolved) if unresolved else "none"))
    return "\n".join(lines)


def _load_settings() -> Settings:
    try:
        return Settings.load()
    except SettingsError:
        # Deliberately not the exception text: pydantic's message embeds the
        # value that failed validation, and a value that failed to parse can
        # just as easily be the connection string - which carries the
        # database password. The operator needs to know *that* configuration
        # is unusable, and where to look; not a line containing a credential.
        raise _CliError(
            "configuration could not be loaded; check .env against .env.example"
        ) from None


def _read_password(password_stdin: bool) -> str:
    """Return the password for a new account without ever displaying it.

    ``--password-stdin`` is the only non-interactive path, and the only one
    that keeps the value out of the process list: a password given as an
    argument would be visible to ``ps`` and recorded in shell history. With no
    terminal to prompt on and no input to read, refusing beats guessing.
    """
    if password_stdin:
        line = sys.stdin.readline()
        if not line:
            raise _CliError("no password was read from standard input")
        return line.rstrip("\r\n")

    if not sys.stdin.isatty():
        raise _CliError("no terminal to prompt on; pass --password-stdin")

    first = getpass.getpass("Password: ")
    second = getpass.getpass("Password (again): ")
    if first != second:
        raise _CliError("the two passwords did not match")
    return first


def _require_database(settings: Settings) -> None:
    """Refuse to touch a database whose password is still a template value.

    Shared by every command that opens a connection, so a fresh checkout
    fails the same way whichever one it was.
    """
    if settings.is_placeholder("database_password"):
        raise _CliError(
            "DATABASE_PASSWORD still holds a placeholder value; run `npm run env:provision` first"
        )


def _create_user(args: argparse.Namespace) -> int:
    """Create one account and report only what was observed being created."""
    settings = _load_settings()
    _require_database(settings)

    password = _read_password(args.password_stdin)

    async def _run() -> User:
        engine = build_engine(settings.database_url)
        try:
            service = AuthService(
                session_factory=build_session_factory(engine),
                secret_key=settings.auth_secret_key,
                session_ttl=timedelta(minutes=settings.auth_token_expiry_minutes),
            )
            return await service.create_user(
                email=args.email,
                password=password,
                display_name=args.display_name,
                is_superuser=args.superuser,
            )
        finally:
            await dispose_engine(engine)

    try:
        user = asyncio.run(_run())
    except DuplicateUser:
        raise _CliError(f"an account already exists for {args.email}") from None
    except PasswordPolicyError as exc:
        # Safe to show: the policy messages describe the rule that was broken,
        # never the value that broke it.
        raise _CliError(exc.detail) from None
    except DatabaseUnavailable as exc:
        raise _CliError(
            "the database did not accept the connection "
            f"(error type: {exc.error_type}); is it running? see `npm run db:start`"
        ) from None

    # The summary is deliberately the whole of the output: an account was
    # created, here is what it is called, and the password is now only in the
    # operator's head and in Argon2id form in the database.
    print("created account")
    print(f"  id           : {user.id}")
    print(f"  email        : {user.email}")
    print(f"  display name : {user.display_name or '(none)'}")
    print(f"  superuser    : {'yes' if user.is_superuser else 'no'}")
    print(f"  created at   : {user.created_at.isoformat()}")
    return 0


def _run_database_command(
    operation: Callable[[], Coroutine[Any, Any, BackupManifest]], action: str
) -> BackupManifest:
    """Run one database operation, turning failures into printable errors.

    Three failure classes are worth distinguishing, and none of them may
    show the exception's own text: SQLAlchemy and asyncpg both put the
    connection string into some of their messages, and the connection string
    carries the password.

    * A refused socket or a SQL error means the *database* refused. It is
      reported by type, with where to look, exactly as ``user create`` does -
      so the two commands read the same way.
    * ``OSError`` that is not a connection problem means the *destination*
      did, which is a different fix and must not be blamed on the server.
    * A :class:`BackupError` is safe verbatim: those messages contain table
      names, revisions and directory paths, and never a URL.
    """
    try:
        return asyncio.run(operation())
    except BackupError as exc:
        raise _CliError(str(exc)) from None
    except (ConnectionError, TimeoutError, socket.gaierror) as exc:
        raise _CliError(
            f"could not {action}: the database did not accept the connection "
            f"(error type: {type(exc).__name__}); is it running? see `npm run db:start`"
        ) from None
    except SQLAlchemyError as exc:
        raise _CliError(
            f"could not {action}: the database rejected the operation "
            f"(error type: {type(exc).__name__})"
        ) from None
    except OSError as exc:
        raise _CliError(
            f"could not {action}: an I/O operation failed "
            f"(error type: {type(exc).__name__}); check that the destination "
            "directory exists and is writable"
        ) from None


def _report(verb: str, location: Path, manifest: BackupManifest) -> str:
    """A one-screen summary of what was just observed, and nothing else."""
    lines = [
        verb,
        f"  location       : {location.resolve()}",
        f"  schema         : {manifest.schema_revision or '(un-migrated)'}",
        f"  tables         : {len(manifest.tables)}",
        f"  rows           : {manifest.total_rows}",
    ]
    lines.extend(f"    {entry.name:<20} {entry.rows:>10} rows" for entry in manifest.tables)
    return "\n".join(lines)


def _backup(args: argparse.Namespace) -> int:
    """Write a backup, then report what was actually written."""
    settings = _load_settings()
    _require_database(settings)

    async def _run() -> BackupManifest:
        engine = build_engine(settings.database_url)
        try:
            return await export_database(engine, args.output, overwrite=args.overwrite)
        finally:
            await dispose_engine(engine)

    print(_report("backup written", Path(args.output), _run_database_command(_run, "back up")))
    return 0


def _restore(args: argparse.Namespace) -> int:
    """Load a backup, then report what was actually loaded."""
    settings = _load_settings()
    _require_database(settings)

    async def _run() -> BackupManifest:
        engine = build_engine(settings.database_url)
        try:
            return await import_database(
                engine, args.source, replace_existing=args.replace_existing
            )
        finally:
            await dispose_engine(engine)

    print(_report("restore complete", Path(args.source), _run_database_command(_run, "restore")))
    return 0


def _parse_instant(value: str, flag: str) -> datetime:
    """Read an absolute instant that carries its own offset.

    A timestamp without one would mean local time, and a window that
    drifted by the machine's offset would produce a dataset whose
    provenance was wrong by hours while every line of it looked correct.
    Refusing beats guessing.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _CliError(f"{flag} is not an ISO 8601 instant: {value!r}") from None
    if parsed.tzinfo is None:
        raise _CliError(f"{flag} carries no UTC offset; write it as 2026-01-01T00:00:00+00:00")
    return parsed.astimezone(UTC)


async def _confirm_database_is_there(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Prove the manifest can be written *before* anything is fetched.

    Fetched bars with nowhere to register them are an orphan: the
    artefacts exist and nothing in the platform can find them. One round
    trip costs less than that, and it means an unreachable database is
    reported before the network is used rather than after it.
    """
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))


def _ingest_summary(
    stored: StoredDataset,
    report: ValidationReport,
    *,
    dataset_id: uuid.UUID,
    store_root: Path,
) -> str:
    """Everything observed about an ingest that succeeded, and nothing else.

    Deliberately no prices: what is printed is the state of the store and
    the verdict of validation, so a summary pasted into an issue or a
    message cannot be read as a performance figure or as a result.
    """
    accepted = report.accepted_bars
    window = (
        f"{accepted[0].timestamp.isoformat()} .. {accepted[-1].timestamp.isoformat()}"
        if accepted
        else "(none)"
    )
    lines = [
        "ingested",
        f"  dataset         : {stored.name}",
        f"  source          : {stored.source}",
        f"  instrument      : {stored.instrument}",
        f"  timeframe       : {stored.timeframe.value}",
        f"  window          : {window}",
        f"  rows received   : {stored.received}",
        f"  rows stored     : {stored.row_count}",
        f"  duplicates      : {stored.duplicates_removed}",
        f"  gaps            : {stored.gaps}",
        f"  outliers        : {stored.outliers}",
        f"  quality status  : {stored.quality_status.value}",
        f"  version         : {stored.version}",
        f"  store           : {store_root.resolve()}",
        f"  clean artefact  : {stored.clean_path}",
        f"  manifest id     : {dataset_id}",
    ]
    lines.extend(f"  reason          : {reason}" for reason in stored.reasons)
    lines.extend(f"  note            : {note}" for note in stored.notes)
    return "\n".join(lines)


def _quarantine_summary(record: QuarantineRecord, *, store_root: Path) -> str:
    """What happened to a batch validation refused.

    The wording is the point: nothing was written to ``clean/``, no
    manifest row exists, and the batch is kept where the refusal can be
    examined later rather than having to be reproduced from scratch.
    """
    lines = [
        "batch refused",
        f"  dataset         : {record.name}",
        f"  source          : {record.source}",
        f"  quality status  : {record.status.value}",
        f"  rows received   : {record.received}",
        f"  store           : {store_root.resolve()}",
        f"  payload         : {record.payload_path}",
        f"  report          : {record.report_path}",
        "  manifest        : not written; a refused batch is not a dataset",
    ]
    lines.extend(f"  reason          : {reason}" for reason in record.reasons)
    return "\n".join(lines)


def _ingest(args: argparse.Namespace) -> int:
    """Fetch real candles, then say exactly what became of them."""
    # Arguments are judged before configuration or the network is touched:
    # a typo in a timestamp is the operator's to fix, and finding out
    # about it costs nothing if nothing else has happened yet.
    timeframe = Timeframe(args.timeframe)
    start = _parse_instant(args.start, "--start")
    end = None if args.end is None else _parse_instant(args.end, "--end")
    if end is not None and end <= start:
        raise _CliError("--end is not after --start")
    if args.limit is not None and args.limit < 1:
        raise _CliError("--limit must be at least 1 bar")

    settings = _load_settings()
    _require_database(settings)

    name = args.name or f"kraken.{args.symbol.lower()}.{timeframe.value}"
    store_root = Path(args.store)

    async def _run() -> int:
        engine = build_engine(settings.database_url)
        try:
            session_factory = build_session_factory(engine)
            await _confirm_database_is_there(session_factory)

            provider = KrakenProvider(UrllibTransport())
            bars = list(
                await provider.fetch_bars(
                    BarRequest(
                        symbol=args.symbol,
                        timeframe=timeframe,
                        start=start,
                        end=end,
                        limit=args.limit,
                    )
                )
            )
            if not bars:
                # An empty window is an answer, not an error: the provider
                # said there was nothing committed there. Reporting it as a
                # failure would claim knowledge of why.
                raise _CliError("the provider returned no committed candles for that window")

            report = validate_bars(bars, timeframe=timeframe)

            if report.status is DataQualityStatus.INVALID:
                record = quarantine_batch(
                    store_root,
                    name=name,
                    source=provider.source,
                    raw_bars=bars,
                    report=report,
                )
                print(_quarantine_summary(record, store_root=store_root))
                return 1

            stored = store_batch(
                store_root,
                name=name,
                source=provider.source,
                raw_bars=bars,
                report=report,
            )

            try:
                dataset_id = await register_dataset(session_factory, stored)
            except SQLAlchemyError as exc:
                # Half-done, and it may not be reported as done: artefacts
                # exist with no manifest row pointing at them, which is a
                # state to fix rather than a state to celebrate.
                raise _CliError(
                    "the bars were stored but not registered "
                    f"(error type: {type(exc).__name__}); the manifest row is "
                    "missing, so re-run this command before relying on the dataset"
                ) from None

            print(_ingest_summary(stored, report, dataset_id=dataset_id, store_root=store_root))
            return 0
        finally:
            await dispose_engine(engine)

    try:
        return asyncio.run(_run())
    except StoreRefused as exc:
        # The store's own refusal, with its reason and a path - never a
        # payload. Nothing was written to clean/, which is the whole point.
        raise _CliError(str(exc)) from None
    except MarketDataError as exc:
        # The adapter's own wording: a provider's words, a symbol, an HTTP
        # status. This provider never carries a credential, so there is
        # nothing of ours in these messages to redact.
        raise _CliError(str(exc)) from None
    except (ConnectionError, TimeoutError, socket.gaierror, SQLAlchemyError) as exc:
        raise _CliError(
            "could not ingest: the database did not accept the connection "
            f"(error type: {type(exc).__name__}); is it running? see `npm run db:start`"
        ) from None
    except OSError as exc:
        raise _CliError(
            f"could not ingest: an I/O operation failed (error type: {type(exc).__name__}); "
            "check that the store directory exists and is writable"
        ) from None


def _backtest_report(args: argparse.Namespace) -> int:
    """Run one recorded backtest and write its report.

    Everything printed was just observed: the run id the manifest
    derived, the path the file was written to, and the bar, fill and
    ending-equity numbers the engine computed. Failures surface as
    ``_CliError`` so they print as one safe line instead of a traceback.

    Raises:
        _CliError: Any input, store, safety or risk refusal - the
            message is the refusal's own words (they carry no
            credentials; Settings errors were already funnelled through
            :func:`_load_settings`).
    """
    try:
        entry_above: Decimal | None = None
        if args.entry_above != "always":
            entry_above = parse_decimal(args.entry_above, label="--entry-above")
        exit_below: Decimal | None = None
        if args.exit_below is not None:
            exit_below = parse_decimal(args.exit_below, label="--exit-below")

        strategy = CloseThreshold(
            target_qty=parse_decimal(args.target_qty, label="--target-qty"),
            entry_above=entry_above,
            exit_below=exit_below,
        )
        config = BacktestConfig(
            starting_capital=parse_decimal(args.capital, label="--capital"),
            commission=BpsCommission(
                rate_bps=parse_decimal(args.rate_bps, label="--rate-bps"),
                fixed_fee=parse_decimal(args.fixed_fee, label="--fixed-fee"),
            ),
            slippage=FixedBpsSlippage(bps=parse_decimal(args.slippage_bps, label="--slippage-bps")),
        )

        settings = _load_settings()

        def fresh_risk() -> ConfiguredRiskEvaluator:
            """A new evaluator per run - day-start state never carries over."""
            return ConfiguredRiskEvaluator(settings)

        data = load_backtest_data(Path(args.store), args.dataset, version=args.version)
        risk = fresh_risk()
        result = run_backtest(data, strategy, config, risk=risk)
        manifest = build_manifest(result, config=config, risk=risk)
        metrics = compute_metrics(result)
        coverage = window_coverage(data)
        sensitivity = cost_sensitivity(data, strategy, config, risk_factory=fresh_risk)
    except (BacktestError, RecipeError, TradingGateError, ValueError) as exc:
        raise _CliError(str(exc)) from exc

    out_path = (
        Path(args.out)
        if args.out
        else DEFAULT_REPORT_ROOT / f"backtest-{args.dataset}-{str(manifest['run_id'])[:12]}.md"
    )
    report_text = build_report(
        result,
        manifest=manifest,
        metrics=metrics,
        coverage=coverage,
        sensitivity=sensitivity,
        strategy_note=(
            "The strategy is the harness's reference rule and its parameters "
            "are inputs chosen to make this run possible, not the output of "
            "a parameter search."
        ),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")

    print(f"run id: {manifest['run_id']}")
    print(f"report: {out_path}")
    print(
        f"bars: {len(result.equity_curve)}  filled: {len(result.filled)}  "
        f"ending equity: {result.ending_equity}"
    )
    return 0


def _strategy_command(args: argparse.Namespace) -> int:
    """Run one strategy-promotion command against the records on disk.

    Everything printed was just read from or written to a record:
    stages, references, kinds, who recorded what and why. The gates
    live in :mod:`harsh_quant_os.backtesting.promotion`, so a
    refusal's own words are what reaches stderr.

    Raises:
        _CliError: Any refusal from the workflow or the filesystem,
        with the message the refusal produced.
    """
    root = Path(args.strategies_dir)
    try:
        if args.strategy_command == "register":
            record = promotion.register(
                slug=args.slug,
                hypothesis=args.hypothesis,
                author=args.author,
                at=datetime.now(UTC),
                reference=args.run_id,
                detail=args.run_detail,
            )
            path = promotion.save_record(root, record)
            print(f"registered: {record.slug} -> candidates ({path})")
            return 0

        if args.strategy_command == "evidence":
            record = promotion.load_record(root, args.slug)
            updated = promotion.add_evidence(
                record,
                kind=args.kind,
                reference=args.reference,
                detail=args.detail,
                recorded_by=args.recorded_by,
                at=datetime.now(UTC),
            )
            path = promotion.save_record(root, updated)
            print(f"recorded: {args.kind} on {args.slug} ({path})")
            return 0

        if args.strategy_command == "promote":
            record = promotion.load_record(root, args.slug)
            reason = args.reason or (
                "passed the section 3 gates: held-out, walk-forward, "
                "sensitivity and critique all recorded"
            )
            updated = promotion.promote_to_validated(
                record,
                actor=args.actor,
                reason=reason,
                at=datetime.now(UTC),
            )
            path = promotion.save_record(root, updated)
            print(f"promoted: {args.slug} -> validated ({path})")
            print(
                "note: live consideration is Phase 10 plus human approval; "
                "this workflow reaches validated and stops."
            )
            return 0

        if args.strategy_command == "reject":
            record = promotion.load_record(root, args.slug)
            updated = promotion.reject(
                record,
                actor=args.actor,
                reason=args.reason,
                at=datetime.now(UTC),
            )
            path = promotion.save_record(root, updated)
            print(f"rejected: {args.slug} ({path})")
            print(f"reason kept: {updated.history[-1].reason}")
            return 0

        if args.strategy_command == "archive":
            record = promotion.load_record(root, args.slug)
            updated = promotion.archive(
                record,
                actor=args.actor,
                reason=args.reason,
                at=datetime.now(UTC),
            )
            path = promotion.save_record(root, updated)
            print(f"archived: {args.slug} ({path})")
            print(f"reason kept: {updated.history[-1].reason}")
            return 0

        if args.strategy_command == "show":
            if args.slug:
                records = [promotion.load_record(root, args.slug)]
            else:
                records = list(promotion.iter_records(root))
            if not records:
                print(f"no promotion records under {root}")
                return 0
            for record in records:
                print(f"{record.stage}/{record.slug} - author {record.author}")
                print(f"  hypothesis: {record.hypothesis}")
                for entry in record.evidence:
                    print(
                        f"  evidence: {entry.kind} ({entry.reference}) "
                        f"recorded by {entry.recorded_by} at "
                        f"{entry.recorded_at.isoformat()}"
                    )
                missing = record.missing_for_validated
                if missing:
                    print(f"  missing for validated: {', '.join(missing)}")
                else:
                    print("  missing for validated: none - section 3 kinds all recorded")
                if record.stage == "candidates" and not missing:
                    critique = next(entry for entry in record.evidence if entry.kind == "critique")
                    if critique.recorded_by == record.author:
                        print(
                            f"  critique independence: would refuse - "
                            f"{critique.recorded_by} also authored the candidate"
                        )
                    else:
                        print(
                            "  critique independence: ok - recorded by "
                            f"{critique.recorded_by}, author {record.author}"
                        )
                for move in record.history:
                    print(
                        f"  history: {move.at.isoformat()} "
                        f"{move.from_stage} -> {move.to_stage} "
                        f"by {move.actor}: {move.reason}"
                    )
            return 0
    except (BacktestError, OSError) as exc:
        raise _CliError(str(exc)) from exc

    raise _CliError(f"unknown strategy command: {args.strategy_command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    if args.command == "version":
        print(_version_text())
        return 0

    if args.command == "status":
        print(_status_text(Settings()))
        return 0

    if args.command == "user":
        if args.user_command != "create":
            print(f"Unknown command: user {args.user_command}", file=sys.stderr)
            return 2
        try:
            return _create_user(args)
        except _CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "db":
        if args.db_command not in {"backup", "restore"}:
            print(f"Unknown command: db {args.db_command}", file=sys.stderr)
            return 2
        handler = _backup if args.db_command == "backup" else _restore
        try:
            return handler(args)
        except _CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "data":
        if args.data_command != "ingest":
            print(f"Unknown command: data {args.data_command}", file=sys.stderr)
            return 2
        try:
            return _ingest(args)
        except _CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "backtest":
        if args.backtest_command != "report":
            print(f"Unknown command: backtest {args.backtest_command}", file=sys.stderr)
            return 2
        try:
            return _backtest_report(args)
        except _CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.command == "strategy":
        if args.strategy_command not in {
            "register",
            "evidence",
            "promote",
            "reject",
            "archive",
            "show",
        }:
            print(f"Unknown command: strategy {args.strategy_command}", file=sys.stderr)
            return 2
        try:
            return _strategy_command(args)
        except _CliError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
