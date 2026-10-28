"""Unit tests for ``execution/liquidator.py``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_pump.bot.position_manager import PositionManager
from trading_pump.execution.executor import ExecutionResult, OrderExecutor
from trading_pump.execution.liquidator import OrderLiquidator
from trading_pump.strategies.base import TradingBotConfig
from trading_pump.tests.support.constants import SAMPLE_MINT, WSOL_MINT
from trading_pump.tests.support.factories import make_config


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


@pytest.mark.regression("BUG-65")
async def test_liquidator_never_sells_phantom_balance():
    # BUG-65: remaining 0 must not become a 100M-token sell
    manager = PositionManager(make_config(dry_run=False))
    manager.record_buy(mint="M", token_amount=0, cost_sol=0.01, entry_market_cap=30.0)
    executor = MagicMock()
    executor.execute_sell = AsyncMock()
    liquidator = OrderLiquidator(executor, manager)
    assert await liquidator.liquidate_position("M") is False
    executor.execute_sell.assert_not_called()


async def test_liquidator_and_api_edge_branches():
    from trading_pump.bot.position_manager import PositionManager
    from trading_pump.execution.executor import ExecutionResult, OrderExecutor
    from trading_pump.execution.liquidator import OrderLiquidator

    exec_mock = MagicMock(spec=OrderExecutor)
    pm = PositionManager(make_config(dry_run=False))
    pm.record_buy(SAMPLE_MINT, token_amount=1000, cost_sol=0.01, entry_market_cap=27.96)
    liquidator = OrderLiquidator(
        executor=exec_mock, position_manager=pm, config=make_config(dry_run=False)
    )

    exec_mock.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC fail", dry_run=False)
    )
    results = await liquidator.liquidate_all_positions(reason="panic")
    assert results == []

    exec_mock.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=True, signature="sold_all", dry_run=False)
    )
    results2 = await liquidator.liquidate_all_positions(reason="panic")
    assert SAMPLE_MINT in results2
    assert len(pm.get_all_positions()) == 0


async def test_order_liquidator_branches():
    executor = MagicMock(spec=OrderExecutor)
    pm = PositionManager(make_config(dry_run=False))
    liquidator = OrderLiquidator(executor=executor, position_manager=pm)

    # Empty positions
    liquidated = await liquidator.liquidate_all_positions()
    assert liquidated == []

    # Populated positions
    pm.record_buy(SAMPLE_MINT, 1000, 0.05, 30.0, dry_run=True)
    pm.record_buy(WSOL_MINT, 2000, 0.10, 40.0, dry_run=True)

    # Mock execute_sell success and failure
    async def mock_sell(mint, token_amount, *args, **kwargs):
        if mint == SAMPLE_MINT:
            return ExecutionResult(
                success=True, mint=mint, amount_sol=0.06, token_amount=token_amount
            )
        raise RuntimeError("Liquidate fail")

    executor.execute_sell = AsyncMock(side_effect=mock_sell)
    liquidated = await liquidator.liquidate_all_positions(reason="panic_test")
    assert liquidated == [SAMPLE_MINT]
