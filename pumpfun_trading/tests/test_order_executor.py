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


@pytest.mark.asyncio
async def test_order_executor_live_buy(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.signature == "BuySignature111"
    mock_exec_client.buy.assert_awaited_once_with(
        "Mint111", "BondingCurvePubkey111", 0.1, slippage_bps=300
    )
    mock_exec_client.confirm_transaction.assert_awaited_once_with("BuySignature111")


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
    mock_exec_client.sell.assert_awaited_once_with(
        "Mint111", "BondingCurvePubkey111", 500_000, min_sol_output=500_000_000
    )


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
