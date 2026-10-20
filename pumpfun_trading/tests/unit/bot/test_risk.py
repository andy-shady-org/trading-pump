"""Unit tests for ``bot/risk.py``: net PnL and cost tracking (FEAT-49)."""

from __future__ import annotations

import datetime
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.bot.risk import (
    CircuitBreakerAction,
    DailyEquityTracker,
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
    evaluate_portfolio_circuit_breaker,
    track_position_peak,
)
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.strategies.filters import TokenScreeningVerdict
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)
from pumpfun_trading.tests.support.factories import make_config

UTC = datetime.timezone.utc


def test_record_realized_trade_tracks_net_and_costs() -> None:
    tracker = DailyEquityTracker()

    tracker.record_realized_trade(-0.0021, 0.0021)  # buy: costs only
    tracker.record_realized_trade(0.0029, -0.0019)  # closing sell: rent refund

    assert tracker.realized_daily_pnl_sol == pytest.approx(0.0008)
    assert tracker.realized_daily_costs_sol == pytest.approx(0.0002)
    assert tracker.realized_daily_gross_pnl_sol == pytest.approx(0.001)
    tracker.record_realized_trade(0.5)
    assert tracker.realized_daily_costs_sol == pytest.approx(0.0002)


def test_record_withdrawal_is_not_a_drawdown_and_never_trips_breaker() -> None:
    """FEAT-42: sweeping 0.6 of 1.0 SOL out must leave drawdown at zero."""
    day = datetime.datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    tracker = DailyEquityTracker(drawdown_reference_mode="baseline")
    tracker.initialize_or_rollover(1.0, 0.0, day)

    tracker.record_withdrawal(0.6)
    tracker.record_withdrawal(-5.0)  # negative amounts are ignored

    assert tracker.starting_equity_sol == pytest.approx(0.4)
    assert tracker.peak_daily_equity_sol == pytest.approx(0.4)
    assert tracker.calculate_drawdown(0.4, 0.0, day) == 0.0
    locked, _ = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.1,
        emergency_hard_lock_hours=24,
        current_wallet_balance_sol=0.4,
        now_timestamp=day.timestamp(),
        now_utc=day,
    )
    assert locked is False
    tracker.record_withdrawal(10.0)
    assert (tracker.starting_equity_sol, tracker.peak_daily_equity_sol) == (0.0, 0.0)


def test_costs_reset_on_utc_rollover_and_round_trip() -> None:
    tracker = DailyEquityTracker()
    day1 = datetime.datetime(2026, 10, 16, 23, 0, tzinfo=UTC)
    tracker.initialize_or_rollover(1.0, 0.0, day1)
    tracker.record_realized_trade(-0.01, 0.003)

    restored = DailyEquityTracker.from_dict(tracker.to_dict())
    assert restored.realized_daily_costs_sol == pytest.approx(0.003)
    assert tracker.to_dict()["realized_daily_gross_pnl_sol"] == pytest.approx(-0.007)

    tracker.initialize_or_rollover(0.99, 0.0, day1 + datetime.timedelta(hours=2))
    assert tracker.realized_daily_pnl_sol == 0.0
    assert tracker.realized_daily_costs_sol == 0.0


def test_lock_expiry_resets_costs() -> None:
    tracker = DailyEquityTracker(
        starting_equity_sol=1.0,
        peak_daily_equity_sol=1.0,
        circuit_breaker_engaged=True,
        locked_at_timestamp=0.0,
        realized_daily_pnl_sol=-0.3,
        realized_daily_costs_sol=0.01,
        last_reset_date_utc=DailyEquityTracker.get_current_utc_date(),
    )

    tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.2,
        emergency_hard_lock_hours=1,
        current_wallet_balance_sol=0.7,
        now_timestamp=7_200.0,
    )

    assert tracker.realized_daily_costs_sol == 0.0


def test_daily_equity_tracker_initialization_and_rollover():
    tracker = DailyEquityTracker()
    assert tracker.starting_equity_sol == 0.0
    assert tracker.peak_daily_equity_sol == 0.0
    assert tracker.last_reset_date_utc == ""
    assert not tracker.circuit_breaker_engaged

    # Initial setup on day 1
    day1 = datetime.datetime(2026, 10, 12, 10, 0, 0, tzinfo=datetime.timezone.utc)
    res = tracker.initialize_or_rollover(10.0, 2.5, now_utc=day1)
    assert res is True
    assert tracker.starting_equity_sol == 12.5
    assert tracker.peak_daily_equity_sol == 12.5
    assert tracker.last_reset_date_utc == "2026-10-12"

    # Same day call should not reset
    res = tracker.initialize_or_rollover(9.0, 2.0, now_utc=day1)
    assert res is False
    assert tracker.starting_equity_sol == 12.5

    # Day 2 rollover at 00:00 UTC
    day2 = datetime.datetime(2026, 10, 13, 0, 1, 0, tzinfo=datetime.timezone.utc)
    tracker.record_realized_trade(1.5)
    assert tracker.realized_daily_pnl_sol == 1.5

    res = tracker.initialize_or_rollover(11.0, 1.0, now_utc=day2)
    assert res is True
    assert tracker.starting_equity_sol == 12.0
    assert tracker.peak_daily_equity_sol == 12.0
    assert tracker.realized_daily_pnl_sol == 0.0
    assert tracker.last_reset_date_utc == "2026-10-13"


def test_equity_updates_and_drawdown_calculation():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # Valuation rises
    current_eq, dd = tracker.update_valuation(12.0, 0.0, now_utc=day)
    assert current_eq == 12.0
    assert tracker.peak_daily_equity_sol == 12.0
    assert dd == 0.0

    # Valuation drops to 10.2 SOL from peak of 12.0 SOL
    # Drop = 1.8 SOL -> Drawdown = 1.8 / 12.0 (peak) = 15%
    current_eq, dd = tracker.update_valuation(10.2, 0.0, now_utc=day)
    assert current_eq == 10.2
    assert tracker.peak_daily_equity_sol == 12.0
    assert pytest.approx(dd, 0.001) == 0.15


@pytest.mark.regression("BUG-12")
def test_drawdown_calculation_with_low_baseline_high_peak():
    """
    Regression test for BUG-12: Small starting baseline (0.20 SOL) with large peak (37.3841 SOL).
    A minor pullback from peak (e.g. 0.6904 SOL to 36.6937 SOL) must be ~1.85% drawdown,
    NOT >100% or falsely tripping the circuit breaker limit (20.00%).
    """
    tracker = DailyEquityTracker()
    assert tracker.calculate_drawdown(0.0, 0.0) == 0.0

    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(0.20, 0.0, now_utc=day)
    assert tracker.starting_equity_sol == 0.20
    assert tracker.peak_daily_equity_sol == 0.20

    # Equity grows to 37.3841 SOL
    current_eq, dd = tracker.update_valuation(37.3841, 0.0, now_utc=day)
    assert current_eq == 37.3841
    assert tracker.peak_daily_equity_sol == 37.3841
    assert dd == 0.0

    # Equity pulls back to 36.6937 SOL (drop = 0.6904 SOL)
    current_eq, dd = tracker.update_valuation(36.6937, 0.0, now_utc=day)
    assert current_eq == 36.6937
    assert tracker.peak_daily_equity_sol == 37.3841
    # 0.6904 / 37.3841 = 0.0184676... (~1.85%)
    expected_dd = (37.3841 - 36.6937) / 37.3841
    assert pytest.approx(dd, 1e-6) == expected_dd
    assert dd < 0.02  # Less than 2%

    # Evaluate circuit breaker with 20% max allowed limit
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=36.6937,
        open_positions_valuation_sol=0.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged


def test_circuit_breaker_trigger_and_auto_unlock():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # 1. Normal trading within limits (5% drop from peak 10.0 -> 9.5 SOL)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=9.5,
        open_positions_valuation_sol=0.0,
        now_timestamp=1000.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged

    # 2. Severe loss breaching 15% limit (peak 10.0 -> 8.0 SOL = 20% drawdown)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0,
        now_utc=day,
    )
    assert locked
    assert "portfolio drawdown 20.00% exceeded" in reason
    assert tracker.circuit_breaker_engaged
    assert tracker.locked_at_timestamp == 1100.0
    assert tracker.total_lock_count == 1

    # 3. Subsequent check while lock duration is active (e.g., after 1 hour = 3600s)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0 + 3600.0,
        now_utc=day,
    )
    assert locked
    assert "portfolio drawdown 20.00% exceeded" in reason

    # 4. Auto-unlock after 24 hours (24 * 3600 = 86400s)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0 + 86400.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged
    assert tracker.starting_equity_sol == 8.0
    assert tracker.peak_daily_equity_sol == 8.0


def test_circuit_breaker_manual_reset():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # Trip breaker
    tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.10,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.5,
        now_timestamp=1000.0,
        now_utc=day,
    )
    assert tracker.circuit_breaker_engaged

    # Manual reset with new baseline
    tracker.reset_circuit_breaker(force=True, new_baseline_sol=8.5)
    assert not tracker.circuit_breaker_engaged
    assert tracker.locked_at_timestamp is None
    assert tracker.lock_reason == ""
    assert tracker.starting_equity_sol == 8.5
    assert tracker.peak_daily_equity_sol == 8.5


def test_daily_equity_tracker_serialization():
    tracker = DailyEquityTracker(
        starting_equity_sol=15.0,
        peak_daily_equity_sol=18.5,
        realized_daily_pnl_sol=3.5,
        last_reset_date_utc="2026-10-12",
        circuit_breaker_engaged=True,
        locked_at_timestamp=1700000000.0,
        lock_reason="test lock",
        total_lock_count=2,
    )
    data = tracker.to_dict()
    assert data["starting_equity_sol"] == 15.0
    assert data["peak_daily_equity_sol"] == 18.5
    assert data["circuit_breaker_engaged"] is True

    restored = DailyEquityTracker.from_dict(data)
    assert restored.starting_equity_sol == 15.0
    assert restored.peak_daily_equity_sol == 18.5
    assert restored.realized_daily_pnl_sol == 3.5
    assert restored.last_reset_date_utc == "2026-10-12"
    assert restored.circuit_breaker_engaged is True
    assert restored.locked_at_timestamp == 1700000000.0
    assert restored.lock_reason == "test lock"
    assert restored.total_lock_count == 2


def test_evaluate_portfolio_circuit_breaker_with_bot_mock():
    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 10.0
            self.active_positions = {
                "mintA": {
                    "cost_sol": 2.0,
                    "entry_sol": 2.0,
                    "entry_market_cap": 2.0,
                    "current_market_cap": 2.0,
                },
            }
            self.config = make_config(
                dry_run=False,
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # Initial evaluation sets baseline to 12.0 SOL (10.0 wallet + 2.0 position)
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert reason == ""
    assert bot.daily_equity_tracker.starting_equity_sol == 12.0
    assert check_daily_drawdown(bot) is True

    # Drop position valuation to 0.0 SOL and wallet to 9.5 SOL -> total equity 9.5 SOL (drop of 2.5 SOL on 12.0 = 20.8%)
    bot.wallet_balance_sol = 9.5
    bot.active_positions["mintA"]["current_market_cap"] = 0.0

    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert is_breached
    assert "portfolio drawdown" in reason
    assert "circuit breaker:" in bot._last_event
    assert check_daily_drawdown(bot) is False


@pytest.mark.regression("BUG-15")
def test_circuit_breaker_realistic_pumpfun_lifecycle():
    """
    Regression test for BUG-15:
    Realistic trade lifecycle on Pump.fun (~27.96 SOL initial market cap).
    Opening a position (0.01 SOL cost) and subsequently closing it with a small profit
    must not trigger a false-positive 99%+ portfolio drawdown circuit breaker lock.
    """

    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 0.10
            self.active_positions = {}
            self.config = make_config(
                dry_run=False,
                buy_amount_sol=0.01,
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # 1. Starting state: wallet = 0.10 SOL, no positions -> baseline equity = 0.10 SOL
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.starting_equity_sol == 0.10
    assert bot.daily_equity_tracker.peak_daily_equity_sol == 0.10

    # 2. Buy token: wallet drops to 0.09 SOL, position opened with 0.01 SOL cost at 27.95899 SOL MC
    mint = "PumpFunToken111111111111111111111111111111"
    bot.wallet_balance_sol = 0.09
    bot.active_positions[mint] = {
        "cost_sol": 0.01,
        "entry_sol": 0.01,
        "entry_market_cap": 27.95899,
        "current_market_cap": 27.95899,
        "token_amount": 100_000_000,
    }

    # Evaluate circuit breaker: open value is 0.01 SOL, total equity is 0.10 SOL
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(
        0.10, rel=1e-5
    )

    # 3. Market cap increases slightly to 28.50 SOL (+1.93%)
    bot.active_positions[mint]["current_market_cap"] = 28.50
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    expected_peak = 0.09 + (0.01 * (28.50 / 27.95899))
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(
        expected_peak, rel=1e-5
    )

    # 4. Position closes with 0.0102 SOL proceeds (+2% profit returned to wallet)
    bot.active_positions.pop(mint)
    bot.wallet_balance_sol = 0.1002

    # Evaluate circuit breaker after trade close: total equity = 0.1002 SOL (drawdown = 0.0%)
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert reason == ""
    assert bot.daily_equity_tracker.circuit_breaker_engaged is False


@pytest.mark.regression("BUG-21")
def test_circuit_breaker_partial_exit_lifecycle():
    """
    Regression test for BUG-21:
    Verifies that when a position executes a partial exit (e.g. 50% sold at 2.0x),
    the circuit breaker evaluates remaining holding value accurately (scaled by 50%),
    preventing over-inflation of peak equity and avoiding false drawdown spikes when the
    remainder is subsequently closed.
    """

    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 0.90
            self.config = make_config(
                dry_run=False,
                buy_amount_sol=0.10,
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.position_manager = PositionManager(self.config)
            self.active_positions = self.position_manager._positions
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # 1. Starting baseline: wallet = 0.90 SOL + buy 0.10 SOL -> baseline = 1.00 SOL
    mint = "PartialPumpToken11111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint,
        token_amount=1_000_000,
        cost_sol=0.10,
        entry_market_cap=30.0,
    )
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.starting_equity_sol == pytest.approx(1.00)
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.00)

    # 2. Market cap rises to 60.0 SOL (2.0x) -> open value = 0.20 SOL -> peak equity = 0.90 + 0.20 = 1.10 SOL
    bot.position_manager.update_price(mint, 60.0)
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.10)

    # 3. Tier 1 partial exit: sell 50% (500k tokens), returning 0.10 SOL to wallet -> wallet = 1.00 SOL
    closed, rem = bot.position_manager.record_sell(
        mint, sold_tokens=500_000, proceeds_sol=0.10, target_tier=1, is_partial=True
    )
    assert not closed
    assert rem == 500_000
    bot.wallet_balance_sol = 1.00

    # With BUG-21 fixed: remaining open value = 0.05 * (60 / 30) = 0.10 SOL
    # Total equity = 1.00 (wallet) + 0.10 (open) = 1.10 SOL (exact match to peak!)
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.10)
    assert bot.daily_equity_tracker.calculate_drawdown(
        bot.wallet_balance_sol, bot.position_manager.calculate_total_open_value()
    ) == pytest.approx(0.0)

    # 4. Final close of remaining 50% tokens at 60.0 SOL (yielding 0.10 SOL -> wallet = 1.10 SOL)
    bot.position_manager.record_sell(
        mint, sold_tokens=500_000, proceeds_sol=0.10, is_partial=False
    )
    bot.wallet_balance_sol = 1.10
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.circuit_breaker_engaged is False


async def test_trading_bot_circuit_breaker_liquidates_and_locks(tmp_path):
    from unittest.mock import MagicMock

    status_file = tmp_path / "status.json"
    audit_file = tmp_path / "audit.jsonl"

    config = make_config(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        auto_liquidate_on_circuit_breaker=True,
        dry_run=True,
    )
    bot = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot.alert_enabled = True
    bot._send_alert = MagicMock()

    # Seed initial position and baseline (baseline = 10.0 + 2.0 = 12.0 SOL)
    mint = "TestMint1111111111111111111111111111111111"
    bot.wallet_balance_sol = 10.0
    bot.active_positions[mint] = {
        "name": "TestToken",
        "entry_market_cap": 2.0,
        "current_market_cap": 2.0,
        "peak_market_cap": 2.0,
        "token_amount": 1_000_000,
        "initial_token_amount": 1_000_000,
        "cost_sol": 2.0,
        "entry_sol": 2.0,
    }
    bot.daily_equity_tracker.initialize_or_rollover(10.0, 2.0)

    # 1. Update with minor drop (mc = 1.8 SOL -> total equity 11.8 / 12.0 = ~1.6% dd)
    update = BondingCurveStateUpdate(
        mint=mint,
        bonding_curve_pubkey="Curve111111111111111111111111111111111111111",
        slot=100,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=1.8,
        timestamp=1000.0,
    )
    await bot._handle_bonding_curve_state_update(update)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged
    assert mint in bot.active_positions

    # 2. Update with catastrophic drop (mc = 0.05 SOL, wallet drops to 9.5 SOL -> total equity 9.55 / 12.0 = 20.4% dd > 15%)
    bot.wallet_balance_sol = 9.5
    update_crash = BondingCurveStateUpdate(
        mint=mint,
        bonding_curve_pubkey="Curve111111111111111111111111111111111111111",
        slot=101,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.0001,
        market_cap_sol=0.05,
        timestamp=1001.0,
    )
    await bot._handle_bonding_curve_state_update(update_crash)

    # Verify circuit breaker engaged, position emergency liquidated, alert sent
    assert bot.daily_equity_tracker.circuit_breaker_engaged
    assert mint not in bot.active_positions
    bot._send_alert.assert_called()

    # 3. New candidate token rejected immediately while circuit breaker locked
    candidate_mint = "CandidateMint22222222222222222222222222pump"
    update_candidate = BondingCurveStateUpdate(
        mint=candidate_mint,
        bonding_curve_pubkey="Curve222222222222222222222222222222222222222",
        slot=102,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.005,
        market_cap_sol=10.0,
        timestamp=1002.0,
    )
    await bot._handle_bonding_curve_state_update(update_candidate)
    assert candidate_mint not in bot.active_positions
    assert bot._last_event == "circuit_breaker_active"

    # Also via new token event
    await bot._handle_new_token_event({"mint": candidate_mint, "marketCapSol": 10.0})
    assert candidate_mint not in bot.active_positions
    assert bot._last_event == "circuit_breaker_active"

    # 4. Manual operator reset
    bot.reset_circuit_breaker(force=True)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged


async def test_trading_bot_circuit_breaker_snapshot_persistence_and_restore(tmp_path):

    status_file = tmp_path / "status.json"
    audit_file = tmp_path / "audit.jsonl"

    config = make_config(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        dry_run=True,
    )
    bot = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot.daily_equity_tracker.circuit_breaker_engaged = True
    bot.daily_equity_tracker.lock_reason = "drawdown test limit breached"
    bot.daily_equity_tracker.starting_equity_sol = 20.0
    bot.daily_equity_tracker.peak_daily_equity_sol = 22.0
    bot.daily_equity_tracker.last_reset_date_utc = (
        DailyEquityTracker.get_current_utc_date()
    )
    bot.wallet_balance_sol = 20.0
    bot._write_status_snapshot()

    assert status_file.exists()

    # Create new bot instance and verify safe_startup restores lock state
    bot2 = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot2.safe_startup()
    assert bot2.daily_equity_tracker.circuit_breaker_engaged is True
    assert bot2.daily_equity_tracker.starting_equity_sol == 20.0
    assert bot2.daily_equity_tracker.peak_daily_equity_sol == 22.0


async def test_trading_bot_trade_event_triggers_circuit_breaker():
    from unittest.mock import MagicMock

    config = make_config(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        dry_run=True,
    )
    bot = TradingBot("1" * 64, "https://mock.rpc", config=config)
    bot.alert_enabled = True
    bot._send_alert = MagicMock()

    mint = "TradeEventMint1111111111111111111111111111"
    bot.wallet_balance_sol = 8.0
    bot.active_positions[mint] = {
        "name": "TokenTrade",
        "entry_market_cap": 2.0,
        "current_market_cap": 2.0,
        "peak_market_cap": 2.0,
        "token_amount": 1_000_000,
        "cost_sol": 2.0,
        "entry_sol": 2.0,
    }
    bot.daily_equity_tracker.initialize_or_rollover(8.0, 2.0)  # baseline = 10.0 SOL

    # Severe dump via TradeEventUpdate: virtual sol reserves drop
    update = TradeEventUpdate(
        mint=mint,
        sol_amount_lamports=1_000_000_000,
        token_amount=1000,
        is_buy=False,
        user="Seller111",
        timestamp=1000,
        virtual_sol_reserves=50_000,  # 0.00005 SOL -> 0.05 SOL market cap
        virtual_token_reserves=1_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
        slot=12345,
        signature="sig1",
        received_at=1000.0,
    )
    await bot._handle_trade_event_update(update)
    assert bot.daily_equity_tracker.circuit_breaker_engaged


@pytest.mark.regression("BUG-44")
async def test_circuit_breaker_edge_cases_and_liquidation_branches():
    from unittest.mock import MagicMock

    from pumpfun_trading.bot.run import TradingBot

    config = make_config(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        auto_liquidate_on_circuit_breaker=True,
        dry_run=True,
    )
    bot = TradingBot("1" * 64, "https://mock.rpc", config=config)
    bot.alert_enabled = False

    # 1. Reset circuit breaker without alert_enabled
    bot.daily_equity_tracker.circuit_breaker_engaged = True
    bot.reset_circuit_breaker(force=True)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged

    # 2. _liquidate_all_positions when sell fails vs succeeds
    mint1 = "Mint1111111111111111111111111111111111111"
    mint2 = "Mint2222222222222222222222222222222222222"
    bot.active_positions[mint1] = {"name": "Token1", "entry_market_cap": 1.0}
    bot.active_positions[mint2] = {"name": "Token2", "entry_market_cap": 1.0}

    bot._sell_token = AsyncMock(side_effect=[True, False])
    liquidated = await bot._liquidate_all_positions(reason="test_liq")
    assert liquidated == [mint1]

    # 3. CompleteEventUpdate for mint not in active_positions vs in active_positions
    complete_update_missing = CompleteEventUpdate(
        mint="NotInPos1111111111111111111111111111111111",
        user="User11111111111111111111111111111111111111",
        bonding_curve="Curve1111111111111111111111111111111111111",
        timestamp=1000,
        slot=100,
    )
    await bot._handle_complete_event_update(complete_update_missing)

    bot.active_positions[mint1] = {"name": "Token1", "entry_market_cap": 1.0}
    complete_update_active = CompleteEventUpdate(
        mint=mint1,
        user="User11111111111111111111111111111111111111",
        bonding_curve="Curve1111111111111111111111111111111111111",
        timestamp=1001,
        slot=101,
    )
    bot._sell_token = AsyncMock(return_value=True)
    await bot._handle_complete_event_update(complete_update_active)
    # BUG-44/123: marked migrating, so _sell_token routes the exit to PumpSwap
    # (or waits for the pool) instead of selling on the completed curve.
    bot._sell_token.assert_awaited_once_with(mint1, reason="bonding_curve_graduated")
    assert mint1 in bot._migrating_mints

    # 4. _handle_new_token_event missing mint and stopped requested
    await bot._handle_new_token_event({})
    bot._stop_requested = True
    await bot._handle_new_token_event({"mint": mint1})
    bot._stop_requested = False

    # 5. _handle_bonding_curve_state_update candidate buy success branch
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    mint_candidate = "BuyCandidate11111111111111111111111111111"
    update_buy = BondingCurveStateUpdate(
        mint=mint_candidate,
        bonding_curve_pubkey="CurveBuy1111111111111111111111111111111111",
        slot=200,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.005,
        market_cap_sol=12.0,
        timestamp=1000.0,
    )
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=mint_candidate, passed=True, risk_score=10.0, reasons=[]
        )
    )
    bot._should_buy = MagicMock(return_value=True)
    bot._buy_token = AsyncMock(return_value=True)
    bot.wallet_balance_sol = 10.0
    await bot._handle_bonding_curve_state_update(update_buy)
    bot._buy_token.assert_called_once()


def test_effective_baseline_ratchet_calculation() -> None:
    tracker = DailyEquityTracker(
        starting_equity_sol=0.20,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.50,
    )
    # Initially, with 0 realized PnL, effective baseline is starting equity
    assert tracker.effective_baseline_sol == pytest.approx(0.20)

    # Realized loss does not degrade baseline below starting equity
    tracker.record_realized_trade(-0.05)
    assert tracker.realized_daily_pnl_sol == pytest.approx(-0.05)
    assert tracker.effective_baseline_sol == pytest.approx(0.20)

    # Reset realized PnL and simulate positive realized profit
    tracker.realized_daily_pnl_sol = 0.1616
    # 0.20 + 0.50 * 0.1616 = 0.2808 SOL
    assert tracker.effective_baseline_sol == pytest.approx(0.2808)


def test_pixpad_parabolic_runner_scenario() -> None:
    """
    Validates the exact empirical scenario from /runtime/test-data/ (pixpad trade):
    - Starting capital: 0.20 SOL
    - Token explodes 22.89x; TP1 realized +0.1144 SOL, TP2 realized +0.0572 SOL (total +0.1616 SOL)
    - Peak total equity reaches 0.3244 SOL
    - Moonbag retraces dropping equity to 0.2572 SOL (20.72% pullback)
    - Under adaptive_ratchet with 35% profit tolerance, bot does NOT trigger emergency liquidation or lock out.
    """
    tracker = DailyEquityTracker(
        starting_equity_sol=0.20,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.50,
        profit_drawdown_tolerance_pct=0.35,
    )
    # Bank profits from TP1 and TP2
    tracker.record_realized_trade(0.1144)
    tracker.record_realized_trade(0.0572)
    assert tracker.realized_daily_pnl_sol == pytest.approx(0.1716)

    # Peak equity recorded during explosive moonbag pump
    tracker.update_valuation(
        current_wallet_balance_sol=0.20 + 0.1716, open_positions_valuation_sol=0.1528
    )
    assert tracker.peak_daily_equity_sol == pytest.approx(0.5244)

    # Simulate pullback to 0.3800 SOL total equity (well above starting 0.20 SOL)
    # Drawdown from peak: (0.5244 - 0.3800) / 0.5244 = 27.53% (< 35% tolerance)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=0.30,
        open_positions_valuation_sol=0.08,
    )
    assert not locked
    assert reason == ""
    assert tracker.circuit_breaker_action == CircuitBreakerAction.NONE

    # Test the exact numbers from the test report:
    tracker2 = DailyEquityTracker(
        starting_equity_sol=0.20,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.50,
        profit_drawdown_tolerance_pct=0.35,
    )
    tracker2.peak_daily_equity_sol = 0.3244
    tracker2.record_realized_trade(0.1616)

    # Current equity settles at 0.2572 SOL (20.72% pullback)
    locked2, reason2 = tracker2.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=0.20,
        open_positions_valuation_sol=0.0572,
    )
    assert not locked2
    assert reason2 == ""
    assert tracker2.circuit_breaker_action == CircuitBreakerAction.NONE


def test_profit_run_zone_soft_halt_trigger() -> None:
    """When in profit run zone, a pullback exceeding profit_drawdown_tolerance_pct engages HALT_NEW_BUYS."""
    tracker = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.50,
        profit_drawdown_tolerance_pct=0.30,  # 30% tolerance
    )
    tracker.peak_daily_equity_sol = 2.0
    tracker.record_realized_trade(0.80)

    # Equity pulls back to 1.30 SOL (35% drop from peak of 2.0 SOL, but still > starting 1.0 SOL)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=1.30,
        open_positions_valuation_sol=0.0,
    )
    assert locked
    assert "profit run retracement" in reason
    assert tracker.circuit_breaker_action == CircuitBreakerAction.HALT_NEW_BUYS


def test_principal_protection_zone_emergency_liquidate() -> None:
    """When equity drops below starting capital by more than max_daily_drawdown_pct, EMERGENCY_LIQUIDATE is engaged."""
    tracker = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.50,
    )
    # Equity drops to 0.75 SOL (25% loss from starting 1.0 SOL > 20% limit)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=0.75,
        open_positions_valuation_sol=0.0,
    )
    assert locked
    assert "portfolio drawdown" in reason
    assert tracker.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE


def test_baseline_and_trailing_hwm_modes() -> None:
    # 1. Baseline mode only looks at starting capital loss
    tracker_baseline = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="baseline",
    )
    tracker_baseline.peak_daily_equity_sol = 5.0
    # Drop from 5.0 to 1.5 is a 70% peak drop, but equity is 1.5 > starting 1.0
    locked, _ = tracker_baseline.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=1.5,
        open_positions_valuation_sol=0.0,
    )
    assert not locked

    # Drop to 0.75 is a 25% loss from starting 1.0 -> trips
    locked2, reason2 = tracker_baseline.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=0.75,
        open_positions_valuation_sol=0.0,
    )
    assert locked2
    assert "portfolio principal loss" in reason2
    assert (
        tracker_baseline.circuit_breaker_action
        == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )

    # 2. Legacy Trailing HWM mode trips on any peak-to-trough drop > limit
    tracker_hwm = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="trailing_hwm",
    )
    tracker_hwm.peak_daily_equity_sol = 2.0
    # Drop from 2.0 to 1.5 is a 25% drop > 20% limit -> trips immediately
    locked_hwm, reason_hwm = tracker_hwm.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=1.5,
        open_positions_valuation_sol=0.0,
    )
    assert locked_hwm
    assert "portfolio drawdown" in reason_hwm
    assert (
        tracker_hwm.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )


def test_daily_equity_tracker_serialization_and_reset() -> None:
    tracker = DailyEquityTracker(
        starting_equity_sol=0.5,
        peak_daily_equity_sol=1.2,
        realized_daily_pnl_sol=0.4,
        drawdown_reference_mode="adaptive_ratchet",
        profit_ratchet_ratio=0.5,
        profit_drawdown_tolerance_pct=0.35,
        circuit_breaker_action=CircuitBreakerAction.HALT_NEW_BUYS,
        last_reset_date_utc="2026-10-14",
        circuit_breaker_engaged=True,
        lock_reason="test soft halt",
        total_lock_count=1,
    )
    data = tracker.to_dict()
    assert data["effective_baseline_sol"] == pytest.approx(0.7)
    assert data["circuit_breaker_action"] == "halt_new_buys"

    restored = DailyEquityTracker.from_dict(data)
    assert restored.starting_equity_sol == 0.5
    assert restored.circuit_breaker_action == CircuitBreakerAction.HALT_NEW_BUYS
    assert restored.effective_baseline_sol == pytest.approx(0.7)

    # Test manual reset
    restored.reset_circuit_breaker(new_baseline_sol=1.0)
    assert not restored.circuit_breaker_engaged
    assert restored.circuit_breaker_action == CircuitBreakerAction.NONE
    assert restored.starting_equity_sol == 1.0


def test_evaluate_portfolio_circuit_breaker_integration() -> None:
    class MockBot:
        def __init__(self) -> None:
            self.config = make_config(
                dry_run=False,
                max_daily_drawdown_pct=0.20,
                emergency_hard_lock_hours=24.0,
                drawdown_reference_mode="adaptive_ratchet",
                profit_drawdown_tolerance_pct=0.35,
            )
            self.daily_equity_tracker = DailyEquityTracker(
                starting_equity_sol=1.0,
                peak_daily_equity_sol=1.0,
            )
            self.wallet_balance_sol = 1.0
            self.active_positions: dict[str, Any] = {}
            self._last_event = ""

    bot = MockBot()
    # Within safe limits
    is_locked, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_locked
    assert check_daily_drawdown(bot) is True

    # Drop balance to 0.70 SOL (30% principal loss)
    bot.wallet_balance_sol = 0.70
    is_locked, reason = evaluate_portfolio_circuit_breaker(bot)
    assert is_locked
    assert "portfolio drawdown" in reason
    assert check_daily_drawdown(bot) is False


async def test_bot_circuit_breaker_two_tier_actions() -> None:

    bot = TradingBot(
        private_key_b58="3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLyKfmogN5328W5REGLxmGfV5nCeqvE8j5Fh8n2xJvTfH24x9C8eZ56Tz",
        rpc_url="http://127.0.0.1:8899",
        dry_run=True,
        config=make_config(
            dry_run=False,
            max_daily_drawdown_pct=0.20,
            drawdown_reference_mode="adaptive_ratchet",
            profit_drawdown_tolerance_pct=0.35,
            auto_liquidate_on_circuit_breaker=True,
        ),
    )
    bot.daily_equity_tracker.starting_equity_sol = 1.0
    bot.daily_equity_tracker.peak_daily_equity_sol = 2.0
    bot.daily_equity_tracker.realized_daily_pnl_sol = 0.8
    bot.wallet_balance_sol = (
        1.2  # 40% pullback from peak 2.0 -> soft halt HALT_NEW_BUYS
    )

    liquidated_mints: list[str] = []

    async def mock_liquidate(reason: str = "") -> list[str]:
        liquidated_mints.append("liquidated")
        return ["liquidated"]

    bot._liquidate_all_positions = mock_liquidate  # type: ignore

    # Trigger circuit breaker check
    tripped = await bot._check_and_enforce_circuit_breaker()
    assert tripped is True
    # For HALT_NEW_BUYS, emergency liquidation should NOT have been called!
    assert len(liquidated_mints) == 0
    assert (
        bot.daily_equity_tracker.circuit_breaker_action
        == CircuitBreakerAction.HALT_NEW_BUYS
    )

    # Now drop equity to 0.70 SOL (breach of principal floor 1.0 * (1 - 0.20) = 0.80 SOL)
    bot.wallet_balance_sol = 0.70
    bot.active_positions["tokenA"] = {"cost_sol": 0.01}
    bot.daily_equity_tracker.circuit_breaker_engaged = False  # Reset for check

    tripped2 = await bot._check_and_enforce_circuit_breaker()
    assert tripped2 is True
    assert (
        bot.daily_equity_tracker.circuit_breaker_action
        == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )
    assert len(liquidated_mints) == 1
    assert bot._risk_killed is True


@pytest.mark.regression("BUG-30")
async def test_dry_run_simulated_cash_flow_and_circuit_breaker_resilience() -> None:
    """
    Validates BUG-30 fix:
    - In dry_run mode, buying decrements wallet_balance_sol and selling increments wallet_balance_sol.
    - Prevents false-positive circuit breaker trips after profitable runner trades.
    """

    bot = TradingBot(
        private_key_b58="3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLyKfmogN5328W5REGLxmGfV5nCeqvE8j5Fh8n2xJvTfH24x9C8eZ56Tz",
        rpc_url="http://127.0.0.1:8899",
        dry_run=True,
        config=make_config(
            dry_run=False,
            buy_amount_sol=0.01,
            max_daily_drawdown_pct=0.20,
            drawdown_reference_mode="adaptive_ratchet",
            profit_ratchet_ratio=0.50,
            profit_drawdown_tolerance_pct=0.35,
        ),
    )
    # Set starting balance and initialize equity tracker
    bot.wallet_balance_sol = 0.20
    bot.daily_equity_tracker.initialize_or_rollover(0.20, 0.0)

    # 1. Buy Token 1 (cost 0.01 SOL)
    mint1 = "Stockguy1111111111111111111111111111111111"
    buy_ok = await bot._buy_token(mint1, market_cap_sol=30.0, token_name="Stockguy")
    assert buy_ok is True
    # Paper wallets also pay the modelled fee, tip and token-account rent (FEAT-49).
    buy_costs = bot._trade_ledger[-1]["costs_sol"]
    assert buy_costs > 0
    assert bot.wallet_balance_sol == pytest.approx(0.19 - buy_costs)
    assert mint1 in bot.active_positions
    fee_factor = bot._paper_round_trip_fee_factor()

    # 2. Simulate explosive 22.3x price surge (market cap 30.0 -> 669.0 SOL)
    bot.position_manager.update_price(mint1, 669.0)
    # Peak equity during pump
    open_val = bot.position_manager.calculate_total_open_value()
    bot.daily_equity_tracker.update_valuation(bot.wallet_balance_sol, open_val)
    assert bot.daily_equity_tracker.peak_daily_equity_sol >= 0.40

    # 3. Sell 50% partial exit (TP1)
    sold_tp1 = await bot._sell_token(
        mint1, sell_fraction=0.50, reason="take_profit_tier1", target_tier=1
    )
    assert sold_tp1 is True
    # Proceeds: (0.01 * 0.5) * (669.0 / 30.0) = 0.1115 SOL before protocol fees
    half_proceeds = 0.1115 * fee_factor
    tp1_costs = bot._trade_ledger[-1]["costs_sol"]
    expected_wallet = 0.19 - buy_costs + half_proceeds - tp1_costs
    assert bot.wallet_balance_sol == pytest.approx(expected_wallet)

    # 4. Sell full remaining exit (Moonbag)
    sold_full = await bot._sell_token(mint1, sell_fraction=1.0, reason="timeout_exit")
    assert sold_full is True
    assert mint1 not in bot.active_positions
    # Remaining 50% proceeds; the full exit refunds the token-account rent.
    exit_costs = bot._trade_ledger[-1]["costs_sol"]
    assert exit_costs < 0
    expected_wallet += half_proceeds - exit_costs
    assert bot.wallet_balance_sol == pytest.approx(expected_wallet)
    total_costs = buy_costs + tp1_costs + exit_costs
    assert bot.daily_equity_tracker.realized_daily_pnl_sol == pytest.approx(
        2 * half_proceeds - 0.01 - total_costs
    )

    # 5. Open new position (cost 0.01 SOL)
    mint2 = "NextToken2222222222222222222222222222222222"
    buy_ok2 = await bot._buy_token(mint2, market_cap_sol=30.0, token_name="NextToken")
    assert buy_ok2 is True
    assert bot.wallet_balance_sol == pytest.approx(
        expected_wallet - 0.01 - bot._trade_ledger[-1]["costs_sol"]
    )

    # 6. Evaluate circuit breaker
    tripped = await bot._check_and_enforce_circuit_breaker()
    assert tripped is False
    assert not bot.daily_equity_tracker.circuit_breaker_engaged
    assert bot.daily_equity_tracker.circuit_breaker_action == CircuitBreakerAction.NONE
    assert bot._risk_killed is False


def test_bot_risk_track_position_peak():
    class DummyBot:
        def __init__(self):
            self.active_positions = {
                "mint_123": {
                    "entry_market_cap": 10.0,
                    "current_market_cap": 10.0,
                }
            }

    bot = DummyBot()
    peak = track_position_peak(bot, mint="mint_123", current_market_cap=25.0)
    assert peak == 25.0
    assert bot.active_positions["mint_123"]["peak_market_cap"] == 25.0
    assert bot.active_positions["mint_123"]["current_market_cap"] == 25.0

    # Non-existent mint returns market cap safely
    peak_missing = track_position_peak(
        bot, mint="missing_mint", current_market_cap=12.0
    )
    assert peak_missing == 12.0


def test_risk_limits_checks():
    bot = MagicMock()
    bot.config = make_config(
        dry_run=False,
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.3,
        buy_amount_sol=0.1,
        max_loss_per_trade_sol=0.05,
        max_daily_drawdown_pct=0.20,
    )
    bot._last_event = ""

    current_positions = {
        "Mint1": {
            "cost_sol": 0.2,
            "entry_sol": 0.2,
            "entry_market_cap": 28.0,
            "current_market_cap": 28.0,
        },
    }

    # 1. Successful check
    assert check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )

    # 2. Exceeds max total exposure (0.2 + 0.9 = 1.1 > 1.0)
    assert not check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.9,
        current_positions=current_positions,
    )
    assert "max exposure" in bot._last_event

    # 3. Exceeds max position size
    assert not check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.4,
        current_positions=current_positions,
    )
    assert "position cap" in bot._last_event

    # 4. Mint already active
    assert not check_risk_limits(
        bot,
        mint="Mint1",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )
    assert "already active" in bot._last_event

    # 5. Token concentration cap breached (0.2 / 1.0 = 20% > 15%)
    bot.config = make_config(
        dry_run=False,
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.3,
        buy_amount_sol=0.1,
        max_token_concentration_pct=0.15,
    )
    assert not check_risk_limits(
        bot,
        mint="Mint3",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )
    assert "concentration cap reached" in bot._last_event


@pytest.mark.regression("BUG-14")
def test_risk_limits_realistic_market_cap_and_fallbacks():
    """
    Regression test for BUG-14:
    Pump.fun tokens have ~27.96 SOL market cap at bonding curve creation.
    Ensure that market cap is not conflated with position capital outlay (cost_sol ~0.01 SOL).
    """
    bot = MagicMock()
    bot.config = make_config(
        dry_run=False,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.10,
        buy_amount_sol=0.01,
        max_token_concentration_pct=0.35,
    )
    bot._last_event = ""

    # Position with 27.96 SOL entry MC and 0.01 SOL cost
    current_positions = {
        "PumpToken1": {
            "cost_sol": 0.01,
            "entry_sol": 0.01,
            "entry_market_cap": 27.95899,
            "current_market_cap": 27.95899,
        }
    }

    # Should allow opening a second position of 0.01 SOL (total exposure 0.02 <= 0.25)
    assert check_risk_limits(
        bot,
        mint="PumpToken2",
        proposed_entry_sol=0.01,
        current_positions=current_positions,
    )

    # Test fallback to entry_sol when cost_sol is missing
    current_positions_entry_sol = {
        "PumpToken1": {
            "entry_sol": 0.05,
            "entry_market_cap": 28.0,
        }
    }
    assert check_risk_limits(
        bot,
        mint="PumpToken2",
        proposed_entry_sol=0.05,
        current_positions=current_positions_entry_sol,
    )

    # Test fallback to buy_amount_sol when neither cost_sol nor entry_sol is present
    current_positions_no_cost = {
        "PumpToken1": {
            "entry_market_cap": 28.0,
        }
    }
    # default cost = 0.01 (buy_amount_sol), proposed = 0.01 -> exposure 0.02 <= 0.25
    assert check_risk_limits(
        bot,
        mint="PumpToken2",
        proposed_entry_sol=0.01,
        current_positions=current_positions_no_cost,
    )

    # Exposure cap rejection: current 0.22 SOL cost + proposed 0.05 SOL = 0.27 SOL > 0.25 SOL
    current_positions_near_cap = {
        "PumpToken1": {
            "cost_sol": 0.22,
            "entry_market_cap": 28.0,
        }
    }
    assert not check_risk_limits(
        bot,
        mint="PumpToken2",
        proposed_entry_sol=0.05,
        current_positions=current_positions_near_cap,
    )
    assert "max exposure" in bot._last_event

    # Concentration cap rejection: single position of 0.10 SOL against max 0.25 SOL = 40% > 35%
    current_positions_concentrated = {
        "PumpToken1": {
            "cost_sol": 0.10,
            "entry_market_cap": 28.0,
        }
    }
    assert not check_risk_limits(
        bot,
        mint="PumpToken2",
        proposed_entry_sol=0.01,
        current_positions=current_positions_concentrated,
    )
    assert "concentration cap reached" in bot._last_event


@pytest.mark.regression("BUG-22")
def test_risk_limits_proposed_trade_concentration_cap_rejection():
    """
    Regression test for BUG-22:
    Ensure per-token concentration check evaluates proposed candidate trade outlay
    (proposed_entry_sol / max_total_exposure_sol) against max_token_concentration_pct
    even when existing active positions are empty or hold small allocations.
    """
    bot = MagicMock()
    bot.config = make_config(
        dry_run=False,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.20,
        buy_amount_sol=0.05,
        max_token_concentration_pct=0.35,  # 35% max per token = 0.0875 SOL max
    )
    bot._last_event = ""

    # 1. Empty positions: proposed trade of 0.10 SOL is 40% of max exposure (0.10 / 0.25) -> rejected
    assert not check_risk_limits(
        bot,
        mint="CandidateMint1",
        proposed_entry_sol=0.10,
        current_positions={},
    )
    assert "concentration cap reached" in bot._last_event
    assert "40.00% > 35.00%" in bot._last_event

    # 2. Empty positions: proposed trade of 0.08 SOL is 32% of max exposure (0.08 / 0.25) -> allowed
    assert check_risk_limits(
        bot,
        mint="CandidateMint1",
        proposed_entry_sol=0.08,
        current_positions={},
    )

    # 3. Small existing position (0.02 SOL): proposed oversized trade of 0.10 SOL -> rejected
    small_positions = {
        "ExistingMint": {
            "cost_sol": 0.02,
            "entry_sol": 0.02,
            "entry_market_cap": 28.0,
        }
    }
    assert not check_risk_limits(
        bot,
        mint="CandidateMint2",
        proposed_entry_sol=0.10,
        current_positions=small_positions,
    )
    assert "concentration cap reached" in bot._last_event
    assert "40.00% > 35.00%" in bot._last_event

    # 4. Small existing position (0.02 SOL): compliant proposed trade of 0.05 SOL (20% <= 35%) -> allowed
    assert check_risk_limits(
        bot,
        mint="CandidateMint2",
        proposed_entry_sol=0.05,
        current_positions=small_positions,
    )


def test_daily_drawdown_and_trade_loss():
    bot = MagicMock()
    bot.config = make_config(
        dry_run=False,
        max_daily_drawdown_pct=0.25,
        max_loss_per_trade_sol=0.05,
        buy_amount_sol=0.1,
    )
    bot.active_positions = {}

    # Empty positions
    assert check_daily_drawdown(bot)

    # Zero equity positions
    bot.active_positions = {"MintZero": {"cost_sol": 0.0, "entry_market_cap": 0.0}}
    assert check_daily_drawdown(bot)

    # Drawdown within acceptable limit (10% drop < 25%)
    bot.active_positions = {
        "Mint1": {
            "cost_sol": 0.1,
            "entry_market_cap": 1.0,
            "current_market_cap": 0.9,
        }
    }
    assert check_daily_drawdown(bot)

    # Drawdown breached (40% drop > 25%)
    bot.active_positions = {
        "Mint1": {
            "cost_sol": 0.1,
            "entry_market_cap": 1.0,
            "current_market_cap": 0.6,
        }
    }
    assert not check_daily_drawdown(bot)
    assert "daily drawdown" in bot._last_event

    # check_loss_per_trade
    # Non-existent mint
    assert check_loss_per_trade(bot, mint="NonExistent")

    # Entry market cap <= 0
    bot.active_positions = {"MintZero": {"entry_market_cap": 0.0}}
    assert check_loss_per_trade(bot, mint="MintZero")

    # Trade loss within limits (loss ratio 0.2 < 0.05/0.1 = 0.5)
    bot.active_positions = {
        "MintPos": {"entry_market_cap": 1.0, "current_market_cap": 0.8}
    }
    assert check_loss_per_trade(bot, mint="MintPos")

    # Trade loss exceeds max limit (loss ratio 0.6 > 0.5)
    bot.active_positions = {
        "MintPos": {"entry_market_cap": 1.0, "current_market_cap": 0.4}
    }
    assert not check_loss_per_trade(bot, mint="MintPos")
    assert "trade loss" in bot._last_event


MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


MINT_2 = "So11111111111111111111111111111111111111112"


@pytest.mark.regression("BUG-47")
def test_daily_rollover_releases_latched_breaker():
    """BUG-47: a lock taken late on day 1 clears at the next UTC date."""
    tracker = DailyEquityTracker()
    day1 = datetime.datetime(2026, 10, 15, 23, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(1.0, 0.0, day1)
    tracker.realized_daily_pnl_sol = -0.5
    tracker.circuit_breaker_engaged = True
    tracker.locked_at_timestamp = day1.timestamp()
    tracker.lock_reason = "locked"

    locked, _ = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.2,
        emergency_hard_lock_hours=24,
        current_wallet_balance_sol=0.5,
        now_timestamp=day1.timestamp() + 600,
        now_utc=day1 + datetime.timedelta(minutes=10),
    )
    assert locked is True

    day2 = day1 + datetime.timedelta(hours=2)
    locked, _ = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.2,
        emergency_hard_lock_hours=24,
        current_wallet_balance_sol=0.5,
        now_timestamp=day2.timestamp(),
        now_utc=day2,
    )
    assert locked is False
    assert tracker.circuit_breaker_engaged is False
    assert tracker.locked_at_timestamp is None
    assert tracker.realized_daily_pnl_sol == 0.0
    assert tracker.starting_equity_sol == pytest.approx(0.5)


def _risk_bot(**config):
    return SimpleNamespace(
        config=SimpleNamespace(**config), active_positions={}, _last_event=""
    )


@pytest.mark.regression("BUG-70")
def test_loss_per_trade_compares_sol_and_handles_zero_buy_amount():
    """BUG-70: the cap fires on SOL lost and never divides by buy_amount_sol."""
    bot = _risk_bot(max_loss_per_trade_sol=0.005, buy_amount_sol=0.0)
    bot.active_positions[MINT] = {"cost_sol": 0.01, "entry_market_cap": 30.0}
    assert check_loss_per_trade(bot, mint=MINT, current_market_cap=27.0) is True
    assert check_loss_per_trade(bot, mint=MINT, current_market_cap=12.0) is False
    assert "trade loss" in bot._last_event


@pytest.mark.regression("BUG-71")
def test_exposure_scaled_by_remaining_fraction():
    """BUG-71: partially sold positions only count their remaining cost."""
    bot = _risk_bot(
        buy_amount_sol=0.05,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.1,
        max_token_concentration_pct=0.5,
    )
    positions = {
        MINT: {
            "cost_sol": 0.2,
            "initial_token_amount": 1_000,
            "remaining_token_amount": 500,
        }
    }
    assert check_risk_limits(
        bot, mint=MINT_2, proposed_entry_sol=0.05, current_positions=positions
    )


def test_daily_equity_tracker_modes_and_resets():
    # Baseline mode
    tracker_base = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="baseline",
    )
    is_locked, reason = tracker_base.evaluate_circuit_breaker(
        current_wallet_balance_sol=0.75,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked is True
    assert (
        tracker_base.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )

    # Trailing HWM mode
    tracker_hwm = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="trailing_hwm",
    )
    tracker_hwm.update_valuation(2.0, 0.0)
    is_locked_hwm, _ = tracker_hwm.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.5,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked_hwm is True
    assert (
        tracker_hwm.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE
    )

    # Lock expiration check
    now = time.time()
    tracker_hwm.locked_at_timestamp = now - 7200.0  # 2 hours ago
    is_locked_after, _ = tracker_hwm.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.5,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=1.0,  # 1 hour lock
        now_timestamp=now,
    )
    assert is_locked_after is False  # Unlocked

    # Reset circuit breaker
    tracker_hwm.circuit_breaker_engaged = True
    tracker_hwm.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
    tracker_hwm.reset_circuit_breaker(force=True, new_baseline_sol=1.5)
    assert tracker_hwm.circuit_breaker_engaged is False
    assert tracker_hwm.starting_equity_sol == 1.5

    # Serializations
    d = tracker_hwm.to_dict()
    assert d["starting_equity_sol"] == 1.5
    restored = DailyEquityTracker.from_dict(d)
    assert restored.starting_equity_sol == 1.5


def test_daily_equity_tracker_midnight_and_profit_run_zone():
    tracker = DailyEquityTracker(
        starting_equity_sol=1.0,
        drawdown_reference_mode="adaptive_ratchet",
        profit_drawdown_tolerance_pct=0.35,
        profit_ratchet_ratio=0.50,
    )

    # 1. Realized trade raises baseline
    tracker.record_realized_trade(0.50)
    assert tracker.effective_baseline_sol == 1.25

    # 2. Update valuation in profit run zone
    tracker.update_valuation(1.80, 0.20)
    assert tracker.peak_daily_equity_sol == 2.00

    # 3. Pullback within profit tolerance (2.0 -> 1.50 = 25% retracement < 35%)
    is_locked, _ = tracker.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.50,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked is False
    assert tracker.circuit_breaker_action == CircuitBreakerAction.NONE

    # 4. Pullback exceeding profit tolerance (2.0 -> 1.20 = 40% retracement > 35%)
    is_locked_breach, reason = tracker.evaluate_circuit_breaker(
        current_wallet_balance_sol=1.20,
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
    )
    assert is_locked_breach is True
    assert tracker.circuit_breaker_action == CircuitBreakerAction.HALT_NEW_BUYS
    assert "profit run retracement" in reason

    # 5. Midnight rollover resets tracking
    import datetime

    tomorrow_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=2
    )
    tracker.update_valuation(
        1.50,
        0.0,
        now_utc=tomorrow_dt,
    )
    assert tracker.starting_equity_sol == 1.50
    assert tracker.realized_daily_pnl_sol == 0.0


def test_risk_helpers_and_limits():
    from pumpfun_trading.bot.risk import (
        _extract_position_cost,
        _extract_position_fraction,
        check_daily_drawdown,
        check_loss_per_trade,
        check_risk_limits,
        track_position_peak,
    )

    # Object-based position extraction
    class DummyPos:
        def __init__(self, cost_sol=0.01, init_tokens=1000, rem_tokens=500):
            self.cost_sol = cost_sol
            self.initial_token_amount = init_tokens
            self.remaining_token_amount = rem_tokens
            self.entry_market_cap = 30.0
            self.current_market_cap = 30.0
            self.peak_market_cap = 30.0

    pos_obj = DummyPos(cost_sol=0.02, init_tokens=1000, rem_tokens=800)
    assert _extract_position_cost(pos_obj) == 0.02
    assert _extract_position_fraction(pos_obj) == 0.8
    assert _extract_position_cost("invalid_type", default_cost=0.05) == 0.05
    assert _extract_position_fraction("invalid_type") == 1.0

    # check_risk_limits branches
    mock_bot = MagicMock()
    mock_bot.config.max_total_exposure_sol = 0.05
    mock_bot.config.max_position_size_sol = 0.03
    mock_bot.config.max_token_concentration_pct = 0.50
    mock_bot.config.buy_amount_sol = 0.01

    positions = {
        "m1": {
            "cost_sol": 0.02,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
        },
        "m2": {
            "cost_sol": 0.02,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
        },
    }

    # Exposure exceeded (0.04 + 0.02 > 0.05)
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.02, current_positions=positions
        )
        is False
    )

    # Position cap exceeded (0.04 > 0.03)
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.04, current_positions={}
        )
        is False
    )

    # Mint already active
    assert (
        check_risk_limits(
            mock_bot, mint="m1", proposed_entry_sol=0.01, current_positions=positions
        )
        is False
    )

    # Concentration cap exceeded
    mock_bot.config.max_total_exposure_sol = 0.10
    mock_bot.config.max_token_concentration_pct = 0.30
    assert (
        check_risk_limits(
            mock_bot, mint="m3", proposed_entry_sol=0.04, current_positions={}
        )
        is False
    )

    # check_daily_drawdown without tracker
    mock_bot.daily_equity_tracker = None
    mock_bot.active_positions = {}
    assert check_daily_drawdown(mock_bot) is True

    mock_bot.active_positions = {"m1": {"cost_sol": 0.0, "initial_token_amount": 0}}
    assert check_daily_drawdown(mock_bot) is True

    mock_bot.active_positions = {
        "m1": {
            "cost_sol": 0.01,
            "initial_token_amount": 1000,
            "remaining_token_amount": 1000,
            "entry_market_cap": 30.0,
            "current_market_cap": 15.0,
        }
    }
    mock_bot.config.max_daily_drawdown_pct = 0.20
    assert check_daily_drawdown(mock_bot) is False

    # check_loss_per_trade
    mock_bot.config.max_loss_per_trade_sol = 0.002
    mock_bot.config.buy_amount_sol = 0.01
    assert check_loss_per_trade(mock_bot, mint="non_existent") is True
    assert check_loss_per_trade(mock_bot, mint="m1", current_market_cap=10.0) is False

    # track_position_peak
    assert (
        track_position_peak(mock_bot, mint="non_existent", current_market_cap=50.0)
        == 50.0
    )
    assert track_position_peak(mock_bot, mint="m1", current_market_cap=60.0) == 60.0


@pytest.mark.regression("BUG-114")
@pytest.mark.parametrize(
    "hours, expected_offset",
    [
        (0.0, 11 * 3600.0),  # unlocks at the next 00:00 UTC
        (24.0, 11 * 3600.0),  # midnight comes before the 24 h hard lock
        (2.0, 2 * 3600.0),  # a shorter hard lock ends first
    ],
)
def test_lockout_until_reports_release_time(
    hours: float, expected_offset: float
) -> None:
    locked_at = datetime.datetime(
        2026, 10, 17, 13, 0, tzinfo=datetime.timezone.utc
    ).timestamp()
    tracker = DailyEquityTracker(
        circuit_breaker_engaged=True, locked_at_timestamp=locked_at
    )

    assert tracker.lockout_until(hours) == pytest.approx(locked_at + expected_offset)
    tracker.circuit_breaker_engaged = False
    assert tracker.lockout_until(hours) is None
