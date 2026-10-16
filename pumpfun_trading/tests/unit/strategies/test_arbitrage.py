"""Unit tests for ``strategies/arbitrage.py``."""

from __future__ import annotations

import pytest

from pumpfun_trading.strategies.arbitrage import (
    CrossVenueDisparityMonitor,
    MempoolBackrunEngine,
    OptimalArbitrageCalculator,
    calculate_cross_venue_spread,
)
from pumpfun_trading.tests.support.factories import make_pool_keys


def test_spread_calculation_and_directions() -> None:
    """Test percentage spread calculation and direction labeling across price regimes."""
    # Scenario 1: Pump.fun cheaper -> pump_to_raydium
    spread, direction = calculate_cross_venue_spread(
        pump_spot_price=0.000030, raydium_spot_price=0.000036
    )
    assert direction == "pump_to_raydium"
    assert pytest.approx(spread, rel=1e-4) == 0.20  # (0.36 - 0.30) / 0.30 = 20%

    # Scenario 2: Raydium cheaper -> raydium_to_pump
    spread, direction = calculate_cross_venue_spread(
        pump_spot_price=0.000040, raydium_spot_price=0.000032
    )
    assert direction == "raydium_to_pump"
    assert pytest.approx(spread, rel=1e-4) == 0.25  # (0.40 - 0.32) / 0.32 = 25%

    # Scenario 3: Equal prices -> no profitable spread
    spread, direction = calculate_cross_venue_spread(0.000030, 0.000030)
    assert spread == 0.0
    assert direction == "raydium_to_pump" or direction == "pump_to_raydium"

    # Scenario 4: Invalid/zero prices -> 0 spread and none direction
    spread, direction = calculate_cross_venue_spread(0.0, 0.000030)
    assert spread == 0.0
    assert direction == "none"

    spread, direction = calculate_cross_venue_spread(-0.000030, 0.000030)
    assert spread == 0.0
    assert direction == "none"


def test_optimal_arbitrage_calculator_closed_form() -> None:
    """Verify closed-form optimal swap sizing math and positive net profit generation."""
    calc = OptimalArbitrageCalculator(
        pump_fee_pct=0.01,
        raydium_fee_pct=0.0025,
        gas_estimate_sol=0.0003,
        jito_tip_profit_share_pct=0.50,
        min_jito_tip_sol=0.0001,
    )

    # Direction 1: pump_to_raydium (Pump.fun spot is cheap, Raydium pool is expensive)
    pump_sol = 32_000_000_000  # 32 SOL
    pump_tok = 1_000_000_000_000_000  # 1B tokens -> spot = 0.000032 SOL/k-tok
    ray_sol = 85_000_000_000  # 85 SOL
    ray_tok = 200_000_000_000_000  # 200M tokens -> spot = 0.000425 SOL/k-tok

    opt_input, net_profit = calc.calculate_optimal_input(
        pump_virtual_sol=pump_sol,
        pump_virtual_token=pump_tok,
        raydium_sol_reserve=ray_sol,
        raydium_token_reserve=ray_tok,
        direction="pump_to_raydium",
        min_input_sol=0.01,
        max_input_sol=0.50,
    )

    assert 0.01 <= opt_input <= 0.50
    assert net_profit > 0.0

    # Direction 2: raydium_to_pump
    # Raydium spot is cheap, Pump.fun is expensive
    pump_sol_high = 85_000_000_000
    pump_tok_low = 200_000_000_000_000
    ray_sol_low = 32_000_000_000
    ray_tok_high = 1_000_000_000_000_000

    opt_input_rev, net_profit_rev = calc.calculate_optimal_input(
        pump_virtual_sol=pump_sol_high,
        pump_virtual_token=pump_tok_low,
        raydium_sol_reserve=ray_sol_low,
        raydium_token_reserve=ray_tok_high,
        direction="raydium_to_pump",
        min_input_sol=0.01,
        max_input_sol=0.50,
    )

    assert 0.01 <= opt_input_rev <= 0.50
    assert net_profit_rev > 0.0

    # No profit case: equal spot prices or negative spread
    opt_zero, net_zero = calc.calculate_optimal_input(
        pump_virtual_sol=30_000_000_000,
        pump_virtual_token=1_000_000_000_000_000,
        raydium_sol_reserve=30_000_000_000,
        raydium_token_reserve=1_000_000_000_000_000,
        direction="pump_to_raydium",
    )
    assert opt_zero == 0.0
    assert net_zero == 0.0


def test_disparity_monitor_evaluation_and_hurdle_filtering() -> None:
    """Test CrossVenueDisparityMonitor spread evaluation, hurdle filtering, and opportunity generation."""
    monitor = CrossVenueDisparityMonitor(
        min_arbitrage_spread_pct=0.015,  # 1.5%
        min_arbitrage_profit_sol=0.003,  # 0.003 SOL
        max_arbitrage_input_sol=0.50,
        min_arbitrage_input_sol=0.01,
        jito_tip_profit_share_pct=0.50,
    )
    keys = make_pool_keys("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", unique=False)

    # Valid profitable opportunity
    opp = monitor.evaluate_spread(
        mint=keys.coin_mint,
        pump_virtual_sol=35_000_000_000,
        pump_virtual_token=900_000_000_000_000,
        raydium_sol_reserve=85_000_000_000,
        raydium_token_reserve=180_000_000_000_000,
        raydium_keys=keys,
    )

    assert opp is not None
    assert opp.mint == keys.coin_mint
    assert opp.direction == "pump_to_raydium"
    assert opp.spread_pct > 0.015
    assert opp.net_profit_sol >= 0.003
    assert opp.is_profitable
    assert opp.pool_keys == keys

    # Serialization test
    d = opp.to_dict()
    assert d["mint"] == keys.coin_mint
    assert d["direction"] == "pump_to_raydium"
    assert "optimal_input_sol" in d
    assert "pool_keys" in d

    # Rejected opportunity: spread too narrow (e.g. 0.5% spread below 1.5% hurdle)
    narrow_opp = monitor.evaluate_spread(
        mint=keys.coin_mint,
        pump_virtual_sol=50_000_000_000,
        pump_virtual_token=500_000_000_000_000,
        raydium_sol_reserve=50_200_000_000,
        raydium_token_reserve=500_000_000_000_000,
        raydium_keys=keys,
    )
    assert narrow_opp is None

    # Invalid zero reserves
    assert monitor.evaluate_spread("mint", 0, 100, 100, 100) is None
    assert monitor.evaluate_spread("mint", 100, 0, 100, 100) is None


def test_mempool_backrun_engine() -> None:
    """Test MempoolBackrunEngine identifying large whale orders and generating back-run rebalancing."""
    monitor = CrossVenueDisparityMonitor(
        min_arbitrage_spread_pct=0.01,
        min_arbitrage_profit_sol=0.001,
    )
    engine = MempoolBackrunEngine(
        disparity_monitor=monitor,
        whale_sol_threshold=1.0,
        min_curve_impact_pct=0.02,
    )
    keys = make_pool_keys("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", unique=False)

    # Small trade (< 1.0 SOL) does not trigger backrun evaluation
    small_opp = engine.evaluate_whale_transaction(
        mint=keys.coin_mint,
        is_buy=True,
        trade_sol=0.05,
        pump_virtual_sol=35_000_000_000,
        pump_virtual_token=900_000_000_000_000,
        raydium_sol_reserve=85_000_000_000,
        raydium_token_reserve=180_000_000_000_000,
    )
    assert small_opp is None

    # Large whale buy (5.0 SOL) pushes bonding curve price way above Raydium AMM price -> raydium_to_pump backrun
    whale_opp = engine.evaluate_whale_transaction(
        mint=keys.coin_mint,
        is_buy=True,
        trade_sol=5.0,
        pump_virtual_sol=80_000_000_000,
        pump_virtual_token=250_000_000_000_000,
        raydium_sol_reserve=40_000_000_000,
        raydium_token_reserve=200_000_000_000_000,
        raydium_keys=keys,
    )
    assert whale_opp is not None
    assert whale_opp.direction == "raydium_to_pump"
    assert whale_opp.is_profitable
