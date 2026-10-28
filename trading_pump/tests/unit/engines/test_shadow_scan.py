"""Unit tests for ``engines/shadow_scan.py`` (offline shadow variants)."""

from __future__ import annotations

from typing import Any

import pytest

from trading_pump.engines.shadow_report import build_shadow_report
from trading_pump.engines.shadow_scan import (
    FILL_WINDOW_SECONDS,
    scan_shadow_entries,
    with_scanned_entries,
)
from trading_pump.tests.support.factories import make_config

MINT = "ScanMint"


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "entry_mode": "confirmed",
        "paper_entry_delay_seconds": 1.5,
        "momentum_window_seconds": 30,
        "momentum_min_unique_buyers": 3,
        "momentum_min_buy_ratio": 1.0,
        "momentum_min_z_score": -100.0,
        "momentum_min_net_inflow_sol": 0.1,
        "momentum_min_token_age_seconds": 0.0,
        "momentum_max_token_age_seconds": 3600,
        "min_market_cap_sol": 1.0,
        "momentum_max_market_cap_sol": 500.0,
        "shadow_variants": ({"name": "baseline"},),
    }
    base.update(overrides)
    return make_config(**base)


def _trade(ts: float, user: str, mc: float, *, buy: bool = True) -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": MINT,
        "price": mc / 1e9,
        "market_cap_sol": mc,
        "is_buy": buy,
        "sol_amount": 0.5,
        "user": user,
        "signal": "buy" if buy else "sell",
    }


def _poll(ts: float, mc: float, real: float, source: str = "watch") -> dict[str, Any]:
    return {
        "timestamp": ts,
        "mint": MINT,
        "event": "curve_poll",
        "source": source,
        "price": mc / 1e9,
        "market_cap_sol": mc,
        "real_sol_reserves": real,
    }


def _capture() -> list[dict[str, Any]]:
    return [
        {"timestamp": 0.0, "mint": MINT, "market_cap_sol": 28.0, "price": 2.8e-8},
        {
            "timestamp": 0.5,
            "mint": MINT,
            "event": "screening",
            "screening": {
                "creator": "Dev",
                "early_holders": 3,
                "early_holder_pct": 0.1,
            },
        },
        _trade(10.0, "Dev", 30.0),  # the creator never counts as a buyer
        _trade(11.0, "A", 31.0),
        _trade(12.0, "B", 32.0),
        _trade(13.0, "C", 33.0),  # third buyer: the baseline fires here
        _poll(14.0, 34.0, 4.0, source="position"),  # the fill: first read >= 14.5
        _poll(14.6, 35.0, 4.2),
        # A recorded row that the scan replaces, and one of the bot's fills.
        {"timestamp": 15.0, "mint": MINT, "event": "shadow_entry", "variant": "old"},
        {"timestamp": 15.0, "mint": MINT, "price": 3.5e-8, "reason": "momentum"},
    ]


def test_scan_writes_the_rows_the_bot_would_have_written() -> None:
    rows = scan_shadow_entries(_capture(), _config())

    assert len(rows) == 1
    row = rows[0]
    assert row["event"] == "shadow_entry" and row["variant"] == "baseline"
    assert row["scanned"] is True
    assert row["signal_timestamp"] == 13.0
    assert row["signal_market_cap_sol"] == 33.0
    # Due at 14.5: the first recorded price at or after it is the 14.6 poll.
    assert row["timestamp"] == 14.6
    assert row["fill_market_cap_sol"] == 35.0
    assert row["fill_drift_pct"] == pytest.approx(35.0 / 33.0 - 1, abs=1e-4)
    metrics = row["entry_metrics"]
    assert metrics["unique_buyers"] == 3
    assert metrics["early_holders"] == 3  # FEAT-61 from the screening record
    assert metrics["token_age_seconds"] == 13.0  # age from the create row


def test_scan_never_fills_from_record_only_observation_polls() -> None:
    capture = _capture()
    # An rc.3 observation poll right after the due time: the live shadow fill
    # never sees it, so the fill is still the 14.6 watch poll.
    capture.insert(5, _poll(14.55, 99.0, 9.0, source="discovery"))
    (row,) = scan_shadow_entries(capture, _config())
    assert row["timestamp"] == 14.6 and row["fill_market_cap_sol"] == 35.0


def test_scan_refuses_a_fill_with_no_recorded_price_in_time() -> None:
    capture = [r for r in _capture() if r.get("event") != "curve_poll"]
    capture.append(_trade(14.5 + FILL_WINDOW_SECONDS + 1.0, "D", 40.0))

    rows = scan_shadow_entries(capture, _config())

    assert rows[0]["refused"] == "no_curve"
    assert rows[0]["timestamp"] == 14.5


def test_scan_runs_pullback_curve_variants_on_watch_polls() -> None:
    config = _config(
        shadow_variants=(
            {
                "name": "pbc",
                "kind": "pullback_curve",
                "pullback_min_token_age_seconds": 0,
                "pullback_window_seconds": 6,
            },
        )
    )
    capture = [
        _poll(10.0, 60.0, 20.0),
        _poll(12.0, 36.0, 10.0),
        _poll(18.0, 36.5, 10.1),
        _poll(22.0, 38.0, 10.5),  # base 10 s, 5% off the low, +0.4 SOL in 6 s
        _poll(24.0, 38.5, 10.6),
        _poll(26.0, 39.0, 10.7, source="position"),  # never evaluated
    ]

    rows = scan_shadow_entries(capture, config)

    assert [r["variant"] for r in rows] == ["pbc"]
    assert rows[0]["kind"] == "pullback_curve"
    assert rows[0]["signal_timestamp"] == 22.0
    assert rows[0]["fill_market_cap_sol"] == 38.5  # the 24.0 read
    # Without a create row the mint's age starts at its first event.
    assert rows[0]["entry_metrics"]["token_age_seconds"] == 12.0


def test_scan_needs_variants_and_replaces_recorded_rows() -> None:
    assert scan_shadow_entries(_capture(), _config(shadow_variants=())) == []
    explicit = scan_shadow_entries(_capture(), _config(), variants=[{"name": "x"}])
    assert [r["variant"] for r in explicit] == ["x"]

    merged = with_scanned_entries(_capture(), _config())
    shadow = [r for r in merged if r.get("event") == "shadow_entry"]
    assert [r["variant"] for r in shadow] == ["baseline"]
    assert len(merged) == len(_capture())  # one recorded row out, one scanned in


def test_scanned_rows_feed_the_shadow_report() -> None:
    config = _config()
    report = build_shadow_report(
        with_scanned_entries(_capture(), config), config, cost_model=None
    )
    stats = report["variants"]["baseline"]["segments"]["all"]
    assert stats["signals"] == 1 and stats["positions"] == 1
    assert "old" not in report["variants"]
