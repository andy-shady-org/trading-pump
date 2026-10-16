"""Unit tests for ``cli/main.py`` subcommand dispatch and ``ops`` maintenance commands."""

from __future__ import annotations

import argparse
import io
import json
import os
import runpy
import sys
import tempfile
import time
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from pumpfun_trading.cli import main as main_cli
from pumpfun_trading.cli.main import _build_parser, main, run_ops_cli


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    """The CLI console, recording instead of writing to the terminal."""
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(main_cli, "console", console)
    return console


@pytest.mark.parametrize(
    ("argv", "handler"),
    [
        (["arb"], "run_arbitrage_cli"),
        (["arbitrage"], "run_arbitrage_cli"),
        (["events", "--errors-only"], "run_events_cli"),
        (["record", "--synthetic", "flash_rug"], "run_record_cli"),
    ],
)
def test_main_subcommand_dispatches_to_its_handler_only(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], handler: str
) -> None:
    handlers = {
        name: MagicMock()
        for name in (
            "run_arbitrage_cli",
            "run_audit_cli",
            "run_events_cli",
            "run_optimize_cli",
            "run_record_cli",
            "run_ops_cli",
        )
    }
    for name, mock in handlers.items():
        monkeypatch.setattr(main_cli, name, mock)
    monkeypatch.setattr(sys, "argv", ["pumpfun", *argv])

    main_cli.main()

    handlers[handler].assert_called_once()
    (args,), _ = handlers[handler].call_args
    assert args.command == argv[0]
    assert [n for n, m in handlers.items() if m.called] == [handler]


def test_build_ops_parser_standalone_parses_prune_options() -> None:
    parser = main_cli.build_ops_parser()

    args = parser.parse_args(["prune", "--days", "5", "--max-files", "3"])

    assert parser.description is not None and "retention" in parser.description
    assert (args.ops_command, args.days, args.max_files, args.compress) == (
        "prune",
        5,
        3,
        False,
    )


def test_run_ops_cli_prune_without_compress_removes_only_expired_archives(
    tmp_path: Path, output: Console
) -> None:
    old = tmp_path / "bot.log.1"
    old.write_text("old", encoding="utf-8")
    stale = time.time() - 10 * 86_400
    os.utime(old, (stale, stale))
    live = tmp_path / "bot.log"
    live.write_text("live", encoding="utf-8")
    args = main_cli.build_ops_parser().parse_args(
        ["prune", "--target", str(tmp_path), "--days", "1"]
    )

    main_cli.run_ops_cli(args)

    out = output.export_text()
    assert not old.exists() and live.exists()
    assert "Successfully pruned 1 expired files" in out
    assert "Compressed" not in out


def test_run_ops_cli_unknown_command_does_nothing(
    tmp_path: Path, output: Console
) -> None:
    archive = tmp_path / "bot.log.1"
    archive.write_text("keep", encoding="utf-8")
    args = argparse.Namespace(ops_command="defrag", target=str(tmp_path))

    main_cli.run_ops_cli(args)

    assert archive.exists()
    assert output.export_text() == ""


def test_main_module_run_as_script_prints_ops_status_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "bot.log").write_text("x" * 10, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["pumpfun", "ops", "status", "--json"])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("pumpfun_trading.cli.main", run_name="__main__")

    stats = json.loads(capsys.readouterr().out)
    assert stats["directory"] == "."
    assert stats["exists"] is True
    assert stats["file_count"] == 1
    assert stats["total_bytes"] == 10


def test_build_ops_parser():
    parser = _build_parser()
    args = parser.parse_args(["ops", "status", "--target", ".", "--json"])
    assert args.command == "ops"
    assert args.ops_command == "status"
    assert args.json is True

    args_prune = parser.parse_args(
        ["ops", "prune", "--target", "/tmp", "--days", "15", "--compress"]
    )
    assert args_prune.command == "ops"
    assert args_prune.ops_command == "prune"
    assert args_prune.days == 15
    assert args_prune.compress is True


def test_run_ops_cli_status_and_prune():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "test.log").write_text("hello log", encoding="utf-8")
        (td / "test.log.1").write_text("old log", encoding="utf-8")

        parser = _build_parser()

        # Status text table
        args_status = parser.parse_args(["ops", "status", "--target", str(td)])
        run_ops_cli(args_status)

        # Status JSON
        args_status_json = parser.parse_args(
            ["ops", "status", "--target", str(td), "--json"]
        )
        run_ops_cli(args_status_json)

        # Prune and compress
        args_prune = parser.parse_args(
            ["ops", "prune", "--target", str(td), "--days", "0", "--compress"]
        )
        run_ops_cli(args_prune)

        # Main entrypoint dispatch
        with patch("sys.argv", ["pumpfun", "ops", "status", "--target", str(td)]):
            main()
