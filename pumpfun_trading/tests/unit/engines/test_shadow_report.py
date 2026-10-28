"""Unit tests for ``engines/shadow_report.py`` (FEAT-58 shadow-variant read-out)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.shadow_report import (
    build_shadow_report,
    render_shadow_report,
    shadow_entries,
    simulate_fills,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.tests.support.factories import make_config


def _config(**overrides: Any) -> TradingBotConfig:
    base: dict[str, Any] = {
        "entry_mode": "confirmed",
        "buy_amount_sol": 0.02,
        "paper_entry_slippage_bps": 100,
        "shadow_variants": (
            {"name": "baseline"},
            {"name": "strict", "momentum_min_unique_buyers": 9},
            {"name": "drift5", "max_entry_drift_pct": 0.05},
        ),
    }
    base.update(overrides)
    return make_config(**base)


def _poll(mint: str, ts: float, mc: float, source: str = "watch") -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "event": "curve_poll",
        "source": source,
        "price": mc / 1e9,
        "market_cap_sol": mc,
    }


def _trade(
    mint: str, ts: float, mc: float, *, buy: bool = True, sol: float = 0.5
) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "price": mc / 1e9,
        "market_cap_sol": mc,
        "is_buy": buy,
        "sol_amount": sol,
        "user": "OtherWallet",
        "signal": "buy" if buy else "sell",
    }


def _shadow(
    mint: str,
    variant: str,
    ts: float,
    fill: float | None,
    *,
    signal: float = 40.0,
    refused: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "timestamp": ts,
        "mint": mint,
        "event": "shadow_entry",
        "variant": variant,
        "signal_timestamp": ts - 1.5,
        "signal_market_cap_sol": signal,
        "entry_metrics": {"unique_buyers": 5},
    }
    if fill is not None:
        row["fill_market_cap_sol"] = fill
        row["fill_drift_pct"] = round(fill / signal - 1.0, 4)
    if refused:
        row["refused"] = refused
    return row


def _capture() -> list[dict[str, Any]]:
    """Mint A runs up after the shadow fill; mint B dumps into the stop loss."""
    return [
        {
            "timestamp": 90.0,
            "mint": "A",
            "event": "screening",
            "screening": {"creator": "DevA", "passed": True},
        },
        _poll("A", 100.0, 40.0),
        # The bot's own fill: never mirrored as a variant entry.
        {
            "timestamp": 100.5,
            "mint": "A",
            "price": 40.5 / 1e9,
            "market_cap_sol": 40.5,
            "signal": "buy",
            "reason": "momentum_confirmed",
            "sol_amount": 0.02,
        },
        _shadow("A", "baseline", 101.5, 41.0),
        _shadow("A", "strict", 101.5, 41.0),
        _shadow("A", "drift5", 101.5, 41.0),
        _poll("A", 101.5, 41.0, "shadow_fill"),
        _trade("A", 105.0, 50.0),
        _trade("A", 110.0, 55.0),
        _trade("A", 115.0, 60.0),
        _poll("B", 1_000.0, 40.0),
        _shadow("B", "baseline", 1_001.5, 41.0),
        _shadow("B", "drift5", 1_001.5, 44.0, refused="entry_drift"),
        _shadow("B", "late", 1_001.5, None, refused="curve_error: RuntimeError"),
        _trade("B", 1_005.0, 30.0, buy=False),
        _trade("B", 1_010.0, 25.0, buy=False),
    ]


def test_shadow_entries_are_time_ordered_and_complete() -> None:
    rows = shadow_entries(
        [
            {"event": "shadow_entry", "variant": "v", "mint": "B", "timestamp": 2},
            {"event": "shadow_entry", "variant": "v", "mint": "A", "timestamp": 1},
            {"event": "shadow_entry", "mint": "C", "timestamp": 3},  # no variant
            {"event": "curve_poll", "mint": "A", "timestamp": 1},
        ]
    )
    assert [r["mint"] for r in rows] == ["A", "B"]


def test_report_models_each_variant_from_its_fills() -> None:
    report = build_shadow_report(_capture(), _config(), cost_model=ReplayCostModel())

    assert report["shadow_entries"] == 6 and report["baseline"] == "baseline"
    variants = report["variants"]
    # Config order first, then variants only seen in the capture.
    assert list(variants) == ["baseline", "strict", "drift5", "late"]

    base = variants["baseline"]["segments"]["all"]
    assert (base["signals"], base["fills"], base["positions"]) == (2, 2, 2)
    assert base["exit_reasons"] == {"stagnant_buy_flow": 1, "stop_loss": 1}
    winner, loser = variants["baseline"]["positions"]
    # The entry is the shadow fill, not the bot's own fill half a second earlier.
    assert winner["mint"] == "A" and winner["entry_ts"] == 101.5
    assert winner["net"] > 0 > loser["net"]
    assert base["net_sol"] == pytest.approx(winner["net"] + loser["net"])
    assert base["random_cut"] is None

    strict = variants["strict"]
    stats = strict["segments"]["all"]
    # Only A, still held when the data ends: marked to market at its last price.
    assert stats["open_at_end"] == 1 and stats["exit_reasons"] == {"open_at_end": 1}
    assert stats["net_sol"] == pytest.approx(winner["net"])
    cut = stats["random_cut"]
    assert cut["random_cut_net_sol"] == pytest.approx(base["net_sol"] / 2)
    assert cut["edge_sol"] == pytest.approx(winner["net"] - base["net_sol"] / 2)
    assert strict["beats_random_cut"] is True

    drift = variants["drift5"]["segments"]["all"]
    assert drift["refused"] == {"entry_drift": 1} and drift["positions"] == 1
    assert drift["drift_median"] == pytest.approx(0.0625)
    assert drift["drift_over"] == {"0.05": 0.5, "0.08": 0.5, "0.10": 0.0}

    late = variants["late"]["segments"]["all"]
    assert late["refused"] == {"curve_error": 1} and late["positions"] == 0
    assert late["drift_median"] is None and late["drift_p90"] is None
    assert late["win_rate"] == 0.0 and late["expectancy_sol"] == 0.0
    assert variants["late"]["beats_random_cut"] is False


def test_report_splits_the_capture_into_halves() -> None:
    report = build_shadow_report(_capture(), _config(), split_at="mid")

    assert report["split_at"] == pytest.approx((90.0 + 1_010.0) / 2)
    assert report["costs_modelled"] is False
    strict = report["variants"]["strict"]
    assert strict["segments"]["A"]["positions"] == 1
    assert strict["segments"]["B"]["positions"] == 0
    # Half B has a baseline position the strict rule did not take: no evidence
    # of an edge there, so it does not beat the random cut in both halves.
    assert strict["segments"]["B"]["random_cut"]["edge_sol"] == pytest.approx(0.0)
    assert strict["beats_random_cut"] is False


def test_report_without_a_baseline_has_no_random_cut() -> None:
    report = build_shadow_report(_capture(), _config(), baseline="nope")

    assert report["baseline"] is None
    assert all(v["beats_random_cut"] is None for v in report["variants"].values())


def test_simulate_fills_without_fills_or_with_unpriced_data() -> None:
    assert simulate_fills([], [], _config()) == []
    fill = _shadow("C", "baseline", 10.0, 30.0)
    (position,) = simulate_fills([fill], [], _config(), cost_model=ReplayCostModel())
    # No later data: open at the end and marked at the fill price, so it shows
    # the round-trip costs and the paper penalty as a loss.
    assert position["exit_reason"] == "open_at_end" and position["net"] < 0
    assert position["fill_drift_pct"] == pytest.approx(-0.25)


def test_render_shadow_report_prints_every_segment() -> None:
    console = Console(record=True, width=220, file=io.StringIO())
    render_shadow_report(
        build_shadow_report(_capture(), _config(), split_at="mid"), console
    )
    out = console.export_text()
    assert "Whole capture" in out and "Half A" in out and "Half B" in out
    assert "strict: does not beat a random cut" in out
    assert "Costs are not modelled" in out

    console = Console(record=True, width=220, file=io.StringIO())
    render_shadow_report(
        build_shadow_report(_capture(), _config(), cost_model=ReplayCostModel()),
        console,
    )
    out = console.export_text()
    assert "strict: beats a random cut" in out and "(overall)" in out
    assert "Costs are not modelled" not in out

    console = Console(record=True, width=220, file=io.StringIO())
    render_shadow_report(
        build_shadow_report(_capture(), _config(), baseline="nope"), console
    )
    assert "No baseline variant" in console.export_text()

    console = Console(record=True, width=220, file=io.StringIO())
    render_shadow_report(build_shadow_report([], _config(shadow_variants=())), console)
    assert "No shadow_entry rows" in console.export_text()
