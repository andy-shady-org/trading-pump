"""Unit tests for FEAT-29 Adaptive Realized-Ratchet and Dual-Tier Drawdown Engine."""

from __future__ import annotations

from typing import Any

import pytest

from pumpfun_trading.bot.risk import (
    CircuitBreakerAction,
    DailyEquityTracker,
    check_daily_drawdown,
    evaluate_portfolio_circuit_breaker,
)
from pumpfun_trading.strategies.base import TradingBotConfig


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
            self.config = TradingBotConfig(
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


@pytest.mark.asyncio
async def test_bot_circuit_breaker_two_tier_actions() -> None:
    from pumpfun_trading.bot.run import TradingBot

    bot = TradingBot(
        private_key_b58="3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLyKfmogN5328W5REGLxmGfV5nCeqvE8j5Fh8n2xJvTfH24x9C8eZ56Tz",
        rpc_url="http://127.0.0.1:8899",
        dry_run=True,
        config=TradingBotConfig(
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
