"""Structured logging helpers for production bot operations."""

from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
import re
import shutil
import sys
from typing import Any

from rich.console import Console

from pumpfun_trading.config.env import sanitize_env_for_logging

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def gzip_rotator(source: str, dest: str) -> None:
    """Compress rotated log file to destination gzip archive and remove original."""
    with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    try:
        os.remove(source)
    except OSError:
        pass


def gzip_namer(default_name: str) -> str:
    """Append .gz suffix to rotated log file name if not present."""
    if not default_name.endswith(".gz"):
        return default_name + ".gz"
    return default_name


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
    defaults: dict[str, Any] = {
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
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    rotation_type: str = "size",
    compress: bool = True,
    when: str = "midnight",
    interval: int = 1,
    utc: bool = True,
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

        norm_rotation = (rotation_type or "size").strip().lower()
        file_handler: logging.Handler
        if norm_rotation == "size" and max_bytes > 0:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            if compress:
                file_handler.rotator = gzip_rotator  # type: ignore[assignment]
                file_handler.namer = gzip_namer  # type: ignore[assignment]
        elif norm_rotation == "time":
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_file,
                when=when,
                interval=interval,
                backupCount=backup_count,
                utc=utc,
                encoding="utf-8",
            )
            if compress:
                file_handler.rotator = gzip_rotator  # type: ignore[assignment]
                file_handler.namer = gzip_namer  # type: ignore[assignment]
        else:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

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
    "gzip_namer",
    "gzip_rotator",
    "is_color_enabled",
    "log_runtime_event",
    "setup_structured_logging",
    "strip_ansi",
]
