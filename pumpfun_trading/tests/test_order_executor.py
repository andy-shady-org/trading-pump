from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.base import TradingBotConfig


@pytest.fixture
def mock_exec_client() -> MagicMock:
    client = MagicMock(spec=PumpFunExecutionClient)
    client.default_slippage_bps = 250
    client.get_bonding_curve_pda.return_value = ("BondingCurvePubkey111", 255)
    client.buy = AsyncMock(return_value="BuySignature111")
    client.sell = AsyncMock(return_value="SellSignature111")
    client.swap_raydium = AsyncMock(return_value="RaydiumSignature111")
    client.confirm_transaction = AsyncMock(return_value=True)
    client.get_token_balance = AsyncMock(return_value=1_000_000)
    client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    client.calculate_sell_sol_output = MagicMock(return_value=500_000_000)
    return client


@pytest.fixture
def base_config() -> TradingBotConfig:
    return TradingBotConfig(
        buy_amount_sol=0.1,
        take_profit=1.5,
        stop_loss=0.8,
        dry_run=False,
    )


@pytest.mark.asyncio
async def test_order_executor_dry_run():
    exec_client = MagicMock()
    executor = OrderExecutor(exec_client, dry_run=True)

    buy_res = await executor.execute_buy("Mint111", 0.1, reason="dry_buy")
    assert buy_res.success
    assert buy_res.dry_run
    assert buy_res.mint == "Mint111"
    assert buy_res.is_buy

    sell_res = await executor.execute_sell("Mint111", 500_000, reason="dry_sell")
    assert sell_res.success
    assert sell_res.dry_run
    assert not sell_res.is_buy
    assert sell_res.token_amount == 500_000
    assert sell_res.amount_sol == 0.0

    # With min_sol_output_lamports
    sell_res_lamports = await executor.execute_sell(
        "Mint111",
        500_000,
        min_sol_output_lamports=50_000_000,
        reason="dry_sell_lamports",
    )
    assert sell_res_lamports.amount_sol == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_order_executor_live_buy(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    mock_exec_client.get_token_balance = AsyncMock(return_value=12_345_678)
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.signature == "BuySignature111"
    assert res.token_amount == 12_345_678
    mock_exec_client.buy.assert_awaited_once_with(
        "Mint111", "BondingCurvePubkey111", 0.1, slippage_bps=300
    )
    mock_exec_client.confirm_transaction.assert_awaited_once_with("BuySignature111")


@pytest.mark.asyncio
async def test_order_executor_live_buy_curve_fallback(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    mock_exec_client.get_token_balance = AsyncMock(return_value=0)
    mock_exec_client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_073_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.signature == "BuySignature111"
    assert res.token_amount > 0


@pytest.mark.asyncio
async def test_order_executor_buy_confirmation_failed(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    mock_exec_client.confirm_transaction = AsyncMock(return_value=False)
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1)
    assert not res.success
    assert res.error == "buy_confirmation_failed"


@pytest.mark.asyncio
async def test_order_executor_live_sell(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_sell("Mint111", 500_000, slippage_bps=500)
    assert res.success
    assert res.signature == "SellSignature111"
    assert res.amount_sol == pytest.approx(0.50)  # 500_000_000 lamports
    mock_exec_client.sell.assert_awaited_once_with(
        "Mint111",
        "BondingCurvePubkey111",
        500_000,
        min_sol_output=500_000_000,
        slippage_bps=500,
    )


@pytest.mark.asyncio
async def test_bot_sell_populates_audit_record_and_ledger(tmp_path):
    """
    Regression test for BUG-18:
    Verifies that when _sell_token executes (full or partial), the resulting
    sell_price and exit proceeds are accurately populated and written to the audit log.
    """
    from pumpfun_trading.bot.run import TradingBot

    audit_file = tmp_path / "audit.jsonl"
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        audit_log_path=str(audit_file),
    )

    mint = "MintSellTest111111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint,
        token_amount=1_000_000,
        cost_sol=0.10,
        entry_market_cap=30.0,
        name="SellTestToken",
    )
    bot.position_manager.update_price(mint, 60.0)  # 2x price surge
    bot.active_positions = bot.position_manager.get_all_positions()

    # 1. Execute partial sell (50%)
    success = await bot._sell_token(
        mint=mint,
        sell_amount_tokens=500_000,
        sell_fraction=0.5,
        reason="tier1_take_profit",
        target_tier=1,
    )
    assert success
    assert len(bot._trade_ledger) == 1
    last_trade = bot._trade_ledger[-1]
    assert last_trade["action"] == "partial_sell"
    # Cost basis for 50% is 0.05 SOL, exit proceeds at 2x is 0.10 SOL
    assert last_trade["exit"] == pytest.approx(0.10)
    assert last_trade["sell_price"] == pytest.approx(0.10)
    assert last_trade["entry"] == pytest.approx(0.05)

    # 2. Execute full exit on remaining 50%
    success_full = await bot._sell_token(
        mint=mint,
        reason="stop_loss",
    )
    assert success_full
    assert len(bot._trade_ledger) == 2
    full_trade = bot._trade_ledger[-1]
    assert full_trade["action"] == "sell"
    assert full_trade["exit"] == pytest.approx(0.10)
    assert full_trade["sell_price"] == pytest.approx(0.10)

    # Verify audit file lines contain valid sell_price
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    import json

    trade_records = [
        json.loads(line) for line in lines if json.loads(line).get("type") == "trade"
    ]
    assert len(trade_records) == 2
    assert trade_records[0]["payload"]["sell_price"] == pytest.approx(0.10)
    assert trade_records[1]["payload"]["sell_price"] == pytest.approx(0.10)

    # Verify DailyEquityTracker realized PnL was incremented on both partial and full sells
    # Partial sell PnL = 0.10 - 0.05 = +0.05 SOL
    # Full sell PnL = 0.10 - 0.05 = +0.05 SOL
    # Total realized daily PnL = +0.10 SOL
    assert bot.daily_equity_tracker.realized_daily_pnl_sol == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_order_executor_raydium(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)
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
        coin_mint="Mint111",
        pc_mint="So11111111111111111111111111111111111111112",
        lp_mint="LpMint111",
    )

    buy_res = await executor.execute_raydium_buy("Mint111", pool_keys, 0.25)
    assert buy_res.success
    assert buy_res.signature == "RaydiumSignature111"

    sell_res = await executor.execute_raydium_sell("Mint111", pool_keys, 1_000_000)
    assert sell_res.success
    assert sell_res.signature == "RaydiumSignature111"


@pytest.mark.asyncio
async def test_order_liquidator(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)
    pm = PositionManager(base_config)

    pm.record_buy(
        mint="Mint1",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
    )
    pm.record_buy(
        mint="Mint2",
        token_amount=2_000_000,
        cost_sol=0.2,
        entry_market_cap=40.0,
    )

    liquidator = OrderLiquidator(executor, pm, base_config)

    # Liquidate single position
    success = await liquidator.liquidate_position("Mint1", reason="manual_panic")
    assert success
    assert not pm.has_position("Mint1")
    assert pm.has_position("Mint2")

    # Liquidate remaining positions batch
    liquidated = await liquidator.liquidate_all_positions(reason="circuit_breaker_lock")
    assert liquidated == ["Mint2"]
    assert len(pm) == 0


@pytest.mark.asyncio
async def test_bugs_24_to_28_comprehensive_validation(tmp_path):
    """
    Comprehensive regression tests for:
    - BUG-24: Dry-run token sizing and positive exit proceeds on profitable pump (Torq Rigs scenario)
    - BUG-25: Internal bot buy and sell executions recorded into replay log (.jsonl)
    - BUG-26: Position ID correlation preserved across partial and full exits in audit trail
    - BUG-27: Total SOL capital and token unit prices properly differentiated in audit records
    - BUG-28: PositionManager effective buy price scaled by UI token units
    """
    import json
    from pumpfun_trading.bot.run import TradingBot

    audit_file = tmp_path / "audit_trail.jsonl"
    replay_file = tmp_path / "replay_log.jsonl"

    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        verbose=False,
        dry_run=True,
        audit_log_path=str(audit_file),
        replay_log_path=str(replay_file),
    )
    await bot.replay_recorder.start()

    mint = "TorqRigsPump111111111111111111111111111111111"

    # 1. Execute Buy
    buy_ok = await bot._buy_token(
        mint=mint,
        market_cap_sol=27.96,
        token_name="Torq Rigs",
        buy_amount_sol=0.01,
        reason="momentum_breakout",
    )
    assert buy_ok
    assert bot.position_manager.has_position(mint)
    pos = bot.position_manager.get_position(mint)

    # BUG-24 & BUG-28 checks on entry
    assert (
        pos["initial_token_amount"] > 100_000_000
    )  # Calculated from curve (~357M units)
    # Unit price is ~2.796e-8 SOL (0.02796 µSOL), not 1e-10 or 1e-14
    assert 1e-9 < pos["buy_price"] < 1e-6

    # 2. Simulate 2.06x price surge (Take profit tier 1)
    bot.position_manager.update_price(mint, 57.60)  # ~2.06x
    bot.active_positions = bot.position_manager.get_all_positions()

    partial_ok = await bot._sell_token(
        mint=mint,
        sell_fraction=0.5,
        reason="take_profit_tier_1",
        target_tier=1,
    )
    assert partial_ok

    # 3. Simulate trailing stop exit at 2.71x
    bot.position_manager.update_price(mint, 75.77)  # ~2.71x
    bot.active_positions = bot.position_manager.get_all_positions()

    full_ok = await bot._sell_token(
        mint=mint,
        reason="trailing_stop_hit",
    )
    assert full_ok
    assert not bot.position_manager.has_position(mint)

    # BUG-24 check: Verify bot realized positive cumulative profit (+0.0138 SOL), NOT ~99.9% loss!
    # Entry cost: 0.01 SOL (0.005 + 0.005). Tier 1 exit (0.005 * 2.06 = 0.0103 SOL), Trailing exit (0.005 * 2.71 = 0.01355 SOL)
    # Total exit: ~0.02385 SOL -> Net profit: ~+0.01385 SOL
    realized_pnl = bot.daily_equity_tracker.realized_daily_pnl_sol
    assert realized_pnl > 0.010

    # Flush replay recorder
    await bot.replay_recorder.flush()
    await bot.replay_recorder.close()

    # BUG-25 check: Verify replay log contains BOTH buy and sell snapshots
    assert replay_file.exists()
    replay_lines = [
        json.loads(line)
        for line in replay_file.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert len(replay_lines) == 3
    assert replay_lines[0]["signal"] == "buy"
    assert replay_lines[0]["is_buy"] is True
    assert replay_lines[0]["mint"] == mint
    assert replay_lines[1]["signal"] == "sell"
    assert replay_lines[1]["is_buy"] is False
    assert replay_lines[1]["reason"] == "take_profit_tier_1"
    assert replay_lines[2]["signal"] == "sell"
    assert replay_lines[2]["is_buy"] is False
    assert replay_lines[2]["reason"] == "trailing_stop_hit"

    # BUG-26 & BUG-27 check: Verify audit trail position ID correlation & unit price differentiation
    assert audit_file.exists()
    audit_lines = [
        json.loads(line)
        for line in audit_file.read_text(encoding="utf-8").strip().splitlines()
        if json.loads(line).get("type") == "trade"
    ]
    assert len(audit_lines) == 3
    initial_pos_id = audit_lines[0]["payload"]["position_id"]
    assert initial_pos_id.startswith("trade-")
    # All exits share the same parent position_id
    assert audit_lines[1]["payload"]["position_id"] == initial_pos_id
    assert audit_lines[2]["payload"]["position_id"] == initial_pos_id

    # Verify unit price vs capital differentiation (BUG-27)
    for rec in audit_lines:
        payload = rec["payload"]
        assert "unit_price_sol" in payload
        assert "cost_sol" in payload
        assert "proceeds_sol" in payload
        assert "sol_amount" in payload
