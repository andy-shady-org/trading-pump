from __future__ import annotations

import time
from unittest.mock import MagicMock

from rich.console import Console

from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.storage.status import (
    build_status_snapshot,
    safe_read_status_snapshot,
    write_status_snapshot,
)
from pumpfun_trading.ui.dashboard import build_dashboard


def test_ui_dashboard_rendering():
    # Setup mock bot
    config = TradingBotConfig(
        strategy_preset="balanced",
        buy_amount_sol=0.05,
        take_profit=1.5,
        stop_loss=0.85,
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.2,
        max_loss_per_trade_sol=0.05,
        max_daily_drawdown_pct=0.15,
        reserve_balance_sol=0.1,
        health_check_timeout_seconds=30.0,
    )
    bot = MagicMock()
    bot.config = config
    bot.max_active_positions = 3
    bot.min_market_cap_sol = 20.0
    bot.dry_run = False
    bot.paper_trade = False
    bot._risk_killed = False
    bot.state = TradingBotState.HOLDING
    bot._health_ok = True
    bot._last_event = "token buy confirmed"
    bot._last_status = "monitoring active tokens"
    bot._last_message_at = time.monotonic() - 5.0
    bot.stream_url = "wss://pumpportal.fun/api/data"
    bot.audit_log_path = "audit.jsonl"
    bot._last_new_token_name = "SuperCoin"
    bot._last_health_check = time.monotonic() - 2.0
    bot._stop_requested = False

    # Positions with positive and negative performance
    bot.active_positions = {
        "MintPos1111111111111111111111111111111": {
            "name": "Winning Token",
            "entry_market_cap": 25.0,
            "current_market_cap": 37.5,
            "token_amount": 1000000,
            "buy_timestamp": time.time() - 60,
        },
        "MintPos2222222222222222222222222222222": {
            "name": "Losing Token",
            "entry_market_cap": 30.0,
            "current_market_cap": 24.0,
            "token_amount": 500000,
            "buy_timestamp": time.time() - 120,
        },
    }

    bot._recent_actions = ["buy Winning Token", "sell Old Token"]
    bot._recent_events = ["new token Mint1", "tx confirmed"]
    bot._trade_ledger = [
        {
            "timestamp": time.time() - 300,
            "mint": "MintOld",
            "action": "sell",
            "entry": 0.05,
            "reason": "take_profit",
        }
    ]
    bot._metrics = {
        "buys": 5,
        "sells": 4,
        "retries": 1,
        "connection_losses": 0,
        "failures": {},
    }

    panel = build_dashboard(bot)
    assert panel is not None

    console = Console(file=None, record=True)
    console.print(panel)

    # Test dashboard with empty positions & degraded health
    bot.active_positions = {}
    bot._last_message_at = None
    bot._health_ok = False
    bot._risk_killed = True
    bot._stop_requested = True
    bot.dry_run = True

    panel_empty = build_dashboard(bot)
    console.print(panel_empty)

    # Test live console with alternate screen rendering
    from rich.live import Live

    with Live(
        panel,
        console=console,
        refresh_per_second=2,
        transient=True,
        screen=False,
    ) as live:
        live.update(panel_empty, refresh=True)


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
