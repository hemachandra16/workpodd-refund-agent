"""Structured logging setup (structlog).

JSON in production, pretty console output in development. Logs intentionally
avoid raw PII — payment tokens are redacted at the data layer before they ever
reach a log line. This module only shapes the transport.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(environment: str = "development") -> None:
    renderer: object
    if environment == "production":
        renderer = __import__("structlog").processors.JSONRenderer()
        log_level = logging.INFO
    else:
        renderer = __import__("structlog").dev.ConsoleRenderer(colors=False)
        log_level = logging.DEBUG

    structlog = __import__("structlog")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
