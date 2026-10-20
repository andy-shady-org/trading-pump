"""Unit tests for ``engines/cuts.py`` (entry features rebuilt from a capture)."""

from __future__ import annotations

from typing import Any

import pytest

from pumpfun_trading.engines.cuts import (
    CaptureIndex,
    creator_prior_losses,
    early_inflow,
    enrich_positions,
    flow_features,
)


def _trade(
    mint: str,
    ts: float,
    user: str,
    *,
    buy: bool = True,
    sol: float = 0.5,
    mc: float = 32.0,
) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "price": mc / 1e9,
        "market_cap_sol": mc,
        "is_buy": buy,
        "sol_amount": sol,
        "user": user,
        "signal": "buy" if buy else "sell",
    }


def _records() -> list[dict[str, Any]]:
    return [
        {"timestamp": 1.0, "mint": "A", "market_cap_sol": 28.0, "price": 2.8e-8},
        {
            "timestamp": 1.5,
            "mint": "A",
            "event": "screening",
            "screening": {"creator": "Dev"},
        },
        {"timestamp": 1.6, "mint": "B", "event": "screening", "screening": {}},
        {"timestamp": 3.0, "mint": "A", "event": "curve_poll", "price": 3e-8},
        _trade("A", 4.0, "W1", sol=1.0),
        _trade("A", 2.0, "Dev", sol=2.0),  # out of order; creator never counts
        _trade("A", 5.0, "W1", buy=False, sol=0.9),
        _trade("A", 6.0, "W2", sol=0.5),
        {
            "timestamp": 7.0,
            "mint": "A",
            "price": 3e-8,
            "signal": "buy",
            "reason": "momentum_confirmed",
        },
        _trade("A", 9.0, "W3", sol=5.0),  # after entry: never seen by the rule
        {"timestamp": 1.0, "mint": ""},
    ]


def test_capture_index_keeps_market_data_only() -> None:
    index = CaptureIndex.from_records(_records())
    assert index.creator("A") == "Dev" and index.creator("B") is None
    assert [t["timestamp"] for t in index.trades["A"]] == [2.0, 4.0, 5.0, 6.0, 9.0]
    assert index.creates["A"]["timestamp"] == 1.0


def test_flow_features_score_only_pre_entry_trades_without_the_creator() -> None:
    index = CaptureIndex.from_records(_records())
    features = flow_features(index, "A", until=7.0)
    assert features == {
        "pre_entry_buys": 2,
        "unique_buyers": 2,
        "top_buyer_share": pytest.approx(0.6667, abs=1e-4),
        "wallet_diversity": pytest.approx(0.3333, abs=1e-4),
        "round_trip_wallets": 1,
        "round_trip_share": pytest.approx(0.75, abs=1e-3),
        "quick_flips": 1,
    }
    assert flow_features(index, "A", until=1.0) is None
    assert flow_features(index, "missing", until=10.0) is None


def test_early_inflow_measures_sol_before_the_first_trade() -> None:
    index = CaptureIndex.from_records(_records())
    early = early_inflow(index, "A")
    assert early is not None
    assert early["first_trade_gap_seconds"] == pytest.approx(1.0)
    assert early["early_sol"] > 0
    assert early_inflow(index, "B") is None


def test_creator_book_only_uses_losses_closed_before_entry() -> None:
    creators = {"m1": "C", "m2": "C", "m3": "C", "m4": None}
    positions = [
        {"mint": "m1", "entry_ts": 10.0, "exit_ts": 20.0, "net": -0.01},
        {"mint": "m2", "entry_ts": 15.0, "exit_ts": 40.0, "net": 0.02},  # m1 open
        {"mint": "m3", "entry_ts": 30.0, "exit_ts": 50.0, "net": 0.01},  # m1 closed
        {"mint": "m4", "entry_ts": 60.0, "exit_ts": 70.0, "net": -0.01},
    ]
    assert creator_prior_losses(positions, creators) == [0, 0, 1, 0]


def test_enrich_positions_prefers_recorded_metrics() -> None:
    index = CaptureIndex.from_records(_records())
    positions = [
        {
            "mint": "A",
            "entry_ts": 7.0,
            "exit_ts": 8.0,
            "net": -0.01,
            "entry_metrics": {"top_buyer_share": 0.1},
        },
        {"mint": "A", "entry_ts": 1.0, "exit_ts": 2.0, "net": 0.0, "creator": None},
        {"mint": "B", "entry_ts": 5.0, "net": 0.0},
    ]
    enriched = enrich_positions(positions, index)
    first = enriched[0]["entry_metrics"]
    assert first["top_buyer_share"] == 0.1  # recorded wins
    assert first["wallet_diversity"] == pytest.approx(0.3333, abs=1e-4)
    assert first["creator_prior_loss"] == 0 and "early_sol" in first
    assert enriched[0]["creator"] == "Dev"
    assert "pre_entry_buys" not in enriched[1]["entry_metrics"]
    assert enriched[2]["entry_metrics"] == {}
    assert positions[0]["entry_metrics"] == {"top_buyer_share": 0.1}
