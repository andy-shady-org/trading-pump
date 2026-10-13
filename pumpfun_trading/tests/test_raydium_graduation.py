"""Unit tests for Raydium graduation tracking and GraduationEngine."""

from pumpfun_trading.strategies.graduation import (
    GraduationCandidate,
    GraduationEngine,
    GraduationTracker,
    RaydiumPoolKeys,
)


def make_sample_pool_keys(
    mint: str = "TestMint1111111111111111111111111111111111",
) -> RaydiumPoolKeys:
    return RaydiumPoolKeys(
        amm_id="RaydiumAmm1111111111111111111111111111111111",
        amm_authority="RaydiumAuth111111111111111111111111111111111",
        amm_open_orders="OpenOrders1111111111111111111111111111111111",
        amm_target_orders="TargetOrders11111111111111111111111111111111",
        pool_coin_token_account="CoinVault111111111111111111111111111111111",
        pool_pc_token_account="PcVault111111111111111111111111111111111111",
        serum_program_id="srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
        serum_market="SerumMarket11111111111111111111111111111111",
        serum_bids="SerumBids11111111111111111111111111111111111",
        serum_asks="SerumAsks11111111111111111111111111111111111",
        serum_event_queue="EventQueue111111111111111111111111111111111",
        serum_coin_vault="SerumCoinVault11111111111111111111111111111",
        serum_pc_vault="SerumPcVault1111111111111111111111111111111",
        serum_vault_signer="SerumSigner1111111111111111111111111111111",
        coin_mint=mint,
        pc_mint="So11111111111111111111111111111111111111112",
        lp_mint="LpMint1111111111111111111111111111111111111",
    )


def test_raydium_pool_keys_to_and_from_dict():
    keys = make_sample_pool_keys()
    d = keys.to_dict()
    assert d["amm_id"] == "RaydiumAmm1111111111111111111111111111111111"
    assert d["coin_mint"] == "TestMint1111111111111111111111111111111111"
    assert d["pc_mint"] == "So11111111111111111111111111111111111111112"

    restored = RaydiumPoolKeys.from_dict(d)
    assert restored.amm_id == keys.amm_id
    assert restored.serum_market == keys.serum_market
    assert restored.lp_mint == keys.lp_mint


def test_graduation_candidate_model_and_dict():
    cand = GraduationCandidate(
        mint="MintA1111111111111111111111111111111111111",
        bonding_curve="CurveA111111111111111111111111111111111111",
        real_sol_reserves=42.5,
        virtual_sol_reserves=72.5,
        market_cap_sol=50.0,
        progress_pct=50.0,
    )
    d = cand.to_dict()
    assert d["mint"] == "MintA1111111111111111111111111111111111111"
    assert d["real_sol_reserves"] == 42.5
    assert d["progress_pct"] == 50.0
    assert d["is_completed"] is False
    assert d["pool_keys"] is None


def test_graduation_tracker_lifecycle_and_signals():
    tracker = GraduationTracker(
        mint="MintB1111111111111111111111111111111111111",
        bonding_curve="CurveB111111111111111111111111111111111111",
        real_sol_reserves=10.0,
        virtual_sol_reserves=40.0,
        market_cap_sol=35.0,
        target_graduation_sol=85.0,
        timestamp=1000.0,
    )

    # Initial state (10 SOL / 85 SOL ≈ 11.76%)
    assert tracker.candidate.progress_pct == 11.76
    sig_init = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_init.triggered is False
    assert sig_init.stage == "none"

    # Update reserves to 81.0 SOL (Pre-graduation trigger)
    tracker.update_reserves(
        real_sol_reserves=81.0,
        virtual_sol_reserves=111.0,
        market_cap_sol=65.0,
        timestamp=1010.0,
    )
    assert tracker.candidate.progress_pct == 95.29
    sig_pre = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_pre.triggered is True
    assert sig_pre.stage == "pre_graduation"
    assert sig_pre.real_sol_reserves == 81.0

    # With require_pool_ready=True, pre-graduation should not fire
    sig_pre_strict = tracker.evaluate_signal(
        pre_migration_threshold_sol=80.0, require_pool_ready=True
    )
    assert sig_pre_strict.triggered is False
    assert sig_pre_strict.stage == "pre_graduation"

    # Mark curve as completed
    tracker.mark_completed(timestamp=1020.0)
    assert tracker.candidate.is_completed is True
    assert tracker.candidate.completed_at == 1020.0
    assert tracker.candidate.progress_pct == 100.0

    sig_completed = tracker.evaluate_signal(pre_migration_threshold_sol=80.0)
    assert sig_completed.triggered is True
    assert sig_completed.stage == "graduated"

    # Set Raydium pool keys
    pool_keys = make_sample_pool_keys(mint="MintB1111111111111111111111111111111111111")
    tracker.set_raydium_pool(pool_keys, timestamp=1030.0)
    assert tracker.candidate.raydium_pool_id == pool_keys.amm_id
    assert tracker.candidate.pool_keys == pool_keys

    sig_ready = tracker.evaluate_signal(
        pre_migration_threshold_sol=80.0, require_pool_ready=True
    )
    assert sig_ready.triggered is True
    assert sig_ready.stage == "raydium_pool_ready"
    assert sig_ready.pool_keys is not None
    assert sig_ready.pool_keys.amm_id == pool_keys.amm_id


def test_graduation_engine_multi_token_management():
    engine = GraduationEngine(
        target_graduation_sol=85.0,
        candidate_ttl_seconds=300,
        pre_migration_threshold_sol=80.0,
    )

    t0 = 1000.0
    engine.update_bonding_curve(
        mint="Token11111111111111111111111111111111111111",
        bonding_curve="Curve11111111111111111111111111111111111111",
        real_sol_reserves=50.0,
        virtual_sol_reserves=80.0,
        market_cap_sol=55.0,
        timestamp=t0,
    )
    engine.update_bonding_curve(
        mint="Token22222222222222222222222222222222222222",
        bonding_curve="Curve22222222222222222222222222222222222222",
        real_sol_reserves=82.5,
        virtual_sol_reserves=112.5,
        market_cap_sol=68.0,
        timestamp=t0,
    )

    assert engine.tracked_candidate_count == 2
    c1 = engine.get_candidate("Token11111111111111111111111111111111111111")
    assert c1 is not None
    assert c1.progress_pct == round((50.0 / 85.0) * 100.0, 2)

    sig1 = engine.evaluate_graduation_signal(
        "Token11111111111111111111111111111111111111"
    )
    assert sig1.triggered is False

    sig2 = engine.evaluate_graduation_signal(
        "Token22222222222222222222222222222222222222"
    )
    assert sig2.triggered is True
    assert sig2.stage == "pre_graduation"

    # Untracked token evaluation
    sig_untracked = engine.evaluate_graduation_signal(
        "UnknownMint1111111111111111111111111111111"
    )
    assert sig_untracked.triggered is False
    assert sig_untracked.reason == "candidate_not_tracked"

    # Record complete event
    engine.record_complete_event(
        "Token22222222222222222222222222222222222222", timestamp=t0 + 10
    )
    c2 = engine.get_candidate("Token22222222222222222222222222222222222222")
    assert c2.is_completed is True

    # Record Raydium pool initialization
    keys2 = make_sample_pool_keys("Token22222222222222222222222222222222222222")
    engine.record_raydium_pool(
        "Token22222222222222222222222222222222222222", keys2, timestamp=t0 + 20
    )

    sig2_pool = engine.evaluate_graduation_signal(
        "Token22222222222222222222222222222222222222"
    )
    assert sig2_pool.triggered is True
    assert sig2_pool.stage == "raydium_pool_ready"
    assert sig2_pool.pool_keys is not None


def test_graduation_engine_ttl_cleanup_and_clear():
    engine = GraduationEngine(candidate_ttl_seconds=100)
    t0 = 500.0

    engine.update_bonding_curve(
        mint="StaleMint111111111111111111111111111111111111",
        bonding_curve="StaleCurve111111111111111111111111111111111",
        real_sol_reserves=20.0,
        virtual_sol_reserves=50.0,
        market_cap_sol=35.0,
        timestamp=t0,
    )
    engine.update_bonding_curve(
        mint="FreshMint111111111111111111111111111111111111",
        bonding_curve="FreshCurve111111111111111111111111111111111",
        real_sol_reserves=70.0,
        virtual_sol_reserves=100.0,
        market_cap_sol=55.0,
        timestamp=t0 + 80,
    )

    assert engine.tracked_candidate_count == 2

    # Cleanup at t0 + 120 (StaleMint updated at 500 -> 620-500 = 120 > 100 => evicted)
    evicted = engine.cleanup_expired_candidates(current_time=t0 + 120)
    assert evicted == 1
    assert engine.tracked_candidate_count == 1
    assert engine.get_candidate("StaleMint111111111111111111111111111111111111") is None
    assert (
        engine.get_candidate("FreshMint111111111111111111111111111111111111")
        is not None
    )

    engine.clear()
    assert engine.tracked_candidate_count == 0
