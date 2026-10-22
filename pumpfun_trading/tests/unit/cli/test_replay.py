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


def test_shadow_scan_rebuilds_the_rows_from_the_config_variants(tmp_path, monkeypatch):
    output = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(cli_replay, "console", output)
    capture, config = _shadow_capture(tmp_path)
    config.write_text(
        json.dumps(
            {
                "entry_mode": "confirmed",
                "buy_amount_sol": 0.02,
                "shadow_variants": [{"name": "scanned"}],
            }
        ),
        encoding="utf-8",
    )
    args = build_replay_parser().parse_args(
        [
            "--path",
            str(capture),
            "--config",
            str(config),
            "--shadow-report",
            "--shadow-scan",
            "--no-costs",
            "--json",
        ]
    )

    run_replay_cli(args)

    report = json.loads(output.export_text())
    # The recorded "baseline" row is replaced; the capture has no trades, so the
    # scanned variant never fires.
    assert list(report["variants"]) == ["scanned"]
    assert report["shadow_entries"] == 0


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


def _fills_capture(tmp_path):
    """Two recorded bot fills (one per half) and the market trades after them."""
    rows: list[dict] = []
    for mint, start in (("A", 100.0), ("B", 1_000.0)):
        rows.append(
            {
                "timestamp": start - 1.0,
                "mint": mint,
                "event": "screening",
                "screening": {"creator": "Dev"},
            }
        )
        rows.append(
            {
                "timestamp": start - 0.5,
                "mint": mint,
                "price": 4e-8,
                "is_buy": True,
                "sol_amount": 0.4,
                "user": "Early",
            }
        )
        rows.append(
            {
                "timestamp": start,
                "mint": mint,
                "price": 4e-8,
                "signal": "buy",
                "reason": "momentum_confirmed",
            }
        )
        rows += [
            {
                "timestamp": start + dt,
                "mint": mint,
                "price": p,
                "is_buy": False,
                "sol_amount": 0.5,
                "user": "Early",
            }
            for dt, p in ((5.0, 3.52e-8), (20.0, 2e-8))
        ]
    capture = tmp_path / "replay_capture.jsonl"
    capture.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    config = tmp_path / "cfg.json"
    config.write_text(
        json.dumps(
            {
                "buy_amount_sol": 0.02,
                "stop_loss": 0.85,
                "max_token_concentration_pct": 1.0,
                "max_total_exposure_sol": 1.0,
                "reserve_balance_sol": 0.0,
                "paper_entry_delay_seconds": 2.0,
                "paper_entry_slippage_bps": 50,
            }
        ),
        encoding="utf-8",
    )
    return capture, config


@pytest.fixture
def recorded(monkeypatch):
    output = Console(record=True, width=220, file=io.StringIO())
    monkeypatch.setattr(cli_replay, "console", output)
    return output


def _run(*argv: str) -> None:
    run_replay_cli(build_replay_parser().parse_args(list(argv)))


def test_sweep_flag_replays_each_value_per_half(tmp_path, recorded):
    capture, config = _fills_capture(tmp_path)
    _run(
        "--path",
        str(capture),
        "--config",
        str(config),
        "--tip-lamports",
        "0",
        "--sweep",
        "stop_loss=0.9",
        "--json",
    )
    report = json.loads(recorded.export_text())
    assert [r["label"] for r in report["results"]] == ["base", "stop_loss=0.9"]
    assert set(report["results"][0]["segments"]) == {"all", "A", "B"}

    recorded.export_text(clear=True)
    _run(
        "--path",
        str(capture),
        "--preset",
        "momentum",
        "--no-costs",
        "--sweep",
        "stop_loss_arm_seconds=0,5",
        "--split-at",
        "",
    )
    assert "Config sweep" in recorded.export_text()


def test_sweep_and_keep_need_a_config_and_valid_specs(tmp_path, recorded):
    capture, config = _fills_capture(tmp_path)
    with pytest.raises(SystemExit, match="--sweep needs --config"):
        _run("--path", str(capture), "--sweep", "stop_loss=0.9")
    with pytest.raises(SystemExit, match="--sweep: Bad sweep"):
        _run("--path", str(capture), "--config", str(config), "--sweep", "nope=1")
    with pytest.raises(SystemExit, match="--keep needs --config"):
        _run("--path", str(capture), "--keep", "quick_flips<1")
    with pytest.raises(SystemExit, match="--keep: Bad rule"):
        _run("--path", str(capture), "--config", str(config), "--keep", "x")


def test_keep_flag_tests_rules_on_replayed_positions(tmp_path, recorded):
    capture, config = _fills_capture(tmp_path)
    _run(
        "--path",
        str(capture),
        "--config",
        str(config),
        "--tip-lamports",
        "0",
        "--keep",
        "unique_buyers>=1",
        "--keep",
        "creator_prior_loss<1",
        "--split-at",
        "mid",
        "--json",
    )
    report = json.loads(recorded.export_text())
    assert report["positions"] == 2
    assert report["rules"][0]["segments"]["all"]["kept"] == 2
    assert report["rules"][1]["segments"]["all"]["missing"] == 0
    # B's creator lost on A, which closed before B was bought.
    assert report["rules"][1]["segments"]["all"]["kept"] == 1

    recorded.export_text(clear=True)
    _run("--path", str(capture), "--config", str(config), "--keep", "quick_flips<1")
    assert "Entry rules against a random cut" in recorded.export_text()


def test_wallet_scores_flag_scores_and_validates(tmp_path, recorded):
    capture, config = _fills_capture(tmp_path)
    _run(
        "--path",
        str(capture),
        "--config",
        str(config),
        "--tip-lamports",
        "0",
        "--wallet-scores",
        "--min-copies",
        "1",
        "--validate-path",
        str(capture),
        "--json",
    )
    payload = json.loads(recorded.export_text())
    assert payload["scores"]["delay_seconds"] == 2.0
    assert payload["scores"]["penalty_bps"] == 50
    assert "creators" not in payload["scores"]
    assert payload["validation"]["selected"] == 0  # Early's copies lost

    recorded.export_text(clear=True)
    _run(
        "--path",
        str(capture),
        "--wallet-scores",
        "--copy-delay",
        "0.5",
        "--wallet",
        "Dev",
        "--no-costs",
    )
    text = recorded.export_text()
    assert "0.5 s delay" in text and "0.02 SOL" in text
    assert "Dev: no closed copy on this capture (launched 2 screened mints)" in text

    zero_delay = tmp_path / "zero.json"
    zero_delay.write_text(json.dumps({"buy_amount_sol": 0.01}), encoding="utf-8")
    recorded.export_text(clear=True)
    _run("--path", str(capture), "--config", str(zero_delay), "--wallet-scores")
    assert "1.5 s delay" in recorded.export_text()


# --- Circuit breaker and paper-wallet cash (FEAT-66) -------------------------


def _captured_engine(tmp_path, *argv: str):
    """Run ``pumpfun-replay`` on an empty capture; return the engine it built."""
    capture = tmp_path / "capture.jsonl"
    capture.write_text("", encoding="utf-8")
    seen: dict = {}

    def fake_run_replay(path, *, engine, **_):
        seen["engine"] = engine
        return {}

    parser = build_replay_parser()
    args = parser.parse_args(["--path", str(capture), "--mode", "summary", *argv])
    with (
        patch.object(cli_replay, "run_replay", side_effect=fake_run_replay),
        patch.object(cli_replay, "render_replay_summary"),
    ):
        run_replay_cli(args)
    return seen["engine"]


def test_config_replay_models_the_breaker_from_the_paper_wallet(tmp_path):
    config = tmp_path / "paper.json"
    config.write_text(
        json.dumps({"buy_amount_sol": 0.02, "reserve_balance_sol": 0.1}),
        encoding="utf-8",
    )
    engine = _captured_engine(tmp_path, "--config", str(config))
    assert engine.circuit_breaker is True
    # reserve + 10 buys, the wallet a paper bot starts with.
    assert engine.initial_cash == pytest.approx(0.3)

    config.write_text(
        json.dumps({"buy_amount_sol": 0.02, "paper_starting_balance_sol": 1.5}),
        encoding="utf-8",
    )
    assert _captured_engine(tmp_path, "--config", str(config)).initial_cash == 1.5


def test_no_circuit_breaker_and_initial_cash_flags(tmp_path):
    engine = _captured_engine(
        tmp_path,
        "--preset",
        "conservative",
        "--no-circuit-breaker",
        "--initial-cash",
        "100",
    )
    assert engine.circuit_breaker is False
    assert engine.initial_cash == 100.0


def test_simple_exit_replay_keeps_the_legacy_bankroll(tmp_path):
    engine = _captured_engine(tmp_path, "--preset", "conservative", "--simple-exits")
    assert engine.live_fidelity is False
    assert engine.circuit_breaker is False
    assert engine.initial_cash == 100.0
    # --initial-cash alone (no config) keeps the legacy engine.
    plain = _captured_engine(tmp_path, "--initial-cash", "7")
    assert plain.circuit_breaker is False and plain.initial_cash == 7.0
