"""Unit tests for CopyTradeEngine, WalletRegistry, TrackedWallet, and sizing models."""

import os

import pytest

from pumpfun_trading.config.env import get_env_list
from pumpfun_trading.strategies.copy_trading import (
    CopyTradeEngine,
    CopyTradeSignal,
    TrackedWallet,
    WalletRegistry,
)
from pumpfun_trading.tests.support.constants import SAMPLE_MINT


def test_tracked_wallet_creation_and_dict():
    """Verify TrackedWallet initialization, dictionary serialization, and deserialization."""
    wallet = TrackedWallet(
        address="SmartTrader11111111111111111111111111111111",
        label="Alpha Whale",
        win_rate=0.75,
        total_trades=20,
        avg_return_pct=45.5,
        risk_score=15.0,
        reference_bankroll_sol=25.0,
        max_allocation_sol=0.10,
        enabled=True,
    )

    data = wallet.to_dict()
    assert data["address"] == "SmartTrader11111111111111111111111111111111"
    assert data["label"] == "Alpha Whale"
    assert data["win_rate"] == 0.75
    assert data["total_trades"] == 20
    assert data["reference_bankroll_sol"] == 25.0
    assert data["max_allocation_sol"] == 0.10

    loaded = TrackedWallet.from_dict(data)
    assert loaded.address == wallet.address
    assert loaded.label == wallet.label
    assert loaded.win_rate == wallet.win_rate
    assert loaded.total_trades == wallet.total_trades
    assert loaded.avg_return_pct == wallet.avg_return_pct
    assert loaded.risk_score == wallet.risk_score


def test_tracked_wallet_record_trade_outcome():
    """Verify dynamic win rate and ROI recalculation upon trade outcome recording."""
    wallet = TrackedWallet(
        address="Trader1",
        win_rate=0.50,
        total_trades=2,
        avg_return_pct=10.0,
        risk_score=20.0,
    )
    # Trade 1: 100% gain (win)
    wallet.record_trade_outcome(return_pct=100.0, timestamp=1000.0)
    assert wallet.total_trades == 3
    # previous wins = 0.50 * 2 = 1.0; new wins = 2.0; win_rate = 2/3 = 0.6667
    assert wallet.win_rate == 0.6667
    # previous return = 10 * 2 = 20.0; new return = 120.0; avg_return = 40.0
    assert wallet.avg_return_pct == 40.0
    assert wallet.risk_score <= 20.0  # large gain reduces risk score

    # Trade 2: -50% loss (large drawdown)
    wallet.record_trade_outcome(return_pct=-50.0, timestamp=1010.0)
    assert wallet.total_trades == 4
    # previous wins = 2.0; win_rate = 2/4 = 0.50
    assert wallet.win_rate == 0.50
    # risk score penalized on large drawdown (< -20%)
    assert wallet.risk_score >= 20.0


def test_wallet_registry_crud_and_ranking():
    """Verify WalletRegistry operations: add, list, get, update, rank, remove, clear."""
    registry = WalletRegistry()
    assert registry.wallet_count == 0

    w1 = TrackedWallet(
        address="Addr1",
        label="Trader 1",
        win_rate=0.70,
        avg_return_pct=30.0,
        risk_score=15.0,
    )
    w2 = TrackedWallet(
        address="Addr2",
        label="Trader 2",
        win_rate=0.85,
        avg_return_pct=80.0,
        risk_score=25.0,
    )
    w3 = TrackedWallet(
        address="Addr3",
        label="Trader 3",
        win_rate=0.45,
        avg_return_pct=-10.0,
        risk_score=60.0,
        enabled=False,
    )

    registry.register_wallets([w1, w2.to_dict(), w3])
    assert registry.wallet_count == 3
    assert len(registry.list_wallets(only_enabled=True)) == 2

    # Lookup
    assert registry.get_wallet("Addr1") is not None
    assert registry.get_wallet("Addr1").label == "Trader 1"
    assert registry.get_wallet("Unknown") is None

    # Ranking
    ranked = registry.get_ranked_wallets(min_win_rate=0.60, max_risk_score=30.0)
    assert len(ranked) == 2
    assert ranked[0].address == "Addr2"  # 0.85 win rate comes first
    assert ranked[1].address == "Addr1"

    # Update performance
    registry.update_wallet_performance("Addr1", return_pct=50.0)
    assert registry.get_wallet("Addr1").total_trades == 1

    # Remove & clear
    assert registry.remove_wallet("Addr1") is True
    assert registry.get_wallet("Addr1") is None
    assert registry.wallet_count == 2
    registry.clear()
    assert registry.wallet_count == 0


def test_proportional_position_sizing():
    """Verify proportional position sizing logic with reference bankroll and caps."""
    registry = WalletRegistry()
    wallet = TrackedWallet(
        address="Whale1",
        reference_bankroll_sol=20.0,
        max_allocation_sol=0.08,
    )
    registry.register_wallet(wallet)

    engine = CopyTradeEngine(
        registry=registry,
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.05,
        sizing_mode="proportional",
        scale_factor=1.0,
    )

    # Tracked wallet places 10 SOL trade (50% of 20 SOL bankroll)
    # Computed = 0.02 * 1.0 * (10 / 20) = 0.01 SOL
    size = engine.calculate_copy_size(wallet, trade_sol=10.0)
    assert size == 0.01

    # Tracked wallet places 100 SOL trade (500% of bankroll)
    # Computed = 0.02 * 1.0 * (100 / 20) = 0.10 SOL
    # Max cap is min(wallet.max_allocation_sol=0.08, engine.max_position_size_sol=0.05) = 0.05 SOL
    size_capped = engine.calculate_copy_size(wallet, trade_sol=100.0)
    assert size_capped == 0.05


def test_scaled_and_fixed_position_sizing():
    """Verify scaled (conviction-weighted) and fixed position sizing."""
    wallet_high_win = TrackedWallet(
        address="Pro1",
        win_rate=0.75,
        max_allocation_sol=0.10,
    )

    engine_scaled = CopyTradeEngine(
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.08,
        sizing_mode="scaled",
        scale_factor=1.0,
    )
    # conviction = win_rate / 0.50 = 0.75 / 0.50 = 1.5x
    # size = 0.02 * 1.0 * 1.5 = 0.03 SOL
    assert engine_scaled.calculate_copy_size(wallet_high_win, trade_sol=5.0) == 0.03

    engine_fixed = CopyTradeEngine(
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.08,
        sizing_mode="fixed",
        scale_factor=1.5,
    )
    # fixed = 0.02 * 1.5 = 0.03 SOL
    assert engine_fixed.calculate_copy_size(wallet_high_win, trade_sol=5.0) == 0.03


def test_evaluate_copy_signal_buy_trigger():
    """Verify smart money buy event generates qualified CopyTradeSignal."""
    registry = WalletRegistry()
    wallet = TrackedWallet(
        address="SmartWalletAlpha",
        label="TopAlpha",
        win_rate=0.70,
        risk_score=15.0,
        reference_bankroll_sol=10.0,
        max_allocation_sol=0.04,
    )
    registry.register_wallet(wallet)

    engine = CopyTradeEngine(
        registry=registry,
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.05,
        min_wallet_win_rate=0.60,
        max_wallet_risk_score=30.0,
    )

    # Ingest buy event from SmartWalletAlpha
    sig = engine.record_and_evaluate(
        user="SmartWalletAlpha",
        mint="TokenMint123456789",
        sol_amount=5.0,
        is_buy=True,
    )

    assert sig.triggered is True
    assert sig.mint == "TokenMint123456789"
    assert sig.wallet_address == "SmartWalletAlpha"
    assert sig.wallet_label == "TopAlpha"
    assert sig.is_buy is True
    assert sig.sol_amount == 5.0
    # 0.02 * (5 / 10) = 0.01 SOL
    assert sig.computed_copy_size_sol == 0.01
    assert "smart_money_buy_TopAlpha" in sig.reason


def test_evaluate_copy_signal_sell_trigger():
    """Verify smart money sell event triggers exit signal when mirror_sells is active."""
    registry = WalletRegistry()
    wallet = TrackedWallet(
        address="SmartWalletAlpha",
        label="TopAlpha",
        win_rate=0.70,
        risk_score=15.0,
    )
    registry.register_wallet(wallet)

    engine = CopyTradeEngine(
        registry=registry,
        mirror_sells=True,
    )

    # Ingest sell event
    sig = engine.record_and_evaluate(
        user="SmartWalletAlpha",
        mint="TokenMint123456789",
        sol_amount=10.0,
        is_buy=False,
    )

    assert sig.triggered is True
    assert sig.is_buy is False
    assert "smart_money_sell_TopAlpha" in sig.reason

    # Test with mirror_sells = False
    engine.mirror_sells = False
    sig_disabled = engine.record_and_evaluate(
        user="SmartWalletAlpha",
        mint="TokenMint123456789",
        sol_amount=10.0,
        is_buy=False,
    )
    assert sig_disabled.triggered is False
    assert sig_disabled.reason == "mirror_sells_disabled"


def test_copy_trade_signal_disqualification_filters():
    """Verify filters disqualify untracked, low win rate, high risk, or disabled wallets."""
    registry = WalletRegistry()
    w_low_win = TrackedWallet(address="LowWin", win_rate=0.40, risk_score=20.0)
    w_high_risk = TrackedWallet(address="HighRisk", win_rate=0.80, risk_score=75.0)
    w_disabled = TrackedWallet(
        address="Disabled", win_rate=0.80, risk_score=20.0, enabled=False
    )

    registry.register_wallets([w_low_win, w_high_risk, w_disabled])

    engine = CopyTradeEngine(
        registry=registry,
        min_wallet_win_rate=0.60,
        max_wallet_risk_score=40.0,
    )

    # Untracked wallet
    sig_untracked = engine.record_and_evaluate(
        user="UnknownUser", mint="MintA", sol_amount=1.0, is_buy=True
    )
    assert sig_untracked.triggered is False
    assert sig_untracked.reason == "untracked_wallet"

    # Low win rate wallet
    sig_low_win = engine.record_and_evaluate(
        user="LowWin", mint="MintA", sol_amount=1.0, is_buy=True
    )
    assert sig_low_win.triggered is False
    assert "below_min" in sig_low_win.reason

    # High risk wallet
    sig_high_risk = engine.record_and_evaluate(
        user="HighRisk", mint="MintA", sol_amount=1.0, is_buy=True
    )
    assert sig_high_risk.triggered is False
    assert "exceeds_max" in sig_high_risk.reason

    # Disabled wallet
    sig_disabled = engine.record_and_evaluate(
        user="Disabled", mint="MintA", sol_amount=1.0, is_buy=True
    )
    assert sig_disabled.triggered is False
    assert sig_disabled.reason == "wallet_disabled"


def test_copy_trade_strategy_presets_and_config():
    """Verify strategy presets and TradingStrategy decision integration for copy-trading."""
    from pumpfun_trading.strategies.decision import TradingStrategy
    from pumpfun_trading.strategies.presets import resolve_strategy_config

    # Conservative preset
    cfg_cons = resolve_strategy_config("conservative")
    assert cfg_cons.enable_copy_trading is True
    assert cfg_cons.copy_trading_min_wallet_win_rate == 0.70
    assert cfg_cons.copy_trading_max_wallet_risk_score == 30.0
    assert cfg_cons.copy_trading_scale_factor == 0.8

    # Aggressive preset
    cfg_agg = resolve_strategy_config("aggressive")
    assert cfg_agg.enable_copy_trading is True
    assert cfg_agg.copy_trading_min_wallet_win_rate == 0.50
    assert cfg_agg.copy_trading_max_wallet_risk_score == 50.0
    assert cfg_agg.copy_trading_scale_factor == 1.5

    # Config serialization
    data = cfg_agg.to_dict()
    assert "enable_copy_trading" in data
    assert data["copy_trading_scale_factor"] == 1.5

    # Signal & Strategy decision integration
    strategy = TradingStrategy(cfg_cons)
    engine = CopyTradeEngine()
    engine.registry.register_wallet(
        TrackedWallet(
            address="Alpha1",
            win_rate=0.80,
            risk_score=20.0,
            reference_bankroll_sol=10.0,
        )
    )

    sig = strategy.evaluate_copy_trade(
        engine,
        user="Alpha1",
        mint="TokenMintXYZ",
        sol_amount=2.0,
        is_buy=True,
    )
    assert sig.triggered is True
    assert sig.is_buy is True

    # Check should_buy_copy_trade
    assert (
        strategy.should_buy_copy_trade(
            copy_trade_signal=sig,
            active_positions=0,
            buy_attempts=0,
            mint_seen_recently=False,
        )
        is True
    )

    # Reject if active positions limit reached
    assert (
        strategy.should_buy_copy_trade(
            copy_trade_signal=sig,
            active_positions=1,  # max_active_positions is 1 in conservative
            buy_attempts=0,
            mint_seen_recently=False,
        )
        is False
    )


def test_copy_trading_and_env_missing_branches():
    # Env list helper
    os.environ["PUMPFUN_TEST_LIST"] = " mint1, mint2 , mint3 "

    assert get_env_list("PUMPFUN_TEST_LIST") == ("mint1", "mint2", "mint3")
    assert get_env_list("PUMPFUN_NONEXISTENT_ENV", default=("def",)) == ("def",)

    # CopyTradeSignal to_dict
    sig = CopyTradeSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        wallet_address="Wallet111",
        wallet_label="Whale1",
        is_buy=True,
        sol_amount=1.5,
        computed_copy_size_sol=0.05,
        reason="whale_buy",
    )
    d = sig.to_dict()
    assert d["triggered"] is True
    assert d["wallet_label"] == "Whale1"

    # WalletRegistry tests
    reg = WalletRegistry()
    with pytest.raises(ValueError, match="Wallet address cannot be empty"):
        reg.register_wallet(TrackedWallet(address=""))

    w1 = TrackedWallet(
        address="W1", label="One", enabled=True, win_rate=0.75, risk_score=20.0
    )
    w2 = TrackedWallet(
        address="W2", label="Two", enabled=False, win_rate=0.40, risk_score=50.0
    )
    reg.register_wallets([w1, w2])
    assert reg.wallet_count == 2
    assert len(reg.list_wallets(only_enabled=True)) == 1
    assert len(reg.list_wallets(only_enabled=False)) == 2
    assert reg.remove_wallet("W1") is True
    assert reg.remove_wallet("W_NON") is False
    assert reg.wallet_count == 1
    reg.clear()
    assert reg.wallet_count == 0

    # CopyTradeEngine evaluations
    engine = CopyTradeEngine(
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.05,
        sizing_mode="scaled",
        min_wallet_win_rate=0.60,
        max_wallet_risk_score=40.0,
        mirror_sells=True,
        enabled=True,
    )
    # Disabled wallet
    w_dis = TrackedWallet(address="W_DIS", label="Dis", enabled=False)
    assert (
        engine.evaluate_copy_signal(w_dis, SAMPLE_MINT, 1.0, True).reason
        == "wallet_disabled"
    )

    # Low win rate
    w_low_wr = TrackedWallet(address="W_LOW", label="Low", enabled=True, win_rate=0.30)
    assert (
        "below_min"
        in engine.evaluate_copy_signal(w_low_wr, SAMPLE_MINT, 1.0, True).reason
    )

    # High risk score
    w_high_risk = TrackedWallet(
        address="W_RISK", label="Risk", enabled=True, win_rate=0.80, risk_score=80.0
    )
    assert (
        "exceeds_max"
        in engine.evaluate_copy_signal(w_high_risk, SAMPLE_MINT, 1.0, True).reason
    )

    # Mirror sells disabled
    engine_no_mirror = CopyTradeEngine(mirror_sells=False, enabled=True)
    w_good = TrackedWallet(
        address="W_GOOD", label="Good", enabled=True, win_rate=0.80, risk_score=20.0
    )
    assert (
        engine_no_mirror.evaluate_copy_signal(w_good, SAMPLE_MINT, 1.0, False).reason
        == "mirror_sells_disabled"
    )

    # Engine disabled
    engine_dis = CopyTradeEngine(enabled=False)
    assert (
        engine_dis.evaluate_copy_signal(w_good, SAMPLE_MINT, 1.0, True).reason
        == "copy_trading_disabled"
    )

    # calculate_copy_size with max_allocation <= 0
    w_good.max_allocation_sol = 0.0
    size = engine.calculate_copy_size(w_good, 1.0)
    assert size <= 0.05

    # record_and_evaluate on unregistered wallet
    assert (
        engine.record_and_evaluate("UNREGISTERED", SAMPLE_MINT, 1.0, True).triggered
        is False
    )
