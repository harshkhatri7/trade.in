"""Command line entry point (``hqos``).

Only reports real state - it never claims success it did not observe.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
from collections.abc import Sequence

from harsh_quant_os.config import Settings
from harsh_quant_os.safety import resolve_trading_mode
from harsh_quant_os.version import DISPLAY_VERSION, PROJECT_NAME, __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hqos",
        description=f"{PROJECT_NAME} command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Print the project version.")
    subparsers.add_parser("status", help="Print the real environment and safety status.")
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    if args.command == "version":
        print(_version_text())
        return 0

    if args.command == "status":
        print(_status_text(Settings()))
        return 0

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
