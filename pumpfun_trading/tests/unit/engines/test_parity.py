"""Unit tests for ``engines/parity.py`` replay-vs-live parity and the
``pumpfun-replay --compare-audit`` report (Sprint 24C)."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from pumpfun_trading.cli import replay as replay_cli
from pumpfun_trading.engines.parity import (
    compare_replay_to_audit,
    normalise_exit_reason,
    provenance_notes,
)
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.tests.support.factories import make_config


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "circuit_breaker: portfolio drawdown 12.00% exceeded maximum allowed",
            "circuit_breaker_liquidation",
        ),
        ("circuit_breaker_liquidation", "circuit_breaker_liquidation"),
        (
            "stagnant_curve_timeout (181.0s >= 180.0s without price movement)",
            "stagnant_timeout",
        ),
        ("stop_loss_hit (85.00% <= 90.00%)", "stop_loss"),
        ("take_profit_tier_1_full (1.90x >= 1.80x)", "tier_1"),
        ("trailing_stop_hit (drawdown 12% >= 10% from peak 1.5x)", "trailing_stop"),
        ("pre_graduation_tranche_2 (80% >= 75%)", "pre_graduation_tranche"),
        ("trailing_stop", "trailing_stop"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_normalise_exit_reason(reason: str | None, expected: str) -> None:
    assert normalise_exit_reason(reason) == expected


def _live(mint: str, action: str, net: float = 0.0, reason: str = "") -> dict:
    return {"mint": mint, "action": action, "net_pnl_sol": net, "reason": reason}


def _replayed(mint: str, action: str, pnl: float = 0.0, reason: str = "") -> dict:
    return {"mint": mint, "action": action, "pnl": pnl, "reason": reason}


def test_compare_lines_up_mints_exits_and_net_pnl() -> None:
    live = [
        _live("A", "buy"),
        _live("A", "sell", -0.002, "stop_loss_hit (85% <= 90%)"),
        _live("B", "buy"),
        _live("B", "sell", 0.004, "trailing_stop_hit (drawdown …)"),
        _live("C", "buy"),
        _live("C", "sell", 0.001, "stagnant_curve_timeout (…)"),
    ]
    replay = [
        _replayed("A", "buy"),
        _replayed("A", "sell", -0.0021, "stop_loss"),
        _replayed("B", "buy"),
        _replayed("B", "sell", 0.003, "stagnant_timeout"),
        _replayed("D", "buy"),
        _replayed("D", "sell", 0.0005, "max_hold_timeout"),
        {"action": "buy"},  # no mint: ignored
    ]

    report = compare_replay_to_audit(replay, live, tolerance_sol=0.001)

    rows = {row["mint"]: row for row in report["mints"]}
    assert rows["A"]["status"] == "both" and rows["A"]["exit_match"] is True
    assert rows["B"]["exit_match"] is False
    assert rows["C"]["status"] == "live_only"
    assert rows["D"]["status"] == "replay_only"
    assert report["counts"] == {
        "both": 2,
        "live_only": 1,
        "replay_only": 1,
        "exit_match": 1,
    }
    assert report["live_net_pnl_sol"] == pytest.approx(0.003)
    assert report["replay_net_pnl_sol"] == pytest.approx(0.0014)
    assert report["gap_sol"] == pytest.approx(-0.0016)
    assert report["within_tolerance"] is False


def test_compare_relative_tolerance_scales_with_live_pnl() -> None:
    live = [_live("A", "buy"), _live("A", "sell", 1.0, "stop_loss_hit")]
    replay = [_replayed("A", "buy"), _replayed("A", "sell", 0.95, "stop_loss")]

    report = compare_replay_to_audit(replay, live, tolerance_sol=0.0, tolerance_pct=0.1)

    assert report["allowed_gap_sol"] == pytest.approx(0.1)
    assert report["within_tolerance"] is True


@pytest.mark.regression("BUG-119")
def test_compare_counts_live_buy_costs_in_net_pnl() -> None:
    # Live buys carry their fee, tip and rent as a negative net; replay sells
    # already include the buy-side costs and replay buys book 0.
    live = [
        {"mint": "A", "action": "buy", "costs_sol": 0.0016, "net_pnl_sol": -0.0016},
        _live("A", "sell", 0.0010, "stop_loss_hit (85% <= 90%)"),
        {"mint": "B", "action": "buy", "costs_sol": 0.0016},  # no net field
        _live("B", "sell", 0.0004, "stagnant_curve_timeout (…)"),
    ]
    replay = [
        _replayed("A", "buy"),
        _replayed("A", "sell", -0.0006, "stop_loss"),
        _replayed("B", "buy"),
        _replayed("B", "sell", -0.0012, "stagnant_timeout"),
    ]

    report = compare_replay_to_audit(replay, live, tolerance_sol=0.0001)

    rows = {row["mint"]: row for row in report["mints"]}
    assert rows["A"]["live_net_pnl_sol"] == pytest.approx(-0.0006)
    assert rows["B"]["live_net_pnl_sol"] == pytest.approx(-0.0012)
    assert report["live_net_pnl_sol"] == pytest.approx(-0.0018)
    assert report["gap_sol"] == pytest.approx(0.0)
    assert report["within_tolerance"] is True
    assert rows["A"]["live_buys"] == 1 and rows["A"]["live_exits"] == ["stop_loss"]


def test_compare_marks_mints_without_entries() -> None:
    report = compare_replay_to_audit([_replayed("A", "quote")], [])

    assert report["mints"][0]["status"] == "no_entry"


def _config() -> TradingBotConfig:
    return make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        max_position_size_sol=0.01,
        max_total_exposure_sol=0.03,
        max_token_concentration_pct=0.5,
        reserve_balance_sol=0.0,
        max_active_positions=2,
        stop_loss=0.9,
        enable_momentum_signals=False,
        enable_stagnant_exit=False,
        enable_max_hold_timeout=False,
    )


def _capture() -> list[dict[str, Any]]:
    """What ``pumpbot --record-replay`` writes: new tokens, market trades, fills."""
    return [
        {"mint": "A", "price": 30.0, "timestamp": 0.0, "is_buy": True, "signal": "buy"},
        {"mint": "B", "price": 30.0, "timestamp": 1.0, "is_buy": True, "signal": "buy"},
        {
            "mint": "A",
            "price": 30.0,
            "timestamp": 2.0,
            "is_buy": True,
            "signal": "buy",
            "reason": "entry",
            "token_amount": 1,
        },
        {
            "mint": "A",
            "price": 26.0,
            "timestamp": 3.0,
            "is_buy": False,
            "signal": "sell",
            "user": "someone",
        },
    ]


@pytest.mark.parametrize(
    ("entry_mode", "bought"),
    [("auto", {"A"}), ("live_fills", {"A"}), ("signals", {"A", "B"})],
)
def test_entry_mode_selects_live_fills_or_signals(
    entry_mode: str, bought: set[str]
) -> None:
    engine = PaperTradingEngine(
        initial_cash=1.0,
        strategy_config=_config(),
        live_fidelity=True,
        entry_mode=entry_mode,
    )

    summary = engine.run(_capture())

    buys = {t["mint"] for t in summary["trades"] if t["action"] == "buy"}
    assert buys == bought
    # A market sell is a price point, not an exit order: A exits on its stop-loss.
    sells = [t for t in summary["trades"] if t["action"] == "sell"]
    assert [t["reason"] for t in sells if t["mint"] == "A"] == ["stop_loss"]


def test_unknown_entry_mode_rejected() -> None:
    with pytest.raises(ValueError, match="entry_mode"):
        PaperTradingEngine(entry_mode="everything")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _args(capture: Path, audit: Path, **overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "path": str(capture),
        "config": None,
        "preset": "conservative",
        "initial_cash": 1.0,
        "simple_exits": False,
        "no_costs": True,
        "tip_lamports": None,
        "priority_fee_lamports": 0,
        "compare_audit": str(audit),
        "parity_tolerance_sol": 0.002,
        "parity_tolerance_pct": 0.10,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _output() -> Console:
    return Console(record=True, width=200, file=io.StringIO())


@pytest.mark.parametrize(("live_net", "passes"), [(None, True), (5.0, False)])
def test_replay_cli_compare_audit_reports_and_exits_on_gap(
    tmp_path: Path, live_net: float | None, passes: bool
) -> None:
    capture = tmp_path / "capture.jsonl"
    audit = tmp_path / "audit.jsonl"
    _write_jsonl(capture, _capture())
    summary = PaperTradingEngine(
        initial_cash=1.0, strategy_config=_config(), live_fidelity=True
    ).run(_capture())
    replay_net = sum(t["pnl"] for t in summary["trades"] if t["action"] == "sell")
    _write_jsonl(
        audit,
        [
            {"type": "trade", "payload": _live("A", "buy")},
            {
                "type": "trade",
                "payload": _live(
                    "A",
                    "sell",
                    replay_net if live_net is None else live_net,
                    "stop_loss_hit (86% <= 90%)",
                ),
            },
        ],
    )
    console = _output()

    with (
        patch.object(replay_cli, "console", console),
        patch(
            "pumpfun_trading.strategies.presets.resolve_strategy_config",
            return_value=_config(),
        ),
    ):
        if passes:
            replay_cli.run_replay_cli(_args(capture, audit))
        else:
            with pytest.raises(SystemExit) as excinfo:
                replay_cli.run_replay_cli(_args(capture, audit))
            assert excinfo.value.code == 1

    text = console.export_text()
    assert "Replay vs live" in text
    assert ("PASS" in text) is passes
    assert "Entries in both: 1 (same exit: 1)" in text


def test_replay_cli_compare_audit_needs_live_fidelity(tmp_path: Path) -> None:
    capture = tmp_path / "capture.jsonl"
    _write_jsonl(capture, _capture())

    with pytest.raises(SystemExit, match="live-fidelity"):
        replay_cli.run_replay_cli(
            _args(capture, tmp_path / "audit.jsonl", simple_exits=True)
        )


# --- Run provenance in the parity report (FEAT-68) ----------------------------


def _run_started(config_hash: str | None, dirty: bool = False) -> dict[str, Any]:
    return {
        "type": "run_started",
        "payload": {
            "started_at_utc": "2026-10-15T00:00:00Z",
            "package_version": "0.3.0rc4",
            "git_commit": "abcdef1234567890",
            "git_dirty": dirty,
            "mode": "paper",
            "config_path": "configs/canary.json",
            "config_file_sha256": config_hash,
        },
    }


def test_provenance_notes_flag_old_trails_dirty_builds_and_other_configs(
    tmp_path: Path,
) -> None:
    assert provenance_notes([{"type": "trade", "payload": {}}], None) == [
        "audit trail has no run provenance (written before rc.4)"
    ]
    config = tmp_path / "canary.json"
    config.write_text("{}", encoding="utf-8")
    from pumpfun_trading.ops.provenance import file_sha256

    same = provenance_notes([_run_started(file_sha256(config))], str(config))
    assert len(same) == 1
    assert "0.3.0rc4 @ abcdef12" in same[0] and "paper" in same[0]

    other = provenance_notes([_run_started("0" * 64, dirty=True)], str(config))
    assert any("modified tracked files" in note for note in other)
    assert any("parity compares different settings" in note for note in other)


def test_compare_audit_prints_provenance_and_replay_skips_the_stamp(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture.jsonl"
    audit = tmp_path / "audit.jsonl"
    stamp = {
        "event": "run_provenance",
        "timestamp": 0.5,
        "package_version": "0.3.0rc4",
        "git_commit": "abcdef1234567890",
        "config_sha256": "c" * 64,
        "mode": "paper",
    }
    _write_jsonl(capture, [stamp, *_capture()])
    summary = PaperTradingEngine(
        initial_cash=1.0, strategy_config=_config(), live_fidelity=True
    ).run([stamp, *_capture()])
    assert summary["capture_runs"] == [
        {
            "package_version": "0.3.0rc4",
            "git_commit": "abcdef1234567890",
            "mode": "paper",
            "config_sha256": "c" * 64,
        }
    ]
    plain = PaperTradingEngine(
        initial_cash=1.0, strategy_config=_config(), live_fidelity=True
    ).run(_capture())
    assert "capture_runs" not in plain
    assert summary["trades"] == plain["trades"]

    replay_net = sum(t["pnl"] for t in summary["trades"] if t["action"] == "sell")
    _write_jsonl(
        audit,
        [
            _run_started("0" * 64),
            {"type": "trade", "payload": _live("A", "buy")},
            {
                "type": "trade",
                "payload": _live("A", "sell", replay_net, "stop_loss_hit (86%)"),
            },
        ],
    )
    console = _output()
    config_file = tmp_path / "replay.json"
    config_file.write_text("{}", encoding="utf-8")
    with (
        patch.object(replay_cli, "console", console),
        patch(
            "pumpfun_trading.strategies.presets.resolve_strategy_config",
            return_value=_config(),
        ),
    ):
        replay_cli.run_replay_cli(_args(capture, audit, config=str(config_file)))

    text = console.export_text()
    assert "run 2026-10-15T00:00:00Z: 0.3.0rc4 @ abcdef12" in text
    assert "parity compares different settings" in text
