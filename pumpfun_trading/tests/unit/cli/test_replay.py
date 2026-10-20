"""Unit tests for ``cli/replay.py``."""

from __future__ import annotations

import argparse
import io
import json
from unittest.mock import patch

import pytest
from rich.console import Console

import pumpfun_trading.cli.replay as cli_replay
from pumpfun_trading.cli.main import _build_parser
from pumpfun_trading.cli.replay import build_replay_parser, run_replay_cli


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


@pytest.mark.regression("BUG-85")
def test_replay_mode_flags_resolve(tmp_path):
    """BUG-85: `--replay-mode` works and does not collide with the parent `--mode`."""
    assert (
        build_replay_parser()
        .parse_args(["--path", "x", "--replay-mode", "summary"])
        .replay_output
        == "summary"
    )
    args = _build_parser().parse_args(["replay", "--path", "x", "--mode", "trades"])
    assert args.replay_output == "trades"

    dataset = tmp_path / "d.json"
    dataset.write_text("[]", encoding="utf-8")
    with patch("pumpfun_trading.cli.replay.render_replay_summary") as summary:
        run_replay_cli(
            argparse.Namespace(
                path=str(dataset),
                replay_path=None,
                mode="replay",
                replay_mode="summary",
                config=None,
                preset=None,
            )
        )
    assert summary.called


def _shadow_capture(tmp_path):
    rows = [
        {"timestamp": 10.0, "mint": "A", "event": "curve_poll", "price": 4e-8},
        {
            "timestamp": 11.5,
            "mint": "A",
            "event": "shadow_entry",
            "variant": "baseline",
            "signal_timestamp": 10.0,
            "signal_market_cap_sol": 40.0,
            "fill_market_cap_sol": 41.0,
            "fill_drift_pct": 0.025,
        },
        {"timestamp": 20.0, "mint": "A", "event": "curve_poll", "price": 5e-8},
    ]
    capture = tmp_path / "replay_capture.jsonl"
    capture.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    config = tmp_path / "capture.json"
    config.write_text(
        json.dumps({"entry_mode": "confirmed", "buy_amount_sol": 0.02}),
        encoding="utf-8",
    )
    return capture, config


def test_shadow_report_flag_prints_the_read_out(tmp_path, monkeypatch):
    output = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(cli_replay, "console", output)
    capture, config = _shadow_capture(tmp_path)
    args = build_replay_parser().parse_args(
        [
            "--path",
            str(capture),
            "--config",
            str(config),
            "--shadow-report",
            "--split-at",
            "mid",
            "--tip-lamports",
            "0",
            "--json",
        ]
    )

    run_replay_cli(args)

    report = json.loads(output.export_text())
    assert report["costs_modelled"] is True
    assert report["split_at"] == pytest.approx(15.0)
    assert report["variants"]["baseline"]["segments"]["all"]["positions"] == 1

    with patch("pumpfun_trading.cli.replay.render_replay_summary") as summary:
        with patch(
            "pumpfun_trading.engines.shadow_report.render_shadow_report"
        ) as render:
            run_replay_cli(
                build_replay_parser().parse_args(
                    [
                        "--path",
                        str(capture),
                        "--preset",
                        "momentum",
                        "--shadow-report",
                        "--no-costs",
                    ]
                )
            )
    assert render.call_args.args[0]["costs_modelled"] is False
    assert not summary.called


def test_shadow_report_needs_a_config_and_a_valid_split(tmp_path):
    capture, config = _shadow_capture(tmp_path)
    with pytest.raises(SystemExit, match="needs --config"):
        run_replay_cli(
            build_replay_parser().parse_args(
                ["--path", str(capture), "--shadow-report"]
            )
        )
    with pytest.raises(SystemExit, match="--shadow-report: could not convert"):
        run_replay_cli(
            build_replay_parser().parse_args(
                [
                    "--path",
                    str(capture),
                    "--config",
                    str(config),
                    "--shadow-report",
                    "--split-at",
                    "noon",
                ]
            )
        )
