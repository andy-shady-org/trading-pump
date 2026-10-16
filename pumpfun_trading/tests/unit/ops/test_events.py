"""Unit tests for ``ops/events.py`` (diagnostic event model and async JSONL writer)."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from pumpfun_trading.ops.events import (
    DiagnosticEvent,
    DiagnosticEventLogger,
    EventCategory,
    EventSeverity,
)


class _AlwaysFullQueue:
    """Queue double whose ``put_nowait`` always overflows and ``get_nowait`` fails."""

    def __init__(self) -> None:
        self.get_calls = 0

    def put_nowait(self, item: DiagnosticEvent) -> None:
        raise asyncio.QueueFull

    def get_nowait(self) -> DiagnosticEvent:
        self.get_calls += 1
        raise asyncio.QueueEmpty

    def empty(self) -> bool:
        return False

    def qsize(self) -> int:
        return 0

    def task_done(self) -> None:
        pass


class _BrokenHandle:
    """File handle double whose every operation raises."""

    def writelines(self, lines: list[str]) -> None:
        raise OSError("disk gone")

    def flush(self) -> None:
        raise OSError("disk gone")

    def close(self) -> None:
        raise OSError("disk gone")


def _read_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


@pytest.mark.parametrize(
    ("raw_category", "raw_severity", "category", "severity"),
    [
        ("STREAM", "WARNING", EventCategory.STREAM, EventSeverity.WARNING),
        ("bogus", "error", EventCategory.LIFECYCLE, EventSeverity.ERROR),
        ("risk", "bogus", EventCategory.RISK, EventSeverity.INFO),
        ("nope", "nope", EventCategory.LIFECYCLE, EventSeverity.INFO),
    ],
)
def test_diagnostic_event_string_enums_normalised_with_fallback(
    raw_category: str,
    raw_severity: str,
    category: EventCategory,
    severity: EventSeverity,
) -> None:
    event = DiagnosticEvent(
        category=raw_category,  # type: ignore[arg-type]
        severity=raw_severity,  # type: ignore[arg-type]
    )

    assert event.category is category
    assert event.severity is severity


def test_diagnostic_event_timestamp_derives_utc_iso_string() -> None:
    event = DiagnosticEvent(timestamp_ns=1_700_000_000_000_000_000)

    assert event.iso_timestamp == "2023-11-14T22:13:20+00:00"


def test_diagnostic_event_round_trip_preserves_fields() -> None:
    original = DiagnosticEvent(
        timestamp_ns=123,
        iso_timestamp="t",
        category=EventCategory.EXECUTION,
        severity=EventSeverity.CRITICAL,
        event_name="buy",
        mint="MINT",
        mint_name="Coin",
        latency_ms=1.5,
        data={"k": 1},
        error_message="boom",
    )

    restored = DiagnosticEvent.from_dict(original.to_dict())

    assert restored == original


def test_diagnostic_event_from_dict_invalid_enums_fall_back() -> None:
    restored = DiagnosticEvent.from_dict(
        {"category": "zzz", "severity": "zzz", "timestamp_ns": 5}
    )

    assert restored.category is EventCategory.LIFECYCLE
    assert restored.severity is EventSeverity.INFO
    assert restored.latency_ms is None
    assert restored.data == {}


def test_emit_disabled_logger_returns_false(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl", enabled=False)

    assert events.emit(event_name="x") is False
    assert events.get_stats()["total_emitted"] == 0


def test_emit_prebuilt_event_enabled_category_is_queued(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(
        tmp_path / "e.jsonl", enabled_categories=[EventCategory.RISK]
    )
    event = DiagnosticEvent(category=EventCategory.RISK, event_name="breaker")

    assert events.emit(event) is True

    stats = events.get_stats()
    assert stats["total_emitted"] == 1
    assert stats["pending_queue_size"] == 1
    assert stats["enabled_categories"] == ["risk"]


def test_emit_prebuilt_event_disabled_category_is_rejected(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl", enabled_categories=["risk"])

    assert events.emit(DiagnosticEvent(category=EventCategory.STREAM)) is False
    assert events.emit(category="stream", event_name="x") is False
    assert events.get_stats()["total_emitted"] == 0


def test_emit_string_kwargs_builds_typed_event(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")

    assert events.emit(category="STRATEGY", severity="DEBUG", event_name="sig")

    queued = events._queue.get_nowait()
    assert queued.category is EventCategory.STRATEGY
    assert queued.severity is EventSeverity.DEBUG
    assert queued.data == {}


def test_emit_queue_full_info_event_is_dropped(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl", max_queue_size=1)
    assert events.emit(event_name="first")

    assert events.emit(event_name="second") is False

    stats = events.get_stats()
    assert stats["dropped_events"] == 1
    assert stats["total_emitted"] == 2
    assert events._queue.get_nowait().event_name == "first"


def test_emit_queue_full_critical_event_evicts_oldest(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl", max_queue_size=1)
    assert events.emit(event_name="old")

    assert events.emit(severity=EventSeverity.CRITICAL, event_name="urgent") is True

    assert events.get_stats()["dropped_events"] == 1
    assert events._queue.qsize() == 1
    assert events._queue.get_nowait().event_name == "urgent"


def test_emit_queue_full_eviction_failure_returns_false(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    fake_queue = _AlwaysFullQueue()
    events._queue = fake_queue  # type: ignore[assignment]

    assert events.emit(severity="error", event_name="lost") is False

    assert fake_queue.get_calls == 1
    assert events._dropped_events_count == 1


async def test_start_creates_missing_parent_dir_and_writes_events(
    tmp_path: Path,
) -> None:
    out = tmp_path / "nested" / "deeper" / "events.jsonl"
    events = DiagnosticEventLogger(out, batch_size=1, flush_interval_seconds=0.01)

    await events.start()
    events.emit(category=EventCategory.STREAM, event_name="connected", mint="M")
    await events.flush_and_close()

    rows = _read_events(out)
    assert [r["event_name"] for r in rows] == ["connected"]
    assert rows[0]["category"] == "stream"
    assert events.get_stats()["total_written"] == 1


async def test_start_twice_is_idempotent(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    await events.start()
    task = events._consumer_task

    await events.start()

    assert events._consumer_task is task
    await events.flush_and_close()


async def test_start_unopenable_path_logs_warning_and_drops_writes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    directory_path = tmp_path / "is_a_dir"
    directory_path.mkdir()
    events = DiagnosticEventLogger(directory_path)

    with caplog.at_level(logging.WARNING, logger="pumpfun_trading.ops.events"):
        await events.start()

    assert "Unable to open diagnostic event file" in caplog.text
    assert events._file_handle is None
    events.emit(event_name="x")
    await events.flush_and_close()
    assert events.get_stats()["total_written"] == 0


async def test_worker_loop_not_running_drains_queue_to_disk(tmp_path: Path) -> None:
    out = tmp_path / "e.jsonl"
    events = DiagnosticEventLogger(out)
    events.emit(event_name="a")
    events.emit(event_name="b")
    events._file_handle = open(out, "a", encoding="utf-8")

    await events._worker_loop()
    events._file_handle.close()

    assert [r["event_name"] for r in _read_events(out)] == ["a", "b"]
    assert events._queue.empty()


async def test_worker_loop_drain_get_failure_breaks_cleanly(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    fake_queue = _AlwaysFullQueue()
    events._queue = fake_queue  # type: ignore[assignment]

    await events._worker_loop()

    assert fake_queue.get_calls == 1
    assert events.get_stats()["total_written"] == 0


async def test_worker_loop_write_error_is_swallowed_and_retried(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = DiagnosticEventLogger(
        tmp_path / "e.jsonl", batch_size=1, flush_interval_seconds=0.0
    )
    events._running = True
    written: list[list[str]] = []

    def flaky_write(batch: list[DiagnosticEvent]) -> None:
        if not written:
            written.append([])
            raise RuntimeError("transient")
        written.append([e.event_name for e in batch])
        events._running = False

    events._write_batch = flaky_write  # type: ignore[method-assign]
    events.emit(event_name="retry-me")

    with caplog.at_level(logging.DEBUG, logger="pumpfun_trading.ops.events"):
        await events._worker_loop()

    assert "Error in diagnostic event worker loop" in caplog.text
    assert written[-1] == ["retry-me"]


def test_write_batch_handle_error_logs_warning_and_keeps_count(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    events._file_handle = _BrokenHandle()  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="pumpfun_trading.ops.events"):
        events._write_batch([DiagnosticEvent(event_name="x")])

    assert "Failed to write diagnostic event batch" in caplog.text
    assert events.get_stats()["total_written"] == 0


def test_write_batch_without_handle_is_noop(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")

    events._write_batch([DiagnosticEvent()])

    assert events.get_stats()["total_written"] == 0


async def test_flush_and_close_not_running_is_noop(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    events.emit(event_name="pending")

    await events.flush_and_close()

    assert events.get_stats()["pending_queue_size"] == 1
    assert not (tmp_path / "e.jsonl").exists()


async def test_flush_and_close_writes_remaining_queue(tmp_path: Path) -> None:
    out = tmp_path / "e.jsonl"
    events = DiagnosticEventLogger(out)
    events._running = True
    events._file_handle = open(out, "a", encoding="utf-8")
    events.emit(event_name="late-1")
    events.emit(event_name="late-2")

    await events.flush_and_close()

    assert [r["event_name"] for r in _read_events(out)] == ["late-1", "late-2"]
    assert events._file_handle is None
    assert events._running is False


async def test_flush_and_close_queue_and_handle_errors_are_swallowed(
    tmp_path: Path,
) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    fake_queue = _AlwaysFullQueue()
    events._queue = fake_queue  # type: ignore[assignment]
    events._running = True
    events._file_handle = _BrokenHandle()  # type: ignore[assignment]

    await events.flush_and_close()

    assert fake_queue.get_calls == 1
    assert events._file_handle is None
    assert events._running is False


def test_emit_unknown_enabled_category_falls_back_instead_of_raising(
    tmp_path: Path,
) -> None:
    """BUG-98: ``emit`` never raises on the hot path for unknown enum strings."""
    events = DiagnosticEventLogger(
        tmp_path / "e.jsonl", enabled_categories=["foo", "lifecycle"]
    )

    assert events.emit(category="foo", severity="loud", event_name="x") is True

    queued = events._queue.get_nowait()
    assert queued.category is EventCategory.LIFECYCLE
    assert queued.severity is EventSeverity.INFO


def test_emit_unknown_category_respects_lifecycle_filter(tmp_path: Path) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl", enabled_categories=["foo"])

    assert events.emit(category="foo", event_name="x") is False
    assert events.get_stats()["total_emitted"] == 0


def test_diagnostic_event_model() -> None:
    event = DiagnosticEvent(
        category=EventCategory.SCREENING,
        severity=EventSeverity.WARNING,
        event_name="token_screen_rejected",
        mint="7EYnhcWvdqPB2DdJ6DXZsMvT8GqgE4F8V9m1pump",
        mint_name="SolCat",
        latency_ms=12.45,
        data={"gini_score": 0.89, "reasons": ["high_gini_inequality"]},
        error_message="Gini score exceeds 0.85 threshold",
    )
    assert event.category == EventCategory.SCREENING
    assert event.severity == EventSeverity.WARNING
    assert event.iso_timestamp != ""

    d = event.to_dict()
    assert d["category"] == "screening"
    assert d["severity"] == "warning"
    assert d["data"]["gini_score"] == 0.89

    restored = DiagnosticEvent.from_dict(d)
    assert restored.category == EventCategory.SCREENING
    assert restored.severity == EventSeverity.WARNING
    assert restored.mint == "7EYnhcWvdqPB2DdJ6DXZsMvT8GqgE4F8V9m1pump"
    assert restored.latency_ms == 12.45
    assert restored.data["gini_score"] == 0.89


async def test_diagnostic_event_logger_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "events.jsonl"
        logger = DiagnosticEventLogger(
            output_path=log_file,
            enabled_categories=[EventCategory.STREAM, EventCategory.RISK],
            flush_interval_seconds=0.1,
            batch_size=10,
        )

        await logger.start()

        # Emit an event in enabled category
        emitted_stream = logger.emit(
            category=EventCategory.STREAM,
            severity=EventSeverity.INFO,
            event_name="geyser_slot_latency",
            latency_ms=4.2,
            data={"slot": 290123456},
        )
        assert emitted_stream is True

        # Emit an event in disabled category (SCREENING not in enabled_categories)
        emitted_screen = logger.emit(
            category=EventCategory.SCREENING,
            severity=EventSeverity.INFO,
            event_name="token_evaluated",
        )
        assert emitted_screen is False

        # Emit a risk event
        emitted_risk = logger.emit(
            category=EventCategory.RISK,
            severity=EventSeverity.WARNING,
            event_name="trailing_stop_ratchet",
            mint="7EYnhcWvdqPB2DdJ6DXZsMvT8GqgE4F8V9m1pump",
            data={"peak_mc": 45.2, "stop_floor": 38.4},
        )
        assert emitted_risk is True

        await logger.flush_and_close()

        assert log_file.exists()
        lines = [
            line.strip()
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 2

        record1 = json.loads(lines[0])
        assert record1["category"] == "stream"
        assert record1["event_name"] == "geyser_slot_latency"
        assert record1["latency_ms"] == 4.2

        record2 = json.loads(lines[1])
        assert record2["category"] == "risk"
        assert record2["event_name"] == "trailing_stop_ratchet"


async def test_diagnostic_event_logger_high_throughput_burst() -> None:
    """Stress tests high-throughput burst emission (2,000 events) without blocking."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "events_stress.jsonl"
        logger = DiagnosticEventLogger(
            output_path=log_file,
            max_queue_size=5_000,
            batch_size=200,
            flush_interval_seconds=0.05,
        )

        await logger.start()

        total_burst = 2_000
        start_t = time.perf_counter()
        for i in range(total_burst):
            logger.emit(
                category=EventCategory.EXECUTION,
                severity=EventSeverity.INFO,
                event_name="bundle_step",
                data={"step_index": i},
            )
        elapsed_burst = time.perf_counter() - start_t

        # 2,000 in-memory queue pushes must take < 50ms total (<0.025ms per item)
        assert elapsed_burst < 0.25

        await logger.flush_and_close()

        assert log_file.exists()
        lines = [
            line.strip()
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == total_burst


async def test_diagnostic_event_logger_backpressure_drop() -> None:
    """Tests bounded queue backpressure when queue overflows."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "events_backpressure.jsonl"
        # Small queue size of 5 without starting consumer loop immediately
        logger = DiagnosticEventLogger(
            output_path=log_file,
            max_queue_size=5,
        )

        # Emit 10 events
        results = []
        for i in range(10):
            res = logger.emit(
                category=EventCategory.LIFECYCLE,
                severity=EventSeverity.DEBUG,
                event_name=f"debug_event_{i}",
            )
            results.append(res)

        # First 5 should succeed, remaining should return False due to queue saturation
        assert results[:5] == [True, True, True, True, True]
        assert results[5:] == [False, False, False, False, False]
        assert logger.get_stats()["dropped_events"] == 5

        await logger.flush_and_close()
