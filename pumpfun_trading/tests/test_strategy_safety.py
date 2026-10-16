import json
import time
from unittest.mock import AsyncMock

import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import (
    TradingBotConfig,
    TradingStrategy,
    resolve_strategy_config,
)


@pytest.mark.asyncio
async def test_bot_kill_switches_when_health_stale_or_balance_check_fails():
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        config=resolve_strategy_config(
            "balanced",
            overrides={"health_check_timeout_seconds": 1},
        ),
    )
    bot._health_ok = True
    bot._last_message_at = 0.0
    bot._last_health_check = 0.0

    await bot._update_health_state()
    assert bot._risk_killed is True
    assert bot._health_ok is False

    bot._risk_killed = False
    bot._health_ok = True
    bot.execution = AsyncMock()
    bot.execution.get_balance_sol = AsyncMock(side_effect=RuntimeError("API down"))

    assert await bot._check_account_equity_guard(required_sol=0.1) is False
    assert bot._risk_killed is True
    assert "risk kill: API balance check failed" in bot._last_event


@pytest.mark.asyncio
async def test_bot_resolves_names_and_tracks_position_metadata():
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
    )
    bot._health_ok = True
    bot._risk_killed = False
    bot._last_message_at = time.monotonic()
    bot._last_health_check = time.monotonic()
    bot.dry_run = True

    assert await bot._resolve_token_name("mint", "PumpCoin") == "PumpCoin"
    assert await bot._resolve_token_name("mint", None) is None

    assert await bot._buy_token("mint", 30.0, "PumpCoin") is True
    position = bot.active_positions["mint"]
    assert position["name"] == "PumpCoin"
    assert position["entry_market_cap"] == 30.0
    assert position["current_market_cap"] == 30.0


@pytest.mark.asyncio
async def test_websocket_failure_sets_risk_kill_and_reconnect_status():
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        config=resolve_strategy_config(
            "balanced",
            overrides={"health_check_timeout_seconds": 1},
        ),
    )
    bot._health_ok = True
    bot._risk_killed = False
    bot._last_message_at = time.monotonic() - 10

    await bot._update_health_state()
    assert bot._risk_killed is True
    assert bot._last_status == "health timeout"
    assert "stream stale" in bot._last_event

    # Simulate a websocket reconnect path and ensure the loop still marks health as failed
    bot._risk_killed = False
    bot._health_ok = True
    bot._last_health_check = time.monotonic()
    bot._mark_health_check()
    assert bot._health_ok_for_trading() is True
    bot._last_health_check = 0.0
    assert bot._health_ok_for_trading() is False


def test_trading_bot_audit_log_records_trade_id_and_exit_reason(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        audit_log_path=str(audit_path),
        verbose=False,
    )

    bot._record_trade(
        mint="So11111111111111111111111111111111111111112",
        action="buy",
        entry=0.01,
        reason="entry",
    )
    bot.active_positions["So11111111111111111111111111111111111111112"] = {
        "entry_market_cap": 10.0,
        "current_market_cap": 12.0,
    }
    bot._record_trade(
        mint="So11111111111111111111111111111111111111112",
        action="sell",
        exit_value=0.011,
        reason="take_profit",
        position_id=bot._trade_ledger[0]["position_id"],
        trade_id=f"{bot._trade_ledger[0]['trade_id']}-exit",
    )

    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    records = [json.loads(line) for line in lines]
    trade_records = [record for record in records if record["type"] == "trade"]
    assert len(trade_records) >= 2
    assert trade_records[0]["payload"]["trade_id"]
    assert trade_records[1]["payload"]["reason"] == "take_profit"
    assert (
        trade_records[1]["payload"]["position_id"]
        == trade_records[0]["payload"]["position_id"]
    )


def test_strategy_config_includes_risk_fields():
    config = resolve_strategy_config("balanced")
    assert config.max_total_exposure_sol > 0
    assert config.max_position_size_sol > 0
    assert config.max_loss_per_trade_sol > 0
    assert config.reserve_balance_sol >= 0
    assert config.health_check_timeout_seconds > 0


def test_trading_strategy_should_buy_respects_risk_bounds():
    config = TradingBotConfig(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        max_active_positions=2,
        min_market_cap_sol=5.0,
        max_buy_attempts_per_mint=3,
        min_balance_sol=0.05,
        max_total_exposure_sol=0.2,
        max_position_size_sol=0.05,
        max_loss_per_trade_sol=0.02,
        max_daily_drawdown_pct=0.2,
        reserve_balance_sol=0.1,
        health_check_timeout_seconds=60,
    )
    strategy = TradingStrategy(config)

    assert strategy.should_buy(
        market_cap_sol=15.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert not strategy.should_buy(
        market_cap_sol=3.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )


def test_trading_strategy_summary_has_risk_snapshot():
    strategy = TradingStrategy(resolve_strategy_config("balanced"))
    summary = strategy.summary()
    assert "max_total_exposure_sol" in summary
    assert "reserve_balance_sol" in summary
    assert "health_check_timeout_seconds" in summary


def test_bot_metrics_track_buy_sell_failures_and_latency():
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
    )

    bot._record_metric("buys", 2)
    bot._record_metric("sells", 1)
    bot._record_metric("failures", 3)
    bot._record_metric("retries", 2)
    bot._record_metric("connection_loss", 1)
    bot._record_metric("stale_data", 1)
    bot._record_latency_ms(0.0)

    snapshot = bot._metrics_snapshot()
    assert snapshot["buys"] == 2
    assert snapshot["sells"] == 1
    assert snapshot["failures"] == 3
    assert snapshot["retries"] == 2
    assert snapshot["connection_loss"] == 1
    assert snapshot["stale_data"] == 1
    assert snapshot["latency_ms"]["samples"] >= 1
    assert snapshot["latency_ms"]["avg_ms"] >= 0

    bot._record_trade(
        mint="So11111111111111111111111111111111111111112",
        action="buy",
        entry=0.01,
        reason="entry",
    )
    bot._record_trade(
        mint="So11111111111111111111111111111111111111112",
        action="sell",
        exit_value=0.011,
        reason="take_profit",
    )
    assert bot._metrics_snapshot()["buys"] >= 3
    assert bot._metrics_snapshot()["sells"] >= 2


def test_bot_restores_persisted_state(tmp_path):
    status_path = tmp_path / "status.json"
    status_path.write_text(
        json.dumps(
            {
                "active_positions": {
                    "So11111111111111111111111111111111111111112": {
                        "name": "PersistedCoin",
                        "entry_market_cap": 25.0,
                        "current_market_cap": 27.5,
                    }
                },
                "buy_attempts": {"So11111111111111111111111111111111111111112": 1},
                "seen_mints": {"So11111111111111111111111111111111111111112": 123.0},
                "trade_ledger": [
                    {
                        "action": "buy",
                        "mint": "So11111111111111111111111111111111111111112",
                    }
                ],
                "recent_actions": [
                    {
                        "type": "trade",
                        "payload": {
                            "mint": "So11111111111111111111111111111111111111112"
                        },
                    }
                ],
                "recent_events": ["restored"],
                "state": "holding",
                "health_ok": True,
                "risk_killed": False,
                "stop_requested": False,
                "last_message_at": 12.0,
                "last_event": "restored",
                "last_status": "restored",
                "last_new_token": "So11111111111111111111111111111111111111112",
                "last_new_token_name": "PersistedCoin",
                "trade_sequence": 3,
                "metrics": {
                    "buys": 1,
                    "sells": 0,
                    "failures": 0,
                    "retries": 0,
                    "connection_loss": 0,
                    "stale_data": 0,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        bot_status_path=str(status_path),
    )

    assert (
        bot.active_positions["So11111111111111111111111111111111111111112"]["name"]
        == "PersistedCoin"
    )
    assert (
        bot.active_positions["So11111111111111111111111111111111111111112"][
            "current_market_cap"
        ]
        == 27.5
    )
    assert bot.state == "holding"
    assert bot._trade_sequence >= 3
    assert "restored" in list(bot._recent_events)


@pytest.mark.asyncio
async def test_concurrent_mint_events_do_not_exceed_max_positions():
    import asyncio

    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        config=resolve_strategy_config(
            "balanced", overrides={"max_active_positions": 1}
        ),
    )

    mint1 = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    mint2 = "9xNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"

    class DummyWS:
        async def send(self, *args, **kwargs):
            pass

    ws = DummyWS()
    # Dispatch concurrent new token events
    task1 = asyncio.create_task(
        bot._handle_new_token_event(
            {
                "mint": mint1,
                "marketCapSol": 35.0,
                "name": "Coin1",
                "traderPublicKey": "DevWa11et1111111111111111111111111111111111",
            },
            ws,
        )
    )
    task2 = asyncio.create_task(
        bot._handle_new_token_event(
            {
                "mint": mint2,
                "marketCapSol": 35.0,
                "name": "Coin2",
                "traderPublicKey": "DevWa11et1111111111111111111111111111111111",
            },
            ws,
        )
    )

    await asyncio.gather(task1, task2)
    # Because max_active_positions is 1 and trade lock serializes checks, exactly 1 position is opened
    assert len(bot.active_positions) == 1
