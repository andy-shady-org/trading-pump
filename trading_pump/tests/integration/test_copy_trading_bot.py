"""Integration tests for live bot Yellowstone Geyser stream and WebSocket copy-trading."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from trading_pump.bot.run import TradingBot
from trading_pump.bot.strategy import (
    TokenScreeningVerdict,
)
from trading_pump.streams.geyser import TradeEventUpdate
from trading_pump.tests.support.constants import SAMPLE_PRIVATE_KEY
from trading_pump.tests.support.factories import make_config
from trading_pump.tests.support.fakes import FakeCurves

SAMPLE_MINT = "So11111111111111111111111111111111111111112"
COPY_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SMART_WALLET_1 = "SmartWhale111111111111111111111111111111111"
SMART_WALLET_2 = "AlphaTrader22222222222222222222222222222222"


@pytest.fixture
def bot(tmp_path):
    config = make_config(
        buy_amount_sol=0.02,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=5.0,
        enable_copy_trading=True,
        copy_trading_wallets=(
            {
                "address": SMART_WALLET_1,
                "label": "WhaleAlpha",
                "win_rate": 0.75,
                "risk_score": 15.0,
                "reference_bankroll_sol": 10.0,
                "max_allocation_sol": 0.04,
                "enabled": True,
            },
            {
                "address": SMART_WALLET_2,
                "label": "AlphaTrader",
                "win_rate": 0.65,
                "risk_score": 25.0,
                "reference_bankroll_sol": 20.0,
                "max_allocation_sol": 0.05,
                "enabled": True,
            },
        ),
        copy_trading_sizing_mode="proportional",
        copy_trading_scale_factor=1.0,
        copy_trading_min_wallet_win_rate=0.60,
        copy_trading_max_wallet_risk_score=40.0,
        copy_trading_mirror_sells=True,
        copy_trading_require_anti_rug_screen=False,
        dry_run=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    # Paper buys read the curve (BUG-145).
    FakeCurves().install(bot)
    return bot


async def test_geyser_trade_event_copy_trade_buy_trigger(bot):
    """Verify smart money buy event in Geyser stream triggers copy-trade buy."""
    now = time.time()
    event = TradeEventUpdate(
        mint=COPY_MINT,
        sol_amount_lamports=int(
            5.0 * 1_000_000_000
        ),  # 5 SOL trade by WhaleAlpha (50% of 10 SOL bankroll)
        token_amount=1_000_000,
        is_buy=True,
        user=SMART_WALLET_1,
        timestamp=int(now),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=700_000_000_000_000,
        received_at=now,
    )

    await bot._handle_trade_event_update(event)

    # Bot should have bought the token
    assert COPY_MINT in bot.active_positions
    pos = bot.active_positions[COPY_MINT]
    assert pos["entry_reason"] == "copy_trade_WhaleAlpha"
    assert bot._last_new_token == COPY_MINT

    # Verify telemetry snapshot
    snapshot = bot.get_status_snapshot()
    assert snapshot["enable_copy_trading"] is True
    assert snapshot["copy_trading_tracked_wallets"] == 2


async def test_geyser_trade_event_smart_money_sell_mirror(bot):
    """Verify smart money sell event on held position triggers mirrored sell exit."""
    # Setup open position
    bot.active_positions[COPY_MINT] = {
        "name": "HeldToken",
        "entry_market_cap": 30.0,
        "current_market_cap": 35.0,
        "peak_market_cap": 35.0,
        "initial_token_amount": 100_000_000,
        "remaining_token_amount": 100_000_000,
        "token_amount": 100_000_000,
        "dry_run": True,
    }

    now = time.time()
    event = TradeEventUpdate(
        mint=COPY_MINT,
        sol_amount_lamports=int(10.0 * 1_000_000_000),
        token_amount=1_000_000,
        is_buy=False,  # Sell event by smart money
        user=SMART_WALLET_1,
        timestamp=int(now),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=700_000_000_000_000,
        received_at=now,
    )

    await bot._handle_trade_event_update(event)

    # Position should have been liquidated
    assert COPY_MINT not in bot.active_positions


async def test_websocket_trade_update_copy_trade_buy_and_sell(bot):
    """Verify WebSocket _handle_trade_update triggers copy buy and mirrored sell."""
    now = time.time()

    # Buy event via websocket payload
    data_buy = {
        "mint": COPY_MINT,
        "txType": "buy",
        "solAmount": 5.0,
        "user": SMART_WALLET_2,
        "marketCapSol": 35.0,
        "name": "AlphaMeme",
        "timestamp": now,
    }

    await bot._handle_trade_update(data_buy)
    assert COPY_MINT in bot.active_positions
    assert bot.active_positions[COPY_MINT]["entry_reason"] == "copy_trade_AlphaTrader"

    # Sell event via websocket payload
    data_sell = {
        "mint": COPY_MINT,
        "txType": "sell",
        "solAmount": 5.0,
        "user": SMART_WALLET_2,
        "marketCapSol": 40.0,
        "timestamp": now + 10,
    }

    await bot._handle_trade_update(data_sell)
    assert COPY_MINT not in bot.active_positions


async def test_copy_trade_buy_rejected_by_anti_rug_screening(bot):
    """Verify copy-trade buy is blocked when anti-rug screening fails."""
    bot.config = make_config(
        buy_amount_sol=0.02,
        enable_copy_trading=True,
        copy_trading_wallets=(
            {
                "address": SMART_WALLET_1,
                "label": "WhaleAlpha",
                "win_rate": 0.75,
                "risk_score": 15.0,
                "enabled": True,
            },
        ),
        copy_trading_require_anti_rug_screen=True,
        dry_run=True,
    )
    bot.copy_trade_engine.registry.register_wallets(
        list(bot.config.copy_trading_wallets)
    )

    # Mock screening to return failure
    mock_verdict = TokenScreeningVerdict(
        mint=COPY_MINT,
        passed=False,
        risk_score=75.0,
        reasons=["High creator allocation: 25%"],
    )

    with patch.object(
        bot,
        "_enrich_and_screen_token",
        new_callable=AsyncMock,
        return_value=mock_verdict,
    ):
        now = time.time()
        event = TradeEventUpdate(
            mint=COPY_MINT,
            sol_amount_lamports=int(2.0 * 1_000_000_000),
            token_amount=1_000_000,
            is_buy=True,
            user=SMART_WALLET_1,
            timestamp=int(now),
            virtual_sol_reserves=35_000_000_000,
            virtual_token_reserves=1_000_000_000_000_000,
            real_sol_reserves=5_000_000_000,
            real_token_reserves=700_000_000_000_000,
            received_at=now,
        )
        await bot._handle_trade_event_update(event)

    # Token should NOT be bought
    assert COPY_MINT not in bot.active_positions


async def test_untracked_wallet_does_not_trigger_copy_trade(bot):
    """Verify regular non-tracked user trades do not trigger copy trading."""
    now = time.time()
    event = TradeEventUpdate(
        mint=COPY_MINT,
        sol_amount_lamports=int(2.0 * 1_000_000_000),
        token_amount=1_000_000,
        is_buy=True,
        user="RandomUntrackedUser123456789",
        timestamp=int(now),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=700_000_000_000_000,
        received_at=now,
    )

    await bot._handle_trade_event_update(event)
    assert COPY_MINT not in bot.active_positions
