"""Unit tests for ``engines/replay.py`` live-fidelity replay (BUG-61): live sizing,
live risk limits and the live exit stack."""

from __future__ import annotations

import argparse
import io
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from pumpfun_trading.cli import replay as replay_cli
from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.replay import (
    PaperTradingEngine,
    ReplayEngine,
    render_replay_dashboard,
    render_replay_summary,
    render_replay_trades,
    run_replay,
)
from pumpfun_trading.ops.retention import compress_file_to_gzip
from pumpfun_trading.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.copy_trading import TrackedWallet
from pumpfun_trading.tests.support.factories import make_config

MINT_A = "MintA"
MINT_B = "MintB"


def _config(**overrides: Any) -> TradingBotConfig:
    base = make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        max_position_size_sol=0.01,
        max_total_exposure_sol=0.03,
        max_token_concentration_pct=0.5,
        reserve_balance_sol=0.0,
        max_active_positions=2,
        stop_loss=0.9,
        enable_momentum_signals=False,
        enable_tiered_take_profit=True,
        tier_1_take_profit=1.8,
        tier_1_sell_fraction=0.6,
        tier_2_take_profit=2.8,
        tier_2_sell_fraction=0.2,
        moonbag_trailing_floor=2.0,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.35,
        trailing_stop_drop_pct=0.10,
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=180.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=900.0,
    )
    return replace(base, **overrides)


def _snap(mint: str, price: float, ts: float, buy: bool = False, **extra: Any) -> dict:
    return {"mint": mint, "price": price, "timestamp": ts, "buy_signal": buy, **extra}


def _engine(**overrides: Any) -> PaperTradingEngine:
    return PaperTradingEngine(
        initial_cash=1.0,
        fee_bps=0,
        slippage_bps=0,
        strategy_config=_config(**overrides),
        live_fidelity=True,
    )


def _sells(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in summary["trades"] if t["action"] == "sell"]


def test_live_fidelity_without_config_raises() -> None:
    with pytest.raises(ValueError, match="strategy_config"):
        PaperTradingEngine(live_fidelity=True)


def test_live_entry_spends_buy_amount_not_cash_fraction() -> None:
    summary = _engine().run([_snap(MINT_A, 1.0, 0.0, buy=True)])

    assert summary["live_fidelity"] is True
    assert summary["positions"][MINT_A]["cost_basis"] == pytest.approx(0.01)
    assert "exit_state" not in summary["positions"][MINT_A]
    assert summary["final_cash"] == pytest.approx(0.99)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"max_total_exposure_sol": 0.015, "max_token_concentration_pct": 1.0},
            "max_total_exposure",
        ),
        ({"max_position_size_sol": 0.005}, "max_position_size"),
        ({"max_token_concentration_pct": 0.25}, "token_concentration"),
        ({"reserve_balance_sol": 0.995}, "reserve_balance"),
        ({"buy_amount_sol": 0.0}, "no_buy_amount"),
    ],
)
def test_live_entry_rejected_by_live_risk_limits(
    overrides: dict[str, Any], reason: str
) -> None:
    summary = _engine(**overrides).run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_B, 1.0, 1.0, buy=True)]
    )

    assert summary["entry_rejections"].get(reason, 0) >= 1
    if reason != "max_total_exposure":
        assert summary["buy_count"] == 0


def test_screening_records_are_not_replayed_as_market_data() -> None:
    screening = {
        "event": "screening",
        "mint": MINT_A,
        "price": 1.0,
        "timestamp": 0.0,
        "buy_signal": True,
        "screening": {"passed": True},
    }

    summary = _engine().run([screening])

    assert summary["buy_count"] == 0
    assert summary["entry_rejections"] == {}


def test_live_entry_respects_max_buy_attempts_per_mint() -> None:
    snaps = [
        _snap(MINT_A, 1.0, 0.0, buy=True),
        _snap(MINT_A, 0.5, 1.0),  # stop-loss exit
        _snap(MINT_A, 0.5, 2.0, buy=True),
    ]
    summary = _engine(max_buy_attempts_per_mint=1).run(snaps)

    assert summary["buy_count"] == 1
    assert summary["entry_rejections"] == {"max_buy_attempts_per_mint": 1}


def test_tiered_take_profit_sells_tier_fraction_and_keeps_rest() -> None:
    summary = _engine().run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_A, 1.8, 10.0)]
    )

    (sell,) = _sells(summary)
    assert sell["reason"] == "tier_1"
    assert sell["partial"] is True
    assert sell["cost"] == pytest.approx(0.006)
    assert sell["pnl"] == pytest.approx(0.006 * 0.8)
    assert summary["positions"][MINT_A]["cost_basis"] == pytest.approx(0.004)


def test_trailing_stop_fires_on_drop_from_peak() -> None:
    summary = _engine(enable_tiered_take_profit=False, take_profit=10.0).run(
        [
            _snap(MINT_A, 1.0, 0.0, buy=True),
            _snap(MINT_A, 1.5, 10.0),
            _snap(MINT_A, 1.3, 20.0),
        ]
    )

    (sell,) = _sells(summary)
    assert sell["reason"] == "trailing_stop"
    assert sell["partial"] is False
    assert sell["pnl"] == pytest.approx(0.003)
    assert summary["open_positions"] == 0


def test_stop_loss_full_exit() -> None:
    summary = _engine().run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_A, 0.85, 5.0)]
    )

    (sell,) = _sells(summary)
    assert sell["reason"] == "stop_loss"
    assert sell["pnl"] == pytest.approx(-0.0015)


def test_stagnant_exit_fires_on_replay_clock_from_another_mint() -> None:
    summary = _engine(enable_max_hold_timeout=False).run(
        [
            _snap(MINT_A, 1.0, 0.0, buy=True),
            _snap(MINT_B, 2.0, 200.0),
        ]
    )

    (sell,) = _sells(summary)
    assert sell["mint"] == MINT_A
    assert sell["reason"] == "stagnant_timeout"
    assert sell["hold_seconds"] == pytest.approx(200.0)
    assert sell["exit_price"] == pytest.approx(1.0)


def test_max_hold_exit_when_price_keeps_moving() -> None:
    snaps = [_snap(MINT_A, 1.0, 0.0, buy=True)] + [
        _snap(MINT_A, 1.0 + 0.01 * (i % 2), 100.0 * i) for i in range(1, 11)
    ]
    summary = _engine().run(snaps)

    (sell,) = _sells(summary)
    assert sell["reason"] == "max_hold_timeout"


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"complete": True}, "bonding_curve_graduated"),
        ({"sell_signal": True}, "sell_signal"),
    ],
)
def test_forced_exit_reasons(extra: dict[str, Any], reason: str) -> None:
    summary = _engine().run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_A, 1.1, 5.0, **extra)]
    )

    (sell,) = _sells(summary)
    assert sell["reason"] == reason
    assert sell["partial"] is False


def _cli_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "path": "capture.jsonl",
        "config": None,
        "preset": "conservative",
        "initial_cash": 1.0,
        "simple_exits": False,
        "replay_output": "summary",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.parametrize(("simple_exits", "expected"), [(False, True), (True, False)])
def test_replay_cli_preset_uses_live_fidelity_unless_simple_exits(
    simple_exits: bool, expected: bool
) -> None:
    captured: dict[str, PaperTradingEngine] = {}

    def fake_run_replay(path: str, *, engine: PaperTradingEngine, **_: Any) -> dict:
        captured["engine"] = engine
        return {}

    with (
        patch.object(replay_cli, "run_replay", side_effect=fake_run_replay),
        patch.object(replay_cli, "render_replay_summary"),
    ):
        replay_cli.run_replay_cli(_cli_args(simple_exits=simple_exits))

    assert captured["engine"].live_fidelity is expected


def _costed_engine(**overrides: Any) -> PaperTradingEngine:
    return PaperTradingEngine(
        initial_cash=1.0,
        slippage_bps=0,
        strategy_config=_config(**overrides),
        live_fidelity=True,
        cost_model=ReplayCostModel(protocol_fee_bps=0, tip_lamports=100_000),
    )


def test_cost_model_requires_live_fidelity() -> None:
    with pytest.raises(ValueError, match="live_fidelity"):
        PaperTradingEngine(cost_model=ReplayCostModel())


def test_cost_model_sets_protocol_fee() -> None:
    engine = PaperTradingEngine(
        strategy_config=_config(),
        live_fidelity=True,
        cost_model=ReplayCostModel(protocol_fee_bps=125),
    )
    assert engine.fee_bps == 125


def test_round_trip_books_net_pnl_and_recovers_rent() -> None:
    rent = TOKEN_ACCOUNT_RENT_LAMPORTS / 1e9
    leg = (5_000 + 100_000) / 1e9
    summary = _costed_engine().run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_A, 0.85, 5.0)]
    )

    (sell,) = _sells(summary)
    assert sell["gross_pnl_sol"] == pytest.approx(-0.0015)
    # Two network fees + tips; the rent paid on the buy is refunded on the close.
    assert sell["costs_sol"] == pytest.approx(2 * leg)
    assert sell["net_pnl_sol"] == pytest.approx(-0.0015 - 2 * leg)
    assert sell["pnl"] == sell["net_pnl_sol"]
    assert summary["final_cash"] == pytest.approx(1.0 - 0.0015 - 2 * leg)
    assert summary["costs_modelled"] is True
    assert summary["net_pnl_sol"] == pytest.approx(sell["net_pnl_sol"])
    assert summary["gross_pnl_sol"] == pytest.approx(-0.0015)
    buy = summary["trades"][0]
    assert buy["costs_sol"] == pytest.approx(leg + rent)


def test_partial_exit_allocates_buy_costs_and_keeps_rent_until_close() -> None:
    rent = TOKEN_ACCOUNT_RENT_LAMPORTS / 1e9
    leg = (5_000 + 100_000) / 1e9
    summary = _costed_engine().run(
        [_snap(MINT_A, 1.0, 0.0, buy=True), _snap(MINT_A, 1.8, 10.0)]
    )

    (sell,) = _sells(summary)
    assert sell["partial"] is True
    assert sell["costs_sol"] == pytest.approx(0.6 * (leg + rent) + leg)
    assert summary["open_position_costs_sol"] == pytest.approx(0.4 * (leg + rent))


def test_entry_skipped_when_cash_cannot_cover_costs() -> None:
    engine = PaperTradingEngine(
        initial_cash=0.0101,
        slippage_bps=0,
        strategy_config=_config(),
        live_fidelity=True,
        cost_model=ReplayCostModel(protocol_fee_bps=0),
    )

    summary = engine.run([_snap(MINT_A, 1.0, 0.0, buy=True)])

    assert summary["buy_count"] == 0
    assert summary["final_cash"] == pytest.approx(0.0101)


@pytest.mark.parametrize(
    ("overrides", "has_costs"),
    [({}, True), ({"no_costs": True}, False)],
)
def test_replay_cli_models_costs_unless_no_costs(
    overrides: dict[str, Any], has_costs: bool
) -> None:
    captured: dict[str, PaperTradingEngine] = {}

    def fake_run_replay(path: str, *, engine: PaperTradingEngine, **_: Any) -> dict:
        captured["engine"] = engine
        return {}

    args = _cli_args(
        **{
            "no_costs": False,
            "tip_lamports": 50_000,
            "priority_fee_lamports": 1_000,
            **overrides,
        }
    )
    with (
        patch.object(replay_cli, "run_replay", side_effect=fake_run_replay),
        patch.object(replay_cli, "render_replay_summary"),
    ):
        replay_cli.run_replay_cli(args)

    model = captured["engine"].cost_model
    assert (model is not None) is has_costs
    if model is not None:
        assert model.tip_lamports == 50_000
        assert model.priority_fee_lamports == 1_000


def test_render_summary_shows_net_pnl_and_rejections() -> None:
    console = Console(record=True, width=200, file=io.StringIO())
    summary = _costed_engine(max_total_exposure_sol=0.015).run(
        [
            _snap(MINT_A, 1.0, 0.0, buy=True),
            _snap(MINT_B, 1.0, 1.0, buy=True),
            _snap(MINT_A, 0.85, 5.0),
        ]
    )

    render_replay_summary(summary, console)

    text = console.export_text()
    assert "live fidelity + costs" in text
    assert "net_pnl_sol" in text
    assert "token_concentration=" in text


def test_paper_trading_engine_data_loading(tmp_path):
    # Non-existent file
    assert PaperTradingEngine.load_history(tmp_path / "missing.json") == []

    # Empty file
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("   \n", encoding="utf-8")
    assert PaperTradingEngine.load_history(empty_file) == []

    # Invalid JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json}", encoding="utf-8")
    assert PaperTradingEngine.load_history(bad_json) == []

    # JSON with wrapper object
    wrapped_json = tmp_path / "wrapped.json"
    wrapped_json.write_text(
        json.dumps({"snapshots": [{"mint": "Mint1", "price": 1.0}]}), encoding="utf-8"
    )
    assert len(PaperTradingEngine.load_history(wrapped_json)) == 1

    # JSONL loading with comments / blank lines / bad lines
    jsonl_file = tmp_path / "history.jsonl"
    jsonl_content = (
        '{"mint": "Mint1", "price": 1.0}\n\n'
        "{bad json line}\n"
        '{"mint": "Mint2", "price": 2.0}\n'
    )
    jsonl_file.write_text(jsonl_content, encoding="utf-8")
    records = PaperTradingEngine.load_history(jsonl_file)
    assert len(records) == 2
    assert records[0]["mint"] == "Mint1"
    assert records[1]["mint"] == "Mint2"


def test_paper_trading_engine_helpers():
    snapshot = {
        "mint": "MintABC",
        "name": "Token ABC",
        "timestamp": 12345678,
        "marketCapSol": "50.5",
        "price": "1.25",
        "buy_signal": True,
        "sell_signal": False,
    }
    assert PaperTradingEngine._snapshot_mint(snapshot) == "MintABC"
    assert PaperTradingEngine._snapshot_mint({}) == "unknown-mint"
    assert PaperTradingEngine._snapshot_name(snapshot) == "Token ABC"
    assert PaperTradingEngine._snapshot_name({}) == "unknown"
    assert PaperTradingEngine._snapshot_timestamp(snapshot) == 12345678
    assert PaperTradingEngine._snapshot_price(snapshot) == 1.25
    assert PaperTradingEngine._snapshot_float(snapshot, "marketCapSol") == 50.5
    assert PaperTradingEngine._snapshot_float(snapshot, "nonexistent") == 0.0
    assert PaperTradingEngine._snapshot_float({"bad": "not_a_float"}, "bad") == 0.0
    assert PaperTradingEngine._buy_signal(snapshot) is True
    assert PaperTradingEngine._buy_signal({"signal": "BUY"}) is True
    assert PaperTradingEngine._buy_signal({"should_buy": True}) is True
    assert PaperTradingEngine._sell_signal({"signal": "exit"}) is True
    assert PaperTradingEngine._sell_signal({"should_sell": True}) is True


def test_paper_trading_engine_simulation_and_metrics():
    engine = PaperTradingEngine(
        initial_cash=100.0,
        max_positions=2,
        fee_bps=100,
        slippage_bps=100,
        buy_fraction=0.5,
        take_profit=1.5,
        stop_loss=0.8,
    )

    snapshots = [
        # Ignore zero price
        {"mint": "MintZero", "price": 0.0},
        # Buy Mint1
        {
            "mint": "Mint1",
            "name": "M1",
            "price": 10.0,
            "timestamp": 100,
            "buy_signal": True,
        },
        # Hold Mint1
        {"mint": "Mint1", "name": "M1", "price": 12.0, "timestamp": 101},
        # Buy Mint2
        {
            "mint": "Mint2",
            "name": "M2",
            "price": 5.0,
            "timestamp": 102,
            "buy_signal": True,
        },
        # Try to buy Mint3 (exceeds max_positions 2)
        {
            "mint": "Mint3",
            "name": "M3",
            "price": 1.0,
            "timestamp": 103,
            "buy_signal": True,
        },
        # Mint1 take profit (multiplier 26/10 = 2.6 >= 1.5)
        {"mint": "Mint1", "name": "M1", "price": 26.0, "timestamp": 104},
        # Mint2 stop loss (multiplier 0.5/5 = 0.1 <= 0.8)
        {"mint": "Mint2", "name": "M2", "price": 0.5, "timestamp": 105},
    ]

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 4  # 2 buys, 2 sells
    assert summary["buy_count"] == 2
    assert summary["sell_count"] == 2
    assert summary["win_rate"] == 0.5
    assert "profit_factor" in summary
    assert "max_drawdown" in summary


def test_paper_trading_engine_run_and_render(tmp_path):
    snapshots = [
        {
            "mint": "MintA",
            "name": "A",
            "price": 10.0,
            "timestamp": 1000,
            "buy_signal": True,
        },
        {"mint": "MintA", "name": "A", "price": 11.0, "timestamp": 1010},
        {
            "mint": "MintA",
            "name": "A",
            "price": 12.0,
            "timestamp": 1020,
            "sell_signal": True,
        },
    ]
    file_path = tmp_path / "dataset.json"
    file_path.write_text(json.dumps(snapshots), encoding="utf-8")

    engine = ReplayEngine(initial_cash=200.0)
    summary = run_replay(file_path, engine=engine)
    assert summary["total_trades"] == 2  # 1 buy, 1 sell
    assert len(summary["trades"]) == 2

    # Test rendering functions
    console = Console(width=120, file=None, record=True)
    render_replay_summary(summary, console)
    render_replay_trades(summary["trades"], console)
    output = console.export_text()
    assert "Mint Name" in output
    assert "MintA" in output
    assert "A" in output
    render_replay_trades([], console)  # Empty trades
    render_replay_dashboard(summary, console)

    # Test filtering by mint and mint_name
    summary_mint = run_replay(file_path, mint="MintA")
    assert summary_mint["total_trades"] == 2
    summary_mint_name = run_replay(file_path, mint_name="A")
    assert summary_mint_name["total_trades"] == 2
    summary_none = run_replay(file_path, mint="NonExistent")
    assert summary_none["total_trades"] == 0


def test_paper_trading_engine_with_order_flow_momentum():

    config = make_config(
        dry_run=False,
        enable_momentum_signals=True,
        momentum_window_seconds=30,
        momentum_min_buy_ratio=2.0,
        momentum_min_z_score=1.5,
        momentum_min_unique_buyers=2,
        momentum_min_net_inflow_sol=0.2,
        momentum_baseline_window_seconds=300,
        take_profit=1.5,
        stop_loss=0.85,
    )
    engine = PaperTradingEngine(
        initial_cash=100.0,
        strategy_config=config,
        enable_order_flow_momentum=True,
    )

    base_time = 1000.0
    snapshots = []
    # Baseline trades (1 trade per slice in slices 1..9)
    for slice_idx in range(1, 10):
        t = base_time - (slice_idx * 30 + 15)
        snapshots.append(
            {
                "mint": "TokenMom",
                "name": "MomToken",
                "price": 10.0,
                "timestamp": t,
                "is_buy": True,
                "sol_amount": 0.05,
                "user": f"User{slice_idx}",
            }
        )

    # Current burst (3 trades with 1.0 SOL each from distinct users)
    for i in range(3):
        snapshots.append(
            {
                "mint": "TokenMom",
                "name": "MomToken",
                "price": 10.0,
                "timestamp": base_time - 5 + i,
                "is_buy": True,
                "sol_amount": 1.0,
                "user": f"Buyer{i}",
            }
        )

    # Price rise for take profit (performance (26-10)/10 = 1.6 >= 1.5)
    snapshots.append(
        {
            "mint": "TokenMom",
            "name": "MomToken",
            "price": 26.0,
            "timestamp": base_time + 10,
        }
    )

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 2  # 1 buy (momentum_spike), 1 sell (take_profit)
    assert summary["trades"][0]["action"] == "buy"
    assert summary["trades"][0]["reason"] == "momentum_spike"
    assert summary["trades"][1]["action"] == "sell"
    assert summary["trades"][1]["reason"] == "take_profit"


def test_paper_trading_engine_with_raydium_graduation():

    config = make_config(
        dry_run=False,
        enable_raydium_migration_sniping=True,
        take_profit=1.5,
        stop_loss=0.85,
    )
    engine = PaperTradingEngine(
        initial_cash=100.0,
        strategy_config=config,
        enable_raydium_graduation=True,
    )

    snapshots = [
        # Bonding curve progression
        {
            "mint": "GradToken",
            "name": "GradToken",
            "price": 50.0,
            "real_sol_reserves": 50.0,
            "timestamp": 1000,
        },
        # Raydium pool created -> trigger snipe
        {
            "mint": "GradToken",
            "name": "GradToken",
            "price": 69.0,
            "event": "raydium_pool_created",
            "timestamp": 1010,
        },
        # Price climbs -> take profit exit
        {
            "mint": "GradToken",
            "name": "GradToken",
            "price": 180.0,
            "timestamp": 1020,
        },
    ]

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 2
    assert summary["trades"][0]["action"] == "buy"
    assert summary["trades"][0]["reason"] == "raydium_graduation_snipe"
    assert summary["trades"][1]["action"] == "sell"
    assert summary["trades"][1]["reason"] == "take_profit"


def test_paper_trading_engine_with_copy_trading():

    config = make_config(
        dry_run=False,
        enable_copy_trading=True,
        copy_trading_wallets=(
            {
                "address": "SmartWhale999",
                "label": "Whale999",
                "win_rate": 0.80,
                "risk_score": 10.0,
                "enabled": True,
            },
        ),
        take_profit=1.5,
        stop_loss=0.85,
    )
    engine = PaperTradingEngine(
        initial_cash=100.0,
        strategy_config=config,
        enable_copy_trading=True,
    )

    snapshots = [
        # Tracked smart money buy event
        {
            "mint": "CopyToken",
            "name": "CopyToken",
            "price": 20.0,
            "txType": "buy",
            "sol_amount": 5.0,
            "user": "SmartWhale999",
            "timestamp": 1000,
        },
        # Tracked smart money sell event (triggers exit)
        {
            "mint": "CopyToken",
            "name": "CopyToken",
            "price": 25.0,
            "txType": "sell",
            "sol_amount": 5.0,
            "user": "SmartWhale999",
            "timestamp": 1010,
        },
    ]

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 2
    assert summary["trades"][0]["action"] == "buy"
    assert summary["trades"][0]["reason"] == "copy_trade_Whale999"
    assert summary["trades"][1]["action"] == "sell"
    assert summary["trades"][1]["reason"] == "copy_trade_exit_Whale999"


def test_paper_trading_engine_exact_multiplier_exits():
    """Verify take-profit at 1.5x and stop-loss at 0.85x trigger accurately."""
    engine = PaperTradingEngine(
        initial_cash=100.0,
        fee_bps=0,
        slippage_bps=0,
        buy_fraction=1.0,
        take_profit=1.5,
        stop_loss=0.85,
    )

    # 1. Take Profit Test (Entry @ 10.0 -> 14.9 [Hold] -> 15.0 [TP exit])
    tp_snapshots = [
        {"mint": "MintTP", "price": 10.0, "timestamp": 1, "buy_signal": True},
        {"mint": "MintTP", "price": 14.9, "timestamp": 2},  # 1.49x, below 1.5x
        {"mint": "MintTP", "price": 15.0, "timestamp": 3},  # 1.50x, triggers TP
    ]
    tp_summary = engine.run(tp_snapshots)
    assert tp_summary["total_trades"] == 2
    assert tp_summary["trades"][1]["action"] == "sell"
    assert tp_summary["trades"][1]["reason"] == "take_profit"
    assert tp_summary["trades"][1]["exit_price"] == 15.0
    assert tp_summary["trades"][1]["pnl"] == pytest.approx(50.0)
    assert tp_summary["trades"][1]["return_pct"] == pytest.approx(0.50)

    # 2. Stop Loss Test (Entry @ 10.0 -> 8.6 [Hold] -> 8.5 [SL exit])
    sl_engine = PaperTradingEngine(
        initial_cash=100.0,
        fee_bps=0,
        slippage_bps=0,
        buy_fraction=1.0,
        take_profit=2.0,
        stop_loss=0.85,
    )
    sl_snapshots = [
        {"mint": "MintSL", "price": 10.0, "timestamp": 1, "buy_signal": True},
        {"mint": "MintSL", "price": 8.6, "timestamp": 2},  # 0.86x, above 0.85x
        {"mint": "MintSL", "price": 8.5, "timestamp": 3},  # 0.85x, triggers SL
    ]
    sl_summary = sl_engine.run(sl_snapshots)
    assert sl_summary["total_trades"] == 2
    assert sl_summary["trades"][1]["action"] == "sell"
    assert sl_summary["trades"][1]["reason"] == "stop_loss"
    assert sl_summary["trades"][1]["exit_price"] == 8.5
    assert sl_summary["trades"][1]["pnl"] == pytest.approx(-15.0)
    assert sl_summary["trades"][1]["return_pct"] == pytest.approx(-0.15)


def test_paper_trading_engine_fee_slippage_and_cash_budget():
    """Verify fee/slippage friction reduces quantities, sell proceeds, and preserves cash >= 0."""
    engine = PaperTradingEngine(
        initial_cash=100.0,
        fee_bps=100,  # 1% fee
        slippage_bps=100,  # 1% slippage
        buy_fraction=1.0,
        take_profit=2.0,
        stop_loss=0.5,
    )

    snapshots = [
        # Buy with 100% of cash (100.0 SOL) at price 10.0
        {"mint": "MintFriction", "price": 10.0, "timestamp": 1, "buy_signal": True},
        # Flat price exit via sell signal
        {"mint": "MintFriction", "price": 10.0, "timestamp": 2, "sell_signal": True},
    ]

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 2
    buy_trade = summary["trades"][0]
    sell_trade = summary["trades"][1]

    # Buy friction assertions:
    # net_spend = 100 / 1.01 = 99.0099...
    # exec_price = 10 * 1.01 = 10.1
    # quantity = 99.0099 / 10.1 = 9.80296...
    expected_qty = (100.0 / 1.01) / (10.0 * 1.01)
    assert buy_trade["quantity"] == pytest.approx(expected_qty, rel=1e-5)
    assert (
        buy_trade["quantity"] < 10.0
    )  # Strictly fewer tokens than frictionless 100/10

    # Sell friction assertions:
    # exec_sell_price = 10 * 0.99 = 9.9
    # gross_exit = quantity * 9.9 = 97.0493...
    # exit_value = gross_exit * 0.99 = 96.0788...
    expected_exit_value = (expected_qty * (10.0 * 0.99)) * 0.99
    expected_pnl = expected_exit_value - 100.0
    expected_return_pct = expected_pnl / 100.0

    assert sell_trade["pnl"] == pytest.approx(expected_pnl, rel=1e-5)
    assert sell_trade["return_pct"] == pytest.approx(expected_return_pct, rel=1e-5)
    assert summary["final_equity"] == pytest.approx(expected_exit_value, rel=1e-5)
    assert summary["final_equity"] >= 0.0


def test_paper_trading_engine_arbitrage_simulation() -> None:
    """Verify PaperTradingEngine simulates cross-venue arbitrage profits over multi-venue datasets."""
    engine = PaperTradingEngine(
        initial_cash=10.0,
        enable_cross_venue_arbitrage=True,
    )
    snapshots = [
        {
            "timestamp": 1700000001,
            "mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "name": "ArbToken",
            "price": 0.000035,
            "virtual_sol_reserves": 35_000_000_000,
            "virtual_token_reserves": 900_000_000_000_000,
            "raydium_sol_reserve": 85.0,  # 85 SOL
            "raydium_token_reserve": 180_000_000_000_000,  # 180M tokens
        }
    ]
    summary = engine.run(snapshots)
    assert summary["total_trades"] >= 1
    assert summary["final_cash"] > 10.0  # Realized arbitrage profit generated!
    arb_trade = summary["trades"][0]
    assert arb_trade["side"] == "ARBITRAGE"
    assert arb_trade["pnl"] > 0.0


def test_replay_load_history_gzip_and_directory(tmp_path: Path):
    """Test PaperTradingEngine.load_history with .gz and directory datasets."""
    import gzip

    # File 1: compressed .jsonl.gz
    f1 = tmp_path / "replay_01.jsonl.gz"
    with gzip.open(f1, "wt", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": 100,
                    "mint": "M1",
                    "price": 0.00000001,
                    "buy_signal": True,
                }
            )
            + "\n"
        )

    # File 2: active .jsonl
    f2 = tmp_path / "replay_02.jsonl"
    f2.write_text(
        json.dumps(
            {"timestamp": 200, "mint": "M2", "price": 0.00000002, "sell_signal": True}
        )
        + "\n",
        encoding="utf-8",
    )

    records = PaperTradingEngine.load_history(tmp_path)
    assert len(records) == 2
    assert records[0]["mint"] == "M1"
    assert records[1]["mint"] == "M2"


@pytest.mark.regression("BUG-62")
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


@pytest.mark.regression("BUG-83")
def test_no_reentry_on_exit_snapshot():
    """BUG-83: a snapshot that closes a position cannot reopen it."""
    engine = PaperTradingEngine(initial_cash=10.0, take_profit=1.5)
    snaps = [
        {"mint": "m", "price": 1.0, "should_buy": True, "timestamp": 1},
        {"mint": "m", "price": 2.0, "should_buy": True, "timestamp": 2},
    ]
    actions = [t["action"] for t in engine.run(snaps)["trades"]]
    assert actions == ["buy", "sell"]


@pytest.mark.regression("BUG-84")
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


@pytest.mark.regression("BUG-63")
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


@pytest.mark.regression("BUG-82")
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


def test_replay_engine_multi_file_and_gzip_loading(tmp_path: Path):
    # Create single jsonl, gzip jsonl, and directory with both
    replay_dir = tmp_path / "replay_data"
    replay_dir.mkdir()

    f1 = replay_dir / "replay_1.jsonl"
    f2 = replay_dir / "replay_2.jsonl"
    event1 = {
        "timestamp": 1000.0,
        "mint": "m1",
        "market_cap_sol": 30.0,
        "is_buy": True,
        "sol_amount": 0.1,
    }
    event2 = {
        "timestamp": 1005.0,
        "mint": "m1",
        "market_cap_sol": 35.0,
        "is_buy": True,
        "sol_amount": 0.2,
    }
    f1.write_text(json.dumps(event1) + "\n", encoding="utf-8")
    f2.write_text(json.dumps(event2) + "\n", encoding="utf-8")

    # Compress f2 to f2.jsonl.gz
    gz_f2 = compress_file_to_gzip(f2)
    assert gz_f2.exists()

    engine = PaperTradingEngine()
    history = engine.load_history(replay_dir)
    assert len(history) >= 2


def test_paper_trading_all_features_simulation():

    cfg = make_config(
        dry_run=False,
        enable_momentum_signals=True,
        enable_copy_trading=True,
        copy_trading_mirror_sells=True,
        enable_raydium_migration_sniping=True,
        enable_pre_graduation_harvesting=True,
        enable_cross_venue_arbitrage=True,
        enable_capital_rotation=True,
        max_active_positions=1,
    )
    engine = PaperTradingEngine(strategy_config=cfg, initial_cash=10.0)

    user_smart = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
    engine.copy_trade_engine.registry.register_wallet(
        TrackedWallet(address=user_smart, label="Whale1")
    )

    now = time.time()
    snapshots = [
        {
            "timestamp": now + 1,
            "mint": "m_copy",
            "market_cap_sol": 30.0,
            "txType": "buy",
            "sol_amount": 1.0,
            "user": user_smart,
        },
        {
            "timestamp": now + 2,
            "mint": "m_copy",
            "market_cap_sol": 32.0,
            "txType": "sell",
            "sol_amount": 1.0,
            "user": user_smart,
        },
        {
            "timestamp": now + 3,
            "mint": "m_arb",
            "market_cap_sol": 30.0,
            "virtual_sol_reserves": 30.0,
            "virtual_token_reserves": 1_000_000_000_000_000,
            "raydium_sol_reserve": 80.0,
            "raydium_token_reserve": 150_000_000_000_000,
        },
        {
            "timestamp": now + 4,
            "mint": "m_grad",
            "market_cap_sol": 85.0,
            "real_sol_reserves": 85.0,
            "complete": True,
        },
    ]

    res = engine.run(snapshots)
    assert res is not None


# -- Confirmed entries (FEAT-52) ------------------------------------------------

CREATOR = "CreatorWallet"


def _confirmed_config(**overrides: Any) -> TradingBotConfig:
    from pumpfun_trading.strategies.presets import resolve_strategy_config

    values: dict[str, Any] = {
        "momentum_min_token_age_seconds": 20.0,
        "momentum_min_unique_buyers": 3,
        "momentum_min_net_inflow_sol": 0.5,
        "momentum_min_buy_ratio": 1.5,
        "momentum_min_z_score": 0.0,
        "watch_promote_min_sol_growth": 1.0,
        "watch_max_trade_subscriptions": 5,
    }
    values.update(overrides)
    return resolve_strategy_config("momentum", overrides=values)


def _create(mint: str, ts: float, mc: float = 28.0) -> dict[str, Any]:
    return {"timestamp": ts, "mint": mint, "market_cap_sol": mc, "signal": "buy"}


def _screen(mint: str, ts: float, passed: bool = True) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "event": "screening",
        "screening": {"passed": passed, "creator": CREATOR},
    }


def _market_trade(
    mint: str, ts: float, mc: float, user: str, sol: float = 0.5, buy: bool = True
) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "market_cap_sol": mc,
        "is_buy": buy,
        "sol_amount": sol,
        "user": user,
        "signal": "buy" if buy else "sell",
    }


def _confirming_flow(mint: str, start: float, mc: float = 45.0) -> list[dict[str, Any]]:
    # The first trade only promotes (live, trades arrive after the subscription);
    # the creator's buy never counts as demand.
    rows = [_market_trade(mint, start, mc, "Promoter")]
    rows.append(_market_trade(mint, start + 1, mc, CREATOR, sol=3.0))
    rows += [_market_trade(mint, start + 2 + i, mc, f"Buyer{i}") for i in range(4)]
    return rows


def _confirmed_engine(cfg: TradingBotConfig, **kwargs: Any) -> PaperTradingEngine:
    return PaperTradingEngine(
        initial_cash=2.0,
        strategy_config=cfg,
        live_fidelity=True,
        max_positions=cfg.max_active_positions,
        **kwargs,
    )


def test_confirmed_replay_watches_then_buys_on_follow_on_demand() -> None:
    cfg = _confirmed_config()
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)] + _confirming_flow(
        MINT_A, 30.0
    )
    summary = _confirmed_engine(cfg).run(snaps)

    buys = [t for t in summary["trades"] if t["action"] == "buy"]
    assert len(buys) == 1
    buy = buys[0]
    assert buy["reason"] == "momentum_confirmed"
    assert buy["strategy"] == "momentum"
    assert buy["timestamp"] == 34.0  # third non-creator buyer after promotion
    assert buy["entry_metrics"]["unique_buyers"] == 3
    assert buy["entry_metrics"]["token_age_seconds"] == 34.0
    assert summary["entries_from"] == "confirmed"
    assert summary["watch_stats"]["watched"] == 1
    assert summary["watch_stats"]["promoted"] == 1
    assert summary["watch_stats"]["confirmed"] == 1


def test_confirmed_replay_skips_rejected_young_and_out_of_band_tokens() -> None:
    cfg = _confirmed_config(momentum_max_market_cap_sol=70.0)
    snaps = (
        [_create(MINT_A, 0.0), _screen(MINT_A, 0.5, passed=False)]
        + _confirming_flow(MINT_A, 30.0)
        + [_create(MINT_B, 0.0)]
        + _confirming_flow(MINT_B, 1.0)  # strong flow, but only a few seconds old
        + [_create("MintC", 0.0)]
        + _confirming_flow("MintC", 40.0, mc=80.0)  # above the band
    )
    snaps.sort(key=lambda s: float(s["timestamp"]))
    summary = _confirmed_engine(cfg).run(snaps)

    assert [t for t in summary["trades"] if t["action"] == "buy"] == []
    assert summary["watch_stats"]["screen_rejected"] == 1


def test_confirmed_replay_respects_ttl_budget_and_cost_guard() -> None:
    cfg = _confirmed_config(watch_ttl_seconds=10.0)
    summary = _confirmed_engine(cfg).run(
        [_create(MINT_A, 0.0)] + _confirming_flow(MINT_A, 30.0)
    )
    assert summary["buy_count"] == 0
    assert summary["watch_stats"]["expired"] == 1

    cfg = _confirmed_config(watch_max_trade_subscriptions=1)
    snaps = [_create(MINT_A, 0.0), _create(MINT_B, 0.0)]
    snaps += [
        _market_trade(MINT_A, 25.0, 45.0, "P"),
        _market_trade(MINT_B, 26.0, 45.0, "P"),
    ]
    summary = _confirmed_engine(cfg).run(snaps)
    assert summary["watch_stats"]["promoted"] == 1
    assert summary["watch_stats"]["budget_full"] == 1

    cfg = _confirmed_config(buy_amount_sol=0.002, max_entry_cost_share_pct=0.10)
    summary = _confirmed_engine(
        cfg, cost_model=ReplayCostModel(tip_lamports=100_000)
    ).run([_create(MINT_A, 0.0)] + _confirming_flow(MINT_A, 30.0))
    assert summary["buy_count"] == 0
    assert summary["watch_stats"]["cost_guard_refused"] >= 1


def test_confirmed_replay_exits_on_buy_flow_stagnation() -> None:
    cfg = _confirmed_config(stagnant_timeout_seconds=35.0, stagnant_min_buy_sol=0.1)
    snaps = [_create(MINT_A, 0.0)] + _confirming_flow(MINT_A, 30.0)
    # Small buys and the creator keep the price moving but are not demand.
    snaps += [
        _market_trade(MINT_A, 40.0 + i * 5, 45.0 + i, "Dust", sol=0.01)
        for i in range(8)
    ]
    snaps.append(_market_trade(MINT_A, 80.0, 52.0, CREATOR, sol=1.0))
    summary = _confirmed_engine(cfg).run(snaps)

    sells = [t for t in summary["trades"] if t["action"] == "sell"]
    assert [t["reason"] for t in sells] == ["stagnant_buy_flow"]
    assert sells[0]["timestamp"] == 70.0


def test_confirmed_entry_mode_requires_live_fidelity() -> None:
    with pytest.raises(ValueError, match="live_fidelity"):
        PaperTradingEngine(entry_mode="confirmed")


@pytest.mark.regression("BUG-121")
def test_confirmed_replay_fills_after_the_paper_entry_delay() -> None:
    # The drift guard is off here: this test is about how the fill is priced.
    cfg = _confirmed_config(
        paper_entry_delay_seconds=1.5,
        paper_entry_slippage_bps=100,
        momentum_max_entry_drift_pct=0.0,
    )
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    snaps += _confirming_flow(MINT_A, 30.0)
    # The signal fires at t=34 (mc 45); the curve dips and then runs while the
    # paper buy is still landing (due at 35.5).
    snaps += [
        _market_trade(MINT_A, 34.5, 30.0, "Dumper", buy=False),
        _market_trade(MINT_A, 35.2, 60.0, "Chaser"),
        _market_trade(MINT_A, 36.0, 60.0, "Chaser2"),
    ]
    summary = _confirmed_engine(cfg).run(snaps)

    # No stop-loss on the dip: the position had not filled yet.
    assert [t["action"] for t in summary["trades"]] == ["buy"]
    buy = summary["trades"][0]
    assert buy["timestamp"] == 34.0
    assert buy["entry_price"] == pytest.approx(60.0 / 0.99)
    assert buy["entry_metrics"]["fill_drift_pct"] == 0.3333
    assert buy["entry_metrics"]["fill_market_cap_sol"] == pytest.approx(
        60.0 / 0.99, abs=1e-4
    )
    assert buy["quantity"] == pytest.approx(0.02 / 1.01 * 0.99 / 60.0)


@pytest.mark.regression("BUG-121")
def test_confirmed_replay_penalty_without_delay_and_fill_at_data_end() -> None:
    cfg = _confirmed_config(paper_entry_slippage_bps=200)
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    snaps += _confirming_flow(MINT_A, 30.0)
    buy = _confirmed_engine(cfg).run(snaps)["trades"][0]
    assert buy["entry_price"] == pytest.approx(45.0 / 0.98)
    assert "fill_drift_pct" not in buy["entry_metrics"]

    cfg = _confirmed_config(paper_entry_delay_seconds=5.0)
    buy = _confirmed_engine(cfg).run(snaps)["trades"][0]
    # The data ends before the buy lands: it fills at the last price seen, and
    # without a penalty the engine's own slippage applies as before.
    assert buy["entry_price"] == pytest.approx(45.0)
    assert buy["quantity"] == pytest.approx(0.02 / 1.01 / (45.0 * 1.01))
    assert buy["entry_metrics"]["fill_drift_pct"] == 0.0


@pytest.mark.regression("BUG-121")
def test_no_paper_entry_model_keeps_signal_price_fills() -> None:
    cfg = _confirmed_config()
    snaps = [_create(MINT_A, 0.0)] + _confirming_flow(MINT_A, 30.0)
    buy = _confirmed_engine(cfg).run(snaps)["trades"][0]
    assert buy["entry_price"] == 45.0
    assert "fill_drift_pct" not in buy["entry_metrics"]


def test_confirmed_replay_drift_guard_skips_a_runaway_fill_and_refunds() -> None:
    cfg = _confirmed_config(
        paper_entry_delay_seconds=1.5,
        paper_entry_slippage_bps=100,
        momentum_max_entry_drift_pct=0.10,
    )
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    snaps += _confirming_flow(MINT_A, 30.0)
    # Signal at t=34 (mc 45); the curve runs to 60 before the buy lands.
    snaps += [_market_trade(MINT_A, 35.2, 60.0, "Chaser")]
    snaps += [_create(MINT_B, 36.0)] + _confirming_flow(MINT_B, 70.0)
    snaps.sort(key=lambda s: float(s["timestamp"]))
    engine = _confirmed_engine(cfg)
    summary = engine.run(snaps)

    buys = [t for t in summary["trades"] if t["action"] == "buy"]
    # MINT_A never filled; MINT_B (no drift) did, and the ledger is renumbered.
    assert [t["mint"] for t in buys] == [MINT_B]
    assert [t["index"] for t in summary["trades"]] == list(
        range(len(summary["trades"]))
    )
    assert not any(t.get("drift_refused") for t in summary["trades"])
    assert summary["entry_rejections"]["entry_drift"] == 1
    assert summary["watch_stats"]["drift_refused"] == 1


def test_confirmed_replay_drift_guard_refund_and_limits() -> None:
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    snaps += _confirming_flow(MINT_A, 30.0)
    snaps += [_market_trade(MINT_A, 34.5, 60.0, "Chaser")]

    # The data ends before the buy lands: refused at the last price, and the
    # spend and its modelled costs come back.
    cfg = _confirmed_config(
        paper_entry_delay_seconds=5.0, momentum_max_entry_drift_pct=0.10
    )
    summary = _confirmed_engine(cfg, cost_model=ReplayCostModel(tip_lamports=0)).run(
        snaps
    )
    assert summary["buy_count"] == 0
    assert summary["final_cash"] == pytest.approx(summary["initial_cash"])
    assert summary["entry_rejections"]["entry_drift"] == 1

    # A wider limit lets the same fill through; no limit is the old behaviour.
    for limit in (0.5, 0.0):
        cfg = _confirmed_config(
            paper_entry_delay_seconds=5.0, momentum_max_entry_drift_pct=limit
        )
        summary = _confirmed_engine(cfg).run(snaps)
        assert summary["buy_count"] == 1
        assert "entry_drift" not in summary["entry_rejections"]


# -- Recorded curve reads (curve_poll), near-graduation set, shadow rows ----------


def _curve_poll(
    mint: str, ts: float, mc: float, real_sol: float | None = None, **extra: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "timestamp": ts,
        "mint": mint,
        "event": "curve_poll",
        "source": "watch",
        "market_cap_sol": mc,
        **extra,
    }
    if real_sol is not None:
        row["real_sol_reserves"] = real_sol
    return row


def _delayed_fill_snaps(*extra: dict[str, Any]) -> list[dict[str, Any]]:
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    snaps += _confirming_flow(MINT_A, 30.0)
    # Signal at t=34 (mc 45); the buy is due at 35.5. A trade runs the price
    # to 60 just before; another mint trades just after the fill is due.
    snaps += [
        _market_trade(MINT_A, 35.2, 60.0, "Chaser"),
        _market_trade(MINT_B, 35.6, 10.0, "Elsewhere"),
        *extra,
    ]
    snaps.sort(key=lambda s: float(s["timestamp"]))
    return snaps


def test_recorded_curve_read_after_the_due_time_prices_the_paper_fill() -> None:
    """The paper fill reads the curve just after its delay; a recorded read of
    that moment (entry_fill / shadow_fill / watch poll) is the fill price."""
    cfg = _confirmed_config(
        paper_entry_delay_seconds=1.5,
        paper_entry_slippage_bps=100,
        momentum_max_entry_drift_pct=0.0,
    )

    read = _curve_poll(MINT_A, 35.7, 50.0, source="entry_fill")
    buy = _confirmed_engine(cfg).run(_delayed_fill_snaps(read))["trades"][0]
    assert buy["entry_price"] == pytest.approx(50.0 / 0.99)
    assert buy["entry_metrics"]["fill_drift_pct"] == pytest.approx(5.0 / 45.0, abs=1e-4)

    # No curve reads in the capture: the last price before the fill, as before.
    buy = _confirmed_engine(cfg).run(_delayed_fill_snaps())["trades"][0]
    assert buy["entry_price"] == pytest.approx(60.0 / 0.99)

    # A read too late to be the fill's own falls back to the price at the fill.
    late = _curve_poll(MINT_A, 37.0, 50.0)
    other = _curve_poll(MINT_B, 30.0, 10.0)  # makes this a capture with reads
    buy = _confirmed_engine(cfg).run(_delayed_fill_snaps(late, other))["trades"][0]
    assert buy["entry_price"] == pytest.approx(60.0 / 0.99)

    # Data ending while the fill waits for its read: priced as of the fill.
    snaps = _delayed_fill_snaps(other)
    snaps = [s for s in snaps if float(s["timestamp"]) <= 35.6]
    buy = _confirmed_engine(cfg).run(snaps)["trades"][0]
    assert buy["entry_price"] == pytest.approx(60.0 / 0.99)


def test_recorded_curve_read_drives_the_drift_guard() -> None:
    cfg = _confirmed_config(
        paper_entry_delay_seconds=1.5,
        paper_entry_slippage_bps=100,
        momentum_max_entry_drift_pct=0.10,
    )
    # The last trade says +33%, the curve read at the fill says +4%: it fills.
    read = _curve_poll(MINT_A, 35.7, 46.8, source="entry_fill")
    summary = _confirmed_engine(cfg).run(_delayed_fill_snaps(read))
    assert summary["buy_count"] == 1
    assert "entry_drift" not in summary["entry_rejections"]


def test_shadow_entry_rows_are_never_market_data() -> None:
    cfg = _confirmed_config()
    snaps = [_create(MINT_A, 0.0)] + _confirming_flow(MINT_A, 30.0)
    shadow = {
        "timestamp": 33.5,
        "mint": MINT_A,
        "event": "shadow_entry",
        "variant": "b6",
        "price": 999.0,  # even a priced row is skipped
        "fill_market_cap_sol": 999.0,
    }
    plain = _confirmed_engine(cfg).run(snaps)
    with_shadow = _confirmed_engine(cfg).run(
        sorted(snaps + [shadow], key=lambda s: float(s["timestamp"]))
    )
    assert with_shadow["trades"] == plain["trades"]


def test_confirmed_replay_promotes_on_polled_curves_like_the_live_poller() -> None:
    cfg = _confirmed_config()
    flow = [_market_trade(MINT_A, 30.0 + i, 45.0, f"Buyer{i}") for i in range(3)]
    # The poll at t=20 shows 3 SOL of growth: promoted there, so every later
    # trade is demand (live, they arrive because of that subscription).
    snaps = [_create(MINT_A, 0.0), _curve_poll(MINT_A, 20.0, 35.0, real_sol=3.0)]
    summary = _confirmed_engine(cfg).run(snaps + flow)
    buys = [t for t in summary["trades"] if t["action"] == "buy"]
    assert [b["timestamp"] for b in buys] == [32.0]
    assert summary["watch_stats"]["promoted"] == 1

    # Not a watch poll (a fill read), or too little growth: no promotion.
    for poll in (
        _curve_poll(MINT_A, 20.0, 35.0, real_sol=3.0, source="shadow_fill"),
        _curve_poll(MINT_A, 20.0, 29.0, real_sol=0.5),
    ):
        summary = _confirmed_engine(cfg).run([_create(MINT_A, 0.0), poll] + flow)
        assert summary["watch_stats"].get("promoted") == 1  # by the first trade
        assert summary["buy_count"] == 0  # only two buyers seen after it

    cfg = _confirmed_config(watch_max_trade_subscriptions=1)
    snaps = [
        _create(MINT_A, 0.0),
        _create(MINT_B, 0.0),
        _curve_poll(MINT_A, 20.0, 35.0, real_sol=3.0),
        _curve_poll(MINT_B, 20.5, 35.0, real_sol=3.0),
    ]
    summary = _confirmed_engine(cfg).run(snaps)
    assert summary["watch_stats"]["promoted"] == 1
    assert summary["watch_stats"]["budget_full"] == 1


def _pre_grad_config(**overrides: Any) -> TradingBotConfig:
    values: dict[str, Any] = {
        "enable_pre_graduation_harvesting": True,
        "pre_graduation_entry_progress_pct": 0.75,
        "pre_graduation_max_entry_progress_pct": 0.88,
        "pre_graduation_min_acceleration": 0.0,
        "pre_graduation_tranches": (
            {"progress_pct": 0.92, "sell_fraction": 0.30},
            {"progress_pct": 0.97, "sell_fraction": 0.30},
        ),
        "watch_promote_min_sol_growth": 500.0,  # isolate the pre-graduation lane
        "near_graduation_max_mints": 5,
        "paper_entry_delay_seconds": 1.5,
        "paper_entry_slippage_bps": 0,
    }
    values.update(overrides)
    return _confirmed_config(**values)


def _pre_grad_snaps() -> list[dict[str, Any]]:
    snaps = [_create(MINT_A, 0.0), _screen(MINT_A, 0.5)]
    # Halfway up the curve before the 600 s watch TTL, still climbing after it.
    snaps += [
        _curve_poll(MINT_A, 500.0, 200.0, real_sol=45.0),
        _curve_poll(MINT_A, 600.0, 210.0, real_sol=46.0),
    ]
    # Accelerating inflow past 75%: 64 -> 64.5 -> 65.5 -> 67 -> 69 SOL.
    for i, real_sol in enumerate([64.0, 64.5, 65.5, 67.0, 69.0]):
        snaps.append(_curve_poll(MINT_A, 700.0 + 2 * i, 300.0, real_sol=real_sol))
    # Tranche exits read curve progress from the polls: 92.9%, then 97.6%.
    snaps.append(_curve_poll(MINT_A, 715.0, 320.0, real_sol=79.0))
    snaps.append(_curve_poll(MINT_A, 720.0, 330.0, real_sol=83.0))
    return snaps


def test_confirmed_replay_runs_the_pre_graduation_lane_on_polled_curves() -> None:
    summary = _confirmed_engine(_pre_grad_config()).run(_pre_grad_snaps())

    assert summary["watch_stats"]["near_graduation"] == 1
    buys = [t for t in summary["trades"] if t["action"] == "buy"]
    assert len(buys) == 1
    buy = buys[0]
    assert buy["reason"] == "pre_graduation_harvesting_entry"
    assert buy["strategy"] == "pre_graduation"
    assert buy["timestamp"] == 706.0  # the fourth reading in the 30 s window
    assert buy["entry_metrics"]["curve_progress_pct"] >= 75.0
    assert buy["entry_metrics"]["market_cap_sol"] == 300.0
    # Filled from the next curve read, at 708 s.
    assert buy["entry_price"] == pytest.approx(300.0)
    sells = [t for t in summary["trades"] if t["action"] == "sell"]
    assert [t["reason"] for t in sells] == [
        "pre_graduation_tranche",
        "pre_graduation_tranche",
    ]


def test_pre_graduation_replay_needs_the_near_graduation_set_and_watch_polls() -> None:
    # Without the near-graduation set the coin expired at the 600 s TTL.
    summary = _confirmed_engine(_pre_grad_config(near_graduation_max_mints=0)).run(
        _pre_grad_snaps()
    )
    assert summary["buy_count"] == 0
    assert summary["watch_stats"]["expired"] == 1

    # Curve data that is not a poll (old captures) never triggers the lane.
    snaps = [
        {**s, "event": "geyser"} if s.get("event") == "curve_poll" else s
        for s in _pre_grad_snaps()
    ]
    assert _confirmed_engine(_pre_grad_config()).run(snaps)["buy_count"] == 0

    # The cost guard applies to this lane too.
    summary = _confirmed_engine(
        _pre_grad_config(buy_amount_sol=0.002, max_entry_cost_share_pct=0.10),
        cost_model=ReplayCostModel(tip_lamports=100_000),
    ).run(_pre_grad_snaps())
    assert summary["buy_count"] == 0
    assert summary["watch_stats"]["cost_guard_refused"] >= 1


def test_mirrored_fill_rows_carry_lane_penalty_and_buy_flow() -> None:
    """Synthetic fills (shadow read-out) set the lane, apply the paper penalty
    and feed the buy-flow stagnation clock; recorded bot fills stay as before."""
    config = _config(
        entry_mode="confirmed",
        stagnant_min_buy_sol=0.1,
        stagnant_timeout_seconds=30.0,
        max_hold_time_seconds=10_000.0,
    )
    shadow_fill = {
        "mint": MINT_A,
        "price": 40.0,
        "timestamp": 100.0,
        "signal": "buy",
        "reason": "shadow:baseline",
        "strategy": "momentum",
        "creator": "Dev",
        "entry_penalty_bps": 100,
        "entry_metrics": {"unique_buyers": 5},
    }
    bot_fill = {
        "mint": MINT_B,
        "price": 40.0,
        "timestamp": 100.0,
        "signal": "buy",
        "reason": "momentum_confirmed",
    }

    def trade(
        mint: str, ts: float, user: str, sol: float = 0.5, price: float = 40.0
    ) -> dict:
        return {
            "mint": mint,
            "price": price,
            "timestamp": ts,
            "is_buy": True,
            "sol_amount": sol,
            "user": user,
        }

    snaps = [
        shadow_fill,
        bot_fill,
        trade(MINT_A, 120.0, "Buyer", price=41.0),
        trade(MINT_B, 120.0, "Buyer"),
        # The creator and small buys never count as demand.
        trade(MINT_A, 125.0, "Dev", price=42.0),
        trade(MINT_A, 140.0, "Small", sol=0.01, price=43.0),
        trade(MINT_B, 145.0, "Buyer"),
    ]
    engine = PaperTradingEngine(
        initial_cash=1.0,
        strategy_config=config,
        live_fidelity=True,
        entry_mode="live_fills",
    )

    summary = engine.run(snaps)

    buys = {t["mint"]: t for t in summary["trades"] if t["action"] == "buy"}
    assert buys[MINT_A]["strategy"] == "momentum"
    assert buys[MINT_A]["entry_metrics"] == {"unique_buyers": 5}
    assert buys[MINT_A]["entry_price"] == pytest.approx(40.0 / 0.99)
    assert "strategy" not in buys[MINT_B]
    assert buys[MINT_B]["entry_price"] == pytest.approx(40.0)
    sells = {t["mint"]: t["reason"] for t in summary["trades"] if t["action"] == "sell"}
    # A's last qualifying buy was at 120 s, so at 145 s it is still held. B is
    # not a momentum fill, its clock was never fed, and it exits 45 s in.
    assert MINT_A not in sells
    assert sells[MINT_B] == "stagnant_buy_flow"
