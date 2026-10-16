"""Unit tests for ``bot/health.py``."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from pumpfun_trading.bot.health import (
    health_ok_for_trading,
    mark_health_check,
    update_health_state,
)


@pytest.mark.regression("BUG-46")
def test_health_checks():
    bot = MagicMock()
    bot._stop_requested = False
    bot._risk_killed = False
    bot._health_ok = True
    bot._last_health_check = time.monotonic()
    bot.config = MagicMock()
    bot.config.health_check_timeout_seconds = 10.0

    # Healthy state
    assert health_ok_for_trading(bot)

    # Stop requested
    bot._stop_requested = True
    assert not health_ok_for_trading(bot)
    bot._stop_requested = False

    # Risk killed
    bot._risk_killed = True
    assert not health_ok_for_trading(bot)
    bot._risk_killed = False

    # Not health ok
    bot._health_ok = False
    assert not health_ok_for_trading(bot)
    bot._health_ok = True

    # Timeout
    bot._last_health_check = time.monotonic() - 20.0
    assert not health_ok_for_trading(bot)
    # BUG-46: a health timeout pauses trading but never latches the kill switch.
    assert bot._risk_killed is False
    assert bot._health_ok is False

    # mark_health_check
    mark_health_check(bot)
    assert bot._health_ok is True

    # update_health_state when stop requested
    bot._stop_requested = True
    update_health_state(bot)
    bot._stop_requested = False

    # update_health_state when stale
    bot._last_message_at = time.monotonic() - 30.0
    bot._health_ok = True
    update_health_state(bot)
    assert bot._health_ok is False
    assert bot._risk_killed is False

    # update_health_state when fresh: trading resumes automatically
    bot._last_message_at = time.monotonic()
    update_health_state(bot)
    assert bot._health_ok is True
    assert health_ok_for_trading(bot)
