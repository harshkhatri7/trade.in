"""Request context: correlation id, timing and one log line per request.

Kept deliberately small. Two endpoints do not justify a logging framework:
every request gets an id (accepted from the caller or generated), the id is
echoed back in ``X-Request-ID`` and attached to the log line, and the status
and duration are logged exactly once.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def install_request_context(app: FastAPI) -> None:
    """Attach ``request.state.request_id``, the response header and the log line."""

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming.strip() or uuid4().hex
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "api.request request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
