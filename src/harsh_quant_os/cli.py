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
import sys
from collections.abc import Sequence
from datetime import timedelta

from harsh_quant_os.auth import AuthService
from harsh_quant_os.auth.errors import DatabaseUnavailable, DuplicateUser, PasswordPolicyError
from harsh_quant_os.config import Settings, SettingsError
from harsh_quant_os.db import build_engine, build_session_factory, dispose_engine
from harsh_quant_os.db.models import User
from harsh_quant_os.safety import resolve_trading_mode
from harsh_quant_os.version import DISPLAY_VERSION, PROJECT_NAME, __version__


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


def _create_user(args: argparse.Namespace) -> int:
    """Create one account and report only what was observed being created."""
    settings = _load_settings()

    if settings.is_placeholder("database_password"):
        raise _CliError(
            "DATABASE_PASSWORD still holds a placeholder value; run `npm run env:provision` first"
        )

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

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
