"""Unit tests for ``engines/wallets.py`` (FEAT-54 copy-simulation wallet scores)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.cuts import CaptureIndex
from pumpfun_trading.engines.wallets import (
    PriceBook,
    copy_trip,
    render_wallet_scores,
    score_wallets,
    validate_wallets,
    wallet_round_trips,
)


def _trade(
    mint: str, ts: float, user: str, price: float, *, buy: bool = True
) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": mint,
        "price": price,
        "is_buy": buy,
        "sol_amount": 0.5,
        "user": user,
    }


def _capture() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": 0.5,
            "mint": "A",
            "event": "screening",
            "screening": {"creator": "Dev"},
        },
        _trade("A", 1.0, "Dev", 1e-8),
        _trade("A", 2.0, "Smart", 1e-8),
        {"timestamp": 3.5, "mint": "A", "event": "curve_poll", "market_cap_sol": 12.0},
        _trade("A", 4.0, "Dumb", 2e-8),
        _trade("A", 10.0, "Smart", 3e-8, buy=False),
        _trade("A", 10.5, "Smart", 3e-8),  # a top-up after its sell
        _trade("A", 12.0, "Other", 3e-8),
        _trade("A", 20.0, "Dumb", 1e-8, buy=False),
        _trade("A", 21.0, "Last", 1e-8),  # never sells: open at the end
        {"timestamp": 22.0, "mint": "A", "price": 5e-8, "reason": "stop_loss"},
        {"timestamp": 23.0, "mint": "A", "event": "shadow_entry", "price": 9e-8},
    ]


def test_price_book_uses_trades_and_curve_polls() -> None:
    book = PriceBook(_capture())
    assert book.at_or_after("A", 3.0) == (3.5, pytest.approx(1.2e-8))
    assert book.at_or_after("A", 30.0) is None
    assert book.at_or_after("missing", 0.0) is None
    assert book.last("A") == (21.0, 1e-8)
    assert book.last("missing") is None


def test_round_trips_skip_the_creator_and_keep_the_first_sell() -> None:
    trips = wallet_round_trips(CaptureIndex.from_records(_capture()))
    assert "Dev" not in trips
    smart = trips["Smart"][0]
    assert smart["buy_ts"] == 2.0 and smart["sell_ts"] == 10.0
    assert smart["own_buy_sol"] == 1.0 and smart["own_sell_sol"] == 0.5
    assert trips["Last"][0]["sell_ts"] is None


def test_copy_trip_fills_after_the_delay_and_pays_costs() -> None:
    book = PriceBook(_capture())
    trip = {"mint": "A", "buy_ts": 2.0, "sell_ts": 10.0}
    gross = copy_trip(
        trip,
        book,
        buy_amount_sol=0.02,
        delay_seconds=1.5,
        penalty_bps=0,
        cost_model=None,
    )
    assert gross is not None
    assert gross["entry_ts"] == 3.5 and gross["exit_ts"] == 12.0
    assert gross["net"] == pytest.approx(0.02 * (3e-8 / 1.2e-8) - 0.02)
    costed = copy_trip(
        trip,
        book,
        buy_amount_sol=0.02,
        delay_seconds=1.5,
        penalty_bps=100,
        cost_model=ReplayCostModel(tip_lamports=0),
    )
    assert costed is not None and costed["net"] < gross["net"]
    assert (
        copy_trip(
            {"mint": "A", "buy_ts": 30.0, "sell_ts": None},
            book,
            buy_amount_sol=0.02,
            delay_seconds=1.5,
            penalty_bps=0,
            cost_model=None,
        )
        is None
    )
    late = copy_trip(
        {"mint": "A", "buy_ts": 19.0, "sell_ts": 20.0},
        book,
        buy_amount_sol=0.02,
        delay_seconds=1.5,
        penalty_bps=0,
        cost_model=None,
    )
    assert late is not None and late["exit_reason"] == "open_at_end"


def test_score_wallets_ranks_closed_copies_only() -> None:
    scores = score_wallets(
        _capture(), buy_amount_sol=0.02, delay_seconds=1.5, min_copies=1
    )
    ranked = [w["wallet"] for w in scores["wallets"]]
    assert ranked[0] == "Smart"
    # Dumb's sell and Other's exit fall after the last recorded price: open
    # marks are stale, so only Smart's closed copy is ranked.
    assert ranked == ["Smart"]
    assert scores["creators"] == {"Dev": 1}
    assert scores["copies"] == 1
    assert scores["copy_net_sol"] == pytest.approx(
        sum(w["copy_net_sol"] for w in scores["wallets"])
    )
    strict = score_wallets(_capture(), buy_amount_sol=0.02, min_copies=2)
    assert strict["wallets"] == [] and strict["copies"] == 1


def test_validate_wallets_against_a_random_cut_and_random_sets() -> None:
    scores = {
        "copies": 10,
        "copy_net_sol": -0.1,
        "wallets": [
            {"wallet": f"W{i}", "copies": 2, "copy_net_sol": -0.02 + 0.01 * i}
            for i in range(5)
        ],
    }
    result = validate_wallets(["W4", "W3", "gone"], scores, draws=50)
    assert result["seen"] == 2 and result["selected"] == 3
    assert result["kept"] == 4
    assert result["kept_net_sol"] == pytest.approx(0.03)
    assert result["random_cut_net_sol"] == pytest.approx(-0.04)
    assert result["random_wallets_beaten"] > 0.5
    empty = validate_wallets([], scores)
    assert empty["random_wallets_mean_sol"] is None


def test_render_wallet_scores_names_creators_and_validation() -> None:
    scores = score_wallets(_capture(), buy_amount_sol=0.02, min_copies=1)
    out = Console(record=True, width=200, file=io.StringIO())
    validation = validate_wallets(["Smart"], scores)
    render_wallet_scores(
        scores, out, top=1, validation=validation, focus=("Dumb", "Dev", "Nobody")
    )
    text = out.export_text()
    assert "Smart" in text and "Dumb" in text
    assert "Dev: no closed copy on this capture (launched 1 screened mints)" in text
    assert "Nobody: no closed copy on this capture" in text
    assert "Validation: 1/1 selected" in text
    out = Console(record=True, width=200, file=io.StringIO())
    render_wallet_scores(
        scores, out, validation={**validation, "random_wallets_beaten": None}
    )
    assert "random wallet sets" not in out.export_text()
