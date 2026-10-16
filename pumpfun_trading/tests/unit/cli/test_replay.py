"""Unit tests for ``cli/replay.py``."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

import pumpfun_trading.cli.replay as cli_replay


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

    # Config file and preset
    cfg = tmp_path / "bot_replay.json"
    cfg.write_text(json.dumps({"take_profit": 2.5, "stop_loss": 0.8}), encoding="utf-8")
    args.config = str(cfg)
    args.preset = None
    args.initial_cash = 250.0
    cli_replay.run_replay_cli(args)

    args.config = None
    args.preset = "conservative"
    cli_replay.run_replay_cli(args)

    # Missing path
    args_empty = argparse.Namespace(path=None, replay_path=None)
    with pytest.raises(SystemExit):
        cli_replay.run_replay_cli(args_empty)

    # Replay main with sys.argv
    with patch(
        "sys.argv",
        [
            "replay_cli",
            "--path",
            str(dataset_file),
            "--mode",
            "summary",
            "--config",
            str(cfg),
        ],
    ):
        cli_replay.main()
