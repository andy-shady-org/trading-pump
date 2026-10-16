"""Regression tests for persistence, cache bounds, risk gate and env aliases (Batch 5)."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pumpfun_trading.bot.persistence import StatusPersistenceManager, atomic_write_json
from pumpfun_trading.config.env import get_runtime_env
from pumpfun_trading.storage.status import build_status_snapshot, write_status_snapshot
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.filters import ScreeningCache, TokenScreeningVerdict
from pumpfun_trading.strategies.graduation import GraduationEngine
from pumpfun_trading.strategies.momentum import OrderFlowEngine
from pumpfun_trading.strategies.risk_validation import validate_risk_limits


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


def test_storage_snapshot_omits_monotonic_clock():
    """BUG-72: `_last_message_at` is a monotonic value and is not persisted."""
    bot = SimpleNamespace(
        state="idle",
        get_status_snapshot=lambda: {"active_positions": {}},
        _metrics_snapshot=lambda: {},
        _last_message_at=12345.0,
    )
    assert "last_message_at" not in build_status_snapshot(bot)


def test_screening_cache_is_bounded():
    """BUG-77: the screening cache evicts the oldest entry at capacity."""
    cache = ScreeningCache(default_ttl=60.0, max_entries=2)
    verdict = TokenScreeningVerdict(mint="m", passed=True, risk_score=0.0)
    for mint in ("a", "b", "c"):
        cache.set(mint, verdict)
    assert cache.size() == 2
    assert cache.get("a") is None and cache.get("c") is verdict
    cache.set("d", verdict, ttl=-1.0)
    cache.set("e", verdict)
    assert cache.size() == 2


def test_order_flow_and_graduation_engines_are_bounded():
    """BUG-77: trackers are capped by least-recent activity."""
    flow = OrderFlowEngine(max_tracked_tokens=2)
    flow.record_trade("a", True, 0.1, "u", timestamp=1.0)
    flow.record_trade("b", True, 0.1, "u", timestamp=3.0)
    flow.record_trade("c", True, 0.1, "u", timestamp=2.0)
    assert flow.tracked_token_count == 2
    assert "a" not in flow._trackers

    grad = GraduationEngine(max_tracked_candidates=2)
    grad.update_bonding_curve("a", "c1", 1.0, 31.0, 30.0, timestamp=1.0)
    grad.update_bonding_curve("b", "c2", 1.0, 31.0, 30.0, timestamp=3.0)
    grad.update_bonding_curve("c", "c3", 1.0, 31.0, 30.0, timestamp=2.0)
    assert grad.tracked_candidate_count == 2
    assert grad.get_candidate("a") is None


def test_validate_risk_limits_applies_capital_caps():
    """BUG-78: exposure, position-size and concentration caps are enforced."""
    config = TradingBotConfig(
        buy_amount_sol=0.05,
        max_active_positions=10,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.1,
        max_token_concentration_pct=0.5,
    )
    assert validate_risk_limits(config, current_positions={}, proposed_entry_sol=0.05)
    assert not validate_risk_limits(
        config, current_positions={}, proposed_entry_sol=0.2
    )
    full = {f"m{i}": {"cost_sol": 0.05} for i in range(5)}
    assert not validate_risk_limits(
        config, current_positions=full, proposed_entry_sol=0.05
    )
    partial = {
        "m": {
            "cost_sol": 0.2,
            "initial_token_amount": 100,
            "remaining_token_amount": 50,
        }
    }
    assert validate_risk_limits(
        config, current_positions=partial, proposed_entry_sol=0.05
    )
    concentrated = TradingBotConfig(
        buy_amount_sol=0.05,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.2,
        max_token_concentration_pct=0.3,
    )
    assert not validate_risk_limits(
        concentrated, current_positions={}, proposed_entry_sol=0.1
    )


def test_status_and_audit_env_aliases(monkeypatch, tmp_path):
    """BUG-87: primary names and aliases resolve in env and the bot."""
    for name in (
        "PUMPFUN_STATUS_PATH",
        "PUMPFUN_AUDIT_LOG_PATH",
        "PUMPFUN_BOT_STATUS_PATH",
        "PUMPFUN_AUDIT_LOG",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", str(tmp_path / "s.json"))
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", str(tmp_path / "a.jsonl"))
    env = get_runtime_env()
    assert env["PUMPFUN_STATUS_PATH"] == str(tmp_path / "s.json")
    assert env["PUMPFUN_AUDIT_LOG_PATH"] == str(tmp_path / "a.jsonl")

    from pumpfun_trading.bot.run import TradingBot

    bot = TradingBot(
        private_key_b58="1" * 64,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(dry_run=True),
    )
    assert bot.bot_status_path == str(tmp_path / "s.json")
    assert bot.audit_log_path == str(tmp_path / "a.jsonl")

    monkeypatch.setenv("PUMPFUN_STATUS_PATH", str(tmp_path / "p.json"))
    assert get_runtime_env()["PUMPFUN_STATUS_PATH"] == str(tmp_path / "p.json")
