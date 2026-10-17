"""Unit tests for OrderFlowEngine, sliding window analytics, and velocity Z-score detector."""

import pytest

from pumpfun_trading.strategies.graduation import GraduationEngine
from pumpfun_trading.strategies.momentum import (
    MomentumSignal,
    OrderFlowEngine,
    TokenOrderFlowTracker,
    TradeRecord,
    WindowMetrics,
)


def test_trade_record_and_window_metrics_dataclass() -> None:
    record = TradeRecord(
        mint="Mint111",
        is_buy=True,
        sol_amount=1.5,
        user="WalletA",
        timestamp=1000.0,
    )
    assert record.mint == "Mint111"
    assert record.is_buy is True
    assert record.sol_amount == 1.5
    assert record.user == "WalletA"
    assert record.timestamp == 1000.0

    metrics = WindowMetrics(
        window_seconds=30,
        trade_count=10,
        buy_count=8,
        sell_count=2,
        buy_volume_sol=5.0,
        sell_volume_sol=1.0,
        buy_sell_ratio=5.0,
        net_sol_inflow=4.0,
        unique_buyers=4,
        unique_sellers=2,
        trade_velocity=0.3333,
    )
    assert metrics.window_seconds == 30
    assert metrics.buy_sell_ratio == 5.0
    assert metrics.net_sol_inflow == 4.0


def test_momentum_signal_to_dict() -> None:
    metrics = WindowMetrics(
        window_seconds=30,
        trade_count=5,
        buy_count=5,
        sell_count=0,
        buy_volume_sol=2.5,
        sell_volume_sol=0.0,
        buy_sell_ratio=999.0,
        net_sol_inflow=2.5,
        unique_buyers=3,
        unique_sellers=0,
        trade_velocity=0.1667,
    )
    signal = MomentumSignal(
        triggered=True,
        mint="MintXYZ",
        z_score=3.12,
        buy_sell_ratio=999.0,
        net_sol_inflow=2.5,
        unique_buyers=3,
        trade_velocity=0.1667,
        metrics=metrics,
        reason="momentum_spike",
    )
    data = signal.to_dict()
    assert data["triggered"] is True
    assert data["mint"] == "MintXYZ"
    assert data["z_score"] == 3.12
    assert data["reason"] == "momentum_spike"
    assert data["metrics"]["buy_sell_ratio"] == 999.0
    assert data["metrics"]["unique_buyers"] == 3


def test_token_tracker_sliding_window_metrics_and_eviction() -> None:
    tracker = TokenOrderFlowTracker(mint="MintABC", max_retention_seconds=60)
    base_time = 1000.0

    # Record 4 buys and 1 sell within 15 seconds
    tracker.record_trade(
        is_buy=True, sol_amount=1.0, user="User1", timestamp=base_time + 1
    )
    tracker.record_trade(
        is_buy=True, sol_amount=2.0, user="User2", timestamp=base_time + 5
    )
    tracker.record_trade(
        is_buy=False, sol_amount=0.5, user="User3", timestamp=base_time + 10
    )
    tracker.record_trade(
        is_buy=True, sol_amount=1.5, user="User1", timestamp=base_time + 12
    )
    tracker.record_trade(
        is_buy=True, sol_amount=0.5, user="User4", timestamp=base_time + 14
    )

    # Metrics over 15s window (at t = 1015)
    m15 = tracker.get_window_metrics(window_seconds=15, current_time=base_time + 15)
    assert m15.trade_count == 5
    assert m15.buy_count == 4
    assert m15.sell_count == 1
    assert m15.buy_volume_sol == 5.0
    assert m15.sell_volume_sol == 0.5
    assert m15.net_sol_inflow == 4.5
    assert m15.buy_sell_ratio == 10.0  # 5.0 / 0.5
    assert m15.unique_buyers == 3  # User1, User2, User4
    assert m15.unique_sellers == 1  # User3
    assert m15.trade_velocity == round(5 / 15.0, 4)

    # Over a shorter 5s window (t = 1010 to 1015), only trades at 10, 12, 14 exist
    m5 = tracker.get_window_metrics(window_seconds=5, current_time=base_time + 15)
    assert m5.trade_count == 3
    assert m5.buy_count == 2
    assert m5.sell_count == 1
    assert m5.buy_volume_sol == 2.0
    assert m5.sell_volume_sol == 0.5

    # Check retention eviction: record trade at t = 1080 (older than 60s from base_time + 1)
    tracker.record_trade(
        is_buy=True, sol_amount=1.0, user="User5", timestamp=base_time + 80
    )
    # The first trade at t=1001 should be pruned since 1080 - 60 = 1020
    assert len(tracker.trades) == 1
    assert tracker.trades[0].user == "User5"


def test_token_tracker_zero_sell_volume_ratio() -> None:
    tracker = TokenOrderFlowTracker(mint="MintZeroSell")
    base_time = 1000.0

    tracker.record_trade(
        is_buy=True, sol_amount=2.0, user="Buyer1", timestamp=base_time + 1
    )
    tracker.record_trade(
        is_buy=True, sol_amount=3.0, user="Buyer2", timestamp=base_time + 2
    )

    metrics = tracker.get_window_metrics(window_seconds=30, current_time=base_time + 10)
    assert metrics.sell_volume_sol == 0.0
    assert metrics.buy_volume_sol == 5.0
    assert metrics.buy_sell_ratio == 999.0
    assert metrics.net_sol_inflow == 5.0


def test_token_tracker_empty_window_metrics() -> None:
    tracker = TokenOrderFlowTracker(mint="MintEmpty")
    metrics = tracker.get_window_metrics(window_seconds=30, current_time=1000.0)
    assert metrics.trade_count == 0
    assert metrics.buy_volume_sol == 0.0
    assert metrics.sell_volume_sol == 0.0
    assert metrics.buy_sell_ratio == 0.0
    assert metrics.net_sol_inflow == 0.0
    assert metrics.unique_buyers == 0
    assert metrics.trade_velocity == 0.0


def test_velocity_z_score_calculation() -> None:
    tracker = TokenOrderFlowTracker(mint="MintZScore", max_retention_seconds=600)
    base_time = 1000.0

    # Create a baseline of 300s (10 slices of 30s)
    # Slices 1 to 9 (from t=700 to t=970): steady 1 trade per slice (velocity = 1/30 = 0.0333)
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        tracker.record_trade(
            is_buy=True, sol_amount=0.1, user=f"User{slice_idx}", timestamp=t
        )

    # In the current slice (t = 970 to 1000), sudden trade burst of 10 trades
    for i in range(10):
        tracker.record_trade(
            is_buy=True,
            sol_amount=0.5,
            user=f"BurstUser{i}",
            timestamp=base_time - 10 + i,
        )

    # Calculate Z-score at current_time = base_time
    z_score = tracker.get_velocity_z_score(
        window_seconds=30,
        baseline_window_seconds=300,
        current_time=base_time,
    )
    # Current slice has 10 trades (velocity = 10/30 = 0.3333)
    # Baseline slices 1..9 had 1 trade each (velocity = 0.0333)
    # Z-score should easily exceed 2.5
    assert z_score > 2.5


def test_velocity_z_score_uniform_baseline() -> None:
    tracker = TokenOrderFlowTracker(mint="MintUniform")
    base_time = 1000.0

    # 1 trade in every 30s slice (slice 0 to 9)
    for slice_idx in range(10):
        t = base_time - (slice_idx * 30 + 15)
        tracker.record_trade(is_buy=True, sol_amount=0.1, user="UserA", timestamp=t)

    z_score = tracker.get_velocity_z_score(
        window_seconds=30,
        baseline_window_seconds=300,
        current_time=base_time,
    )
    # Since all slices have identical velocity, variance is 0 and current == mean -> z_score == 0.0
    assert z_score == 0.0


def test_evaluate_momentum_signal_wash_trading_guard() -> None:
    tracker = TokenOrderFlowTracker(mint="MintWash")
    base_time = 1000.0

    # Burst of 10 buys, but ALL from the same wallet address "WashTrader"
    for i in range(10):
        tracker.record_trade(
            is_buy=True, sol_amount=1.0, user="WashTrader", timestamp=base_time - 10 + i
        )

    signal = tracker.evaluate_momentum_signal(
        window_seconds=30,
        min_buy_ratio=3.0,
        min_z_score=2.0,
        min_unique_buyers=3,
        min_net_inflow_sol=0.5,
        baseline_window_seconds=300,
        current_time=base_time,
    )
    assert signal.triggered is False
    assert signal.unique_buyers == 1
    assert "unique_buyers_1_below_3" in signal.reason


def test_evaluate_momentum_signal_ratio_and_inflow_guards() -> None:
    tracker = TokenOrderFlowTracker(mint="MintGuards")
    base_time = 1000.0

    # 4 distinct buyers with 0.1 SOL each = 0.4 SOL buy volume, but 1.0 SOL sell volume
    tracker.record_trade(
        is_buy=True, sol_amount=0.1, user="UserA", timestamp=base_time - 10
    )
    tracker.record_trade(
        is_buy=True, sol_amount=0.1, user="UserB", timestamp=base_time - 8
    )
    tracker.record_trade(
        is_buy=True, sol_amount=0.1, user="UserC", timestamp=base_time - 6
    )
    tracker.record_trade(
        is_buy=True, sol_amount=0.1, user="UserD", timestamp=base_time - 4
    )
    tracker.record_trade(
        is_buy=False, sol_amount=1.0, user="Seller1", timestamp=base_time - 2
    )

    signal = tracker.evaluate_momentum_signal(
        window_seconds=30,
        min_buy_ratio=3.0,
        min_z_score=1.0,
        min_unique_buyers=3,
        min_net_inflow_sol=0.5,
        current_time=base_time,
    )
    assert signal.triggered is False
    assert "buy_ratio_" in signal.reason or "net_inflow_" in signal.reason


def test_evaluate_momentum_signal_token_age_limit() -> None:
    tracker = TokenOrderFlowTracker(mint="MintOld")
    base_time = 2000.0

    for i in range(5):
        tracker.record_trade(
            is_buy=True, sol_amount=1.0, user=f"Buyer{i}", timestamp=base_time - 5 + i
        )

    signal = tracker.evaluate_momentum_signal(
        window_seconds=30,
        min_buy_ratio=2.0,
        min_z_score=1.0,
        min_unique_buyers=3,
        min_net_inflow_sol=0.5,
        token_creation_timestamp=100.0,  # 1900 seconds old
        max_token_age_seconds=600,  # max 600s
        current_time=base_time,
    )
    assert signal.triggered is False
    assert "token_age_exceeded" in signal.reason


def test_evaluate_momentum_signal_success() -> None:
    tracker = TokenOrderFlowTracker(mint="MintSuccess", max_retention_seconds=600)
    base_time = 1000.0

    # Historical low baseline
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        tracker.record_trade(
            is_buy=True, sol_amount=0.05, user=f"OldUser{slice_idx}", timestamp=t
        )

    # Current burst with 5 distinct buyers, 5.0 SOL buy volume, 0 sells
    for i in range(5):
        tracker.record_trade(
            is_buy=True,
            sol_amount=1.0,
            user=f"NewBuyer{i}",
            timestamp=base_time - 10 + (i * 2),
        )

    signal = tracker.evaluate_momentum_signal(
        window_seconds=30,
        min_buy_ratio=3.0,
        min_z_score=2.0,
        min_unique_buyers=3,
        min_net_inflow_sol=0.5,
        baseline_window_seconds=300,
        token_creation_timestamp=base_time - 100,
        max_token_age_seconds=600,
        current_time=base_time,
    )
    assert signal.triggered is True
    assert signal.mint == "MintSuccess"
    assert signal.z_score >= 2.0
    assert signal.buy_sell_ratio == 999.0
    assert signal.unique_buyers == 5
    assert signal.net_sol_inflow == 5.0
    assert signal.reason == "momentum_spike"


def test_order_flow_engine_multi_token_and_cleanup() -> None:
    engine = OrderFlowEngine(max_retention_seconds=600, recent_token_ttl_seconds=100)
    base_time = 1000.0

    # Record trade for Token1 and Token2
    engine.record_trade(
        "Token1", is_buy=True, sol_amount=1.0, user="UserA", timestamp=base_time - 150
    )
    engine.record_trade(
        "Token2", is_buy=True, sol_amount=2.0, user="UserB", timestamp=base_time - 20
    )

    assert engine.tracked_token_count == 2

    # Query metrics
    m1 = engine.get_metrics("Token1", window_seconds=30, current_time=base_time)
    assert m1.trade_count == 0  # older than 30s
    m2 = engine.get_metrics("Token2", window_seconds=30, current_time=base_time)
    assert m2.trade_count == 1
    assert m2.buy_volume_sol == 2.0

    # Query metrics for unknown token
    m_unknown = engine.get_metrics(
        "UnknownToken", window_seconds=30, current_time=base_time
    )
    assert m_unknown.trade_count == 0
    assert m_unknown.buy_volume_sol == 0.0

    # Query z-score for unknown token
    assert engine.get_velocity_z_score("UnknownToken") == 0.0

    # Query signal for unknown token
    sig_unknown = engine.evaluate_momentum_signal("UnknownToken")
    assert sig_unknown.triggered is False
    assert sig_unknown.reason == "token_not_tracked"

    # Cleanup inactive tokens: Token1 is 150s old (> 100s TTL), Token2 is 20s old
    pruned = engine.cleanup_inactive_tokens(ttl_seconds=100, current_time=base_time)
    assert pruned == 1
    assert engine.tracked_token_count == 1
    assert "Token1" not in engine._trackers
    assert "Token2" in engine._trackers

    # Clear all
    engine.clear()
    assert engine.tracked_token_count == 0


@pytest.mark.regression("BUG-77")
def test_order_flow_and_graduation_engines_are_bounded():
    """BUG-77: trackers are capped by least-recent activity."""
    flow = OrderFlowEngine(max_tracked_tokens=2)
    flow.record_trade("a", True, 0.1, "u", timestamp=1.0)
    flow.record_trade("b", True, 0.1, "u", timestamp=3.0)
    flow.record_trade("c", True, 0.1, "u", timestamp=2.0)
    assert flow.tracked_token_count == 2
    assert "a" not in flow._trackers

    grad = GraduationEngine(max_tracked_candidates=2)
    grad.update_bonding_curve("a", "c1", 1.0, 31.0, 30.0, timestamp=1.0)
    grad.update_bonding_curve("b", "c2", 1.0, 31.0, 30.0, timestamp=3.0)
    grad.update_bonding_curve("c", "c3", 1.0, 31.0, 30.0, timestamp=2.0)
    assert grad.tracked_candidate_count == 2
    assert grad.get_candidate("a") is None
