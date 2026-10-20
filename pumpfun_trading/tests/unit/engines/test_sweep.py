"""Unit tests for ``engines/sweep.py`` (split-half config sweep)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.sweep import (
    apply_overrides,
    grid_label,
    parse_sweep_spec,
    render_sweep,
    replay_positions,
    run_split_sweep,
    sweep_grid,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.tests.support.factories import make_config


def _config(**overrides: Any) -> TradingBotConfig:
    base: dict[str, Any] = {
        "buy_amount_sol": 0.02,
        "stop_loss": 0.85,
        "take_profit": 3.0,
        "enable_tiered_take_profit": False,
        "enable_trailing_stop": False,
        "enable_stagnant_exit": False,
        "enable_max_hold_timeout": False,
        "max_active_positions": 5,
        "max_total_exposure_sol": 1.0,
        "max_position_size_sol": 0.05,
        "max_token_concentration_pct": 1.0,
        "reserve_balance_sol": 0.0,
    }
    base.update(overrides)
    return make_config(**base)


def _capture() -> list[dict[str, Any]]:
    """Two mints, one per half, each dipping to 0.88x and then recovering."""
    rows: list[dict[str, Any]] = []
    for mint, start in (("A", 100.0), ("B", 1_000.0)):
        rows.append(
            {
                "timestamp": start,
                "mint": mint,
                "price": 4e-8,
                "signal": "buy",
                "reason": "momentum_confirmed",
            }
        )
        for offset, price in ((5.0, 3.52e-8), (10.0, 6e-8), (20.0, 14e-8)):
            rows.append(
                {
                    "timestamp": start + offset,
                    "mint": mint,
                    "price": price,
                    "is_buy": True,
                    "sol_amount": 0.5,
                    "user": "U",
                }
            )
    return rows


def test_parse_spec_grid_and_labels() -> None:
    assert parse_sweep_spec("stop_loss=0.8, 0.9") == ("stop_loss", [0.8, 0.9])
    assert parse_sweep_spec("entry_mode=confirmed") == ("entry_mode", ["confirmed"])
    for bad in ("stop_loss", "=0.8", "nope=1", "stop_loss= "):
        with pytest.raises(ValueError, match="Bad sweep"):
            parse_sweep_spec(bad)
    assert sweep_grid([]) == []
    grid = sweep_grid([("a", [1, 2]), ("b", [3])])
    assert grid == [{"a": 1, "b": 3}, {"a": 2, "b": 3}]
    assert grid_label({}) == "base"
    assert grid_label({"a": 1, "b": 3}) == "a=1 b=3"


def test_apply_overrides_coerces_and_validates() -> None:
    config = _config()
    updated = apply_overrides(
        config,
        {
            "stop_loss": 1,
            "max_active_positions": 2.0,
            "enable_trailing_stop": 1,
            "entry_mode": "confirmed",
        },
    )
    assert updated.stop_loss == 1.0 and isinstance(updated.stop_loss, float)
    assert updated.max_active_positions == 2
    assert updated.enable_trailing_stop is True
    assert updated.entry_mode == "confirmed"
    with pytest.raises(ValueError, match="take_profit"):
        apply_overrides(config, {"stop_loss": 3.5})
    with pytest.raises(ValueError, match="hard_floor"):
        apply_overrides(config, {"stop_loss_hard_floor": 0.9})


def test_replay_positions_books_each_position_once() -> None:
    summary = {
        "trades": [
            {"action": "buy", "mint": "A", "timestamp": 1.0, "strategy": "momentum"},
            {
                "action": "sell",
                "mint": "A",
                "timestamp": 2.0,
                "partial": True,
                "net_pnl_sol": 0.01,
                "reason": "tier_1",
            },
            {
                "action": "sell",
                "mint": "A",
                "timestamp": 3.0,
                "pnl": -0.002,
                "reason": "stop_loss",
            },
            {"action": "buy", "mint": "B", "timestamp": 4.0},
            {"action": "sell", "mint": "C", "timestamp": 5.0, "pnl": 1.0},
        ]
    }
    rows = replay_positions(summary)
    assert [r["mint"] for r in rows] == ["A", "B"]
    assert rows[0]["net"] == pytest.approx(0.008)
    assert rows[0]["exit_reason"] == "tier_1"
    assert rows[0]["closed"] and rows[0]["exit_ts"] == 3.0
    assert not rows[1]["closed"] and rows[1]["exit_ts"] is None


def test_split_sweep_needs_both_halves_to_beat_the_base() -> None:
    report = run_split_sweep(
        _capture(),
        _config(),
        [("stop_loss", [0.9, 0.8])],
        cost_model=ReplayCostModel(tip_lamports=0),
        split_at="mid",
    )
    assert report["split_at"] == pytest.approx(560.0)
    base, tight, loose = report["results"]
    assert base["label"] == "base" and not base["beats_base"]
    assert base["segments"]["A"]["positions"] == 1
    assert base["segments"]["B"]["positions"] == 1
    # The base 0.85 stop holds the 0.88x dip and rides the recovery; a 0.9 stop
    # sells the dip in both halves, so it loses to the base.
    assert tight["segments"]["A"]["exit_reasons"] == {"stop_loss": 1}
    assert tight["segments"]["A"]["delta_sol"] < 0
    assert not tight["beats_base"]
    assert loose["segments"]["all"]["delta_sol"] == pytest.approx(0.0)
    assert not loose["beats_base"]

    unsplit = run_split_sweep(
        _capture(), _config(stop_loss=0.9), [("stop_loss", [0.85])], split_at=None
    )
    assert unsplit["split_at"] is None
    assert unsplit["results"][1]["beats_base"]
    assert set(unsplit["results"][1]["segments"]) == {"all"}


def test_render_sweep_shows_halves_and_verdicts() -> None:
    report = run_split_sweep(_capture(), _config(), [("stop_loss", [0.9])])
    out = Console(record=True, width=220, file=io.StringIO())
    render_sweep(report, out)
    text = out.export_text()
    assert "stop_loss=0.9" in text and "A net" in text and "no" in text
    unsplit = run_split_sweep(_capture(), _config(), [], split_at=None)
    out = Console(record=True, width=220, file=io.StringIO())
    render_sweep(unsplit, out)
    assert "A net" not in out.export_text()
