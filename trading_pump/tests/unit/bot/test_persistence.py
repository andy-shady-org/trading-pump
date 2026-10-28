"""Unit tests for ``bot/persistence.py``."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from trading_pump.bot.persistence import StatusPersistenceManager


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


def test_persistence_manager_error_handling(tmp_path):
    # Test open failure on invalid audit log path
    invalid_audit_path = str(tmp_path / "not_a_dir" / "audit.jsonl")
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        pm_fail = StatusPersistenceManager(audit_log_path=invalid_audit_path)
        assert pm_fail._audit_handle is None
        # write_audit_record when opening fails
        pm_fail.write_audit_record("test", "STATE", {"data": 1})
        pm_fail.close()

    # Status write exception
    status_file = tmp_path / "status.json"
    pm = StatusPersistenceManager(bot_status_path=str(status_file))
    with patch("os.replace", side_effect=OSError("Replace error")):
        assert pm.write_status_snapshot({"state": "TEST"}) is False

    # Status load non-dict JSON
    status_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert pm.load_status_snapshot() is None

    # Status load corrupt JSON
    status_file.write_text("invalid json {{{", encoding="utf-8")
    assert pm.load_status_snapshot() is None

    # Audit write exception
    audit_file = tmp_path / "valid_audit.jsonl"
    pm_audit = StatusPersistenceManager(audit_log_path=str(audit_file))
    mock_handle = MagicMock()
    mock_handle.write.side_effect = OSError("Disk write failed")
    pm_audit._audit_handle = mock_handle
    pm_audit.write_audit_record("trade", "BUY", {"amount": 1})
    pm_audit.close()
