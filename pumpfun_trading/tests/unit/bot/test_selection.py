"""Unit tests for ``bot/selection.py`` (entry rules against a random cut)."""

from __future__ import annotations

from typing import Any

import pytest

from pumpfun_trading.bot.selection import (
    KeepRule,
    beats_random_cut,
    closed_positions,
    cut_stats,
    metric_value,
    resolve_split,
    segments,
    selection_report,
)


def _trades(
    position: str,
    *,
    ts: float,
    net: float,
    metrics: dict[str, Any] | None = None,
    strategy: str = "momentum",
) -> list[dict[str, Any]]:
    buy: dict[str, Any] = {
        "action": "buy",
        "position_id": position,
        "mint": f"M-{position}",
        "timestamp": ts,
        "strategy": strategy,
        "net_pnl_sol": -0.001,
        "market_regime": {"hour_utc": 3},
    }
    if metrics is not None:
        buy["entry_metrics"] = metrics
    return [
        buy,
        {
            "action": "partial_sell",
            "position_id": position,
            "timestamp": ts + 5,
            "net_pnl_sol": 0.0,
            "reason": "tier_1_take_profit (2.0x)",
        },
        {
            "action": "sell",
            "position_id": position,
            "timestamp": ts + 10,
            "net_pnl_sol": net + 0.001,
            "reason": "stop_loss",
        },
    ]


def test_keep_rule_parses_and_reads_recorded_metrics() -> None:
    rule = KeepRule.parse(" top_buyer_share <= 0.3 ")
    assert (rule.metric, rule.op, rule.value) == ("top_buyer_share", "<=", 0.3)
    assert rule.label == "top_buyer_share<=0.3"

    position = {"entry_metrics": {"top_buyer_share": 0.2, "flag": True, "x": "s"}}
    assert rule.keeps(position) is True
    assert KeepRule.parse("top_buyer_share>0.3").keeps(position) is False
    assert KeepRule.parse("missing==1").keeps(position) is None
    assert metric_value(position, "flag") == 1.0
    assert metric_value(position, "x") is None
    # market_regime is read when entry_metrics lacks the metric.
    assert (
        KeepRule.parse("hour_utc!=3").keeps({"market_regime": {"hour_utc": 3}}) is False
    )


@pytest.mark.parametrize("text", ["top_buyer_share", "a<b", "1x<2", "a=1"])
def test_keep_rule_rejects_bad_text(text: str) -> None:
    with pytest.raises(ValueError):
        KeepRule.parse(text)


def test_closed_positions_book_buy_and_sells_and_skip_open_ones() -> None:
    trades = (
        _trades("p2", ts=200.0, net=-0.004, metrics={"unique_buyers": 4})
        + _trades("p1", ts=100.0, net=0.003)
        + [{"action": "buy", "position_id": "open", "timestamp": 300.0}]
        + [{"action": "sweep", "position_id": "x"}]
    )

    positions = closed_positions(trades)

    assert [p["position_id"] for p in positions] == ["p1", "p2"]
    first, second = positions
    assert first["net"] == pytest.approx(0.003)
    assert first["exit_reason"] == "tier_1_take_profit"
    assert first["market_regime"] == {"hour_utc": 3}
    assert second["entry_metrics"] == {"unique_buyers": 4}
    assert second["strategy"] == "momentum"


def test_split_and_segments() -> None:
    assert resolve_split(None, 0, 10) is None
    assert resolve_split("", 0, 10) is None
    assert resolve_split("mid", 0, 10) == 5.0
    assert resolve_split("7.5", 0, 10) == 7.5
    items = [{"entry_ts": 1.0}, {"entry_ts": 6.0}]
    parts = segments(items, 5.0)
    assert [len(parts[k]) for k in ("all", "A", "B")] == [2, 1, 1]
    assert list(segments(items, None)) == ["all"]


def test_cut_stats_and_verdict() -> None:
    row = cut_stats(kept=1, kept_net=0.01, total=4, total_net=-0.02)
    assert row["random_cut_net_sol"] == pytest.approx(-0.005)
    assert row["edge_sol"] == pytest.approx(0.015)
    assert cut_stats(kept=0, kept_net=0.0, total=0, total_net=0.0)["edge_sol"] == 0.0

    win = {"total": 2, "edge_sol": 0.1}
    loss = {"total": 2, "edge_sol": -0.1}
    empty = {"total": 0, "edge_sol": 0.0}
    assert beats_random_cut({"all": win}) is True
    assert beats_random_cut({"all": win, "A": win, "B": loss}) is False
    assert beats_random_cut({"all": win, "A": win, "B": empty}) is True
    assert beats_random_cut({"all": empty}) is False


def test_selection_report_compares_each_rule_with_a_random_cut() -> None:
    trades = (
        _trades("a1", ts=100.0, net=0.004, metrics={"top_buyer_share": 0.2})
        + _trades("a2", ts=110.0, net=-0.004, metrics={"top_buyer_share": 0.6})
        + _trades("b1", ts=200.0, net=0.002, metrics={"top_buyer_share": 0.1})
        + _trades("b2", ts=210.0, net=-0.006, metrics={"top_buyer_share": 0.9})
        + _trades("b3", ts=220.0, net=-0.001)  # recorded no metrics
    )
    rules = [KeepRule.parse("top_buyer_share<0.3"), KeepRule.parse("hour_utc==3")]

    report = selection_report(closed_positions(trades), rules, split_at="mid")

    assert report["positions"] == 5 and report["split_at"] == pytest.approx(160.0)
    assert report["segments"]["A"]["positions"] == 2
    share, hour, combined = report["rules"]
    assert combined["rule"] == "top_buyer_share<0.3 & hour_utc==3"
    half_a = share["segments"]["A"]
    assert (half_a["kept"], half_a["total"]) == (1, 2)
    assert half_a["random_cut_net_sol"] == pytest.approx(0.0)
    assert half_a["edge_sol"] == pytest.approx(0.004)
    assert share["segments"]["B"]["missing"] == 1
    assert share["beats_random_cut"] is True
    # Keeping every position is exactly the random cut: no edge.
    assert hour["segments"]["all"]["edge_sol"] == pytest.approx(0.0)
    assert hour["beats_random_cut"] is False
    assert combined["segments"]["all"]["missing"] == 1

    assert selection_report([], rules[:1])["rules"][0]["beats_random_cut"] is False
