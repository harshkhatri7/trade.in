"""Structured error responses.

Every failure that crosses the HTTP boundary is an RFC 7807 problem document
(``application/problem+json``) with ``type``, ``title``, ``status`` and
``detail`` - the convention fixed in docs/architecture/backend.md section 4.

Three handlers are enough for a two-endpoint service: request validation, a
mapped HTTP failure (404/405/...), and one catch-all that logs the stack trace
internally and returns a generic 500. No exception hierarchy is invented until
there is more than health and readiness to fail.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

logger = logging.getLogger(__name__)

_TITLE_BY_STATUS: Mapping[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

_UNHANDLED_DETAIL = (
    "An unexpected error occurred. The details were logged server-side; "
    "internal information is never returned to a client."
)


def problem_response(
    *,
    status: int,
    title: str,
    detail: str,
    instance: str,
    errors: Sequence[Mapping[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build one problem+json payload."""
    payload: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    if errors is not None:
        payload["errors"] = list(errors)
    return JSONResponse(
        content=payload,
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Field-level messages without echoing the submitted values.

    Pydantic attaches the offending ``input`` to every error; a client could
    have posted a token there, so only location, message and type survive.
    """
    errors: list[dict[str, Any]] = []
    for error in exc.errors():
        location = error.get("loc", ())
        errors.append(
            {
                "loc": [str(part) for part in location],
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
        )
    return errors


def install_error_handlers(app: FastAPI) -> None:
    """Register the problem+json handlers on ``app``."""

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        return problem_response(
            status=422,
            title="Request validation failed",
            detail="One or more fields in the request failed validation.",
            instance=request.url.path,
            errors=_safe_validation_errors(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return problem_response(
            status=exc.status_code,
            title=_TITLE_BY_STATUS.get(exc.status_code, "HTTP error"),
            detail=detail,
            instance=request.url.path,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> Response:
        request_id = getattr(request.state, "request_id", "")
        logger.exception(
            "api.unhandled request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        return problem_response(
            status=500,
            title="Internal Server Error",
            detail=_UNHANDLED_DETAIL,
            instance=request.url.path,
        )
