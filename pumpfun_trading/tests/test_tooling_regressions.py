"""Regression tests for replay, optimizer, CLI, ops and dashboard bugs (Batch 6)."""

import argparse
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pumpfun_trading.cli.main import _build_parser
from pumpfun_trading.cli.record import ws_message_to_snapshot
from pumpfun_trading.cli.replay import build_replay_parser, run_replay_cli
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.ops.retention import LogRetentionManager, RetentionPolicy


def test_profit_factor_uses_sol_pnl():
    """BUG-62: a small high-% winner must not outweigh a large low-% loser."""
    engine = PaperTradingEngine(initial_cash=100.0, max_positions=2, buy_fraction=0.5)
    snaps = [
        {"mint": "big", "price": 1.0, "buy_signal": True, "timestamp": 1},
        {"mint": "big", "price": 0.8, "sell_signal": True, "timestamp": 2},
        {"mint": "tiny", "price": 1.0, "buy_signal": True, "timestamp": 3},
        {"mint": "tiny", "price": 1.0, "sell_signal": False, "timestamp": 4},
    ]
    summary = engine.run(snaps)
    sells = [t for t in summary["trades"] if t["action"] == "sell"]
    assert len(sells) == 1 and sells[0]["pnl"] < 0
    assert summary["profit_factor"] == 0.0


def test_no_reentry_on_exit_snapshot():
    """BUG-83: a snapshot that closes a position cannot reopen it."""
    engine = PaperTradingEngine(initial_cash=10.0, take_profit=1.5)
    snaps = [
        {"mint": "m", "price": 1.0, "should_buy": True, "timestamp": 1},
        {"mint": "m", "price": 2.0, "should_buy": True, "timestamp": 2},
    ]
    actions = [t["action"] for t in engine.run(snaps)["trades"]]
    assert actions == ["buy", "sell"]


def test_timestamp_parsing_and_sorting(tmp_path):
    """BUG-84: ISO, seconds and milliseconds sort on one clock."""
    parse = PaperTradingEngine._parse_timestamp
    assert parse("1970-01-01T00:00:10Z") == pytest.approx(10.0)
    assert parse(1_700_000_000_000) == pytest.approx(1_700_000_000.0)
    assert parse("1700000000") == pytest.approx(1_700_000_000.0)
    assert parse("nonsense") is None and parse(None) is None and parse(True) is None
    assert parse("") is None
    assert parse("2024-01-01T00:00:00") == pytest.approx(1_704_067_200.0)

    path = tmp_path / "replay.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"mint": "c", "timestamp": "2024-01-01T00:00:30Z"}',
                '{"mint": "a", "timestamp": 1704067200000}',
                '{"mint": "b", "timestamp": 1704067210}',
            ]
        ),
        encoding="utf-8",
    )
    records = PaperTradingEngine.load_history(path)
    assert [r["mint"] for r in records] == ["a", "b", "c"]


def test_arbitrage_requires_capital_and_cooldown():
    """BUG-63: arbitrage is cooled down per mint and needs input capital."""
    engine = PaperTradingEngine(initial_cash=100.0, enable_cross_venue_arbitrage=True)
    opp = SimpleNamespace(
        is_profitable=True,
        optimal_input_sol=1.0,
        net_profit_sol=0.1,
        direction="pump_to_raydium",
        pump_spot_price=1.0,
        raydium_spot_price=1.2,
        spread_pct=0.2,
        leg1_min_amount_out=1,
        expected_output_sol=1.1,
        estimated_fees_sol=0.0,
        estimated_jito_tip_sol=0.0,
    )
    snaps = [
        {"mint": "m", "price": 1.0, "raydium_sol_reserve": 50.0, "timestamp": t}
        for t in (0, 10, 20, 61)
    ]
    with patch.object(engine.arb_monitor, "evaluate_spread", return_value=opp):
        trades = engine.run(snaps)["trades"]
    assert len([t for t in trades if t["action"] == "arbitrage"]) == 2

    poor = PaperTradingEngine(initial_cash=0.5, enable_cross_venue_arbitrage=True)
    with patch.object(poor.arb_monitor, "evaluate_spread", return_value=opp):
        assert poor.run(snaps[:1])["trades"] == []


def test_pre_graduation_runs_without_arbitrage_flag():
    """BUG-82: pre-grad harvesting is gated only by its own flag."""
    config = SimpleNamespace(
        enable_pre_graduation_harvesting=True,
        pre_graduation_entry_progress_pct=0.5,
        pre_graduation_max_entry_progress_pct=0.9,
        pre_graduation_min_acceleration=0.0,
        enable_momentum_signals=False,
        enable_raydium_migration_sniping=False,
        enable_copy_trading=False,
        enable_cross_venue_arbitrage=False,
        copy_trading_wallets=[],
    )
    engine = PaperTradingEngine(strategy_config=config)  # type: ignore[arg-type]
    signal = SimpleNamespace(triggered=True)
    with patch.object(
        engine.graduation_engine,
        "evaluate_pre_graduation_harvesting_entry",
        return_value=signal,
    ) as evaluate:
        trades = engine.run([{"mint": "m", "price": 1.0, "timestamp": 1}])["trades"]
    assert evaluate.called
    assert trades[0]["reason"] == "pre_graduation_harvesting_entry"


def test_prune_only_touches_rotated_logs_and_enforces_max_files(tmp_path):
    """BUG-64: never delete live sinks or non-log files; honor max_files."""
    old = time.time() - 100 * 86400
    keep = ["events.jsonl", "bot.log", ".env", "config.json", "main.py"]
    for name in keep:
        (tmp_path / name).write_text("x" * 100)
        os.utime(tmp_path / name, (old, old))
    for i in range(1, 5):
        archive = tmp_path / f"bot.log.{i}"
        archive.write_text("y")
        os.utime(archive, (time.time() - i * 10, time.time() - i * 10))

    manager = LogRetentionManager(
        tmp_path,
        policy=RetentionPolicy(max_age_days=30, max_files=2, total_max_bytes=1),
    )
    manager.prune_expired()
    remaining = set(os.listdir(tmp_path))
    assert set(keep) <= remaining
    # max_files keeps the newest 2 archives, then the byte quota drops the older one.
    assert sorted(n for n in remaining if n.startswith("bot.log.")) == ["bot.log.1"]

    for i in range(1, 5):
        (tmp_path / f"events.jsonl.{i}.gz").write_text("z")
        stamp = time.time() - i * 10
        os.utime(tmp_path / f"events.jsonl.{i}.gz", (stamp, stamp))
    LogRetentionManager(tmp_path, policy=RetentionPolicy(max_files=2)).prune_expired()
    assert sorted(n for n in os.listdir(tmp_path) if n.endswith(".gz")) == [
        "events.jsonl.1.gz",
        "events.jsonl.2.gz",
    ]


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


def test_ws_message_snapshot_has_no_fabricated_signal():
    """BUG-86: recorded WS messages never invent buy signals."""
    created = ws_message_to_snapshot(
        {"mint": "M", "txType": "create", "marketCapSol": 30.0}, 5.0
    )
    assert created is not None
    assert "signal" not in created and "is_buy" not in created
    assert created["market_cap_sol"] == 30.0 and created["timestamp"] == 5.0
    sell = ws_message_to_snapshot({"mint": "M", "txType": "sell"}, 5.0)
    assert sell is not None and sell["is_buy"] is False
    assert ws_message_to_snapshot({"txType": "buy"}, 5.0) is None
    assert ws_message_to_snapshot("bad", 5.0) is None


def test_events_tail_waits_for_file(tmp_path):
    """BUG-89: tail polls for the file instead of failing on open."""
    from pumpfun_trading.cli import events as events_cli

    target = tmp_path / "events.jsonl"
    calls = {"n": 0}

    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] == 2:
            target.write_text("")
        if calls["n"] > 3:
            raise KeyboardInterrupt

    args = events_cli.build_events_parser().parse_args(
        ["--path", str(target), "--tail"]
    )
    with patch.object(events_cli.time, "sleep", side_effect=fake_sleep):
        events_cli.run_events_cli(args)
    assert target.exists() and calls["n"] > 3
