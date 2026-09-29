"""FastAPI application factory.

Everything that wires the service together lives here, in one place, driven by
a single explicit :class:`~harsh_quant_os.config.Settings` instance:

* startup/shutdown behaviour (``lifespan``), including the database pool,
* request context and structured error mapping,
* development CORS restricted to configured origins,
* the system routers, mounted at ``/api/v1`` plus their unversioned aliases,
* the authentication router, mounted at ``/api/v1`` only - authentication is
  an application API, not a probe, so it has no unversioned alias,
* the dataset router, also ``/api/v1`` only - reading a dataset is a
  research operation, not something a load balancer probes.

There is no module-level application object in this module: tests build an app
with their own settings, and ``apps/api/main.py`` owns the process-wide one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from harsh_quant_os.auth import AuthService
from harsh_quant_os.config import Settings
from harsh_quant_os.data import DEFAULT_STORE_ROOT
from harsh_quant_os.db import build_engine, build_session_factory, dispose_engine, ping_database
from harsh_quant_os.safety import assert_live_trading_blocked
from hqos_api.core import configure_logging, install_error_handlers, install_request_context
from hqos_api.routers import create_auth_router, create_datasets_router, create_system_router
from hqos_api.services import service_name

logger = logging.getLogger(__name__)

# Deny-by-default: only the verbs this service actually serves may be
# pre-flighted, and only the headers the web client sends are allowed.
# POST is present because authentication is state-changing - without it the
# browser could never preflight a login.
_CORS_METHODS = ["GET", "POST", "HEAD", "OPTIONS"]
_CORS_HEADERS = ["Accept", "Content-Type", "X-Request-ID"]

_DESCRIPTION = (
    "Private quantitative trading research platform. It serves system status, "
    "session authentication against PostgreSQL, and a read-only view of the "
    "market datasets that have been ingested - their provenance, their quality "
    "status and the bars stored on disk, each response tagged with the dataset "
    "version it came from. No orders and no trading: live trading is disabled "
    "at configuration load."
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

    # Built here rather than inside the lifespan so that an application object
    # created by a test can answer `/ready` through the same single code path
    # the process uses. `create_async_engine` performs no I/O: it parses the
    # URL and allocates a pool, so an unreachable database cannot stop the
    # process from starting - it shows up as `failed` on `/ready`, which is
    # the honest report.
    engine = build_engine(resolved.database_url)
    session_factory = build_session_factory(engine)
    auth_service = AuthService(
        session_factory=session_factory,
        secret_key=resolved.auth_secret_key,
        session_ttl=timedelta(minutes=resolved.auth_token_expiry_minutes),
    )

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
        try:
            yield
        finally:
            # Always release the pool, including when shutdown follows an
            # error: a leaked pool keeps connections open and holds the
            # database open long after the process is gone.
            await dispose_engine(engine)
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
    app.state.database_engine = engine
    app.state.session_factory = session_factory
    app.state.auth_service = auth_service
    # Where dataset artefacts are read from. Pinned here rather than read
    # from settings because it is workspace state that follows the
    # process's working directory, not configuration; a test points one
    # application at a store of its own by replacing this attribute.
    app.state.store_root = DEFAULT_STORE_ROOT
    # One ping, built once from this engine, so readiness and the dependency
    # graph can never disagree about which database they mean.
    app.state.database_ping = partial(ping_database, engine)

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

    # Versioned only: authentication is part of the application API, and
    # probes such as Docker or a load balancer have no business logging in.
    app.include_router(create_auth_router(resolved), prefix="/api/v1")

    # Versioned only for the same reason: reading a dataset is a research
    # operation, not a liveness probe, so it gets exactly one spelling.
    app.include_router(create_datasets_router(resolved), prefix="/api/v1")

    return app


__all__ = ["create_app"]
