"""Unit tests for ``cli/events.py`` loading, latency analytics and live tailing."""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import types
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.cli import events as events_cli
from pumpfun_trading.cli.events import (
    calculate_latency_stats,
    filter_diagnostic_events,
    load_diagnostic_events,
    render_events_table,
    render_latency_table,
    run_events_cli,
)
from pumpfun_trading.ops.events import DiagnosticEvent, EventCategory, EventSeverity


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    """The CLI console, recording instead of writing to the terminal."""
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(events_cli, "console", console)
    return console


def _event(**overrides: Any) -> DiagnosticEvent:
    fields: dict[str, Any] = {
        "timestamp_ns": 1_792_141_900_000_000_000,
        "category": EventCategory.EXECUTION,
        "severity": EventSeverity.ERROR,
        "event_name": "buy_failed",
        "mint": "TailMint1111111111111111111111111111111111",
        "latency_ms": 12.5,
        "error_message": "slippage",
    }
    fields.update(overrides)
    return DiagnosticEvent(**fields)


def _line(evt: DiagnosticEvent) -> str:
    return json.dumps(evt.to_dict()) + "\n"


def _args(*argv: str) -> Any:
    return events_cli.build_events_parser().parse_args(list(argv))


def test_load_diagnostic_events_missing_file_returns_empty(tmp_path: Path) -> None:
    assert events_cli.load_diagnostic_events(tmp_path / "absent.jsonl") == []


def test_load_diagnostic_events_skips_blank_and_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n   \n"
        + "{not json\n"
        + '"a bare string"\n'
        + _line(_event(event_name="kept")),
        encoding="utf-8",
    )

    loaded = events_cli.load_diagnostic_events(path)

    assert [e.event_name for e in loaded] == ["kept"]
    assert loaded[0].severity is EventSeverity.ERROR


@pytest.mark.parametrize("latency", [None, -1.0])
def test_calculate_latency_stats_without_valid_latency_reports_zero(
    latency: float | None,
) -> None:
    stats = events_cli.calculate_latency_stats([_event(latency_ms=latency)])
    assert stats == {"total_events_with_latency": 0}


def test_calculate_latency_stats_ignores_negative_latencies() -> None:
    stats = events_cli.calculate_latency_stats(
        [_event(latency_ms=-5.0), _event(latency_ms=10.0), _event(latency_ms=30.0)]
    )

    assert stats["overall"]["count"] == 2
    assert stats["overall"]["min_ms"] == 10.0
    assert stats["overall"]["avg_ms"] == 20.0
    assert set(stats["by_category"]) == {"execution"}


def test_run_events_cli_latency_stats_without_latency_prints_notice(
    tmp_path: Path, output: Console
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(_event(latency_ms=None)), encoding="utf-8")

    events_cli.run_events_cli(_args("--path", str(path), "--latency-stats"))

    assert "No latency telemetry recorded" in output.export_text()


def _tail_with_appended_lines(
    monkeypatch: pytest.MonkeyPatch, path: Path, lines: list[str]
) -> list[float]:
    """Make ``time.sleep`` append ``lines`` on the first poll, then stop the tail."""
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            with open(path, "a", encoding="utf-8") as f:
                f.writelines(lines)
            return
        raise KeyboardInterrupt

    monkeypatch.setattr(events_cli, "time", types.SimpleNamespace(sleep=fake_sleep))
    return sleeps


@pytest.mark.parametrize("as_json", [True, False])
def test_run_events_cli_tail_renders_only_new_matching_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    as_json: bool,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(_event(event_name="historic_error")), encoding="utf-8")
    sleeps = _tail_with_appended_lines(
        monkeypatch,
        path,
        [
            _line(_event(event_name="info_noise", severity=EventSeverity.INFO)),
            "{corrupt\n",
            _line(_event(event_name="fresh_error")),
        ],
    )
    argv = ["--path", str(path), "--tail", "--errors-only"]
    if as_json:
        argv.append("--json")

    events_cli.run_events_cli(_args(*argv))

    out = output.export_text()
    assert sleeps == [0.2, 0.2]
    assert "fresh_error" in out
    assert "historic_error" not in out
    assert "info_noise" not in out
    assert "Tailing stopped." in out
    if as_json:
        assert out.count('"event_name": "fresh_error"') == 1
        assert "Diagnostic Telemetry Events" not in out
    else:
        assert "Diagnostic Telemetry Events (1 records)" in out
        assert "Error: slippage" in out


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
