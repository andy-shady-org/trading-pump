"""Comprehensive test suite for FEAT-28: Cross-Venue Arbitrage & Mempool Back-Running Engine."""

from __future__ import annotations

import asyncio
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.cli.arbitrage import (
    build_arbitrage_parser,
    run_arbitrage_cli,
)
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.arbitrage import (
    ArbitrageOpportunity,
    CrossVenueDisparityMonitor,
    MempoolBackrunEngine,
    OptimalArbitrageCalculator,
    calculate_cross_venue_spread,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config


def _mock_pool_keys(
    mint: str = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
) -> RaydiumPoolKeys:
    """Helper creating mock Raydium AMM v4 pool keys."""
    dummy = str(Pubkey.default())
    return RaydiumPoolKeys(
        amm_id=dummy,
        amm_authority=dummy,
        amm_open_orders=dummy,
        amm_target_orders=dummy,
        pool_coin_token_account=dummy,
        pool_pc_token_account=dummy,
        serum_program_id=dummy,
        serum_market=dummy,
        serum_bids=dummy,
        serum_asks=dummy,
        serum_event_queue=dummy,
        serum_coin_vault=dummy,
        serum_pc_vault=dummy,
        serum_vault_signer=dummy,
        coin_mint=mint,
        pc_mint="So11111111111111111111111111111111111111112",
        lp_mint=dummy,
    )


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
    keys = _mock_pool_keys()

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
    keys = _mock_pool_keys()

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


def test_atomic_arbitrage_builder_and_executor() -> None:
    """Test assembly of atomic multi-hop transactions with dual-leg swaps and dynamic Jito tips."""
    kp = Keypair()
    priv_b58 = kp.to_base58_string() if hasattr(kp, "to_base58_string") else str(kp)
    client = PumpFunExecutionClient(private_key_b58=priv_b58)
    builder = AtomicArbitrageBuilder(client)
    executor = AtomicArbitrageExecutor(
        execution_client=client, builder=builder, dry_run=True
    )

    keys = _mock_pool_keys()
    opp = ArbitrageOpportunity(
        mint=keys.coin_mint,
        direction="pump_to_raydium",
        pump_spot_price=0.000030,
        raydium_spot_price=0.000045,
        spread_pct=0.50,
        optimal_input_sol=0.10,
        expected_output_sol=0.14,
        gross_profit_sol=0.04,
        estimated_fees_sol=0.0003,
        estimated_jito_tip_sol=0.02,
        net_profit_sol=0.0197,
        timestamp=1700000000.0,
        pool_keys=keys,
        pump_reserves=(30_000_000_000, 1_000_000_000_000_000),
        raydium_reserves=(85_000_000_000, 200_000_000_000_000),
        leg1_min_amount_out=3_000_000_000,
        leg2_min_amount_out=135_000_000,
    )

    # 1. Build atomic instructions
    ixs = builder.build_arbitrage_instructions(opp)
    assert len(ixs) >= 4  # compute_limit, compute_price, leg1, leg2, tip
    assert ixs[0].program_id == Pubkey.from_string(
        "ComputeBudget111111111111111111111111111111"
    )

    # 2. Reverse direction instruction check
    rev_opp = ArbitrageOpportunity(
        mint=keys.coin_mint,
        direction="raydium_to_pump",
        pump_spot_price=0.000045,
        raydium_spot_price=0.000030,
        spread_pct=0.50,
        optimal_input_sol=0.10,
        expected_output_sol=0.14,
        gross_profit_sol=0.04,
        estimated_fees_sol=0.0003,
        estimated_jito_tip_sol=0.02,
        net_profit_sol=0.0197,
        timestamp=1700000000.0,
        pool_keys=keys,
        leg1_min_amount_out=3_000_000_000,
        leg2_min_amount_out=135_000_000,
    )
    rev_ixs = builder.build_arbitrage_instructions(rev_opp)
    assert len(rev_ixs) >= 4

    # 3. Dry-run simulation execution
    sim_res = asyncio.run(executor.execute_arbitrage(opp))
    assert sim_res["success"] is True
    assert sim_res["status"] == "simulated"
    assert sim_res["net_profit_sol"] == opp.net_profit_sol


def test_strategy_config_and_presets_integration() -> None:
    """Verify TradingBotConfig arbitrage fields and preset calibrations."""
    cfg = TradingBotConfig(
        enable_cross_venue_arbitrage=True,
        enable_mempool_backrunning=True,
        min_arbitrage_profit_sol=0.004,
        min_arbitrage_spread_pct=0.02,
        max_arbitrage_input_sol=0.75,
        min_arbitrage_input_sol=0.02,
        arbitrage_jito_tip_profit_share_pct=0.45,
    )
    assert cfg.enable_cross_venue_arbitrage is True
    assert cfg.min_arbitrage_profit_sol == 0.004
    d = cfg.to_dict()
    assert d["enable_cross_venue_arbitrage"] is True
    assert d["max_arbitrage_input_sol"] == 0.75

    # Check presets
    cons = resolve_strategy_config("conservative")
    assert cons.enable_cross_venue_arbitrage is True
    assert cons.min_arbitrage_spread_pct == 0.020

    bal = resolve_strategy_config("balanced")
    assert bal.enable_cross_venue_arbitrage is True
    assert bal.min_arbitrage_spread_pct == 0.015

    agg = resolve_strategy_config("aggressive")
    assert agg.enable_cross_venue_arbitrage is True
    assert agg.min_arbitrage_spread_pct == 0.010


def test_arbitrage_cli_parser_and_execution() -> None:
    """Test CLI argument parsing and execution for pumpfun-arb."""
    parser = build_arbitrage_parser()
    args = parser.parse_args(
        [
            "--min-spread",
            "0.02",
            "--min-profit",
            "0.005",
            "--max-input",
            "0.40",
            "--raw",
        ]
    )
    assert args.min_spread == 0.02
    assert args.min_profit == 0.005
    assert args.max_input == 0.40
    assert args.raw is True

    exit_code = run_arbitrage_cli(args)
    assert exit_code == 0


def test_paper_trading_engine_arbitrage_simulation() -> None:
    """Verify PaperTradingEngine simulates cross-venue arbitrage profits over multi-venue datasets."""
    engine = PaperTradingEngine(
        initial_cash=10.0,
        enable_cross_venue_arbitrage=True,
    )
    snapshots = [
        {
            "timestamp": 1700000001,
            "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "name": "ArbToken",
            "price": 0.000035,
            "virtual_sol_reserves": 35_000_000_000,
            "virtual_token_reserves": 900_000_000_000_000,
            "raydium_sol_reserve": 85.0,  # 85 SOL
            "raydium_token_reserve": 180_000_000_000_000,  # 180M tokens
        }
    ]
    summary = engine.run(snapshots)
    assert summary["total_trades"] >= 1
    assert summary["final_cash"] > 10.0  # Realized arbitrage profit generated!
    arb_trade = summary["trades"][0]
    assert arb_trade["side"] == "ARBITRAGE"
    assert arb_trade["pnl"] > 0.0
