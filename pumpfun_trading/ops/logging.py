"""Structured logging helpers for production bot operations."""

from __future__ import annotations

import logging
import os
from typing import Any

from pumpfun_trading.config.env import sanitize_env_for_logging


def setup_structured_logging(
    *,
    logger_name: str = "pumpfun_trading",
    log_level: int = logging.INFO,
    log_file: str | None = None,
    console: bool = False,
) -> logging.Logger:
    """Configure a consistent logger with JSON-like text fields and safe metadata."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    if log_file:
        directory = os.path.dirname(log_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.info(
        "logger_initialized",
        extra={
            "event": "logger_initialized",
            "runtime_env": sanitize_env_for_logging(),
        },
    )
    return logger


def log_runtime_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **context: Any,
) -> None:
    """Emit structured log events with context keys rather than opaque message strings."""
    payload = {"event": event, **context}
    logger.log(level, "event=%s payload=%s", event, payload)


__all__ = ["setup_structured_logging", "log_runtime_event"]
