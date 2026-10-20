"""Unit tests for OrderFlowEngine, sliding window analytics, and velocity Z-score detector."""

from typing import Any

import pytest

from pumpfun_trading.strategies.graduation import GraduationEngine
from pumpfun_trading.strategies.momentum import (
    MomentumSignal,
    OrderFlowEngine,
    TokenOrderFlowTracker,
    TradeRecord,
    WatchEntry,
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


# --- FEAT-51: watch list for confirmed entries ---------------------------------------


def test_watch_entry_growth_and_dict() -> None:
    entry = WatchEntry(mint="M", created_at=1.0, watched_at=2.0)
    assert entry.sol_growth == 0.0
    entry.start_real_sol, entry.last_real_sol = 0.5, 2.25
    assert entry.sol_growth == pytest.approx(1.75)
    data = entry.to_dict()
    assert data["sol_growth"] == pytest.approx(1.75)
    assert data["subscribed"] is False


def test_watch_is_idempotent_and_measures_growth_from_first_reading() -> None:
    engine = OrderFlowEngine()
    first = engine.watch("A", created_at=100.0, creator="Dev", now=100.0)
    assert engine.watch("A", created_at=999.0, now=200.0) is first
    assert engine.is_watched("A") and engine.watch_count == 1
    assert engine.get_watch("A") is first

    engine.update_watch_curve("A", real_sol=0.4, market_cap_sol=29.0, now=102.0)
    engine.update_watch_curve("A", real_sol=2.4, market_cap_sol=33.0, now=104.0)

    assert first.start_real_sol == 0.4
    assert first.sol_growth == pytest.approx(2.0)
    assert first.market_cap_sol == 33.0 and first.last_polled_at == 104.0
    assert engine.update_watch_curve("unknown", real_sol=1, market_cap_sol=1) is None


def test_promotable_respects_growth_threshold_and_subscription_budget() -> None:
    engine = OrderFlowEngine()
    for mint, growth in (("slow", 0.5), ("fast", 4.0), ("mid", 2.0), ("new", 0.0)):
        engine.watch(mint, created_at=0.0, now=0.0, real_sol=0.0)
        engine.update_watch_curve(mint, real_sol=growth, market_cap_sol=30.0)
    engine.watch("unpolled", created_at=0.0, now=0.0)

    assert engine.promotable(min_sol_growth=1.5, budget=5) == ["fast", "mid"]
    assert engine.promotable(min_sol_growth=1.5, budget=1) == ["fast"]

    engine.mark_watch_subscribed("fast")
    engine.mark_watch_subscribed("missing")  # ignored
    assert engine.watch_subscribed_count == 1
    assert engine.promotable(min_sol_growth=1.5, budget=1) == []
    assert engine.promotable(min_sol_growth=1.5, budget=2) == ["mid"]


def test_watch_list_full_evicts_oldest_unsubscribed_first() -> None:
    engine = OrderFlowEngine()
    engine.max_watch_mints = 2
    engine.watch("old", created_at=0.0, now=1.0)
    engine.watch("older_sub", created_at=0.0, now=0.5)
    engine.mark_watch_subscribed("old")

    engine.watch("new", created_at=0.0, now=2.0)

    assert engine.watched_mints() == ["old", "new"]
    assert [e.mint for e in engine.drain_watch_evictions()] == ["older_sub"]
    assert engine.drain_watch_evictions() == []

    engine.mark_watch_subscribed("new")
    engine.watch("newest", created_at=0.0, now=3.0)  # all subscribed: oldest goes
    assert engine.watched_mints() == ["new", "newest"]
    assert [e.mint for e in engine.drain_watch_evictions()] == ["old"]


def test_expire_and_unwatch() -> None:
    engine = OrderFlowEngine()
    engine.watch("stale_sub", created_at=0.0, now=0.0)
    engine.watch("stale", created_at=0.0, now=1.0)
    engine.watch("fresh", created_at=0.0, now=500.0)
    engine.mark_watch_subscribed("stale_sub")

    assert engine.expire_watch(ttl=300.0, now=600.0) == ["stale_sub", "stale"]
    assert [e.mint for e in engine.drain_watch_evictions()] == ["stale_sub"]
    assert engine.watched_mints() == ["fresh"]
    assert engine.unwatch("fresh") is not None
    assert engine.unwatch("fresh") is None
    assert engine.watch_count == 0


def _near_grad_args(**overrides: float) -> dict[str, Any]:
    args: dict[str, Any] = {
        "near_graduation_max": 2,
        "near_graduation_min_real_sol": 40.0,
        "near_graduation_stall_seconds": 120.0,
        "near_graduation_ttl": 3600.0,
    }
    args.update(overrides)
    return args


def test_expiry_keeps_growing_curves_in_the_near_graduation_set() -> None:
    """FEAT-53: an old coin still climbing stays polled for the pre-grad lane."""
    engine = OrderFlowEngine()
    engine.watch("climbing", created_at=0.0, now=0.0, real_sol=5.0)
    engine.watch("low", created_at=0.0, now=0.0, real_sol=5.0)
    engine.watch("stalled", created_at=0.0, now=0.0, real_sol=5.0)
    engine.mark_watch_subscribed("climbing")
    engine.update_watch_curve("climbing", real_sol=50.0, market_cap_sol=80.0, now=550.0)
    engine.update_watch_curve("low", real_sol=20.0, market_cap_sol=40.0, now=550.0)
    engine.update_watch_curve("stalled", real_sol=50.0, market_cap_sol=80.0, now=100.0)

    expired = engine.expire_watch(ttl=300.0, now=600.0, **_near_grad_args())

    assert expired == ["low", "stalled"]
    entry = engine.get_watch("climbing")
    assert entry is not None and entry.near_graduation and not entry.subscribed
    assert entry.to_dict()["near_graduation"] is True
    # The trade subscription it held must be cancelled by the runtime.
    assert [(e.mint, held) for e, held in engine.drain_near_graduation()] == [
        ("climbing", True)
    ]
    assert engine.drain_near_graduation() == []
    assert engine.near_graduation_count == 1
    # Never promoted again, however fast it grows.
    assert engine.promotable(min_sol_growth=0.0, budget=5) == []


def test_near_graduation_set_has_its_own_cap_and_drops_stalled_entries() -> None:
    engine = OrderFlowEngine()
    engine.max_watch_mints = 2
    for mint in ("a", "b", "c"):
        engine.watch(mint, created_at=0.0, now=0.0, real_sol=5.0)
        engine.update_watch_curve(mint, real_sol=60.0, market_cap_sol=90.0, now=500.0)

    # Only two fit in the near-graduation set (one was evicted at the watch cap).
    assert engine.watched_mints() == ["b", "c"]
    engine.drain_watch_evictions()
    engine.expire_watch(ttl=300.0, now=600.0, **_near_grad_args(near_graduation_max=1))
    assert engine.watched_mints() == ["b"]
    assert engine.near_graduation_count == 1

    # Regular capacity ignores the near-graduation entry: no eviction.
    engine.watch("new1", created_at=0.0, now=600.0)
    engine.watch("new2", created_at=0.0, now=600.0)
    assert engine.drain_watch_evictions() == []
    assert set(engine.watched_mints()) == {"b", "new1", "new2"}

    # Growth keeps it; a stall, or the hard TTL, drops it.
    engine.update_watch_curve("b", real_sol=61.0, market_cap_sol=91.0, now=700.0)
    engine.expire_watch(ttl=300.0, now=800.0, **_near_grad_args())
    assert engine.is_watched("b")
    engine.update_watch_curve("b", real_sol=61.0, market_cap_sol=91.0, now=850.0)
    # No growth since 700 s: stalled for longer than 120 s at 941 s.
    assert "b" in engine.expire_watch(ttl=300.0, now=941.0, **_near_grad_args())

    engine.watch("ttl", created_at=0.0, now=0.0, real_sol=50.0)
    engine.update_watch_curve("ttl", real_sol=70.0, market_cap_sol=100.0, now=4_000.0)
    assert "ttl" in engine.expire_watch(
        ttl=300.0, now=4_001.0, **_near_grad_args(near_graduation_ttl=3_600.0)
    )


def test_near_graduation_expiry_reads_the_config() -> None:
    from pumpfun_trading.strategies.momentum import near_graduation_expiry
    from pumpfun_trading.tests.support.factories import make_config

    args = near_graduation_expiry(
        make_config(near_graduation_max_mints=7, near_graduation_min_progress_pct=0.4)
    )

    assert args["near_graduation_max"] == 7
    assert args["near_graduation_min_real_sol"] == pytest.approx(34.0)
    assert args["near_graduation_stall_seconds"] == 300.0
    assert args["near_graduation_ttl"] == 3600.0


def test_momentum_metrics_exclude_creator_and_own_wallet() -> None:
    engine = OrderFlowEngine()
    for user in ("Dev", "Bot", "A", "B"):
        engine.record_trade("M", True, 1.0, user, timestamp=100.0)

    signal = engine.evaluate_momentum_signal(
        "M",
        min_unique_buyers=3,
        min_z_score=0.0,
        min_buy_ratio=0.0,
        min_net_inflow_sol=0.0,
        current_time=101.0,
        exclude_users=frozenset({"Dev", "Bot"}),
    )

    assert signal.unique_buyers == 2
    assert signal.net_sol_inflow == pytest.approx(2.0)
    assert signal.triggered is False


# --- FEAT-56: buy-flow concentration and the first curve poll ----------------------


def test_buy_flow_concentration_scores_spread_and_concentrated_flow() -> None:
    engine = OrderFlowEngine()
    assert engine.buy_flow_concentration("none") == {
        "buys": 0,
        "unique_buyers": 0,
        "top_buyer_share": 0.0,
        "wallet_diversity": 0.0,
    }
    for user in ("a", "b", "c", "d"):
        engine.record_trade("spread", True, 0.5, user, timestamp=100.0)
    engine.record_trade("spread", False, 5.0, "e", timestamp=100.0)  # sells ignored
    spread = engine.buy_flow_concentration("spread")
    assert spread["unique_buyers"] == 4
    assert spread["top_buyer_share"] == 0.25
    assert spread["wallet_diversity"] == 0.75

    for _ in range(4):
        engine.record_trade("whale", True, 2.0, "w", timestamp=100.0)
    engine.record_trade("whale", True, 0.1, "x", timestamp=100.0)
    engine.record_trade("whale", True, 3.0, "creator", timestamp=100.0)
    engine.record_trade("whale", True, 9.0, "late", timestamp=200.0)
    whale = engine.buy_flow_concentration(
        "whale", exclude_users=frozenset({"creator"}), current_time=150.0
    )
    assert whale["buys"] == 5
    assert whale["top_buyer_share"] == round(8.0 / 8.1, 4)
    assert whale["wallet_diversity"] == round((2 / 5) * (1 - 8.0 / 8.1), 4)


def test_round_trip_flow_measures_wallets_trading_against_themselves() -> None:
    """FEAT-57: matched in-and-out volume per wallet, and quick reversals."""
    engine = OrderFlowEngine()
    assert engine.round_trip_flow("none") == {
        "round_trip_wallets": 0,
        "round_trip_share": 0.0,
        "quick_flips": 0,
    }

    # Organic: four buyers, one unrelated seller.
    for user in ("a", "b", "c", "d"):
        engine.record_trade("organic", True, 0.5, user, timestamp=100.0)
    engine.record_trade("organic", False, 0.5, "e", timestamp=101.0)
    assert engine.round_trip_flow("organic")["round_trip_share"] == 0.0

    # Wash: "w" buys 1.0 and sells 1.0 within a second, twice; "a" buys 2.0.
    engine.record_trade("wash", True, 1.0, "w", timestamp=100.0)
    engine.record_trade("wash", False, 1.0, "w", timestamp=100.5)
    engine.record_trade("wash", True, 1.0, "w", timestamp=110.0)
    engine.record_trade("wash", False, 1.0, "w", timestamp=111.0)
    engine.record_trade("wash", True, 2.0, "a", timestamp=112.0)
    # Excluded and future trades don't count.
    engine.record_trade("wash", False, 9.0, "creator", timestamp=105.0)
    engine.record_trade("wash", False, 2.0, "a", timestamp=200.0)

    wash = engine.round_trip_flow(
        "wash", exclude_users=frozenset({"creator"}), current_time=150.0
    )
    assert wash["round_trip_wallets"] == 1
    # matched 2 * min(2, 2) = 4 of 6 SOL traded
    assert wash["round_trip_share"] == round(4.0 / 6.0, 4)
    # buy->sell at +0.5 s, sell->buy at +9 s (too slow), buy->sell at +1 s
    assert wash["quick_flips"] == 2
    slow = engine.round_trip_flow(
        "wash",
        exclude_users=frozenset({"creator"}),
        current_time=150.0,
        quick_flip_seconds=0.75,
    )
    assert slow["quick_flips"] == 1


def test_first_poll_is_kept_after_later_polls() -> None:
    engine = OrderFlowEngine()
    engine.watch("m", created_at=10.0, now=11.0, real_sol=0.5)
    engine.update_watch_curve("m", real_sol=2.0, market_cap_sol=33.0, now=13.0)
    engine.update_watch_curve("m", real_sol=4.0, market_cap_sol=40.0, now=15.0)
    entry = engine.get_watch("m")
    assert entry is not None
    assert entry.first_polled_real_sol == 2.0
    assert entry.first_polled_at == 13.0
    assert entry.last_real_sol == 4.0


def test_buy_timing_separates_drizzle_burst_and_random_buyers() -> None:
    engine = OrderFlowEngine(max_retention_seconds=10_000)
    # Drizzle: the same small buy every 30 s.
    for i in range(6):
        engine.record_trade("drizzle", True, 0.02, f"d{i}", timestamp=30.0 * i)
    drizzle = engine.buy_timing("drizzle")
    assert drizzle["timing_buys"] == 6
    assert drizzle["buy_gap_cv"] == 0.0 and drizzle["buy_size_cv"] == 0.0
    assert drizzle["buy_gap_median_seconds"] == 30.0
    assert drizzle["small_buy_share"] == 1.0
    assert drizzle["burst_share"] == pytest.approx(1 / 6, abs=1e-4)

    # Burst: five buys inside 2 s, then one more a minute later.
    for i, ts in enumerate((0.0, 0.5, 1.0, 1.5, 2.0, 62.0)):
        engine.record_trade("burst", True, 0.1 + i * 0.1, f"b{i}", timestamp=ts)
    burst = engine.buy_timing("burst")
    assert burst["burst_share"] == pytest.approx(5 / 6, abs=1e-4)
    assert burst["buy_gap_cv"] > 1.5
    assert burst["buy_gap_median_seconds"] == 0.5
    assert burst["small_buy_share"] == 0.0 and burst["buy_size_cv"] > 0


def test_buy_timing_skips_sells_excluded_wallets_and_later_trades() -> None:
    engine = OrderFlowEngine(max_retention_seconds=10_000)
    engine.record_trade("m", True, 1.0, "dev", timestamp=1.0)
    engine.record_trade("m", True, 0.5, "a", timestamp=2.0)
    engine.record_trade("m", False, 0.5, "a", timestamp=3.0)
    engine.record_trade("m", True, 0.5, "b", timestamp=4.0)
    engine.record_trade("m", True, 0.5, "c", timestamp=9.0)

    timing = engine.buy_timing("m", exclude_users=frozenset({"dev"}), current_time=5.0)
    # Two buys: sizes and bursts, but no gap statistics.
    assert timing == {
        "timing_buys": 2,
        "small_buy_share": 0.0,
        "buy_size_cv": 0.0,
        "burst_share": 1.0,
    }
    assert engine.buy_timing("unknown") == {"timing_buys": 0}
    even = engine.buy_timing("m", exclude_users=frozenset({"dev"}))
    assert even["buy_gap_median_seconds"] == pytest.approx(3.5)


def test_get_metrics_can_leave_out_wallets() -> None:
    engine = OrderFlowEngine()
    engine.record_trade("m", True, 2.0, "dev", timestamp=100.0)
    engine.record_trade("m", True, 0.5, "a", timestamp=101.0)

    everyone = engine.get_metrics("m", window_seconds=30, current_time=102.0)
    others = engine.get_metrics(
        "m", window_seconds=30, current_time=102.0, exclude_users=frozenset({"dev"})
    )
    assert everyone.buy_volume_sol == pytest.approx(2.5)
    assert others.buy_volume_sol == pytest.approx(0.5) and others.unique_buyers == 1
