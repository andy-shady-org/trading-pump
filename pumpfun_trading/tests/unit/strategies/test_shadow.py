"""Unit tests for ``strategies/shadow.py`` (FEAT-58 shadow variants)."""

from __future__ import annotations

from typing import Any

import pytest

from pumpfun_trading.strategies.momentum import OrderFlowEngine
from pumpfun_trading.strategies.shadow import (
    ShadowSignal,
    ShadowVariant,
    ShadowVariantBook,
    parse_shadow_variants,
    shadow_fill_record,
    variant_config,
)
from pumpfun_trading.tests.support.factories import make_config

MINT = "ShadowMint"


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "entry_mode": "confirmed",
        "momentum_window_seconds": 30,
        "momentum_min_unique_buyers": 3,
        "momentum_min_buy_ratio": 1.0,
        "momentum_min_z_score": -100.0,
        "momentum_min_net_inflow_sol": 0.1,
        "momentum_min_token_age_seconds": 0.0,
        "momentum_max_token_age_seconds": 3600,
        "min_market_cap_sol": 1.0,
        "momentum_max_market_cap_sol": 500.0,
    }
    base.update(overrides)
    return make_config(**base)


def _buys(engine: OrderFlowEngine, users: list[str], *, start: float = 100.0) -> float:
    ts = start
    for user in users:
        engine.record_trade(MINT, True, 0.5, user, timestamp=ts)
        ts += 1.0
    return ts


def test_parse_reads_overrides_drift_and_flow_filters() -> None:
    variants = parse_shadow_variants(
        [
            {"name": "baseline"},
            {
                "name": "buyers8_drift5",
                "momentum_min_unique_buyers": 8,
                "max_entry_drift_pct": 0.05,
                "max_top_buyer_share": 0.4,
                "min_wallet_diversity": 0.3,
            },
        ]
    )

    assert [v.name for v in variants] == ["baseline", "buyers8_drift5"]
    strict = variants[1]
    assert strict.overrides == {"momentum_min_unique_buyers": 8}
    assert strict.max_entry_drift_pct == 0.05
    assert strict.flow_filters == {
        "max_top_buyer_share": 0.4,
        "min_wallet_diversity": 0.3,
    }
    assert strict.to_dict()["max_entry_drift_pct"] == 0.05
    assert variants[0].to_dict() == {"name": "baseline"}
    assert parse_shadow_variants(None) == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (["not a dict"], "JSON objects"),
        ([{"name": ""}], "name"),
        ([{"name": "x" * 41}], "name"),
        ([{"name": "a", "stop_loss": 0.5}], "unknown key"),
        # The bot's own drift guard is set with max_entry_drift_pct instead.
        ([{"name": "a", "momentum_max_entry_drift_pct": 0.1}], "unknown key"),
        ([{"name": "a", "momentum_min_unique_buyers": "8"}], "must be a number"),
        ([{"name": "a", "max_entry_drift_pct": -0.1}], "negative"),
        ([{"name": "a"}, {"name": "a"}], "unique"),
    ],
)
def test_parse_refuses_invalid_variants(raw: list[Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_shadow_variants(raw)


def test_variant_config_types_overrides_like_the_base_field() -> None:
    config = _config()
    variant = ShadowVariant(
        name="v",
        overrides={"momentum_min_unique_buyers": 8.0, "momentum_min_buy_ratio": 2},
    )

    typed = variant_config(config, variant)

    assert typed.momentum_min_unique_buyers == 8
    assert isinstance(typed.momentum_min_unique_buyers, int)
    assert typed.momentum_min_buy_ratio == 2.0
    assert isinstance(typed.momentum_min_buy_ratio, float)
    assert config.momentum_min_unique_buyers == 3  # the bot's config is untouched
    flag = ShadowVariant(name="f", overrides={"enable_momentum_signals": 0})
    # Bool fields are coerced as bools (only reachable through the API).
    assert variant_config(config, flag).enable_momentum_signals is False


def test_each_variant_fires_once_per_mint_at_its_own_threshold() -> None:
    engine = OrderFlowEngine()
    book = ShadowVariantBook(
        _config(),
        parse_shadow_variants(
            [{"name": "b3"}, {"name": "b6", "momentum_min_unique_buyers": 6}]
        ),
    )
    assert book.enabled
    book.remember(MINT, created_at=0.0, creator="Dev")
    book.remember(MINT, created_at=50.0, creator="Other")  # first context wins
    assert book.tracked_mints == 1

    now = _buys(engine, ["a", "b", "c"])
    fired = book.evaluate(engine, MINT, now=now, market_cap_sol=40.0)
    assert [s.variant.name for s in fired] == ["b3"]
    assert fired[0].entry_metrics["unique_buyers"] == 3
    assert fired[0].entry_metrics["token_age_seconds"] == pytest.approx(now)
    assert {"top_buyer_share", "round_trip_share", "quick_flips"} <= set(
        fired[0].entry_metrics
    )

    now = _buys(engine, ["d", "e", "f"], start=now)
    fired = book.evaluate(engine, MINT, now=now, market_cap_sol=45.0)
    assert [s.variant.name for s in fired] == ["b6"]
    assert book.evaluate(engine, MINT, now=now + 1, market_cap_sol=45.0) == []


def test_creator_and_excluded_wallets_do_not_count_as_buyers() -> None:
    engine = OrderFlowEngine()
    book = ShadowVariantBook(_config(), parse_shadow_variants([{"name": "b3"}]))
    book.remember(MINT, created_at=0.0, creator="Dev")
    now = _buys(engine, ["Dev", "Bot", "a", "b"])

    assert (
        book.evaluate(
            engine,
            MINT,
            now=now,
            market_cap_sol=40.0,
            exclude_users=frozenset({"Bot"}),
        )
        == []
    )


def test_unknown_mints_and_unpriced_trades_are_skipped() -> None:
    engine = OrderFlowEngine()
    book = ShadowVariantBook(_config(), parse_shadow_variants([{"name": "b3"}]))
    now = _buys(engine, ["a", "b", "c"])

    assert book.evaluate(engine, MINT, now=now, market_cap_sol=40.0) == []
    book.remember(MINT, created_at=0.0, creator=None)
    assert book.knows(MINT)
    assert book.evaluate(engine, MINT, now=now, market_cap_sol=0.0) == []
    book.forget(MINT)
    assert not book.knows(MINT)
    assert not ShadowVariantBook(_config(), ()).enabled


@pytest.mark.parametrize(
    ("filters", "fires"),
    [
        ({"max_top_buyer_share": 0.8}, True),
        ({"max_top_buyer_share": 0.5}, False),  # one whale bought 70%
        ({"min_wallet_diversity": 0.9}, False),
        ({"max_round_trip_share": 0.0}, True),
        ({"max_quick_flips": 0}, True),
    ],
)
def test_flow_filters_gate_a_variant(filters: dict[str, float], fires: bool) -> None:
    engine = OrderFlowEngine()
    engine.record_trade(MINT, True, 7.0, "whale", timestamp=100.0)
    engine.record_trade(MINT, True, 1.5, "a", timestamp=101.0)
    engine.record_trade(MINT, True, 1.5, "b", timestamp=102.0)
    book = ShadowVariantBook(
        _config(), parse_shadow_variants([{"name": "f", **filters}])
    )
    book.remember(MINT, created_at=0.0, creator=None)

    fired = book.evaluate(engine, MINT, now=102.0, market_cap_sol=40.0)

    assert bool(fired) is fires


def test_book_forgets_the_oldest_mint_when_full() -> None:
    book = ShadowVariantBook(
        _config(), parse_shadow_variants([{"name": "b3"}]), max_mints=2
    )
    for mint in ("m1", "m2", "m3"):
        book.remember(mint, created_at=0.0, creator=None)

    assert not book.knows("m1")
    assert book.knows("m2") and book.knows("m3")


def _signal(drift_limit: float = 0.0) -> ShadowSignal:
    return ShadowSignal(
        variant=ShadowVariant(name="v", max_entry_drift_pct=drift_limit),
        mint=MINT,
        signal_time=100.0,
        signal_market_cap_sol=40.0,
        entry_metrics={"unique_buyers": 3},
    )


def test_shadow_fill_record_prices_the_fill_and_applies_the_variant_guard() -> None:
    filled = shadow_fill_record(
        _signal(0.10), fill_market_cap_sol=42.0, fill_time=101.5
    )
    assert filled["event"] == "shadow_entry"
    assert filled["variant"] == "v"
    assert filled["fill_drift_pct"] == pytest.approx(0.05)
    assert "refused" not in filled
    # No price key: replay never reads it as market data.
    assert "price" not in filled and "market_cap_sol" not in filled

    refused = shadow_fill_record(_signal(0.03), fill_market_cap_sol=42.0, fill_time=1)
    assert refused["refused"] == "entry_drift"

    missing = shadow_fill_record(_signal(), fill_market_cap_sol=None, fill_time=1)
    assert missing["refused"] == "no_curve"
    errored = shadow_fill_record(
        _signal(), fill_market_cap_sol=0.0, fill_time=1, error="curve_error: X"
    )
    assert errored["refused"] == "curve_error: X"
