"""Unit tests for ``engines/replay.py`` live-fidelity replay (BUG-61): live sizing,
live risk limits and the live exit stack."""

from __future__ import annotations

import argparse
import io
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console

from pumpfun_trading.cli import replay as replay_cli
from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.replay import PaperTradingEngine, render_replay_summary
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
