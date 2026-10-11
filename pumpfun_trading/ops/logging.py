"""Structured logging helpers for production bot operations."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from rich.console import Console

from pumpfun_trading.config.env import sanitize_env_for_logging

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    if not isinstance(text, str):
        return str(text)
    return ANSI_ESCAPE_RE.sub("", text)


def is_color_enabled(stream: Any = None) -> bool:
    """Return True if colored output is allowed according to NO_COLOR and TTY status."""
    if os.getenv("NO_COLOR", "").strip() != "":
        return False
    target = stream or sys.stdout
    if hasattr(target, "isatty") and not target.isatty():
        return False
    return True


def get_configured_console(file: Any = None, **kwargs: Any) -> Console:
    """Return a Rich Console instance configured for NO_COLOR and TTY conditions."""
    target = file or sys.stdout
    color_enabled = is_color_enabled(target)
    defaults = {
        "file": target,
        "no_color": not color_enabled,
        "highlight": color_enabled,
    }
    defaults.update(kwargs)
    return Console(**defaults)


class AnsiStrippingFormatter(logging.Formatter):
    """Log formatter that removes ANSI escape sequences for file and non-TTY outputs."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return strip_ansi(formatted)


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

    formatter = AnsiStrippingFormatter(
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


__all__ = [
    "AnsiStrippingFormatter",
    "get_configured_console",
    "is_color_enabled",
    "log_runtime_event",
    "setup_structured_logging",
    "strip_ansi",
]
