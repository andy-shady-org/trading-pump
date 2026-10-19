"""Tests for the sell sizing and proceeds helpers (`execution/sell_pipeline.py`)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pumpfun_trading.execution.sell_pipeline import (
    DRY_RUN_PLACEHOLDER_TOKENS,
    estimate_sell_proceeds,
    plan_sell_size,
    position_entry_sol,
    position_id,
    position_token_amounts,
    sell_replay_snapshot,
    sold_fraction,
)


def test_token_amounts_prefer_explicit_fields() -> None:
    assert position_token_amounts(
        {"initial_token_amount": 1000, "remaining_token_amount": 400}, dry_run=False
    ) == (1000, 400)
    assert position_token_amounts({"token_amount": 700}, dry_run=False) == (700, 700)
    assert position_token_amounts({}, dry_run=False) == (0, 0)
    assert position_token_amounts({}, dry_run=True) == (
        DRY_RUN_PLACEHOLDER_TOKENS,
        DRY_RUN_PLACEHOLDER_TOKENS,
    )


@pytest.mark.parametrize(
    ("amount", "fraction", "expected"),
    [
        (300, 1.0, (300, True)),
        (5000, 1.0, (1000, False)),
        (None, 0.5, (500, True)),
        (None, 0.0001, (1, True)),
        (None, 1.0, (1000, False)),
        (0, 1.0, (1000, False)),
    ],
)
def test_plan_sell_size(
    amount: int | None, fraction: float, expected: tuple[int, bool]
) -> None:
    size = plan_sell_size(
        initial_tokens=1000,
        remaining_tokens=1000,
        sell_amount_tokens=amount,
        sell_fraction=fraction,
        min_sell_balance=0,
    )
    assert (size.tokens_to_sell, size.is_partial) == expected


def test_dust_remainder_is_sold_with_the_rest() -> None:
    size = plan_sell_size(
        initial_tokens=1000,
        remaining_tokens=1000,
        sell_amount_tokens=995,
        sell_fraction=1.0,
        min_sell_balance=10,
    )
    assert size.tokens_to_sell == 1000
    assert size.is_partial is False


def test_fraction_uses_remaining_when_initial_unknown() -> None:
    size = plan_sell_size(
        initial_tokens=0,
        remaining_tokens=800,
        sell_amount_tokens=None,
        sell_fraction=0.25,
        min_sell_balance=0,
    )
    assert size.tokens_to_sell == 200


def test_sold_fraction_is_clamped() -> None:
    assert sold_fraction(250, 1000, 500) == pytest.approx(0.25)
    assert sold_fraction(500, 0, 500) == pytest.approx(1.0)
    assert sold_fraction(5000, 1000, 1000) == pytest.approx(1.0)
    assert sold_fraction(7, 0, 0) == pytest.approx(1.0)


@pytest.mark.regression("BUG-45")
def test_entry_sol_is_the_cost_basis_not_the_unit_price() -> None:
    assert position_entry_sol({"cost_sol": 0.03, "buy_price": 1e-7}, 0.02) == 0.03
    assert position_entry_sol({"entry_sol": 0.04}, 0.02) == 0.04
    assert position_entry_sol({"buy_price": 1e-7}, 0.02) == 0.02
    assert position_entry_sol({}, 0.0) == 0.0


def test_paper_proceeds_follow_market_cap_and_fee() -> None:
    res = SimpleNamespace(amount_sol=9.0)
    kwargs: dict[str, Any] = {"dry_run": True, "fraction": 0.5, "paper_fee_factor": 0.9}
    assert estimate_sell_proceeds(
        res, cost_sol=0.02, entry_market_cap=30.0, current_market_cap=60.0, **kwargs
    ) == pytest.approx(0.02 * 0.5 * 2.0 * 0.9)
    assert estimate_sell_proceeds(
        res, cost_sol=0.02, entry_market_cap=0.0, current_market_cap=60.0, **kwargs
    ) == pytest.approx(0.02 * 0.5 * 0.9)
    assert estimate_sell_proceeds(
        res, cost_sol=0.0, entry_market_cap=0.0, current_market_cap=0.0, **kwargs
    ) == pytest.approx(9.0)


def test_live_proceeds_use_the_swap_amount_then_fall_back() -> None:
    kwargs: dict[str, Any] = {
        "dry_run": False,
        "cost_sol": 0.02,
        "fraction": 1.0,
        "paper_fee_factor": 0.5,
    }
    assert estimate_sell_proceeds(
        SimpleNamespace(amount_sol=0.031),
        entry_market_cap=30.0,
        current_market_cap=60.0,
        **kwargs,
    ) == pytest.approx(0.031)
    assert estimate_sell_proceeds(
        SimpleNamespace(sol_amount=0.025),
        entry_market_cap=30.0,
        current_market_cap=60.0,
        **kwargs,
    ) == pytest.approx(0.025)
    assert estimate_sell_proceeds(
        SimpleNamespace(min_sol_lamports=15_000_000),
        entry_market_cap=30.0,
        current_market_cap=60.0,
        **kwargs,
    ) == pytest.approx(0.015)
    # No amount on the result: market-cap estimate, without the paper fee.
    assert estimate_sell_proceeds(
        SimpleNamespace(), entry_market_cap=30.0, current_market_cap=60.0, **kwargs
    ) == pytest.approx(0.04)
    assert estimate_sell_proceeds(
        SimpleNamespace(), entry_market_cap=0.0, current_market_cap=0.0, **kwargs
    ) == pytest.approx(0.02)
    assert (
        estimate_sell_proceeds(
            SimpleNamespace(),
            dry_run=False,
            cost_sol=0.0,
            fraction=1.0,
            entry_market_cap=0.0,
            current_market_cap=0.0,
            paper_fee_factor=1.0,
        )
        == 0.0
    )


def test_position_id_fallbacks() -> None:
    assert position_id({"position_id": "p", "id": "i"}) == "p"
    assert position_id({"id": "i", "trade_id": "t"}) == "i"
    assert position_id({"trade_id": "t"}) == "t"
    assert position_id({}) is None


def test_sell_replay_snapshot() -> None:
    snap = sell_replay_snapshot(
        mint="M",
        name="Tok",
        position={"current_market_cap": 50.0, "entry_market_cap": 30.0},
        proceeds_sol=0.03,
        tokens_sold=123,
        reason="",
        default_reason="partial_exit",
        timestamp=10.0,
    )
    assert snap == {
        "timestamp": 10.0,
        "mint": "M",
        "name": "Tok",
        "price": 50.0 / 1_000_000_000.0,
        "market_cap_sol": 50.0,
        "is_buy": False,
        "sol_amount": 0.03,
        "token_amount": 123,
        "signal": "sell",
        "reason": "partial_exit",
    }
    snap = sell_replay_snapshot(
        mint="M",
        name="Tok",
        position={},
        proceeds_sol=0.0,
        tokens_sold=1,
        reason="stop_loss",
        default_reason="exit",
    )
    assert snap["price"] == 0.0 and snap["reason"] == "stop_loss"
    assert snap["timestamp"] > 0
