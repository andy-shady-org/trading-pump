"""Unit tests for ``storage/status.py``."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.persistence import StatusPersistenceManager, atomic_write_json
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


@pytest.mark.regression("BUG-72", "BUG-94")
def test_storage_write_is_atomic_and_cleans_temp_on_failure(tmp_path):
    """BUG-72/94: writes go through a temp file that never lingers."""
    path = tmp_path / "sub" / "status.json"
    write_status_snapshot(str(path), {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}

    with patch("pumpfun_trading.bot.persistence.os.replace", side_effect=OSError):
        with pytest.raises(OSError):
            atomic_write_json(str(path), {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}
    assert os.listdir(path.parent) == ["status.json"]

    manager = StatusPersistenceManager(bot_status_path=str(path))
    with patch("pumpfun_trading.bot.persistence.json.dump", side_effect=TypeError):
        assert manager.write_status_snapshot({"bad": 1}) is False
    assert os.listdir(path.parent) == ["status.json"]


@pytest.mark.regression("BUG-72")
def test_storage_snapshot_omits_monotonic_clock():
    """BUG-72: `_last_message_at` is a monotonic value and is not persisted."""
    bot = SimpleNamespace(
        state="idle",
        get_status_snapshot=lambda: {"active_positions": {}},
        _metrics_snapshot=lambda: {},
        _last_message_at=12345.0,
    )
    assert "last_message_at" not in build_status_snapshot(bot)
