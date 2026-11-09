"""Unit tests for ``cli/main.py``: the ``trading-pump`` command."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from trading_pump.cli import main as main_cli
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_reading


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(main_cli, "console", console)
    return console


def _capture(path: Path) -> None:
    rows: list[dict[str, Any]] = [
        {
            "timestamp": 0.0,
            "mint": SAMPLE_MINT,
            "event": "observation_start",
            "source": "graduation",
            "migrated_at": 0.0,
        }
    ]
    rows += [
        make_reading(SAMPLE_MINT, at=2.0 * i).capture_row(source="graduation")
        for i in range(1, 10)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "module": "pumpfun",
                "order_size": 0.02,
                "risk": {"max_total_exposure": 0.2, "max_position_size": 0.02},
            }
        )
    )


def test_replay_prints_a_summary(tmp_path: Path, output: Console) -> None:
    _capture(tmp_path / "c.jsonl")
    _config(tmp_path / "s.json")
    code = main_cli.main(
        [
            "replay",
            "--config",
            str(tmp_path / "s.json"),
            "--capture",
            str(tmp_path / "c.jsonl"),
            "--out",
            str(tmp_path / "run"),
        ]
    )
    text = output.export_text()
    assert code == main_cli.EXIT_OK
    assert "Migrations" in text and "Closed positions" in text
    assert "trading-core-audit pnl --path" in text
    assert (tmp_path / "run" / "audit.jsonl").exists()


def test_replay_errors_exit_2(tmp_path: Path, output: Console) -> None:
    _config(tmp_path / "s.json")
    (tmp_path / "empty.jsonl").write_text("")
    code = main_cli.main(
        [
            "replay",
            "--config",
            str(tmp_path / "s.json"),
            "--capture",
            str(tmp_path / "empty.jsonl"),
            "--out",
            str(tmp_path / "run"),
        ]
    )
    assert code == main_cli.EXIT_USAGE
    assert "no graduation rows" in output.export_text()
    missing = main_cli.main(
        ["replay", "--config", "nope.json", "--capture", "x", "--out", "y"]
    )
    assert missing == main_cli.EXIT_USAGE


def test_lane_rows_writes_the_capture_and_counts_it(
    tmp_path: Path, output: Console
) -> None:
    _capture(tmp_path / "c.jsonl")
    out = tmp_path / "rows.jsonl.gz"
    code = main_cli.main(
        ["lane-rows", "--capture", str(tmp_path / "c.jsonl"), "--out", str(out)]
    )
    text = " ".join(output.export_text().split())
    assert code == main_cli.EXIT_OK and out.exists()
    assert "listing │ 1" in text and "reading │ 9" in text
    assert "trade │ 0" in text and "holders │ 0" in text
    assert "skipped │ 0" in text and "trading-core-lanes sweep --capture pump=" in text


def test_lane_rows_lists_what_it_skipped(tmp_path: Path, output: Console) -> None:
    rows = [
        make_reading(SAMPLE_MINT, at=1.0).capture_row(source="graduation"),
        {"event": "migration", "mint": SAMPLE_MINT, "timestamp": 0.0},
    ]
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    code = main_cli.main(
        [
            "lane-rows",
            "--capture",
            str(tmp_path / "c.jsonl"),
            "--out",
            str(tmp_path / "rows.jsonl"),
            "--source",
            "graduation",
        ]
    )
    text = " ".join(output.export_text().split())
    assert code == main_cli.EXIT_OK
    assert "no listing in the capture" in text and "migration │ 1" in text


def test_lane_rows_errors_exit_2(tmp_path: Path, output: Console) -> None:
    code = main_cli.main(
        ["lane-rows", "--capture", str(tmp_path / "missing.jsonl"), "--out", "x.csv"]
    )
    assert code == main_cli.EXIT_USAGE
    assert "Cannot write lane rows" in output.export_text()


def test_env_lists_names_and_states_never_values(
    monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://rpc.example/?api-key=SECRET")
    monkeypatch.setenv("SOLANA_PRIVATE_KEY", "also-secret")
    monkeypatch.setenv("PUMPFUN_ARB_ENABLED", "true")

    assert main_cli.main(["env"]) == main_cli.EXIT_OK

    text = output.export_text()
    assert "SECRET" not in text and "also-secret" not in text
    assert "set as SOLANA_PRIVATE_KEY" in text
    assert "PUMPFUN_ARB_ENABLED is set but not read" in text
    assert "unset" in text


def test_the_retired_record_command_is_gone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The FEAT-65 slow-lane recorders were retired in 0.5.0 (CHANGELOG).
    with pytest.raises(SystemExit):
        main_cli.main(["record", "--jupiter-quotes"])
    assert "invalid choice: 'record'" in capsys.readouterr().err


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main_cli.main([])


def _probe_result(tmp_path: Path, *, stopped: bool):
    from trading_solana.land_probe import ModeReport

    from trading_pump.probe import ProbeResult

    report = ModeReport("home", "rpc", 2, 2, 0, 1.0, 1.0, 2.0, 0.5, 0.6, 0.9, 5000.0)
    return ProbeResult([], [report], stopped, 0, 1, tmp_path / "p.jsonl.report.json")


@pytest.mark.parametrize("stopped", [False, True])
def test_land_probe_prints_its_report(
    tmp_path: Path, output: Console, monkeypatch: pytest.MonkeyPatch, stopped: bool
) -> None:
    seen: list[Any] = []

    async def fake_run(options: Any, credentials: Any) -> Any:
        seen.append(options)
        return _probe_result(tmp_path, stopped=stopped)

    monkeypatch.setattr(main_cli, "run_land_probe", fake_run)
    code = main_cli.main(
        [
            "land-probe",
            "--modes",
            "rpc, jito",
            "--count",
            "3",
            "--interval",
            "2",
            "--out",
            str(tmp_path / "p.jsonl"),
            "--host",
            "uk",
            "--delays",
            str(tmp_path / "d.txt"),
        ]
    )
    assert code == main_cli.EXIT_OK
    (options,) = seen
    assert options.modes == ("rpc", "jito") and options.host == "uk"
    assert options.count == 3 and options.interval_seconds == 2.0
    assert options.max_spend_sol == 0.01 and options.max_tip_lamports == 10_000
    text = output.export_text()
    assert "Landing probe" in text and "5,000" in text
    assert ("spending cap" in text) is stopped


def test_land_probe_errors_exit_2(tmp_path: Path, output: Console) -> None:
    code = main_cli.main(
        [
            "land-probe",
            "--modes",
            "smoke",
            "--count",
            "1",
            "--interval",
            "1",
            "--out",
            str(tmp_path / "p.jsonl"),
            "--host",
            "uk",
        ]
    )
    assert code == main_cli.EXIT_USAGE
    assert "Cannot run the landing probe" in output.export_text()
