"""Status snapshot helpers for persisted bot state."""

from __future__ import annotations

import json
import os
import time
from typing import Any


def write_status_snapshot(path: str | None, payload: dict[str, Any]) -> None:
    """Write a JSON snapshot for bot state recovery."""
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")


def safe_read_status_snapshot(path: str | None) -> dict[str, Any] | None:
    """Read a persisted status snapshot without failing the bot startup."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
    except (OSError, TypeError, ValueError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


def build_status_snapshot(bot: Any) -> dict[str, Any]:
    """Build a status snapshot for the runtime so it can be persisted independently."""
    return {
        "timestamp": time.time(),
        "state": getattr(bot.state, "value", str(bot.state)),
        "active_positions": bot.get_status_snapshot().get("active_positions", {}),
        "buy_attempts": dict(getattr(bot, "_buy_attempts", {})),
        "seen_mints": dict(getattr(bot, "_seen_mints", {})),
        "trade_ledger": list(getattr(bot, "_trade_ledger", [])),
        "recent_actions": list(getattr(bot, "_recent_actions", [])),
        "recent_events": list(getattr(bot, "_recent_events", [])),
        "metrics": bot._metrics_snapshot(),
        "health_ok": getattr(bot, "_health_ok", True),
        "risk_killed": getattr(bot, "_risk_killed", False),
        "last_event": getattr(bot, "_last_event", ""),
        "last_status": getattr(bot, "_last_status", ""),
        "last_message_at": getattr(bot, "_last_message_at", 0.0),
        "last_new_token": getattr(bot, "_last_new_token", "-"),
        "last_new_token_name": getattr(bot, "_last_new_token_name", "-"),
        "stop_requested": getattr(bot, "_stop_requested", False),
        "trade_sequence": getattr(bot, "_trade_sequence", 0),
        "exit_retry_queue": dict(getattr(bot, "_exit_retry_queue", {})),
        "circuit_breaker_tripped": getattr(bot, "_circuit_breaker_tripped", False),
        "circuit_breaker_engaged": (
            getattr(
                getattr(bot, "daily_equity_tracker", None),
                "circuit_breaker_engaged",
                False,
            )
        ),
        "daily_equity": (
            bot.daily_equity_tracker.to_dict()
            if hasattr(bot, "daily_equity_tracker")
            and hasattr(bot.daily_equity_tracker, "to_dict")
            else {}
        ),
        "stream_consecutive_failures": getattr(
            bot,
            "_stream_consecutive_failures",
            getattr(bot, "_ws_consecutive_failures", 0),
        ),
        "ws_consecutive_failures": getattr(bot, "_ws_consecutive_failures", 0),
    }


__all__ = [
    "build_status_snapshot",
    "safe_read_status_snapshot",
    "write_status_snapshot",
]
