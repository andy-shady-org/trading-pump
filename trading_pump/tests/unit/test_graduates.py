"""Unit tests for ``graduates.py``: following graduates and the capture rows."""

from __future__ import annotations

from typing import Any

import pytest

from trading_pump.config.settings import GraduationSettings
from trading_pump.graduates import GraduateTracker
from trading_pump.sdk.pumpswap import canonical_pool_address
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading


def _tracker(
    rows: list[dict[str, Any]] | None = None, **settings: Any
) -> GraduateTracker:
    sink = rows if rows is not None else []
    return GraduateTracker(
        GraduationSettings(**settings), signal_after_seconds=60.0, record=sink.append
    )


def test_a_migration_starts_an_observation_with_pumpfun_capture_rows() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(rows)

    graduate = tracker.add(SAMPLE_PUMP_MINT, now=100.0, held=True)

    assert graduate is not None and SAMPLE_PUMP_MINT in tracker and len(tracker) == 1
    assert graduate.pool == str(canonical_pool_address(SAMPLE_PUMP_MINT))
    assert graduate.signal_time == 160.0 and graduate.age(130.0) == 30.0
    assert rows == [
        {"timestamp": 100.0, "mint": SAMPLE_PUMP_MINT, "event": "migration"},
        {
            "timestamp": 100.0,
            "mint": SAMPLE_PUMP_MINT,
            "event": "observation_start",
            "source": "graduation",
            "migrated_at": 100.0,
            "pool": graduate.pool,
            "held": True,
        },
    ]
    # A repeated event is ignored and writes nothing.
    assert tracker.add(SAMPLE_PUMP_MINT, now=101.0) is None
    assert len(rows) == 2
    assert tracker.stats["duplicate_migrations"] == 1


def test_invalid_mints_and_a_full_list_are_counted_not_followed() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(rows, max_mints=1)

    assert tracker.add("not-a-mint", now=1.0) is None
    assert tracker.add(SAMPLE_MINT, now=1.0) is not None
    assert tracker.add(SAMPLE_PUMP_MINT, now=1.0) is None

    assert tracker.stats["invalid_mints"] == 1
    assert tracker.stats["list_full"] == 1
    assert tracker.snapshot()["following"] == 1
    # Every new migration is still counted in the capture.
    assert [r["event"] for r in rows].count("migration") == 3


def test_readings_set_first_last_and_signal_and_write_curve_polls() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(rows)
    tracker.add(SAMPLE_MINT, now=100.0)

    tracker.update(make_reading(SAMPLE_MINT, at=101.0))
    tracker.update(make_reading(SAMPLE_MINT, at=150.0, scale=1.1))
    graduate = tracker.update(make_reading(SAMPLE_MINT, at=161.0, scale=1.3))
    tracker.update(make_reading(SAMPLE_MINT, at=171.0, scale=1.4))

    assert graduate is not None
    assert graduate.first is not None and graduate.first.at == 101.0
    assert graduate.signal_reading is not None and graduate.signal_reading.at == 161.0
    assert graduate.last is not None and graduate.last.at == 171.0
    assert graduate.ratio() == pytest.approx(1.4, rel=1e-6)
    assert graduate.ratio(graduate.signal_reading) == pytest.approx(1.3, rel=1e-6)
    polls = [r for r in rows if r["event"] == "curve_poll"]
    assert [r["timestamp"] for r in polls] == [101.0, 150.0, 161.0, 171.0]
    assert {r["source"] for r in polls} == {"graduation"}
    assert tracker.stats["readings"] == 4


def test_a_drained_first_read_is_recorded_but_is_not_the_first_price() -> None:
    tracker = _tracker()
    tracker.add(SAMPLE_MINT, now=0.0)
    graduate = tracker.update(make_reading(SAMPLE_MINT, at=1.0, base=0))
    assert graduate is not None and graduate.first is None
    assert graduate.ratio() is None
    tracker.update(make_reading(SAMPLE_MINT, at=3.0))
    assert graduate.first is not None and graduate.first.at == 3.0


def test_a_repeated_reading_is_not_recorded_twice() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(rows)
    tracker.add(SAMPLE_MINT, now=0.0)
    reading = make_reading(SAMPLE_MINT, at=5.0)

    tracker.update(reading)
    tracker.update(reading)

    assert [r["event"] for r in rows].count("curve_poll") == 1
    assert tracker.stats["readings"] == 1


def test_readings_of_unknown_mints_are_ignored() -> None:
    tracker = _tracker()
    assert tracker.update(make_reading(SAMPLE_MINT)) is None
    tracker.rejected(SAMPLE_MINT, "missing", 1.0)
    tracker.end(SAMPLE_MINT, "ttl", 1.0)
    assert tracker.get(SAMPLE_MINT) is None


def test_schedule_is_fast_then_slow_and_ends_at_the_ttl() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(
        rows,
        observation_seconds=100.0,
        fast_seconds=20.0,
        fast_poll_interval_seconds=2.0,
        poll_interval_seconds=10.0,
    )
    tracker.add(SAMPLE_MINT, now=0.0)
    assert tracker.due(0.0) == [SAMPLE_MINT]
    tracker.update(make_reading(SAMPLE_MINT, at=0.0))
    assert tracker.due(1.0) == [] and tracker.due(2.0) == [SAMPLE_MINT]
    tracker.update(make_reading(SAMPLE_MINT, at=30.0))
    assert tracker.due(35.0) == [] and tracker.due(40.0) == [SAMPLE_MINT]

    assert tracker.expire(99.0) == []
    assert tracker.expire(101.0) == [SAMPLE_MINT]
    end = rows[-1]
    assert end["event"] == "observation_end" and end["cause"] == "ttl"
    assert end["polls"] == 2 and end["observed_seconds"] == 101.0
    assert end["first_real_sol"] == 85.0
    assert tracker.stats["ended_ttl"] == 1


def test_a_missing_pool_is_retried_for_the_grace_period_then_ended() -> None:
    rows: list[dict[str, Any]] = []
    tracker = _tracker(rows, pool_missing_grace_seconds=60.0)
    tracker.add(SAMPLE_MINT, now=0.0)

    tracker.rejected(SAMPLE_MINT, "missing", 10.0)
    assert SAMPLE_MINT in tracker
    assert tracker.due(10.5) == []  # retried on its schedule, not every pass
    tracker.rejected(SAMPLE_MINT, "missing", 61.0)
    assert SAMPLE_MINT not in tracker
    assert rows[-1]["cause"] == "missing"

    tracker.add(SAMPLE_PUMP_MINT, now=0.0)
    tracker.rejected(SAMPLE_PUMP_MINT, "not_sol_pair", 1.0)
    assert SAMPLE_PUMP_MINT not in tracker
    assert tracker.stats["ended_not_sol_pair"] == 1


def test_without_a_lane_there_is_no_signal_time_and_no_recorder_is_fine() -> None:
    tracker = GraduateTracker(GraduationSettings())
    graduate = tracker.add(SAMPLE_MINT, now=0.0)
    assert graduate is not None and graduate.signal_time is None
    tracker.update(make_reading(SAMPLE_MINT, at=100.0))
    assert graduate.signal_reading is None
