"""Comprehensive integration and coverage tests for Yellowstone Geyser bot runtime."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TokenScreeningVerdict, TradingBotConfig
from pumpfun_trading.execution.executor import ExecutionResult
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"
SAMPLE_MINT = "So11111111111111111111111111111111111111112"
SAMPLE_MINT_2 = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.fixture
def bot(tmp_path):
    config = TradingBotConfig(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=10.0,
        enable_tiered_take_profit=False,
        enable_trailing_stop=False,
        dry_run=True,
    )
    return TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


async def test_bonding_curve_state_update_active_position_tp_and_sl(bot):
    # Setup active position
    bot.active_positions[SAMPLE_MINT] = {
        "name": "TestToken",
        "token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }

    # 1. Normal update
    update_normal = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=100,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=33_000_000_000,
        real_token_reserves=700_000_000_000_000,
        real_sol_reserves=3_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.000033,
        market_cap_sol=33.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_normal)
    assert bot.active_positions[SAMPLE_MINT]["current_market_cap"] == 33.0

    # 2. Take profit hit (46 SOL >= 30 * 1.5)
    update_tp = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=101,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=46_000_000_000,
        real_token_reserves=600_000_000_000_000,
        real_sol_reserves=16_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.000046,
        market_cap_sol=46.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_tp)
    assert SAMPLE_MINT not in bot.active_positions

    # 3. Stop loss hit (20 SOL <= 30 * 0.85)
    bot.active_positions[SAMPLE_MINT] = {
        "name": "TestToken2",
        "token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    update_sl = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=102,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=20_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00002,
        market_cap_sol=20.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_sl)
    assert SAMPLE_MINT not in bot.active_positions


async def test_bonding_curve_state_update_new_token_branches(bot):
    # Screening is covered in unit/bot/test_enrichment.py; keep this test off the
    # live Pump.fun API and RPC (it used to pass only when mainnet answered).
    passing = TokenScreeningVerdict(mint=SAMPLE_MINT_2, passed=True, risk_score=0.0)
    screen = patch.object(
        bot.enricher, "enrich_and_screen", AsyncMock(return_value=passing)
    )
    screen.start()
    # 1. New eligible token
    update_new = BondingCurveStateUpdate(
        mint=SAMPLE_MINT_2,
        bonding_curve_pubkey="Curve2",
        slot=200,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_new)
    assert SAMPLE_MINT_2 in bot.active_positions

    # 2. Already seen token is skipped
    await bot._handle_bonding_curve_state_update(update_new)

    # 3. Low market cap token is skipped
    bot.active_positions.clear()
    update_low_mc = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=201,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=5_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.000005,
        market_cap_sol=5.0,  # Below min_market_cap_sol=10.0
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_low_mc)
    assert SAMPLE_MINT not in bot.active_positions

    # 4. Stop requested ignores update
    bot._stop_requested = True
    await bot._handle_bonding_curve_state_update(update_new)
    bot._stop_requested = False
    screen.stop()


async def test_trade_event_update_branches(bot):
    # 1. Non-active position ignored
    trade_ignored = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=10_000_000,
        is_buy=True,
        user="User1",
        timestamp=1728600000,
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=800_000_000_000_000,
    )
    await bot._handle_trade_event_update(trade_ignored)

    # 2. Active position with trade update
    bot.active_positions[SAMPLE_MINT] = {
        "name": "TokenTrade",
        "token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    trade_active = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=2_000_000_000,
        token_amount=20_000_000,
        is_buy=True,
        user="User1",
        timestamp=1728600000,
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=900_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=700_000_000_000_000,
    )
    await bot._handle_trade_event_update(trade_active)
    assert bot.active_positions[SAMPLE_MINT]["current_market_cap"] > 30.0

    # 3. Active position triggering take profit on trade
    trade_tp = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=15_000_000_000,
        token_amount=100_000_000,
        is_buy=True,
        user="Whale",
        timestamp=1728600000,
        virtual_sol_reserves=60_000_000_000,
        virtual_token_reserves=500_000_000_000_000,
        real_sol_reserves=30_000_000_000,
        real_token_reserves=300_000_000_000_000,
    )
    await bot._handle_trade_event_update(trade_tp)
    assert SAMPLE_MINT not in bot.active_positions

    # 4. Active position triggering stop loss on sell trade
    bot.active_positions[SAMPLE_MINT] = {
        "name": "TokenTrade2",
        "token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    trade_sl = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=10_000_000_000,
        token_amount=200_000_000,
        is_buy=False,
        user="Dumper",
        timestamp=1728600000,
        virtual_sol_reserves=15_000_000_000,
        virtual_token_reserves=1_500_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=800_000_000_000_000,
    )
    await bot._handle_trade_event_update(trade_sl)
    assert SAMPLE_MINT not in bot.active_positions

    # 5. Zero virtual token reserves returns 0 market cap
    bot.active_positions[SAMPLE_MINT] = {
        "name": "TokenZero",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    trade_zero = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=10_000_000,
        is_buy=True,
        user="UserZero",
        timestamp=1728600000,
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=0,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    await bot._handle_trade_event_update(trade_zero)

    # 6. Stop requested ignored
    bot._stop_requested = True
    await bot._handle_trade_event_update(trade_active)
    bot._stop_requested = False


async def test_complete_event_update_branches(bot):
    # 1. Non-active token complete event ignored
    complete_update = CompleteEventUpdate(
        mint=SAMPLE_MINT,
        user="User1",
        bonding_curve="Curve1",
        timestamp=1728600000,
    )
    await bot._handle_complete_event_update(complete_update)

    # 2. Active token complete event marks the position migrating (BUG-44):
    # the completed curve rejects sells, so the exit waits for the AMM pool.
    bot.active_positions[SAMPLE_MINT] = {
        "name": "GraduatingToken",
        "entry_market_cap": 30.0,
        "current_market_cap": 85.0,
    }
    await bot._handle_complete_event_update(complete_update)
    assert SAMPLE_MINT in bot.active_positions
    assert SAMPLE_MINT in bot._migrating_mints
    assert await bot._sell_token(SAMPLE_MINT, reason="retry") is False

    # The Raydium pool for a held mint is attached and the exit goes via the AMM.
    pool_keys = RaydiumPoolKeys(
        amm_id="Amm111",
        amm_authority="Auth111",
        amm_open_orders="Open111",
        amm_target_orders="Target111",
        pool_coin_token_account="CoinVault111",
        pool_pc_token_account="PcVault111",
        serum_program_id="Serum111",
        serum_market="Market111",
        serum_bids="Bids111",
        serum_asks="Asks111",
        serum_event_queue="Events111",
        serum_coin_vault="SerumCoin111",
        serum_pc_vault="SerumPc111",
        serum_vault_signer="Signer111",
        coin_mint=SAMPLE_MINT,
        pc_mint="So11111111111111111111111111111111111111112",
        lp_mint="LpMint111",
    )
    raydium_sell = AsyncMock(wraps=bot.executor.execute_raydium_sell)
    bot.executor.execute_raydium_sell = raydium_sell
    await bot._handle_raydium_pool_update(pool_keys)
    raydium_sell.assert_awaited_once()
    assert SAMPLE_MINT not in bot.active_positions

    # 3. Stop requested ignored
    bot._stop_requested = True
    bot.active_positions[SAMPLE_MINT] = {"name": "GraduatingToken"}
    await bot._handle_complete_event_update(complete_update)
    assert SAMPLE_MINT in bot.active_positions
    bot._stop_requested = False


async def test_bot_full_geyser_streaming_lifecycle(bot):
    update_new = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=500,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    update_trade = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=5_000_000_000,
        token_amount=50_000_000,
        is_buy=True,
        user="Buyer",
        timestamp=int(time.time()),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=900_000_000_000_000,
        real_sol_reserves=5_000_000_000,
        real_token_reserves=700_000_000_000_000,
    )
    update_complete = CompleteEventUpdate(
        mint=SAMPLE_MINT,
        user="Migrator",
        bonding_curve="Curve1",
        timestamp=int(time.time()),
    )

    events = [
        update_new,
        update_trade,
        update_complete,
    ]

    async def mock_listen():
        for e in events:
            yield e
        bot.request_shutdown()

    bot.geyser_client.listen = mock_listen
    await bot.start()

    # The completed curve leaves any held position waiting for the AMM (BUG-44).
    assert SAMPLE_MINT not in bot.active_positions or (
        SAMPLE_MINT in bot._migrating_mints
    )
    assert bot.state == TradingBotState.SHUTDOWN
    await bot.close()


async def test_geyser_tiered_and_trailing_exits(tmp_path):
    config = TradingBotConfig(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=10.0,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.50,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.50,
        trailing_stop_drop_pct=0.15,
        dry_run=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    bot.active_positions[SAMPLE_MINT] = {
        "name": "Moonshot",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "peak_market_cap": 30.0,
        "initial_token_amount": 100_000_000,
        "remaining_token_amount": 100_000_000,
        "token_amount": 100_000_000,
        "dry_run": True,
    }

    # 1. Update below tier 1 (e.g. 1.8x -> 54 SOL MC)
    update_18x = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=100,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=54_000_000_000,
        real_token_reserves=500_000_000_000_000,
        real_sol_reserves=24_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.000054,
        market_cap_sol=54.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_18x)
    assert SAMPLE_MINT in bot.active_positions
    assert bot.active_positions[SAMPLE_MINT]["remaining_token_amount"] == 100_000_000

    # 2. Update at Tier 1 (2.0x -> 60 SOL MC): sells 50%
    update_tier1 = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=101,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=60_000_000_000,
        real_token_reserves=400_000_000_000_000,
        real_sol_reserves=30_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00006,
        market_cap_sol=60.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_tier1)
    assert SAMPLE_MINT in bot.active_positions
    assert bot.active_positions[SAMPLE_MINT]["remaining_token_amount"] == 50_000_000
    assert bot.active_positions[SAMPLE_MINT]["tier_1_executed"] is True

    # 3. Update at Tier 2 (3.5x -> 105 SOL MC): sells 25%
    update_tier2 = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=102,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=105_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=75_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.000105,
        market_cap_sol=105.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_tier2)
    assert SAMPLE_MINT in bot.active_positions
    assert bot.active_positions[SAMPLE_MINT]["remaining_token_amount"] == 25_000_000
    assert bot.active_positions[SAMPLE_MINT]["tier_2_executed"] is True
    assert bot.active_positions[SAMPLE_MINT]["moonbag_active"] is True

    # 4. Trailing drop from peak (drop > 15% from 105 -> 80 SOL MC): exits moonbag
    update_drop = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="Curve1",
        slot=103,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=80_000_000_000,
        real_token_reserves=300_000_000_000_000,
        real_sol_reserves=50_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00008,
        market_cap_sol=80.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(update_drop)
    assert SAMPLE_MINT not in bot.active_positions


async def test_websocket_stream_dispatch_when_stream_url_configured(tmp_path):
    config = TradingBotConfig(
        stream_url="wss://pumpportal.fun/api/data",
        paper_trade=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    ws_stream_called = False

    async def fake_websocket_stream():
        nonlocal ws_stream_called
        ws_stream_called = True
        bot.request_shutdown()

    bot._run_websocket_stream = fake_websocket_stream
    await bot.start()

    assert ws_stream_called is True
    assert bot.state == TradingBotState.SHUTDOWN
    await bot.close()


async def test_concurrent_sells_same_mint_send_one_order(bot):
    """BUG-41: overlapping exits for one mint are serialized; only one sell is sent."""
    bot.active_positions[SAMPLE_MINT] = {
        "name": "RaceToken",
        "token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    calls = 0

    async def slow_sell(**kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return ExecutionResult(
            success=True, mint=SAMPLE_MINT, is_buy=False, amount_sol=0.01
        )

    bot.executor.execute_sell = slow_sell
    results = await asyncio.gather(
        bot._sell_token(SAMPLE_MINT, reason="a"),
        bot._sell_token(SAMPLE_MINT, reason="b"),
    )
    assert calls == 1
    assert results.count(True) == 1
    assert SAMPLE_MINT not in bot.active_positions


async def test_health_loop_drains_exit_retry_queue(bot, monkeypatch):
    """BUG-39: the runtime health loop processes the exit retry queue."""
    drained = asyncio.Event()

    async def fake_process(websocket=None):
        drained.set()
        bot._stop_requested = True

    async def fast_sleep(_seconds):
        return None

    bot._process_exit_retry_queue = fake_process
    monkeypatch.setattr("pumpfun_trading.bot.run.asyncio.sleep", fast_sleep)
    await asyncio.wait_for(bot._run_health_loop(), timeout=5)
    assert drained.is_set()


def test_exit_retry_queue_persisted_without_monotonic_times(bot):
    """BUG-39: the snapshot keeps the queue, minus process-local clock values."""
    bot._enqueue_exit_retry(SAMPLE_MINT, reason="sell_exec_failed")
    entry = bot.get_status_snapshot()["exit_retry_queue"][SAMPLE_MINT]
    assert entry["reason"] == "sell_exec_failed"
    assert "next_retry_at" not in entry


async def test_geyser_events_routed_once(bot):
    """BUG-40: start() consumes listen() only and does not also register callbacks."""
    bot.geyser_client.on_bonding_curve = AsyncMock()
    bot.geyser_client.on_trade = AsyncMock()
    bot.geyser_client.on_complete = AsyncMock()

    async def mock_listen():
        yield CompleteEventUpdate(
            mint=SAMPLE_MINT_2, user="U", bonding_curve="C", timestamp=1
        )
        bot.request_shutdown()

    routed = AsyncMock()
    bot.event_router.route_geyser_complete_update = routed
    bot.geyser_client.listen = mock_listen
    await bot.start()
    routed.assert_awaited_once()
    bot.geyser_client.on_complete.assert_not_called()
    await bot.close()
