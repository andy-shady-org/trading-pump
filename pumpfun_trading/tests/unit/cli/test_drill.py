"""Tests for ``cli/drill.py`` (``pumpfun-drill`` / ``pumpfun ops drill``, FEAT-69)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.cli import drill as drill_cli
from pumpfun_trading.cli.main import _build_parser, run_ops_cli
from pumpfun_trading.ops.drills import DrillReport, DrillResult


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(drill_cli, "console", console)
    return console


def test_drill_cli_runs_selected_drills_and_writes_the_report(
    tmp_path: Path, output: Console
) -> None:
    report = tmp_path / "out" / "drills.json"
    args = drill_cli.build_parser().parse_args(
        [
            "--only",
            "slow_tier_sell",
            "--workdir",
            str(tmp_path / "work"),
            "--report",
            str(report),
        ]
    )
    drill_cli.run_drill_cli(args)

    text = output.export_text()
    assert "slow_tier_sell" in text and "1 of 1 drills passed" in text
    data = json.loads(report.read_text())
    assert data["passed"] is True
    assert data["drills"][0]["name"] == "slow_tier_sell"


def test_drill_cli_json_list_and_failure_exit(
    output: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    drill_cli.run_drill_cli(drill_cli.build_parser().parse_args(["--list"]))
    listed = output.export_text()
    assert "cumulative_cap:" in listed and "midnight_lock:" in listed

    failing = DrillResult("midnight_lock", "t")
    failing.check("lock holds", False, "released at 00:00")
    errored = DrillResult("balance_rpc_down", "t", error="RuntimeError: x")

    async def fake_run(names: Any = None, *, workdir: Any = None) -> DrillReport:
        return DrillReport([failing, errored], "/tmp/x", "2026-01-01T00:00:00Z")

    monkeypatch.setattr(drill_cli, "run_drills", fake_run)
    with pytest.raises(SystemExit) as exc:
        drill_cli.run_drill_cli(drill_cli.build_parser().parse_args([]))
    assert exc.value.code == 1
    text = output.export_text()
    assert "FAIL" in text and "ERROR" in text and "0 of 2 drills passed" in text

    with pytest.raises(SystemExit):
        drill_cli.run_drill_cli(drill_cli.build_parser().parse_args(["--json"]))
    assert '"passed": false' in output.export_text()


def test_ops_drill_subcommand_dispatches(
    output: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_cli(args: Any) -> None:
        seen["only"] = args.only

    monkeypatch.setattr(drill_cli, "run_drill_cli", fake_cli)
    args = _build_parser().parse_args(["ops", "drill", "--only", "cumulative_cap"])
    run_ops_cli(args)
    assert seen["only"] == ["cumulative_cap"]


def test_main_parses_the_command_line(
    monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr("sys.argv", ["pumpfun-drill", "--list"])
    drill_cli.main()
    assert "slow_tier_sell" in output.export_text()
