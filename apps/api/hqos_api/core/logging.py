"""Logging configuration for the API.

``LOG_LEVEL`` is configuration, not code (see docs/architecture/backend.md).
Only levels and formats are set here; no configuration *value* is ever written
to a log line, so credentials and tokens cannot leak through logging.
"""

from __future__ import annotations

import logging

from harsh_quant_os.config import Settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

# Request lines are logged once by the request-context middleware; leaving
# uvicorn's own access log at WARNING avoids printing every request twice.
_QUIET_LOGGERS = {"uvicorn.access": logging.WARNING}


def configure_logging(settings: Settings) -> None:
    """Apply ``LOG_LEVEL`` to the root logger and the uvicorn loggers.

    Safe to call more than once: handlers are only added when the root logger
    has none, and levels are simply re-applied.
    """
    level = logging.getLevelNamesMapping().get(settings.log_level, logging.INFO)

    logging.basicConfig(level=level, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)

    for name, logger_level in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(logger_level)

    # Uvicorn's own handlers are disabled (``log_config=None``) so that every
    # line in the process uses the root format configured above.
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
