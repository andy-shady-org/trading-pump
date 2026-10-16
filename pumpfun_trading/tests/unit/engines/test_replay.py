"""Unit tests for ``engines/replay.py`` live-fidelity replay (BUG-61): live sizing,
live risk limits and the live exit stack."""

from __future__ import annotations

import argparse
import io
import json
from dataclasses import replace
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
from pumpfun_trading.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from pumpfun_trading.strategies.base import TradingBotConfig

MINT_A = "MintA"
MINT_B = "MintB"


def _config(**overrides: Any) -> TradingBotConfig:
    base = TradingBotConfig(
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
    from pumpfun_trading.strategies.base import TradingBotConfig

    config = TradingBotConfig(
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
    from pumpfun_trading.strategies.base import TradingBotConfig

    config = TradingBotConfig(
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
    from pumpfun_trading.strategies.base import TradingBotConfig

    config = TradingBotConfig(
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
