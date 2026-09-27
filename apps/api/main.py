"""ASGI entry point for the HARSH QUANT OS API.

Two ways to run it, both driven by the same ``Settings``:

    uvicorn --app-dir apps/api main:app        # import-string target
    python apps/api/main.py [--reload]         # reads host/port from config

The module-level ``app`` is the ASGI target used by uvicorn, gunicorn-style
runners and the integration tests. Configuration is loaded once, here; every
other module receives the settings object explicitly.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from harsh_quant_os.config import Settings, SettingsError
from hqos_api.factory import create_app

try:
    app = create_app()
except SettingsError as exc:
    # Configuration problems are the operator's to fix; fail before serving.
    raise SystemExit(f"configuration error: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Run the API with uvicorn on the configured host and port."""
    parser = argparse.ArgumentParser(prog="hqos-api", description=__doc__)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="restart on code change (development only)",
    )
    args = parser.parse_args(argv)

    settings: Settings = app.state.settings

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=args.reload,
        app_dir=str(Path(__file__).resolve().parent),
        # The application configures logging in create_app(); uvicorn only
        # supplies the server, not the format.
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
