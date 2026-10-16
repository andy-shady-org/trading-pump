"""Unit tests for ``strategies/decision.py``."""

from __future__ import annotations

from unittest.mock import MagicMock

from pumpfun_trading.strategies import TradingStrategy
from pumpfun_trading.strategies.decision import PositionEvEvaluator
from pumpfun_trading.strategies.presets import resolve_strategy_config
from pumpfun_trading.tests.support.factories import make_config


def test_position_ev_evaluator_metrics():
    config = make_config(
        dry_run=False,
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
    config = make_config(dry_run=False)
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


def test_trading_strategy_uses_modular_components():
    strategy = TradingStrategy(
        make_config(
            dry_run=False,
            max_active_positions=2,
            min_market_cap_sol=5.0,
            max_buy_attempts_per_mint=3,
            reserve_balance_sol=0.1,
        )
    )
    assert strategy.should_buy(
        market_cap_sol=10.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert strategy.validate_risk(
        current_positions={"a": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert strategy.should_sell(performance=1.8, token_balance=2)


def test_strategy_momentum_decision_pipeline():
    from pumpfun_trading.strategies.momentum import (
        MomentumSignal,
        OrderFlowEngine,
        WindowMetrics,
    )

    config = resolve_strategy_config("balanced")
    strategy = TradingStrategy(config)
    engine = OrderFlowEngine()

    base_time = 1000.0
    # Ingest trades to create breakout
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        engine.record_trade(
            "TokenBreakout",
            is_buy=True,
            sol_amount=0.05,
            user=f"OldUser{slice_idx}",
            timestamp=t,
        )
    for i in range(5):
        engine.record_trade(
            "TokenBreakout",
            is_buy=True,
            sol_amount=1.0,
            user=f"NewBuyer{i}",
            timestamp=base_time - 10 + i,
        )

    signal = strategy.evaluate_momentum(
        engine,
        "TokenBreakout",
        token_creation_timestamp=base_time - 100,
        current_time=base_time,
    )
    assert signal.triggered is True
    assert signal.z_score >= 2.5
    assert signal.unique_buyers >= 3

    # Check should_buy_momentum
    assert (
        strategy.should_buy_momentum(
            momentum_signal=signal,
            active_positions=0,
            buy_attempts=0,
            mint_seen_recently=False,
        )
        is True
    )

    # Check rejection when active positions full
    assert (
        strategy.should_buy_momentum(
            momentum_signal=signal,
            active_positions=1,
            buy_attempts=0,
            mint_seen_recently=False,
        )
        is False
    )

    # Check rejection when signal not triggered
    failed_signal = MomentumSignal(
        triggered=False,
        mint="TokenFailed",
        z_score=1.0,
        buy_sell_ratio=1.0,
        net_sol_inflow=0.1,
        unique_buyers=1,
        trade_velocity=0.05,
        metrics=WindowMetrics(
            window_seconds=30,
            trade_count=1,
            buy_count=1,
            sell_count=0,
            buy_volume_sol=0.1,
            sell_volume_sol=0.0,
            buy_sell_ratio=999.0,
            net_sol_inflow=0.1,
            unique_buyers=1,
            unique_sellers=0,
            trade_velocity=0.033,
        ),
        reason="failed",
    )
    assert (
        strategy.should_buy_momentum(
            momentum_signal=failed_signal,
            active_positions=0,
            buy_attempts=0,
        )
        is False
    )

    # Check summary contains momentum
    summary = strategy.summary()
    assert summary["enable_momentum_signals"] is True
    assert summary["momentum_min_z_score"] == 2.5
