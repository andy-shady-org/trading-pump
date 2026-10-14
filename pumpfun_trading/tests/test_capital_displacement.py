from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock

from pumpfun_trading.bot.position_manager import (
    CapitalDisplacementEngine,
    PositionManager,
)
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.decision import (
    PositionEvEvaluator,
)


def test_position_ev_evaluator_metrics():
    config = TradingBotConfig(
        min_hold_before_displacement_seconds=45.0,
        stagnant_timeout_seconds=120.0,
    )
    evaluator = PositionEvEvaluator(config)

    now = 1000.0

    # 1. Young position (held 20s < 45s) -> NOT displaceable
    pos_young = {
        "mint": "YoungMint111",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "entry_time": now - 20.0,
        "last_price_change_at": now - 20.0,
        "z_score": 1.0,
        "net_inflow_sol": 0.2,
    }
    score_young = evaluator.evaluate_position(pos_young, current_time=now)
    assert not score_young.is_displaceable
    assert score_young.hold_duration_seconds == 20.0

    # 2. Stagnant older position (held 180s > 45s, flat price) -> Displaceable & lower EV due to stagnation penalty
    pos_stagnant = {
        "mint": "StagnantMint222",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "entry_time": now - 180.0,
        "last_price_change_at": now - 180.0,
        "z_score": 0.0,
        "net_inflow_sol": -0.1,
    }
    score_stagnant = evaluator.evaluate_position(pos_stagnant, current_time=now)
    assert score_stagnant.is_displaceable
    assert score_stagnant.stagnation_factor == 1.0
    assert score_stagnant.ev_score < score_young.ev_score

    # 3. High-flying runner position (2x gains, positive momentum) -> Displaceable by time, but higher EV
    pos_runner = {
        "mint": "RunnerMint333",
        "entry_market_cap": 30.0,
        "current_market_cap": 60.0,
        "entry_time": now - 100.0,
        "last_price_change_at": now - 5.0,
        "z_score": 4.0,
        "net_inflow_sol": 3.0,
    }
    score_runner = evaluator.evaluate_position(pos_runner, current_time=now)
    assert score_runner.is_displaceable
    assert score_runner.stagnation_factor == 0.0
    assert score_runner.ev_score > score_stagnant.ev_score

    # 4. Rank positions
    ranked = evaluator.rank_positions_by_ev(
        {
            "StagnantMint222": pos_stagnant,
            "RunnerMint333": pos_runner,
        },
        current_time=now,
    )
    assert len(ranked) == 2
    assert ranked[0].mint == "StagnantMint222"
    assert ranked[1].mint == "RunnerMint333"


def test_candidate_ev_evaluation():
    config = TradingBotConfig()
    evaluator = PositionEvEvaluator(config)

    signal = MagicMock(
        triggered=True,
        z_score=4.5,
        buy_sell_ratio=5.0,
        net_sol_inflow=3.5,
        unique_buyers=10,
    )

    ev_candidate = evaluator.evaluate_candidate(
        "CandidateMint999",
        momentum_signal=signal,
        conviction_percentile=0.98,
    )
    assert ev_candidate > 0.5


def test_capital_displacement_engine_rules():
    config = TradingBotConfig(
        max_active_positions=1,
        max_total_exposure_sol=0.1,
        enable_capital_rotation=True,
        displacement_min_conviction_percentile=0.95,
        displacement_hurdle_rate_pct=0.03,
        min_hold_before_displacement_seconds=45.0,
        buy_amount_sol=0.05,
        min_slippage_bps=100,
    )
    pos_mgr = PositionManager(config)
    engine = CapitalDisplacementEngine(config, pos_mgr)

    now = 1000.0

    # Case 1: Portfolio has capacity (0 positions held)
    dec_capacity = engine.evaluate_displacement("Cand1", current_time=now)
    assert not dec_capacity.displace
    assert dec_capacity.reason == "portfolio_has_capacity"

    # Add a position to saturate capacity
    pos_mgr.record_buy(
        mint="Stagnant1",
        token_amount=1_000_000,
        cost_sol=0.05,
        entry_market_cap=30.0,
    )
    pos = pos_mgr.get_position("Stagnant1")
    pos["entry_time"] = now - 20.0  # held 20s (less than 45s min hold)

    # Case 2: Protected position (cannot displace young holding)
    dec_protected = engine.evaluate_displacement("Cand1", current_time=now)
    assert not dec_protected.displace
    assert dec_protected.reason == "no_displaceable_positions"

    # Age the position past 45s
    pos["entry_time"] = now - 120.0
    pos["last_price_change_at"] = now - 120.0
    pos["z_score"] = 0.0
    pos["net_inflow_sol"] = 0.0

    # Case 3: Weak candidate with low conviction percentile (below 0.95)
    weak_signal = MagicMock(
        triggered=True,
        z_score=0.5,
        buy_sell_ratio=1.1,
        net_sol_inflow=0.05,
        unique_buyers=2,
    )
    dec_low_ev = engine.evaluate_displacement(
        "WeakCand",
        candidate_signal=weak_signal,
        conviction_percentile=0.90,
        current_time=now,
    )
    assert not dec_low_ev.displace
    assert "conviction_below_min_percentile" in dec_low_ev.reason

    # Case 4: High conviction breakout candidate (exceeds hurdle)
    strong_signal = MagicMock(
        triggered=True,
        z_score=4.5,
        buy_sell_ratio=6.0,
        net_sol_inflow=4.0,
        unique_buyers=12,
    )
    dec_displace = engine.evaluate_displacement(
        "StrongCand",
        candidate_signal=strong_signal,
        conviction_percentile=0.98,
        current_time=now,
    )
    assert dec_displace.displace
    assert dec_displace.displaced_mint == "Stagnant1"
    assert dec_displace.target_mint == "StrongCand"
    assert dec_displace.ev_delta > 0.05
    assert dec_displace.reason == "positive_ev_displacement"


@pytest.mark.asyncio
async def test_trading_bot_atomic_displacement(tmp_path):
    config = TradingBotConfig(
        max_active_positions=1,
        max_total_exposure_sol=0.1,
        enable_capital_rotation=True,
        min_hold_before_displacement_seconds=45.0,
        displacement_min_conviction_percentile=0.95,
        displacement_hurdle_rate_pct=0.02,
        dry_run=True,
        verbose=False,
    )
    bot = TradingBot(
        "11111111111111111111111111111111111111111111111111111111111111111",
        "https://example.com",
        config=config,
        dry_run=True,
        verbose=False,
    )

    now = time.time()
    # 1. Establish initial stagnant position
    stagnant_mint = "StagnantMintAAA111111111111111111111111111"
    bot.position_manager.record_buy(
        mint=stagnant_mint,
        token_amount=1_000_000,
        cost_sol=0.05,
        entry_market_cap=30.0,
        name="StagnantToken",
    )
    pos = bot.position_manager.get_position(stagnant_mint)
    pos["entry_time"] = now - 180.0
    pos["last_price_change_at"] = now - 180.0
    bot.active_positions = bot.position_manager.get_all_positions()

    assert len(bot.active_positions) == 1

    # 2. Ingest strong momentum breakout candidate
    breakout_mint = "BreakoutMintBBB222222222222222222222222222"
    breakout_signal = MagicMock(
        triggered=True,
        z_score=4.8,
        buy_sell_ratio=8.0,
        net_sol_inflow=5.0,
        unique_buyers=15,
    )

    displaced = await bot._evaluate_and_trigger_displacement(
        candidate_mint=breakout_mint,
        market_cap_sol=35.0,
        candidate_signal=breakout_signal,
        conviction_percentile=0.98,
        token_name="BreakoutToken",
    )

    assert displaced is True
    # Verify stagnant position was removed and breakout candidate entered
    assert stagnant_mint not in bot.active_positions
    assert breakout_mint in bot.active_positions
