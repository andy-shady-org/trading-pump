"""Unit tests for ``cli/events.py`` loading, latency analytics and live tailing."""

from __future__ import annotations

import io
import json
import types
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.cli import events as events_cli
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
