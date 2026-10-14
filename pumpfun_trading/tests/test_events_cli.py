"""Unit tests for FEAT-30 Diagnostic Events Inspection CLI."""

from __future__ import annotations

import argparse
import json
import tempfile
from io import StringIO
from pathlib import Path

from rich.console import Console

from pumpfun_trading.cli.events import (
    calculate_latency_stats,
    filter_diagnostic_events,
    load_diagnostic_events,
    render_events_table,
    render_latency_table,
    run_events_cli,
)
from pumpfun_trading.ops.events import DiagnosticEvent, EventCategory, EventSeverity


def _sample_events() -> list[DiagnosticEvent]:
    return [
        DiagnosticEvent(
            timestamp_ns=1700000000000000000,
            iso_timestamp="2026-10-14T12:00:00+00:00",
            category=EventCategory.STREAM,
            severity=EventSeverity.INFO,
            event_name="slot_latency",
            latency_ms=10.5,
            data={"slot": 100},
        ),
        DiagnosticEvent(
            timestamp_ns=1700000001000000000,
            iso_timestamp="2026-10-14T12:00:01+00:00",
            category=EventCategory.SCREENING,
            severity=EventSeverity.WARNING,
            event_name="token_screen_rejected",
            mint="7EYnhcWvdqPB2DdJ6DXZsMvT8GqgE4F8V9m1pump",
            mint_name="SolCat",
            latency_ms=25.0,
            data={"gini_score": 0.88},
            error_message="High Gini inequality",
        ),
        DiagnosticEvent(
            timestamp_ns=1700000002000000000,
            iso_timestamp="2026-10-14T12:00:02+00:00",
            category=EventCategory.EXECUTION,
            severity=EventSeverity.ERROR,
            event_name="bundle_failed",
            mint="3xP9kcWvdqPB2DdJ6DXZsMvT8GqgE4F8V9m1pump",
            mint_name="MoonDog",
            latency_ms=45.2,
            error_message="Tip floor too low",
        ),
    ]


def test_load_and_filter_diagnostic_events() -> None:
    events = _sample_events()
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "test_events.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for evt in events:
                f.write(json.dumps(evt.to_dict()) + "\n")

        loaded = load_diagnostic_events(path)
        assert len(loaded) == 3

        # Filter by category
        stream_events = filter_diagnostic_events(loaded, category="stream")
        assert len(stream_events) == 1
        assert stream_events[0].event_name == "slot_latency"

        # Filter by errors only (warning, error, critical)
        error_events = filter_diagnostic_events(loaded, errors_only=True)
        assert len(error_events) == 2

        # Filter by mint
        mint_events = filter_diagnostic_events(loaded, mint="7EYnh")
        assert len(mint_events) == 1
        assert mint_events[0].mint_name == "SolCat"

        # Filter by token name
        named_events = filter_diagnostic_events(loaded, mint_name="MoonDog")
        assert len(named_events) == 1
        assert named_events[0].event_name == "bundle_failed"


def test_calculate_latency_stats() -> None:
    events = _sample_events()
    stats = calculate_latency_stats(events)

    assert "overall" in stats
    assert stats["overall"]["count"] == 3
    assert stats["overall"]["min_ms"] == 10.5
    assert stats["overall"]["max_ms"] == 45.2
    assert "by_category" in stats
    assert "stream" in stats["by_category"]
    assert "execution" in stats["by_category"]


def test_render_tables() -> None:
    events = _sample_events()
    string_io = StringIO()
    custom_console = Console(file=string_io, color_system=None, width=140)

    render_events_table(events, console_out=custom_console)
    output = string_io.getvalue()
    assert "SolCat" in output
    assert "bundle_failed" in output

    string_io2 = StringIO()
    custom_console2 = Console(file=string_io2, color_system=None, width=140)
    stats = calculate_latency_stats(events)
    render_latency_table(stats, console_out=custom_console2)
    output2 = string_io2.getvalue()
    assert "Overall Portfolio" in output2
    assert "Category: stream" in output2


def test_cli_execution_modes() -> None:
    events = _sample_events()
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "test_events.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for evt in events:
                f.write(json.dumps(evt.to_dict()) + "\n")

        # 1. Test json stdout output
        args_json = argparse.Namespace(
            path=str(path),
            category=None,
            severity=None,
            mint=None,
            mint_name=None,
            event_name=None,
            errors_only=False,
            latency_stats=False,
            limit=50,
            json=True,
            export=None,
            tail=False,
        )
        run_events_cli(args_json)

        # 2. Test export to file
        export_file = Path(tmp_dir) / "exported.json"
        args_export = argparse.Namespace(
            path=str(path),
            category="screening",
            severity=None,
            mint=None,
            mint_name=None,
            event_name=None,
            errors_only=False,
            latency_stats=False,
            limit=50,
            json=False,
            export=str(export_file),
            tail=False,
        )
        run_events_cli(args_export)
        assert export_file.exists()
        exported_data = json.loads(export_file.read_text(encoding="utf-8"))
        assert len(exported_data) == 1
        assert exported_data[0]["event_name"] == "token_screen_rejected"

        # 3. Test latency-stats mode
        args_stats = argparse.Namespace(
            path=str(path),
            category=None,
            severity=None,
            mint=None,
            mint_name=None,
            event_name=None,
            errors_only=False,
            latency_stats=True,
            limit=50,
            json=False,
            export=None,
            tail=False,
        )
        run_events_cli(args_stats)
