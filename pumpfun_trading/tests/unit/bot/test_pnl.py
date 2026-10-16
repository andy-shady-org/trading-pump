"""Unit tests for ``bot/pnl.py`` net PnL accounting (FEAT-49)."""

from __future__ import annotations

import pytest

from pumpfun_trading.bot.pnl import (
    COST_SOURCE_NONE,
    PnlTotals,
    build_pnl_fields,
    cost_fields,
    open_cost_basis,
    summarize_pnl,
    trade_cash_flow,
    trade_net_pnl,
    trade_payloads,
)
from pumpfun_trading.sdk.costs import model_transaction_costs

DAY_1 = 1_792_141_900.0  # 2026-10-16 UTC
DAY_2 = DAY_1 + 86_400


def _buy(position: str, cost: float = 0.01, costs: float = 0.0021) -> dict:
    return {
        "action": "buy",
        "mint": f"Mint-{position}",
        "position_id": position,
        "cost_sol": cost,
        "costs_sol": costs,
        "gross_pnl_sol": 0.0,
        "net_pnl_sol": -costs,
        "reason": "entry",
        "timestamp": DAY_1,
    }


def _sell(
    position: str,
    proceeds: float,
    *,
    cost: float = 0.01,
    costs: float = 0.0001,
    action: str = "sell",
    reason: str = "trailing_stop_hit (drawdown 23%)",
    ts: float = DAY_1,
) -> dict:
    gross = proceeds - cost
    return {
        "action": action,
        "mint": f"Mint-{position}",
        "position_id": position,
        "cost_sol": cost,
        "proceeds_sol": proceeds,
        "costs_sol": costs,
        "fee_sol": 0.00001,
        "tip_sol": 0.0001,
        "rent_sol": -0.002 if action == "sell" else 0.0,
        "gross_pnl_sol": gross,
        "net_pnl_sol": gross - costs,
        "reason": reason,
        "timestamp": ts,
    }


def test_build_pnl_fields_for_buy_and_sell() -> None:
    costs = model_transaction_costs(priority_fee_lamports=0, tip_lamports=100_000)

    buy = build_pnl_fields(action="buy", cost_sol=0.01, proceeds_sol=0.0, costs=costs)
    sell = build_pnl_fields(
        action="partial_sell", cost_sol=0.005, proceeds_sol=0.008, costs=None
    )

    assert buy["gross_pnl_sol"] == 0.0
    assert buy["net_pnl_sol"] == pytest.approx(-0.000105)
    assert buy["cash_flow_sol"] == pytest.approx(-0.010105)
    assert buy["cost_source"] == "modelled"
    assert sell["gross_pnl_sol"] == pytest.approx(0.003)
    assert sell["cash_flow_sol"] == pytest.approx(0.008)
    assert sell["cost_source"] == COST_SOURCE_NONE
    assert cost_fields(None)["costs_sol"] == 0.0


def test_build_pnl_fields_arbitrage_is_a_net_round_trip() -> None:
    """BUG-99: an arbitrage bundle books gross spread minus fees and tip."""
    costs = model_transaction_costs(
        priority_fee_lamports=295_000, tip_lamports=9_700_000
    )

    arb = build_pnl_fields(
        action="ARBITRAGE", cost_sol=1.0, proceeds_sol=1.03, costs=costs
    )

    assert arb["gross_pnl_sol"] == pytest.approx(0.03)
    assert arb["costs_sol"] == pytest.approx(0.01)
    assert arb["net_pnl_sol"] == pytest.approx(0.02)
    assert arb["cash_flow_sol"] == pytest.approx(0.02)


def test_legacy_records_fall_back_to_gross_fields() -> None:
    legacy_sell = {"action": "sell", "entry": 0.004, "exit": 0.0063}
    legacy_buy = {"side": "buy", "entry": 0.01}

    assert trade_net_pnl(legacy_sell) == pytest.approx(0.0023)
    assert trade_net_pnl(legacy_buy) == 0.0
    assert trade_cash_flow(legacy_sell) == pytest.approx(0.0063)
    assert trade_cash_flow(legacy_buy) == pytest.approx(-0.01)
    assert trade_net_pnl({"action": "sell", "exit": "bad"}) == 0.0


def test_summarize_pnl_totals_win_rate_and_cost_share() -> None:
    trades = [
        _buy("p1"),
        _sell("p1", 0.015),
        _buy("p2"),
        _sell("p2", 0.008, reason="stop_loss_hit", ts=DAY_2),
    ]

    summary = summarize_pnl(trades, group_by="reason")
    totals = summary["totals"]

    assert summary["trades"] == 4
    assert totals["buys"] == 2 and totals["sells"] == 2
    assert totals["gross_pnl_sol"] == pytest.approx(0.003)
    assert totals["net_pnl_sol"] == pytest.approx(0.003 - 0.0044)
    assert totals["win_rate"] == pytest.approx(0.5)
    assert totals["expectancy_sol"] == pytest.approx((0.003 - 0.0044) / 2)
    assert totals["cost_share_of_gross"] == pytest.approx(0.0044 / 0.003)
    assert set(summary["groups"]) == {"entry", "trailing_stop_hit", "stop_loss_hit"}
    assert summary["groups"]["stop_loss_hit"]["net_pnl_sol"] == pytest.approx(-0.0021)


@pytest.mark.parametrize(
    "group_by, expected",
    [
        ("day", {"2026-10-16", "2026-10-17"}),
        ("mint", {"Mint-p1", "Mint-p2"}),
        ("strategy", {"default"}),
    ],
)
def test_summarize_pnl_groups(group_by: str, expected: set[str]) -> None:
    trades = [_sell("p1", 0.02), _sell("p2", 0.0, ts=DAY_2)]
    assert set(summarize_pnl(trades, group_by=group_by)["groups"]) == expected


def test_summarize_rejects_unknown_group_and_handles_losses() -> None:
    with pytest.raises(ValueError):
        summarize_pnl([_sell("p1", 0.0)], group_by="weekday")
    summary = summarize_pnl([_sell("p1", 0.0)])
    assert summary["totals"]["cost_share_of_gross"] is None
    assert "groups" not in summary
    assert PnlTotals().win_rate == 0.0 and PnlTotals().expectancy_sol == 0.0


def test_pnl_totals_round_trip() -> None:
    totals = PnlTotals()
    for trade in (_buy("p1"), _sell("p1", 0.02)):
        totals.add(trade)

    restored = PnlTotals.from_dict(totals.to_dict())

    assert restored.net_pnl_sol == pytest.approx(totals.net_pnl_sol)
    assert restored.sells == 1 and restored.winning_sells == 1
    assert PnlTotals.from_dict({"buys": "x"}).buys == 0
    assert PnlTotals.from_dict(None).sells == 0


def test_trade_payloads_and_open_cost_basis() -> None:
    raw = [
        {"type": "trade", "payload": _buy("p1")},
        {"type": "state_transition", "payload": {"to_state": "buying"}},
        {
            "type": "trade",
            "payload": _sell("p1", 0.01, cost=0.004, action="partial_sell"),
        },
        {"type": "trade", "payload": _buy("p2")},
        {"type": "trade", "payload": _sell("p2", 0.02)},
        _buy("p3"),
        "garbage",
    ]

    trades = trade_payloads(raw)  # type: ignore[arg-type]

    assert len(trades) == 5
    basis = open_cost_basis(trades + [{"action": "buy"}])
    assert basis == {"p1": pytest.approx(0.006), "p3": pytest.approx(0.01)}
