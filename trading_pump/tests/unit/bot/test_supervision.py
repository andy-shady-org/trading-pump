"""Unit tests for ``bot/supervision.py``: daily summary, degradation and gap alerts."""

from __future__ import annotations

import datetime

import pytest

from trading_pump.bot.pnl import PnlTotals
from trading_pump.bot.supervision import (
    DailySummarySchedule,
    DegradationMonitor,
    ReconcileGapWatcher,
    format_daily_summary,
    format_duration,
    pnl_delta,
)


def _ts(day: int, hour: int, minute: int = 0) -> float:
    return datetime.datetime(
        2026, 10, day, hour, minute, tzinfo=datetime.timezone.utc
    ).timestamp()


def _totals(**values: float) -> PnlTotals:
    totals = PnlTotals()
    for name, value in values.items():
        setattr(totals, name, value)
    return totals


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (-5.0, "0m"),
        (59.0, "0m"),
        (300.0, "5m"),
        (3_660.0, "1h01m"),
        (90_000.0, "25h00m"),
    ],
)
def test_format_duration_table(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_pnl_delta_subtracts_every_counter() -> None:
    baseline = _totals(net_pnl_sol=0.01, fees_sol=0.001, buys=2, sells=2)
    current = _totals(net_pnl_sol=0.04, fees_sol=0.003, buys=5, sells=4)

    delta = pnl_delta(current, baseline)

    assert delta.net_pnl_sol == pytest.approx(0.03)
    assert delta.fees_sol == pytest.approx(0.002)
    assert (delta.buys, delta.sells) == (3, 2)
    assert isinstance(delta.buys, int)


def test_pnl_delta_after_totals_reset_uses_current() -> None:
    baseline = _totals(net_pnl_sol=1.0, buys=50)
    current = _totals(net_pnl_sol=0.2, buys=3)

    delta = pnl_delta(current, baseline)

    assert (delta.net_pnl_sol, delta.buys) == (0.2, 3)


def test_daily_summary_schedule_first_start_waits_for_next_day() -> None:
    schedule = DailySummarySchedule(hour_utc=0)
    totals = _totals(net_pnl_sol=0.5, buys=4)

    schedule.prime(totals, _ts(17, 10))

    assert schedule.period_start == _ts(17, 10)
    assert schedule.baseline["buys"] == 4
    assert not schedule.due(_ts(17, 23, 59))
    assert schedule.due(_ts(18, 0, 1))


def test_daily_summary_schedule_started_before_hour_sends_same_day() -> None:
    schedule = DailySummarySchedule(hour_utc=18)
    schedule.prime(PnlTotals(), _ts(17, 10))

    assert not schedule.due(_ts(17, 17, 59))
    assert schedule.due(_ts(17, 18))


def test_daily_summary_schedule_prime_keeps_restored_period() -> None:
    schedule = DailySummarySchedule(period_start=5.0, baseline={"buys": 1})

    schedule.prime(_totals(buys=9), _ts(17, 10))

    assert schedule.period_start == 5.0
    assert schedule.baseline == {"buys": 1}


def test_daily_summary_schedule_mark_sent_starts_new_period() -> None:
    schedule = DailySummarySchedule(hour_utc=0)
    schedule.prime(_totals(net_pnl_sol=0.1, buys=1), _ts(17, 10))
    now = _ts(18, 0, 5)
    totals = _totals(net_pnl_sol=0.35, buys=6)

    period = schedule.period_totals(totals)
    schedule.mark_sent(totals, now)

    assert period.net_pnl_sol == pytest.approx(0.25)
    assert period.buys == 5
    assert schedule.last_sent_date == "2026-10-18"
    assert schedule.period_start == now
    assert not schedule.due(_ts(18, 23))
    assert schedule.period_totals(totals).buys == 0


def test_daily_summary_schedule_round_trip_configured_hour_wins() -> None:
    schedule = DailySummarySchedule(
        hour_utc=6, last_sent_date="2026-10-17", period_start=1.0, baseline={"buys": 2}
    )

    restored = DailySummarySchedule.from_dict(schedule.to_dict(), hour_utc=9)

    assert restored.hour_utc == 9
    assert (restored.last_sent_date, restored.period_start, restored.baseline) == (
        "2026-10-17",
        1.0,
        {"buys": 2},
    )


@pytest.mark.parametrize("data", [None, [], {"period_start": "x", "baseline": "y"}])
def test_daily_summary_schedule_from_dict_malformed_falls_back(data: object) -> None:
    restored = DailySummarySchedule.from_dict(data, hour_utc=3)

    assert restored.hour_utc == 3
    assert restored.period_start is None
    assert restored.baseline == {}


def test_format_daily_summary_lists_net_costs_and_state() -> None:
    period = _totals(
        net_pnl_sol=-0.012,
        gross_pnl_sol=0.004,
        costs_sol=0.016,
        fees_sol=0.002,
        tips_sol=0.012,
        rent_sol=0.002,
        buys=8,
        sells=9,
        positions_closed=8,
        winning_positions=2,
        closed_net_pnl_sol=-0.012,
    )

    text = format_daily_summary(
        mode="paper",
        now=_ts(18, 0, 1),
        period_start=_ts(17, 0),
        period=period,
        session=_totals(net_pnl_sol=0.05),
        wallet_balance_sol=0.2512,
        open_positions=1,
        breaker="clear",
        drawdown_pct=0.031,
        reconciliation="OK (8 trades, 2h ago)",
        buying="active",
        health="ok",
        swept_sol=0.5,
    )

    lines = text.splitlines()
    assert lines[0] == (
        "pumpbot daily summary (paper) 2026-10-18, since 2026-10-17 00:00 UTC"
    )
    assert "Net PnL: -0.0120 SOL (gross +0.0040 SOL, costs 0.0160 SOL" in lines[1]
    assert "tips 0.0120" in lines[1]
    assert "8 buys, 9 sells; 8 positions closed, win rate 25%" in lines[2]
    assert "expectancy -0.0015 SOL" in lines[2]
    assert "Session net: +0.0500 SOL | wallet 0.2512 SOL | open positions 1" in text
    assert "Breaker: clear | drawdown today 3.1%" in text
    assert "Reconciliation: OK (8 trades, 2h ago)" in text
    assert "Buying: active | health: ok" in text
    assert lines[-1] == "Swept to cold wallet (total): 0.5000 SOL"


def test_format_daily_summary_without_period_or_sweep() -> None:
    text = format_daily_summary(
        mode="live",
        now=_ts(18, 0),
        period_start=None,
        period=PnlTotals(),
        session=PnlTotals(),
        wallet_balance_sol=0.0,
        open_positions=0,
        breaker="LOCKED",
        drawdown_pct=0.0,
        reconciliation="not run",
        buying="PAUSED (operator, 3m)",
        health="degraded",
    )

    assert "since start" in text
    assert "Swept" not in text
    assert text.splitlines()[-1] == "Buying: PAUSED (operator, 3m) | health: degraded"


def test_degradation_monitor_alerts_once_after_threshold_then_recovers() -> None:
    monitor = DegradationMonitor(threshold_seconds=300.0)

    assert monitor.update("stream", True, now=0.0) is None
    assert monitor.update("stream", True, now=299.0) is None
    assert monitor.degraded_for(299.0) == {"stream": 299.0}
    alert = monitor.update("stream", True, now=301.0, detail="502")
    assert alert == "ALERT stream degraded for 5m: 502"
    assert monitor.update("stream", True, now=900.0) is None
    assert monitor.update("stream", False, now=960.0) == "RECOVERED stream after 16m"
    assert monitor.degraded_for(960.0) == {}
    assert monitor.update("stream", False, now=970.0) is None


def test_degradation_monitor_short_blip_never_alerts() -> None:
    monitor = DegradationMonitor(threshold_seconds=300.0)

    assert monitor.update("rpc", True, now=0.0) is None
    assert monitor.update("rpc", False, now=120.0) is None
    assert monitor.update("rpc", True, now=200.0) is None
    assert monitor.update("rpc", True, now=450.0) is None
    assert monitor.update("rpc", True, now=500.0) == "ALERT rpc degraded for 5m"


def test_degradation_monitor_threshold_zero_disables() -> None:
    monitor = DegradationMonitor(threshold_seconds=0.0)

    assert not monitor.enabled
    assert monitor.update("stream", True, now=10_000.0) is None
    assert monitor.degraded_for(10_000.0) == {}


def test_reconcile_gap_watcher_alerts_once_per_new_gap() -> None:
    watcher = ReconcileGapWatcher()
    gap = {
        "checked_at": 100.0,
        "ok": False,
        "wallet": "Wallet1",
        "problems": ["cash-flow gap", "1 lost", "2 phantom", "ignored 4th"],
    }

    alert = watcher.check(gap)

    assert alert == (
        "ALERT reconciliation GAP for Wallet1: cash-flow gap; 1 lost; 2 phantom"
    )
    assert watcher.check(gap) is None
    assert watcher.check({**gap, "checked_at": 50.0}) is None
    assert watcher.check({"checked_at": 200.0, "ok": True}) is None
    assert watcher.last_checked_at == 200.0
    no_detail = watcher.check({"checked_at": 300.0, "ok": False})
    assert no_detail == "ALERT reconciliation GAP for ?: see reconcile_status.json"


@pytest.mark.parametrize("status", [None, {}, {"ok": False}, {"checked_at": "now"}])
def test_reconcile_gap_watcher_ignores_missing_status(status: object) -> None:
    assert ReconcileGapWatcher().check(status) is None  # type: ignore[arg-type]
