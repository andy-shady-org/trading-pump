"""Unit tests for ``strategies/regime.py``: rolling launch / graduation counts and
the market-regime snapshot recorded on buys and screened launches."""

from __future__ import annotations

import calendar

import pytest

from trading_pump.strategies import regime as regime_module
from trading_pump.strategies.regime import MarketRegimeTracker

# 2026-10-20 14:00:00 UTC, a Tuesday.
T0 = float(calendar.timegm((2026, 10, 20, 14, 0, 0, 0, 0, 0)))


def test_snapshot_counts_events_in_the_window() -> None:
    tracker = MarketRegimeTracker(window_seconds=600, now=T0)
    for offset in range(0, 300, 10):  # 30 launches in 5 min
        tracker.record_launch(T0 + offset)
    assert tracker.record_graduation("A", T0 + 100)
    assert tracker.record_graduation("B", T0 + 200)
    snap = tracker.snapshot(T0 + 300)
    assert snap["hour_utc"] == 14
    assert snap["weekday_utc"] == 1
    assert snap["launches"] == 30
    assert snap["graduations"] == 2
    assert snap["launches_per_minute"] == 3.0
    assert snap["graduations_per_hour"] == 12.0
    assert snap["graduation_ratio"] == round(2 / 30, 5)
    assert snap["warm"] is False
    assert tracker.snapshot(T0 + 600)["warm"] is True


def test_old_events_leave_the_window() -> None:
    tracker = MarketRegimeTracker(window_seconds=60, now=T0)
    tracker.record_launch(T0)
    tracker.record_graduation("A", T0)
    tracker.record_launch(T0 + 50)
    snap = tracker.snapshot(T0 + 100)
    assert snap["launches"] == 1
    assert snap["graduations"] == 0
    empty = MarketRegimeTracker(now=T0).snapshot(T0)
    assert empty["graduation_ratio"] is None


def test_a_graduation_counts_once_per_mint() -> None:
    tracker = MarketRegimeTracker(now=T0)
    assert tracker.record_graduation("A", T0)
    assert not tracker.record_graduation("A", T0 + 1)
    assert not tracker.record_graduation("", T0 + 1)
    assert tracker.snapshot(T0 + 2)["graduations"] == 1


def test_memory_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(regime_module, "MAX_REGIME_EVENTS", 3)
    tracker = MarketRegimeTracker(now=T0)
    for index in range(5):
        tracker.record_graduation(f"M{index}", T0 + index)
    assert tracker.snapshot(T0 + 5)["graduations"] == 3


def test_defaults_use_the_wall_clock() -> None:
    tracker = MarketRegimeTracker(window_seconds=0)
    assert tracker.window_seconds == 1.0
    tracker.record_launch()
    tracker.record_graduation("A")
    snap = tracker.snapshot()
    assert snap["launches"] == 1 and snap["graduations"] == 1
