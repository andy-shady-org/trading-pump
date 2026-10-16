"""Integration tests for live bot Yellowstone Geyser stream order flow momentum triggers."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import (
    TokenScreeningVerdict,
    TradingBotConfig,
)
from pumpfun_trading.streams.geyser import TradeEventUpdate

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"
SAMPLE_MINT = "So11111111111111111111111111111111111111112"
MOMENTUM_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.fixture
def bot(tmp_path):
    config = TradingBotConfig(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=5.0,
        enable_momentum_signals=True,
        momentum_window_seconds=30,
        momentum_min_buy_ratio=3.0,
        momentum_min_z_score=2.0,
        momentum_min_unique_buyers=3,
        momentum_min_net_inflow_sol=0.5,
        momentum_baseline_window_seconds=300,
        enable_anti_rug_filters=False,
        dry_run=True,
    )
    return TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


async def test_geyser_trade_event_momentum_buy_trigger(bot):
    base_time = 1000.0

    # Ingest baseline trades into OrderFlowEngine for MOMENTUM_MINT
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        bot.order_flow_engine.record_trade(
            mint=MOMENTUM_MINT,
            is_buy=True,
            sol_amount=0.05,
            user=f"OldUser{slice_idx}",
            timestamp=t,
        )

    # Ingest sudden burst of 4 trades via _handle_trade_event_update from distinct buyers
    for i in range(4):
        event = TradeEventUpdate(
            mint=MOMENTUM_MINT,
            sol_amount_lamports=int(1.0 * 1_000_000_000),
            token_amount=1_000_000,
            is_buy=True,
            user=f"BurstBuyer{i}",
            timestamp=int(base_time - 5 + i),
            virtual_sol_reserves=35_000_000_000,
            virtual_token_reserves=1_000_000_000_000_000,
            real_sol_reserves=5_000_000_000,
            real_token_reserves=700_000_000_000_000,
            received_at=base_time - 5 + i,
        )
        await bot._handle_trade_event_update(event)

    # Bot should have detected momentum breakout and bought the token
    assert MOMENTUM_MINT in bot.active_positions
    pos = bot.active_positions[MOMENTUM_MINT]
    assert pos["entry_reason"] == "momentum_spike"
    assert bot._last_new_token == MOMENTUM_MINT

    # Check status snapshot
    snapshot = bot.get_status_snapshot()
    assert snapshot["enable_momentum_signals"] is True
    assert snapshot["order_flow_tracked_tokens"] >= 1


async def test_momentum_buy_suppressed_when_active_positions_full(bot):
    bot.config = TradingBotConfig(
        max_active_positions=1,
        enable_momentum_signals=True,
        momentum_min_z_score=1.5,
        momentum_min_unique_buyers=2,
        momentum_min_net_inflow_sol=0.2,
        dry_run=True,
    )
    bot.max_active_positions = 1
    # Occupy the active position
    bot.active_positions[SAMPLE_MINT] = {
        "name": "ExistingHolding",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }

    base_time = 1000.0
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        bot.order_flow_engine.record_trade(
            mint=MOMENTUM_MINT,
            is_buy=True,
            sol_amount=0.05,
            user=f"OldUser{slice_idx}",
            timestamp=t,
        )

    for i in range(5):
        event = TradeEventUpdate(
            mint=MOMENTUM_MINT,
            sol_amount_lamports=int(1.0 * 1_000_000_000),
            token_amount=1_000_000,
            is_buy=True,
            user=f"Buyer{i}",
            timestamp=int(base_time - 5 + i),
            virtual_sol_reserves=35_000_000_000,
            virtual_token_reserves=1_000_000_000_000_000,
            real_sol_reserves=5_000_000_000,
            real_token_reserves=700_000_000_000_000,
            received_at=base_time - 5 + i,
        )
        await bot._handle_trade_event_update(event)

    # Should not buy MOMENTUM_MINT because max_active_positions is reached
    assert MOMENTUM_MINT not in bot.active_positions


async def test_momentum_buy_screen_rejected_when_anti_rug_fails(bot):
    # Enable anti-rug filters
    bot.config = TradingBotConfig(
        enable_momentum_signals=True,
        enable_anti_rug_filters=True,
        momentum_min_z_score=1.5,
        momentum_min_unique_buyers=2,
        momentum_min_net_inflow_sol=0.2,
        dry_run=True,
    )

    base_time = 1000.0
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        bot.order_flow_engine.record_trade(
            mint=MOMENTUM_MINT,
            is_buy=True,
            sol_amount=0.05,
            user=f"OldUser{slice_idx}",
            timestamp=t,
        )

    # Mock screening to fail
    failed_verdict = TokenScreeningVerdict(
        mint=MOMENTUM_MINT,
        passed=False,
        risk_score=85.0,
        reasons=["Dev launched > 5 tokens in 24h"],
    )

    with patch.object(
        bot, "_enrich_and_screen_token", new_callable=AsyncMock
    ) as mock_screen:
        mock_screen.return_value = failed_verdict

        for i in range(4):
            event = TradeEventUpdate(
                mint=MOMENTUM_MINT,
                sol_amount_lamports=int(1.0 * 1_000_000_000),
                token_amount=1_000_000,
                is_buy=True,
                user=f"Buyer{i}",
                timestamp=int(base_time - 5 + i),
                virtual_sol_reserves=35_000_000_000,
                virtual_token_reserves=1_000_000_000_000_000,
                real_sol_reserves=5_000_000_000,
                real_token_reserves=700_000_000_000_000,
                received_at=base_time - 5 + i,
            )
            await bot._handle_trade_event_update(event)

    assert MOMENTUM_MINT not in bot.active_positions
    assert "screen_rejected" in bot._last_event


async def test_active_position_exits_on_trade_event_update(bot):
    # Setup holding position with non-tiered exit
    bot.config = TradingBotConfig(
        take_profit=1.5,
        stop_loss=0.85,
        enable_tiered_take_profit=False,
        enable_trailing_stop=False,
        dry_run=True,
    )
    bot.strategy = bot.strategy.__class__(bot.config)
    bot.active_positions[SAMPLE_MINT] = {
        "name": "HeldToken",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "token_amount": 1000,
    }

    # Trade event with price hitting take profit (46.0 SOL >= 30.0 * 1.5)
    event = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=int(0.5 * 1_000_000_000),
        token_amount=500_000,
        is_buy=True,
        user="ExitTrader",
        timestamp=int(time.time()),
        virtual_sol_reserves=46_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=16_000_000_000,
        real_token_reserves=600_000_000_000_000,
        received_at=time.time(),
    )
    await bot._handle_trade_event_update(event)

    # Position should have exited on take profit
    assert SAMPLE_MINT not in bot.active_positions


async def test_websocket_trade_update_records_in_engine(bot):
    trade_data = {
        "mint": SAMPLE_MINT,
        "txType": "buy",
        "solAmount": 1.25,
        "user": "WSTrader",
        "timestamp": 123456.0,
        "marketCapSol": 25.0,
    }
    await bot._handle_trade_update(trade_data)
    metrics = bot.order_flow_engine.get_metrics(
        SAMPLE_MINT, window_seconds=30, current_time=123460.0
    )
    assert metrics.trade_count == 1
    assert metrics.buy_volume_sol == 1.25
