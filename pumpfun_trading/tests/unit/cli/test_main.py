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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

import pumpfun_trading.cli as cli_init
import pumpfun_trading.cli.main as cli_main_mod
from pumpfun_trading.cli import bot as cli_bot
from pumpfun_trading.cli import main as main_cli
from pumpfun_trading.cli.main import _build_parser, main, run_ops_cli
from pumpfun_trading.tests.support.constants import SAMPLE_MINT


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


def test_cli_init_exports():
    assert hasattr(cli_init, "main")
    assert hasattr(cli_init, "run_replay_cli")
    assert hasattr(cli_init, "load_audit_records")
    assert hasattr(cli_init, "filter_audit_records")
    assert hasattr(cli_init, "export_audit_records")


def test_cli_main_helper_functions():
    # _coerce_list
    assert cli_main_mod._coerce_list([{"a": 1}, "string", 123]) == [{"a": 1}]
    assert cli_main_mod._coerce_list({"data": [{"x": 2}]}) == [{"x": 2}]
    assert cli_main_mod._coerce_list({"items": [{"y": 3}]}) == [{"y": 3}]
    assert cli_main_mod._coerce_list({"coins": [{"c": 4}]}) == [{"c": 4}]
    assert cli_main_mod._coerce_list({"result": [{"r": 5}]}) == [{"r": 5}]
    assert cli_main_mod._coerce_list({"results": [{"rs": 6}]}) == [{"rs": 6}]
    assert cli_main_mod._coerce_list("invalid") == []
    assert cli_main_mod._coerce_list({"other": 123}) == []

    # _first_key
    record = {"a": None, "b": 10, "c": 20}
    assert cli_main_mod._first_key(record, "a", "b", "c") == 10
    assert cli_main_mod._first_key(record, "z", "w") is None

    # _format_value
    assert cli_main_mod._format_value(None) == "-"
    assert cli_main_mod._format_value(True) == "true"
    assert cli_main_mod._format_value(False) == "false"
    assert cli_main_mod._format_value(1234.56789) == "1,234.5679"
    assert cli_main_mod._format_value(1000000) == "1,000,000"
    assert cli_main_mod._format_value("custom") == "custom"


def test_cli_main_rendering():
    # _render_latest_coins
    cli_main_mod._render_latest_coins([])
    cli_main_mod._render_latest_coins(
        [
            {
                "name": "Token A",
                "symbol": "TKA",
                "mint": "Mint1111111111111111111111111111111111",
                "marketCap": 50000.0,
                "price": 0.0012,
                "holders": 42,
            }
        ]
    )

    # _render_market_info
    cli_main_mod._render_market_info(123)  # Non-dict
    cli_main_mod._render_market_info([])  # Empty list
    cli_main_mod._render_market_info(
        [
            {
                "name": "Token B",
                "symbol": "TKB",
                "mint": "Mint2222222222222222222222222222222222",
                "marketCap": 120000.0,
                "price": 0.05,
                "volume": 250000.0,
                "holders": 350,
                "extra_field": "some extra value",
                "extra_dict": {"nested": "value"},
            }
        ]
    )

    # _render_raw_json
    cli_main_mod._render_raw_json({"status": "ok", "value": 123})


def test_cli_main_entrypoint(tmp_path):
    # Test audit subcommand routing
    with patch("pumpfun_trading.cli.main.run_audit_cli") as mock_audit:
        with patch("sys.argv", ["pumpfun", "audit", "--path", "audit.jsonl"]):
            cli_main_mod.main()
            assert mock_audit.called

    # Test replay subcommand routing
    dataset = tmp_path / "data.json"
    dataset.write_text("[]", encoding="utf-8")
    with patch("pumpfun_trading.cli.replay.run_replay_cli") as mock_replay:
        with patch("sys.argv", ["pumpfun", "replay", "--path", str(dataset)]):
            cli_main_mod.main()
            assert mock_replay.called

    with patch("sys.argv", ["pumpfun", "replay"]):
        with pytest.raises(SystemExit):
            cli_main_mod.main()

    # Test mode == latest-coins
    mock_client = MagicMock()
    mock_client.get_latest_coins = AsyncMock(return_value=[{"name": "Coin 1"}])
    mock_client.close = AsyncMock()

    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("asyncio.run", side_effect=lambda coro: coro.close()):
            with patch("sys.argv", ["pumpfun", "--mode", "latest-coins", "--raw"]):
                cli_main_mod.main()

            with patch("sys.argv", ["pumpfun", "--mode", "latest-coins"]):
                cli_main_mod.main()

    # Test mode == market-info
    mock_client.get_coin = AsyncMock(return_value={"name": "Coin 1", "mint": "Mint1"})
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("asyncio.run", side_effect=lambda coro: coro.close()):
            with patch(
                "sys.argv",
                ["pumpfun", "--mode", "market-info", "--mint", "Mint1", "--raw"],
            ):
                cli_main_mod.main()

            with patch(
                "sys.argv", ["pumpfun", "--mode", "market-info", "--mint", "Mint1"]
            ):
                cli_main_mod.main()

        with patch("sys.argv", ["pumpfun", "--mode", "market-info"]):
            with pytest.raises(SystemExit):
                cli_main_mod.main()

    # Test mode == replay with --replay-path
    with patch("pumpfun_trading.cli.replay.run_replay_cli") as mock_replay:
        with patch(
            "sys.argv", ["pumpfun", "--mode", "replay", "--replay-path", str(dataset)]
        ):
            cli_main_mod.main()
            assert mock_replay.called

        with patch("sys.argv", ["pumpfun", "--mode", "replay"]):
            with pytest.raises(SystemExit):
                cli_main_mod.main()

    # Test mode == bot
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    with patch("pumpfun_trading.cli.main.TradingBot.from_env", return_value=mock_bot):
        with patch("asyncio.run", side_effect=lambda coro: coro.close()):
            with patch("sys.argv", ["pumpfun", "--mode", "bot", "--dry-run"]):
                cli_main_mod.main()


def test_cli_all_modes_and_flags(tmp_path):
    cfg_file = tmp_path / "bot_conf.json"
    cfg_file.write_text(json.dumps({"buy_amount_sol": 0.05}), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.get_latest_coins = AsyncMock(return_value=[{"name": "Coin1"}])
    mock_client.get_coin = AsyncMock(
        return_value={"name": "Coin1", "mint": SAMPLE_MINT}
    )
    mock_client.close = AsyncMock()

    # 1. main mode == latest-coins with --raw
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("sys.argv", ["pumpfun", "--mode", "latest-coins", "--raw"]):
            cli_main_mod.main()

    # 2. main mode == market-info with --raw
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch(
            "sys.argv",
            ["pumpfun", "--mode", "market-info", "--mint", SAMPLE_MINT, "--raw"],
        ):
            cli_main_mod.main()

    # 3. main mode == bot with --config and --raw
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    with patch("pumpfun_trading.cli.main.TradingBot.from_env", return_value=mock_bot):
        with patch(
            "sys.argv",
            ["pumpfun", "--mode", "bot", "--config", str(cfg_file), "--dry-run"],
        ):
            cli_main_mod.main()

    # 4. cli_bot main with --config
    with patch("pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot):
        with patch("sys.argv", ["pumpfun-bot", "--config", str(cfg_file), "--dry-run"]):
            cli_bot.main()


def test_cli_runners_execution():
    mock_client = MagicMock()
    mock_client.get_latest_coins = AsyncMock(return_value=[{"name": "Coin1"}])
    mock_client.get_coin = AsyncMock(
        return_value={"name": "Coin1", "mint": SAMPLE_MINT}
    )
    mock_client.close = AsyncMock()

    # 1. main mode == latest-coins
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("sys.argv", ["pumpfun", "--mode", "latest-coins"]):
            cli_main_mod.main()

    # 2. main mode == market-info
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch(
            "sys.argv", ["pumpfun", "--mode", "market-info", "--mint", SAMPLE_MINT]
        ):
            cli_main_mod.main()

    # 3. cli_bot main
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    with patch("pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot):
        with patch("sys.argv", ["pumpfun-bot", "--dry-run"]):
            cli_bot.main()


def test_cli_entrypoints_coverage():
    from pumpfun_trading.cli.bot import main as bot_main_func
    from pumpfun_trading.cli.main import main as cli_main_func

    # Test main CLI with mode=bot catching KeyboardInterrupt
    with (
        patch(
            "sys.argv",
            ["pumpfun-cli", "--mode", "bot", "--dry-run", "--preset", "balanced"],
        ),
        patch("pumpfun_trading.bot.run.TradingBot.from_env") as mock_bot_factory,
    ):
        mock_bot_instance = MagicMock()
        mock_bot_instance.start = AsyncMock(side_effect=KeyboardInterrupt)
        mock_bot_instance.close = AsyncMock()
        mock_bot_factory.return_value = mock_bot_instance

        cli_main_func()
        mock_bot_instance.close.assert_called_once()

    # Test bot CLI main catching KeyboardInterrupt
    with patch("pumpfun_trading.cli.bot.build_parser") as mock_parser_builder:
        parser = MagicMock()
        parser.parse_args.return_value = MagicMock(
            config=None,
            preset="balanced",
            dry_run=True,
            paper_trade=True,
            headless=False,
            buy_amount_sol=None,
            take_profit=None,
            stop_loss=None,
            min_market_cap_sol=None,
            min_balance_sol=None,
        )
        mock_parser_builder.return_value = parser
        with patch("pumpfun_trading.bot.run.TradingBot.from_env") as mock_bot_factory:
            mock_bot_instance = MagicMock()
            mock_bot_instance.start = AsyncMock(side_effect=KeyboardInterrupt)
            mock_bot_instance.close = AsyncMock()
            mock_bot_factory.return_value = mock_bot_instance

            bot_main_func()
            mock_bot_instance.close.assert_called_once()


def test_cli_dispatchers_and_subcommands(tmp_path: Path):
    from pumpfun_trading.cli.bot import build_parser as build_bot_parser
    from pumpfun_trading.cli.main import _build_parser as build_main_parser
    from pumpfun_trading.cli.optimize import build_optimize_parser, run_optimize_cli
    from pumpfun_trading.cli.record import build_record_parser, run_record_cli
    from pumpfun_trading.cli.replay import build_replay_parser, run_replay_cli

    # Bot parser
    bot_p = build_bot_parser()
    bot_args = bot_p.parse_args(["--dry-run", "--headless", "--preset", "aggressive"])
    assert bot_args.preset == "aggressive"

    # Main parser subcommands
    main_p = build_main_parser()
    assert main_p.parse_args(["--mode", "bot", "--dry-run"]).mode == "bot"
    assert main_p.parse_args(["replay", "--path", "dummy.jsonl"]).command == "replay"
    assert main_p.parse_args(["record", "--duration", "5"]).command == "record"
    assert main_p.parse_args(["audit", "--path", "audit.jsonl"]).command == "audit"
    assert main_p.parse_args(["events"]).command == "events"
    assert main_p.parse_args(["optimize"]).command == "optimize"
    assert main_p.parse_args(["arb"]).command == "arb"

    # Optimize CLI run
    replay_file = tmp_path / "opt_rep.jsonl"
    event = {
        "timestamp": 1000.0,
        "mint": "m1",
        "market_cap_sol": 30.0,
        "is_buy": True,
        "sol_amount": 0.1,
    }
    replay_file.write_text(json.dumps(event) + "\n", encoding="utf-8")
    opt_p = build_optimize_parser()
    opt_args = opt_p.parse_args(
        ["--dataset", str(replay_file), "--method", "random", "--iterations", "1"]
    )
    run_optimize_cli(opt_args)

    # Replay CLI run
    rep_p = build_replay_parser()
    rep_args = rep_p.parse_args(["--path", str(replay_file), "--initial-cash", "50.0"])
    run_replay_cli(rep_args)

    # Record CLI synthetic generation
    rec_out = tmp_path / "rec_out.jsonl"
    rec_p = build_record_parser()
    rec_args = rec_p.parse_args(
        ["--synthetic", "multi_tier_take_profit", "--output", str(rec_out)]
    )
    run_record_cli(rec_args)
    assert rec_out.exists()
