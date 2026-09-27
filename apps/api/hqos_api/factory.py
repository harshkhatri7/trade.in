"""FastAPI application factory.

Everything that wires the service together lives here, in one place, driven by
a single explicit :class:`~harsh_quant_os.config.Settings` instance:

* startup/shutdown behaviour (``lifespan``),
* request context and structured error mapping,
* development CORS restricted to configured origins,
* the system routers, mounted at ``/api/v1`` plus their unversioned aliases.

There is no module-level application object in this module: tests build an app
with their own settings, and ``apps/api/main.py`` owns the process-wide one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from harsh_quant_os.config import Settings
from harsh_quant_os.safety import assert_live_trading_blocked
from hqos_api.core import configure_logging, install_error_handlers, install_request_context
from hqos_api.routers import create_system_router
from hqos_api.services import service_name

logger = logging.getLogger(__name__)

# Deny-by-default: only the verbs this service actually serves may be
# pre-flighted, and only the headers the web client sends are allowed.
_CORS_METHODS = ["GET", "HEAD", "OPTIONS"]
_CORS_HEADERS = ["Accept", "Content-Type", "X-Request-ID"]

_DESCRIPTION = (
    "Private quantitative trading research platform. Phase 1 exposes "
    "liveness and readiness only: no market data, no orders, no trading, "
    "and no database dependency yet."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Raises :class:`~harsh_quant_os.config.SettingsError` when configuration is
    invalid and :class:`~harsh_quant_os.safety.LiveTradingBlockedError` at
    startup when live trading is enabled - both fail closed, before a single
    request is served.
    """
    resolved = settings if settings is not None else Settings.load()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Defence in depth: Settings already rejects LIVE_TRADING_ENABLED at
        # load time, so this can only trip if a caller bypassed validation.
        assert_live_trading_blocked(resolved)
        logger.info(
            "api.startup service=%s version=%s environment=%s",
            service_name(resolved),
            resolved.app_version,
            resolved.app_env,
        )
        yield
        logger.info("api.shutdown service=%s", service_name(resolved))

    app = FastAPI(
        title=f"{resolved.project_name} API",
        description=_DESCRIPTION,
        version=resolved.app_version,
        lifespan=lifespan,
        # Interactive documentation is a development aid, not a production page.
        docs_url="/docs" if not resolved.is_production else None,
        redoc_url="/redoc" if not resolved.is_production else None,
        openapi_url="/openapi.json" if not resolved.is_production else None,
    )
    # App-scoped configuration for introspection and for code that runs
    # outside the dependency graph (the CLI entry point, diagnostics).
    app.state.settings = resolved

    install_request_context(app)
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        # Origins come from API_ALLOWED_ORIGINS. Settings rejects a wildcard
        # outside development/test, so this list is never '*' in production.
        allow_origins=resolved.allowed_origins,
        allow_credentials=True,
        allow_methods=_CORS_METHODS,
        allow_headers=_CORS_HEADERS,
    )

    system_router = create_system_router(resolved)
    app.include_router(system_router, prefix="/api/v1")
    app.include_router(system_router)

    return app


__all__ = ["create_app"]
