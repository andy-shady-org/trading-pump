from __future__ import annotations

import argparse
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pumpfun_trading.cli as cli_init
import pumpfun_trading.cli.audit as cli_audit
import pumpfun_trading.cli.bot as cli_bot
import pumpfun_trading.cli.replay as cli_replay

cli_main_mod = sys.modules["pumpfun_trading.cli.main"]


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


def test_cli_audit_subcommand(tmp_path):
    audit_file = tmp_path / "audit.jsonl"
    record = {
        "timestamp": 1700000000.0,
        "type": "trade",
        "mint": "MintAudit111",
        "action": "buy",
        "status": "success",
    }
    audit_file.write_text(json.dumps(record) + "\n", encoding="utf-8")

    # Audit summary
    args = argparse.Namespace(
        path=str(audit_file),
        record_type=None,
        state=None,
        date_from=None,
        date_to=None,
        mint=None,
        token_name=None,
        reason=None,
        status=None,
        limit=None,
        summary=True,
        json=False,
        export=None,
    )
    cli_audit.run_audit_cli(args)

    # Audit export
    export_out = tmp_path / "exported.json"
    args.summary = False
    args.export = str(export_out)
    cli_audit.run_audit_cli(args)
    assert export_out.exists()

    # Audit JSON output
    args.export = None
    args.json = True
    cli_audit.run_audit_cli(args)

    # Audit table output
    args.json = False
    cli_audit.run_audit_cli(args)

    # Audit empty records
    args.mint = "NonExistent"
    cli_audit.run_audit_cli(args)

    # Audit main with parsed args
    with patch(
        "sys.argv",
        ["audit_cli", "--path", str(audit_file), "--summary"],
    ):
        cli_audit.main()


def test_cli_replay_subcommand(tmp_path):
    dataset_file = tmp_path / "replay.json"
    dataset_file.write_text(
        json.dumps(
            [
                {
                    "mint": "MintReplay1",
                    "price": 10.0,
                    "marketCapSol": 25.0,
                    "timestamp": 1700000000,
                    "buy_signal": True,
                },
                {
                    "mint": "MintReplay1",
                    "price": 20.0,
                    "marketCapSol": 50.0,
                    "timestamp": 1700000010,
                    "sell_signal": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    # Summary mode
    args = argparse.Namespace(
        path=str(dataset_file),
        mode="summary",
    )
    cli_replay.run_replay_cli(args)

    # Trades mode
    args.mode = "trades"
    args.mint = "MintReplay1"
    args.mint_name = None
    args.token_name = None
    cli_replay.run_replay_cli(args)

    # Filter with mint_name
    args.mode = "trades"
    args.mint = None
    args.mint_name = "NonExistent"
    cli_replay.run_replay_cli(args)

    # Dashboard mode
    args.mode = "dashboard"
    args.mint = None
    args.mint_name = None
    cli_replay.run_replay_cli(args)

    # Missing path
    args_empty = argparse.Namespace(path=None, replay_path=None)
    with pytest.raises(SystemExit):
        cli_replay.run_replay_cli(args_empty)

    # Replay main with sys.argv
    with patch(
        "sys.argv",
        ["replay_cli", "--path", str(dataset_file), "--mode", "summary"],
    ):
        cli_replay.main()


def test_cli_bot_main(tmp_path):
    cfg_file = tmp_path / "bot_cfg.json"
    cfg_file.write_text("{}", encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "pumpfun-bot",
            "--preset",
            "aggressive",
            "--buy-amount-sol",
            "0.1",
            "--take-profit",
            "2.0",
            "--stop-loss",
            "0.8",
            "--min-market-cap-sol",
            "20",
            "--min-balance-sol",
            "0.5",
            "--dry-run",
            "--config",
            str(cfg_file),
        ],
    ):
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.close = AsyncMock()

        with patch(
            "pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot
        ):
            with patch("asyncio.run", side_effect=lambda coro: coro.close()):
                cli_bot.main()


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
