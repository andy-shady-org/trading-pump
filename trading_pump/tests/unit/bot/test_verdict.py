"""Tests for the pre-registered go / no-go verdict (`bot/verdict.py`, FEAT-67)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trading_pump.bot.verdict import (
    VERDICT_GO,
    VERDICT_NO_GO,
    VerdictRules,
    adjusted_positions,
    bootstrap_mean_interval,
    evaluate_verdict,
)

DAY = 86_400.0
START = 1_792_022_400.0  # 2026-10-15 00:00 UTC


def _position(
    index: int,
    ts: float,
    net: float,
    *,
    proceeds: float = 0.02,
    tip: float = 0.0,
    strategy: str = "momentum",
) -> list[dict[str, Any]]:
    pid = f"p{index}"
    return [
        {
            "action": "buy",
            "position_id": pid,
            "mint": f"Mint{index}",
            "timestamp": ts,
            "strategy": strategy,
            "net_pnl_sol": -0.0001,
            "tip_sol": tip,
        },
        {
            "action": "sell",
            "position_id": pid,
            "mint": f"Mint{index}",
            "timestamp": ts + 60,
            "proceeds_sol": proceeds,
            "net_pnl_sol": net + 0.0001,
            "tip_sol": tip,
        },
    ]


def _trail(nets: list[float], *, days: int = 2) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    step = days * DAY / len(nets)
    for index, net in enumerate(nets):
        trades += _position(index, START + index * step, net)
    return trades


def _rules(**overrides: Any) -> VerdictRules:
    base: dict[str, Any] = {"min_positions": 10, "bootstrap_samples": 500}
    base.update(overrides)
    return VerdictRules(**base)


def _checks(report: dict[str, Any]) -> dict[str, bool]:
    return {c["check"]: c["passed"] for c in report["checks"]}


def test_a_steady_edge_is_go() -> None:
    nets = [0.002, 0.001, -0.0005, 0.0015] * 10
    report = evaluate_verdict(_trail(nets), _rules())

    assert report["verdict"] == VERDICT_GO
    assert all(_checks(report).values())
    assert report["positions"] == 40
    assert report["adjusted_net_sol"] == pytest.approx(sum(nets))
    assert set(report["halves"]) == {"A", "B"}
    assert len(report["days"]) == 2
    assert report["bootstrap"]["low"] > 0


def test_one_lucky_position_is_no_go() -> None:
    # Net positive only because of one big winner.
    nets = [-0.0005] * 39 + [0.05]
    report = evaluate_verdict(_trail(nets), _rules(drop_top=1))

    assert report["adjusted_net_sol"] > 0
    checks = _checks(report)
    assert checks["net_positive"] is True
    assert checks["without_top_winners"] is False
    assert report["verdict"] == VERDICT_NO_GO
    assert report["without_top_sol"]["1"] == pytest.approx(-0.0005 * 39)


def test_one_good_half_is_no_go() -> None:
    nets = [0.003] * 20 + [-0.001] * 20
    report = evaluate_verdict(_trail(nets), _rules())

    checks = _checks(report)
    assert checks["net_positive"] is True
    assert checks["halves_positive"] is False
    assert report["halves"]["B"]["adjusted_net_sol"] < 0
    assert report["verdict"] == VERDICT_NO_GO


def test_too_few_positions_and_noise_are_no_go() -> None:
    few = evaluate_verdict(_trail([0.001] * 5), _rules())
    assert _checks(few)["min_positions"] is False

    noisy = evaluate_verdict(
        _trail([0.01, -0.0099] * 20), _rules(min_positive_day_share=0.0)
    )
    assert _checks(noisy)["bootstrap_lower_bound"] is False
    assert noisy["verdict"] == VERDICT_NO_GO


def test_exit_haircut_and_tip_top_up_are_charged() -> None:
    trades = _position(0, START, 0.001, proceeds=0.02, tip=0.00001)
    rules = _rules(exit_haircut_bps=50, tip_lamports=25_000)
    (position,), still_open = adjusted_positions(trades, rules)

    assert still_open == 0
    assert position["haircut_sol"] == pytest.approx(0.02 * 0.005)
    # Two transactions, each topped up from 10,000 to 25,000 lamports.
    assert position["extra_tip_sol"] == pytest.approx(2 * 0.000015)
    assert position["adjusted_net"] == pytest.approx(0.001 - 0.0001 - 0.00003)

    # A malformed figure counts as zero.
    broken = _position(2, START, 0.001)
    broken[1]["proceeds_sol"] = "n/a"
    (position,), _ = adjusted_positions(broken, rules)
    assert position["haircut_sol"] == 0.0

    # A higher recorded tip is not topped up.
    paid = _position(1, START, 0.001, tip=0.0001)
    (position,), _ = adjusted_positions(paid, rules)
    assert position["extra_tip_sol"] == 0.0


def test_open_positions_and_other_lanes_are_left_out() -> None:
    trades = _trail([0.001] * 12)
    trades += _position(99, START + 10, 0.05, strategy="launch")
    trades.append(
        {
            "action": "buy",
            "position_id": "open",
            "timestamp": START,
            "strategy": "momentum",
        }
    )
    trades.append({"action": "sweep", "amount_sol": 1.0})

    report = evaluate_verdict(trades, _rules(strategy="momentum"))
    assert report["positions"] == 12
    assert report["open_positions"] == 1
    assert report["net_sol"] == pytest.approx(0.012)

    everything = evaluate_verdict(trades, _rules())
    assert everything["positions"] == 13


def test_positive_day_share_and_no_split() -> None:
    nets = [0.002] * 10 + [-0.001] * 10 + [0.002] * 10
    report = evaluate_verdict(
        _trail(nets, days=3), _rules(split_at=None, min_positive_day_share=0.9)
    )
    assert "halves_positive" not in _checks(report)
    assert report["halves"] == {}
    assert _checks(report)["positive_days"] is False  # 2 of 3 days


def test_empty_trail_is_no_go() -> None:
    report = evaluate_verdict([], _rules())
    assert report["verdict"] == VERDICT_NO_GO
    assert report["positions"] == 0
    assert not any(_checks(report).values())


def test_bootstrap_is_seeded_and_brackets_the_mean() -> None:
    values = [0.001, -0.002, 0.003, 0.0005, -0.0001] * 8
    first = bootstrap_mean_interval(values, samples=1000, confidence=0.9, seed=3)
    again = bootstrap_mean_interval(values, samples=1000, confidence=0.9, seed=3)
    assert first == again
    mean, low, high = first
    assert low < mean < high
    assert bootstrap_mean_interval([], samples=100, confidence=0.9, seed=1) == (
        0.0,
        0.0,
        0.0,
    )


def test_rules_file_hash_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"_comment": "fixed before the run", "exit_haircut_bps": 50}),
        encoding="utf-8",
    )
    rules = VerdictRules.from_file(path)
    assert rules.exit_haircut_bps == 50.0
    # 50 and 50.0 are the same rule.
    assert rules.sha256 == VerdictRules(exit_haircut_bps=50.0).sha256
    assert rules.sha256 != VerdictRules().sha256
    assert rules.with_overrides(drop_top=5, seed=None).drop_top == 5
    assert VerdictRules(split_at=1_792_000_000).split_at == 1_792_000_000.0

    path.write_text(json.dumps({"drop_tops": 5}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown verdict rule keys: drop_tops"):
        VerdictRules.from_file(path)
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        VerdictRules.from_file(path)
    with pytest.raises(ValueError, match="Cannot read"):
        VerdictRules.from_file(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_positions": 0},
        {"exit_haircut_bps": 10_000},
        {"tip_lamports": -1},
        {"min_positive_day_share": 1.5},
        {"drop_top": -1},
        {"bootstrap_samples": 10},
        {"confidence": 0.3},
        {"split_at": "later"},
        {"drop_top": 2.5},
        {"seed": True},
    ],
)
def test_bad_rules_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        VerdictRules(**overrides)


def test_shipped_rules_file_loads() -> None:
    shipped = Path(__file__).parents[4] / "configs" / "verdict_rules.json"
    rules = VerdictRules.from_file(shipped)
    assert rules.min_positions == 100
    assert rules.tip_lamports == 25_000
    assert rules.exit_haircut_bps == 50.0
