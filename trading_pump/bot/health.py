"""Health checks and health-state transitions for the live bot runtime."""

from __future__ import annotations

import time
from typing import Any

HEALTH_TIMEOUT_STATUS = "health timeout"
RECOVERED_STATUS = "monitoring active tokens"


def health_ok_for_trading(bot: Any) -> bool:
    if bot._stop_requested or bot._risk_killed:
        return False
    if not bot._health_ok:
        return False
    if (
        time.monotonic() - bot._last_health_check
        > bot.config.health_check_timeout_seconds
    ):
        # Transient: blocks entries until the next healthy check, but does not
        # latch the risk kill switch (BUG-46).
        bot._last_status = HEALTH_TIMEOUT_STATUS
        bot._health_ok = False
        bot._last_event = "trading paused: health timeout"
        if hasattr(bot, "_record_event"):
            bot._record_event("trading paused: health timeout", alert=True)
        return False
    return True


def mark_health_check(bot: Any) -> None:
    """A healthy pass: trading may go on, and a timeout label is cleared.

    The label used to stay "health timeout" after the stream recovered, so
    the dashboard showed a pause that had ended hours before (BUG-155).
    """
    was_ok = bool(getattr(bot, "_health_ok", True))
    bot._last_health_check = time.monotonic()
    bot._health_ok = True
    if getattr(bot, "_last_status", None) == HEALTH_TIMEOUT_STATUS:
        bot._last_status = RECOVERED_STATUS
        if not was_ok:
            bot._last_event = "trading resumed: stream active"
            if hasattr(bot, "_record_event"):
                bot._record_event("trading resumed: stream active", alert=False)


def update_health_state(bot: Any) -> None:
    if bot._stop_requested:
        return
    if (
        time.monotonic() - bot._last_message_at
        > bot.config.health_check_timeout_seconds
    ):
        if bot._health_ok:
            bot._health_ok = False
            bot._last_status = HEALTH_TIMEOUT_STATUS
            bot._last_event = "trading paused: stream stale"
            if hasattr(bot, "_record_event"):
                bot._record_event("trading paused: stream stale", alert=True)
    else:
        mark_health_check(bot)
