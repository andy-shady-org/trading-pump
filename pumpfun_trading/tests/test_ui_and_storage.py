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

    console = Console(width=200, file=None, record=True)
    console.print(panel)
    output = console.export_text()
    assert "Entry MC" in output
    assert "Current MC" in output
    assert "Cost / Spend" in output
    assert "Token Amount" in output
    assert "Unit Token Price" in output
    assert "Perf / PnL" in output
    assert "Open Positions" in output
    assert "+50.00%" in output
    assert "-20.00%" in output
    assert "1.00M" in output
    assert "500.00K" in output

    # Test dashboard with empty positions & degraded health
    bot.active_positions = {}
    bot._last_message_at = None
    bot._health_ok = False
    bot._risk_killed = True
    bot._stop_requested = True
    bot.dry_run = True

    panel_empty = build_dashboard(bot)
    console.print(panel_empty)
    output_empty = console.export_text()
    assert "No active positions." in output_empty


def test_ui_dashboard_table_formatting_and_pnl():
    from pumpfun_trading.ui.dashboard import format_compact_tokens

    # Verify compact token formatting helper
    assert format_compact_tokens(0) == "0"
    assert format_compact_tokens(4) == "4"
    assert format_compact_tokens(500) == "500"
    assert format_compact_tokens(1500) == "1.50K"
    assert format_compact_tokens(500_000) == "500.00K"
    assert format_compact_tokens(2_380_952) == "2.38M"
    assert format_compact_tokens(357_653_812) == "357.65M"
    assert format_compact_tokens(1_000_000_000) == "1.00B"
    assert format_compact_tokens(2_500_000_000) == "2.50B"

    config = TradingBotConfig(buy_amount_sol=0.1)
    bot = MagicMock()
    bot.config = config
    bot.max_active_positions = 4
    bot.min_market_cap_sol = 20.0
    bot.dry_run = False
    bot.paper_trade = False
    bot._risk_killed = False
    bot.state = TradingBotState.HOLDING
    bot._health_ok = True
    bot._last_event = "trade event"
    bot._last_status = "idle"
    bot._last_message_at = time.monotonic()
    bot.stream_url = "wss://pumpportal.fun/api/data"
    bot.geyser_endpoint = None
    bot.audit_log_path = "audit.jsonl"
    bot._last_new_token_name = "AlphaCoin"
    bot._last_health_check = time.monotonic() - 2.0
    bot._stop_requested = False
    bot._observed_tokens_count = 10
    bot._seen_mints = {}
    bot._metrics_snapshot.return_value = {
        "buys": 1,
        "sells": 1,
        "failures": 0,
        "retries": 0,
        "connection_loss": 0,
        "stale_data": 0,
        "latency_ms": {
            "avg_ms": 1.2,
            "samples": 1,
            "last_ms": 1.2,
            "max_ms": 1.2,
            "total_ms": 1.2,
        },
    }

    # Test break-even (0.00%), drop (-10.00%), profit (+50.00%), micro-SOL pricing
    bot.active_positions = {
        "TokenMint1111111111111111111111111111": {
            "name": "AlphaCoin",
            "entry_market_cap": 30.0,
            "current_market_cap": 45.0,
            "buy_price": 0.000042,
            "cost_sol": 0.1,
            "token_amount": 2_380_952,
        },
        "TokenMint2222222222222222222222222222": {
            "name": "BetaCoin",
            "entry_market_cap": 50.0,
            "current_market_cap": 50.0,
            "entry_price": 0.05,
            "cost_sol": 0.2,
            "token_amount": 4,
        },
        "TokenMint3333333333333333333333333333": {
            "name": "GammaCoin",
            "entry_market_cap": 30.0,
            "current_market_cap": 27.0,  # 10% drop
            "cost_sol": 0.01,
            "token_amount": 357_653,
        },
    }
    bot._recent_actions = []
    bot._recent_events = []
    bot._trade_ledger = [
        {
            "action": "buy",
            "mint": "TokenMint1111111111111111111111111111",
            "buy_price": 0.000042,
            "reason": "entry",
        },
        {
            "action": "sell",
            "mint": "TokenMint2222222222222222222222222222",
            "sell_price": 0.08,
            "reason": "take_profit",
        },
    ]

    panel = build_dashboard(bot)
    console = Console(width=200, file=None, record=True)
    console.print(panel)
    output = console.export_text()

    assert "Entry MC" in output
    assert "Current MC" in output
    assert "Cost / Spend" in output
    assert "Token Amount" in output
    assert "Unit Token Price" in output
    assert "Perf / PnL" in output
    # Micro-SOL units
    assert "42.0000 µSOL" in output
    assert "50000.0000 µSOL" in output
    assert "0.0280 µSOL" in output
    # Compact suffixes
    assert "2.38M" in output
    assert "357.65K" in output
    assert "4" in output
    # PnL percentages
    assert "+50.00%" in output
    assert "0.00%" in output
    assert "-10.00%" in output
    # Trade ledger
    assert "BUY TokenMin @ 0.0000 SOL | entry" in output or "BUY TokenMin" in output
    assert "SELL TokenMin -> 0.0800 SOL | take_profit" in output


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


def test_bot_event_recording_and_dashboard_display(tmp_path):
    from pumpfun_trading.bot.run import TradingBot

    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        bot_status_path=str(tmp_path / "status.json"),
    )

    # Initial state should be recorded or updated
    bot._record_event("test event message", alert=False)
    assert any("test event message" in ev for ev in bot._recent_events)

    # State transition records event
    bot._transition_to(TradingBotState.MONITORING, reason="test_start")
    assert any("monitoring" in ev for ev in bot._recent_events)

    # Trade recording records BUY event
    bot._record_trade(
        mint="Mint11111111111111111111111111111111111111111",
        action="buy",
        token_name="TestToken",
        entry=0.01,
        reason="momentum",
    )
    assert any("BUY Mint1111" in ev for ev in bot._recent_events)

    # Dashboard should contain the events
    panel = build_dashboard(bot)
    console = Console(file=None, record=True)
    console.print(panel)
    output = console.export_text()
    assert "BUY Mint1111" in output
    assert "monitoring" in output
    assert "•" in output
