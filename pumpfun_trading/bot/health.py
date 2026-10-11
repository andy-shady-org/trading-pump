"""Health checks and health-state transitions for the live bot runtime."""

from __future__ import annotations

import time
from typing import Any


def health_ok_for_trading(bot: Any) -> bool:
    if bot._stop_requested or bot._risk_killed:
        return False
    if not bot._health_ok:
        return False
    if (
        time.monotonic() - bot._last_health_check
        > bot.config.health_check_timeout_seconds
    ):
        bot._last_status = "health timeout"
        bot._health_ok = False
        bot._risk_killed = True
        bot._last_event = "risk kill: health timeout"
        return False
    return True


def mark_health_check(bot: Any) -> None:
    bot._last_health_check = time.monotonic()
    bot._health_ok = True


def update_health_state(bot: Any) -> None:
    if bot._stop_requested:
        return
    if (
        time.monotonic() - bot._last_message_at
        > bot.config.health_check_timeout_seconds
    ):
        if bot._health_ok:
            bot._health_ok = False
            bot._risk_killed = True
            bot._last_status = "health timeout"
            bot._last_event = "risk kill: websocket stale"
    else:
        mark_health_check(bot)
