"""Unit tests for ``ops/monitoring.py``."""

from __future__ import annotations

from pumpfun_trading.ops.logging import setup_structured_logging
from pumpfun_trading.ops.monitoring import build_runtime_summary, runtime_is_healthy


def test_structured_logging_and_runtime_summary():
    logger = setup_structured_logging(
        logger_name="pumpfun_trading.test", log_file=None, console=False
    )
    assert logger.name == "pumpfun_trading.test"

    class DummyBot:
        state = type("S", (), {"value": "monitoring"})()
        _health_ok = True
        _risk_killed = False
        _stop_requested = False
        active_positions = {"a": {}, "b": {}}
        _buy_attempts = {"a": 2}

        def _metrics_snapshot(self):
            return {"buys": 1, "sells": 0}

        _last_event = "ready"
        _last_status = "monitoring"

    bot = DummyBot()
    summary = build_runtime_summary(bot)
    assert summary["active_positions"] == 2
    assert runtime_is_healthy(bot) is True
