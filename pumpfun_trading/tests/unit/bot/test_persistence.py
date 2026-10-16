"""Unit tests for ``bot/persistence.py``."""

from __future__ import annotations

import json
import os
import tempfile

from pumpfun_trading.bot.persistence import StatusPersistenceManager


def test_status_persistence_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_path = os.path.join(tmpdir, "bot_status.json")
        audit_path = os.path.join(tmpdir, "audit.jsonl")

        pm = StatusPersistenceManager(
            bot_status_path=status_path,
            audit_log_path=audit_path,
        )

        snapshot_data = {
            "state": "RUNNING",
            "active_positions": {"Mint1": {"name": "SolCat", "entry_market_cap": 30.0}},
        }

        success = pm.write_status_snapshot(snapshot_data)
        assert success
        assert os.path.exists(status_path)

        loaded = pm.load_status_snapshot()
        assert loaded is not None
        assert loaded["state"] == "RUNNING"
        assert "Mint1" in loaded["active_positions"]

        pm.write_audit_record("test_event", "RUNNING", {"msg": "hello"})
        pm.close()

        with open(audit_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
            assert len(lines) == 1
            assert lines[0]["type"] == "test_event"
            assert lines[0]["payload"]["msg"] == "hello"


def test_status_persistence_manager_missing_files():
    pm = StatusPersistenceManager(bot_status_path=None, audit_log_path=None)
    assert not pm.write_status_snapshot({"test": 1})
    assert pm.load_status_snapshot() is None
    pm.write_audit_record("test", "IDLE", {})
    pm.close()
