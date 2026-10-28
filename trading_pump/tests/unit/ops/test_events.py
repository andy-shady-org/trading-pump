"""Unit tests for ``ops/events.py`` (diagnostic event model and async JSONL writer)."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from trading_pump.cli.events import filter_diagnostic_events, load_diagnostic_events
from trading_pump.ops.events import (
    DiagnosticEvent,
    DiagnosticEventLogger,
    EventCategory,
    EventSeverity,
)
from trading_pump.ops.retention import (
    LogRetentionManager,
    RetentionPolicy,
    RotatedFileSink,
    compress_file_to_gzip,
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

    with caplog.at_level(logging.WARNING, logger="trading_pump.ops.events"):
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

    with caplog.at_level(logging.DEBUG, logger="trading_pump.ops.events"):
        await events._worker_loop()

    assert "Error in diagnostic event worker loop" in caplog.text
    assert written[-1] == ["retry-me"]


def test_write_batch_handle_error_logs_warning_and_keeps_count(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = DiagnosticEventLogger(tmp_path / "e.jsonl")
    events._file_handle = _BrokenHandle()  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="trading_pump.ops.events"):
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


@pytest.mark.regression("BUG-98")
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


def test_events_cli_deserialization_and_filtering():
    raw_dict = {
        "timestamp_ns": 1_000_000_000,
        "iso_timestamp": "2026-10-15T12:00:00Z",
        "category": "INVALID_CAT",
        "severity": "INVALID_SEV",
        "event_name": "test_event",
        "mint": "mint123",
        "mint_name": "TestToken",
        "latency_ms": 1.25,
        "data": {"k": "v"},
        "error_message": None,
    }
    evt = DiagnosticEvent.from_dict(raw_dict)
    assert evt.category == EventCategory.LIFECYCLE
    assert evt.severity == EventSeverity.INFO

    # String initialization
    evt2 = DiagnosticEvent(
        category="screening", severity="warning", event_name="bad_token"
    )
    assert evt2.category == EventCategory.SCREENING
    assert evt2.severity == EventSeverity.WARNING

    # to_dict / from_dict symmetry
    d = evt2.to_dict()
    assert d["category"] == "screening"
    assert d["severity"] == "warning"


async def test_diagnostic_event_logger_lifecycle_and_edge_cases(tmp_path: Path):
    log_file = tmp_path / "events_test.jsonl"
    logger = DiagnosticEventLogger(
        output_path=log_file,
        max_queue_size=5,
        batch_size=2,
        flush_interval_seconds=0.1,
    )
    await logger.start()

    # Double start is no-op
    await logger.start()

    # Emit normal
    assert logger.emit(category=EventCategory.LIFECYCLE, event_name="e1") is True
    assert logger.emit(category=EventCategory.SCREENING, event_name="e2") is True
    assert logger.emit(category=EventCategory.STRATEGY, event_name="e3") is True
    assert logger.emit(category=EventCategory.EXECUTION, event_name="e4") is True
    assert logger.emit(category=EventCategory.RISK, event_name="e5") is True

    # Fill queue and test drop and critical priority replacement
    logger.emit(category=EventCategory.RISK, event_name="e6")
    logger.emit(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="critical_alert",
    )

    stats = logger.get_stats()
    assert stats["total_emitted"] >= 5

    await asyncio.sleep(0.25)
    await logger.flush_and_close()

    # Double close is no-op
    await logger.flush_and_close()

    assert log_file.exists()
    events = load_diagnostic_events(log_file)
    assert len(events) >= 2


async def test_ops_events_and_retention_deep_branches(tmp_path: Path):
    # 1. Disabled logger and disabled categories
    disabled_logger = DiagnosticEventLogger(enabled=False)
    assert disabled_logger.emit(event_name="noop") is False
    await disabled_logger.start()
    await disabled_logger.flush_and_close()

    # Filtered categories
    filtered_logger = DiagnosticEventLogger(
        output_path=tmp_path / "filtered.jsonl",
        enabled_categories={EventCategory.STRATEGY},
    )
    assert filtered_logger.is_category_enabled(EventCategory.RISK) is False
    assert filtered_logger.is_category_enabled("strategy") is True
    assert (
        filtered_logger.emit(category=EventCategory.RISK, event_name="drop_me") is False
    )

    evt_obj = DiagnosticEvent(category=EventCategory.RISK, event_name="drop_obj")
    assert filtered_logger.emit(evt_obj) is False

    # 2. Worker batch flush when file is None or throws
    logger_flusher = DiagnosticEventLogger(
        output_path=tmp_path / "flusher.jsonl",
        batch_size=1,
        flush_interval_seconds=0.01,
    )
    await logger_flusher.start()
    logger_flusher._file_handle = None  # simulate closed file handle during write
    logger_flusher._write_batch([DiagnosticEvent(event_name="dummy")])
    await logger_flusher.flush_and_close()

    # 3. Quota-based retention pruning with total_max_bytes
    retention_dir = tmp_path / "retention_quota"
    retention_dir.mkdir()
    policy = RetentionPolicy(
        max_bytes=100,
        max_files=5,
        total_max_bytes=150,
        compress_archives=False,
    )
    mgr = LogRetentionManager(
        retention_dir, policy=policy, file_patterns=("*.log", "*.log.*")
    )

    # Create files that exceed total_max_bytes
    for i in range(5):
        f = retention_dir / f"test.log.{i}"
        f.write_text("x" * 50, encoding="utf-8")

    pruned = mgr.prune_expired()
    assert len(pruned) >= 2
    assert mgr.get_storage_stats()["total_bytes"] <= 150

    # 4. compress_uncompressed_archives
    uncomp_log = retention_dir / "audit.jsonl.1"
    uncomp_log.write_text("line 1\nline 2\n", encoding="utf-8")
    comp_results = mgr.compress_uncompressed_archives()
    assert len(comp_results) >= 1
    assert comp_results[0].name.endswith(".gz")

    # 5. Shifting rotated files when destination already exists
    sink_path = retention_dir / "sink_shift.log"
    sink = RotatedFileSink(sink_path, policy=policy)
    # Pre-create destination files
    (retention_dir / "sink_shift.log.1").write_text("old1", encoding="utf-8")
    (retention_dir / "sink_shift.log.2").write_text("old2", encoding="utf-8")
    sink.write_batch(["new line 1\n", "new line 2\n" * 10])
    sink.rotate_now()
    sink.close()


def test_retention_and_events_exhaustive(tmp_path: Path):

    # 1. Zero-byte compression
    zero_file = tmp_path / "zero_src.log"
    zero_file.write_text("", encoding="utf-8")
    assert compress_file_to_gzip(zero_file) == zero_file

    # 2. filter_diagnostic_events
    e1 = DiagnosticEvent(
        category=EventCategory.SCREENING,
        severity=EventSeverity.INFO,
        mint="mint1",
        event_name="pass",
    )
    e2 = DiagnosticEvent(
        category=EventCategory.RISK,
        severity=EventSeverity.ERROR,
        mint="mint2",
        event_name="stop_loss",
        error_message="loss",
    )
    e3 = DiagnosticEvent(
        category=EventCategory.EXECUTION,
        severity=EventSeverity.CRITICAL,
        mint="mint3",
        event_name="timeout",
    )

    all_e = [e1, e2, e3]
    assert len(filter_diagnostic_events(all_e, mint="mint1")) == 1
    assert len(filter_diagnostic_events(all_e, category=EventCategory.RISK)) == 1
    assert len(filter_diagnostic_events(all_e, severity=EventSeverity.ERROR)) == 1
    assert len(filter_diagnostic_events(all_e, event_name="timeout")) == 1
    assert len(filter_diagnostic_events(all_e, errors_only=True)) == 2
    assert len(filter_diagnostic_events(all_e, limit=1)) == 1

    # 3. Retention policy max_bytes <= 0
    p_zero = RetentionPolicy(max_bytes=0)
    sink_zero = RotatedFileSink(tmp_path / "zero.log", policy=p_zero)
    sink_zero.write_batch([])
    assert sink_zero.rotate_if_needed() is False
    sink_zero.close()

    # 4. Retention rotate when base file does not exist
    sink_no_base = RotatedFileSink(
        tmp_path / "no_base.log", policy=RetentionPolicy(max_bytes=100)
    )
    (tmp_path / "no_base.log").unlink(missing_ok=True)
    assert sink_no_base.rotate_now() is False
    sink_no_base.close()


async def test_ops_events_logger_and_properties_deep(tmp_path: Path):
    evt = DiagnosticEvent(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="circuit_breaker",
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        mint_name="TestToken",
        latency_ms=2.5,
        data={"pnl": 0.5},
        error_message="drawdown exceeded",
    )
    d = evt.to_dict()
    assert d["event_name"] == "circuit_breaker"
    assert d["mint"] == "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    assert d["error_message"] == "drawdown exceeded"

    log_file = tmp_path / "diag_deep.jsonl"
    logger = DiagnosticEventLogger(output_path=log_file, max_queue_size=2)
    await logger.start()

    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e1"
    )
    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e2"
    )
    logger.emit(
        category=EventCategory.SCREENING, severity=EventSeverity.INFO, event_name="e3"
    )
    logger.emit(
        category=EventCategory.RISK,
        severity=EventSeverity.CRITICAL,
        event_name="crit_e4",
    )

    logger._queue = MagicMock()
    logger._queue.put_nowait.side_effect = asyncio.QueueFull()
    assert logger.emit(category=EventCategory.EXECUTION, event_name="drop_q") is False

    logger._consumer_task = None
    await logger.flush_and_close()
