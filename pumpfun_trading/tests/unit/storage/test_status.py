"""Unit tests for ``storage/status.py``."""

from __future__ import annotations

from unittest.mock import MagicMock

from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.storage.status import (
    build_status_snapshot,
    safe_read_status_snapshot,
    write_status_snapshot,
)


def test_storage_status_helpers(tmp_path):
    status_file = tmp_path / "subdir" / "status.json"

    # Write snapshot
    payload = {"state": "monitoring", "positions": 2}
    write_status_snapshot(str(status_file), payload)
    assert status_file.exists()

    # Write snapshot with empty path (no-op)
    write_status_snapshot(None, payload)

    # Safe read
    read_data = safe_read_status_snapshot(str(status_file))
    assert read_data == payload

    # Safe read non-existent
    assert safe_read_status_snapshot(str(tmp_path / "missing.json")) is None
    assert safe_read_status_snapshot(None) is None

    # Safe read corrupted
    bad_file = tmp_path / "corrupt.json"
    bad_file.write_text("{bad json", encoding="utf-8")
    assert safe_read_status_snapshot(str(bad_file)) is None

    # Safe read non-dict
    array_file = tmp_path / "array.json"
    array_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert safe_read_status_snapshot(str(array_file)) is None


def test_build_status_snapshot():
    bot = MagicMock()
    bot.state = TradingBotState.HOLDING
    bot.get_status_snapshot.return_value = {"active_positions": {"Mint1": {}}}
    bot._buy_attempts = {"Mint1": 1}
    bot._seen_mints = {"Mint1": 100.0}
    bot._trade_ledger = [{"mint": "Mint1"}]
    bot._recent_actions = ["action1"]
    bot._recent_events = ["event1"]
    bot._metrics_snapshot.return_value = {"buys": 1}
    bot._health_ok = True
    bot._risk_killed = False
    bot._last_event = "event"
    bot._last_status = "status"
    bot._last_message_at = 1000.0
    bot._last_new_token = "Mint1"
    bot._last_new_token_name = "Token1"
    bot._stop_requested = False
    bot._trade_sequence = 1
    bot._exit_retry_queue = {}
    bot._circuit_breaker_tripped = False
    bot._ws_consecutive_failures = 0

    snapshot = build_status_snapshot(bot)
    assert snapshot["state"] == "holding"
    assert "timestamp" in snapshot
    assert snapshot["active_positions"] == {"Mint1": {}}
    assert snapshot["trade_sequence"] == 1
