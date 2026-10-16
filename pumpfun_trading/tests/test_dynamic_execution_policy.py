from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.execution.policy import (
    AdaptiveExecutionPolicy,
    DynamicSlippageResult,
)
from pumpfun_trading.sdk.curve import (
    BondingCurveVolatilityEstimator,
    calculate_spot_price,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config


def test_curve_volatility_estimator_math():
    estimator = BondingCurveVolatilityEstimator(
        window_seconds=60.0,
        default_slippage_bps=250,
        min_slippage_bps=100,
        max_slippage_bps=500,
    )

    # Initially empty
    assert estimator.calculate_price_velocity() == 0.0
    assert estimator.calculate_relative_velocity() == 0.0
    assert estimator.calculate_volatility() == 0.0

    # Add observations
    t0 = 1000.0
    obs1 = estimator.record_observation(
        virtual_sol_reserves=30.0,
        virtual_token_reserves=1_000_000_000.0,
        timestamp=t0,
    )
    assert obs1.spot_price == calculate_spot_price(30.0, 1_000_000_000.0)

    # 10 seconds later: reserves in SOL -> price increases
    t1 = t0 + 10.0
    estimator.record_observation(
        virtual_sol_reserves=36.0,
        virtual_token_reserves=900_000_000.0,
        timestamp=t1,
    )

    # Another 10 seconds later: price changes again
    t2 = t1 + 10.0
    estimator.record_observation(
        virtual_sol_reserves=42.0,
        virtual_token_reserves=850_000_000.0,
        timestamp=t2,
    )

    vel = estimator.calculate_price_velocity(window_seconds=30.0, as_of=t2)
    rel_vel = estimator.calculate_relative_velocity(window_seconds=30.0, as_of=t2)
    assert vel > 0.0
    assert rel_vel > 0.0

    vol = estimator.calculate_volatility(window_seconds=30.0, as_of=t2)
    assert vol > 0.0

    # Test depth consumption
    depth = estimator.calculate_depth_consumption(1.5, 30.0)
    assert pytest.approx(depth, rel=1e-4) == 0.05

    # Test slippage estimation with calm vs volatile market
    slip_normal = estimator.estimate_dynamic_slippage(
        trade_amount_sol=0.1,
        virtual_sol_reserves=30.0,
        virtual_token_reserves=1_000_000_000.0,
        is_buy=True,
        urgency_tier="normal",
    )
    assert 100 <= slip_normal <= 500

    slip_emergency = estimator.estimate_dynamic_slippage(
        trade_amount_sol=0.1,
        virtual_sol_reserves=30.0,
        virtual_token_reserves=1_000_000_000.0,
        is_buy=True,
        urgency_tier="emergency",
        max_slippage_bps=3000,
    )
    assert slip_emergency >= slip_normal

    # Test pruning
    t3 = t0 + 120.0  # past 60s window
    estimator.record_observation(
        virtual_sol_reserves=50.0,
        virtual_token_reserves=800_000_000.0,
        timestamp=t3,
    )
    obs = estimator.get_observations(as_of=t3)
    assert len(obs) == 1
    assert obs[0].timestamp == t3

    estimator.clear()
    assert len(estimator.get_observations()) == 0


def test_adaptive_execution_policy_urgency_tiers():
    config = TradingBotConfig(
        min_slippage_bps=100,
        max_slippage_bps=500,
        max_exit_slippage_bps=5000,
    )
    policy = AdaptiveExecutionPolicy(
        config,
        base_compute_unit_limit=200_000,
        base_compute_unit_price=50_000,
        base_jito_tip_lamports=100_000,
    )

    mint = "TestMint111111111111111111111111111111111111"

    # Normal Entry
    res_normal = policy.resolve_parameters(
        mint=mint,
        trade_amount_sol=0.1,
        is_buy=True,
        urgency="normal",
    )
    assert isinstance(res_normal, DynamicSlippageResult)
    assert res_normal.urgency_tier == "normal"
    assert res_normal.compute_unit_limit == 200_000
    assert res_normal.compute_unit_price_micro_lamports == 50_000
    assert res_normal.jito_tip_lamports == 100_000
    assert 100 <= res_normal.slippage_bps <= 500

    # High Conviction Entry
    res_high = policy.resolve_parameters(
        mint=mint,
        trade_amount_sol=0.5,
        is_buy=True,
        urgency="high_conviction",
    )
    assert res_high.urgency_tier == "high_conviction"
    assert res_high.compute_unit_limit == 250_000
    assert res_high.compute_unit_price_micro_lamports == 75_000  # 1.5x
    assert res_high.jito_tip_lamports == 150_000  # 1.5x

    # Graduation Snipe
    res_grad = policy.resolve_parameters(
        mint=mint,
        trade_amount_sol=0.2,
        is_buy=True,
        urgency="graduation",
    )
    assert res_grad.urgency_tier == "graduation"
    assert res_grad.compute_unit_limit == 300_000
    assert res_grad.compute_unit_price_micro_lamports == 125_000  # 2.5x
    assert res_grad.jito_tip_lamports == 250_000  # 2.5x

    # Emergency Exit
    res_emerg = policy.resolve_parameters(
        mint=mint,
        trade_amount_sol=1.0,
        is_buy=False,
        urgency="emergency",
    )
    assert res_emerg.urgency_tier == "emergency"
    assert res_emerg.compute_unit_limit == 400_000
    assert res_emerg.compute_unit_price_micro_lamports == 200_000  # 4.0x
    assert res_emerg.jito_tip_lamports == 400_000  # 4.0x
    assert res_emerg.slippage_bps <= 5000


async def test_order_executor_dynamic_slippage():
    config = TradingBotConfig(
        dry_run=True,
        enable_dynamic_slippage=True,
        min_slippage_bps=120,
        max_slippage_bps=600,
    )
    mock_client = MagicMock()
    executor = OrderExecutor(mock_client, config=config, dry_run=True)

    mint = "TestToken11111111111111111111111111111111111"

    # Buy resolution
    buy_res = await executor.execute_buy(
        mint=mint,
        amount_sol=0.05,
        urgency="high_conviction",
    )
    assert buy_res.success
    assert buy_res.dry_run

    # Sell resolution
    sell_res = await executor.execute_sell(
        mint=mint,
        token_amount=10_000_000,
        reason="emergency_liquidation",
    )
    assert sell_res.success
    assert sell_res.dry_run


async def test_order_liquidator_emergency_urgency():
    config = TradingBotConfig(
        dry_run=True,
        max_exit_slippage_bps=5000,
    )
    mock_client = MagicMock()
    executor = OrderExecutor(mock_client, config=config, dry_run=True)
    pos_mgr = PositionManager(config)

    mint1 = "MintOne111111111111111111111111111111111111"
    mint2 = "MintTwo222222222222222222222222222222222222"

    pos_mgr.record_buy(mint1, token_amount=1000, cost_sol=0.01, entry_market_cap=30.0)
    pos_mgr.record_buy(mint2, token_amount=2000, cost_sol=0.02, entry_market_cap=30.0)

    liquidator = OrderLiquidator(executor, pos_mgr, config)

    liquidated = await liquidator.liquidate_all_positions(
        reason="panic_circuit_breaker"
    )
    assert len(liquidated) == 2
    assert not pos_mgr.has_position(mint1)
    assert not pos_mgr.has_position(mint2)


def test_presets_validation_dynamic_slippage():
    cfg = resolve_strategy_config("balanced")
    assert cfg.enable_dynamic_slippage is True
    assert cfg.min_slippage_bps == 100
    assert cfg.max_slippage_bps == 500
    assert cfg.max_exit_slippage_bps == 5000

    cfg_dict = cfg.to_dict()
    assert cfg_dict["enable_dynamic_slippage"] is True
    assert cfg_dict["max_exit_slippage_bps"] == 5000

    with pytest.raises(ValueError, match="Invalid slippage bounds"):
        resolve_strategy_config(
            "balanced", overrides={"min_slippage_bps": 600, "max_slippage_bps": 300}
        )
