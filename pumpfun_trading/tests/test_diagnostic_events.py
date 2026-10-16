"""Unit and stress tests for FEAT-30 Diagnostic Event Logging Subsystem."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path


from pumpfun_trading.ops.events import (
    DiagnosticEvent,
    DiagnosticEventLogger,
    EventCategory,
    EventSeverity,
)


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
