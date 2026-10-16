"""Unit tests for ``bot/risk.py``: net PnL and cost tracking (FEAT-49)."""

from __future__ import annotations

import datetime

import pytest

from pumpfun_trading.bot.risk import DailyEquityTracker

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
