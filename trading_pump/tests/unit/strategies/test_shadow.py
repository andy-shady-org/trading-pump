"""Unit tests for ``strategies/shadow.py`` (FEAT-58 shadow variants)."""

from __future__ import annotations

from typing import Any

import pytest

from trading_pump.strategies.momentum import OrderFlowEngine
from trading_pump.strategies.shadow import (
    ShadowSignal,
    ShadowVariant,
    ShadowVariantBook,
    parse_shadow_variants,
    shadow_fill_record,
    variant_config,
)
from trading_pump.tests.support.factories import make_config

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


# --- FEAT-59 pullback variants and FEAT-60/61 filters ---------------------


def _pullback_book(**rule: Any) -> ShadowVariantBook:
    variants = parse_shadow_variants(
        [
            {
                "name": "pb",
                "kind": "pullback",
                "pullback_min_token_age_seconds": 0,
                **rule,
            }
        ]
    )
    book = ShadowVariantBook(_config(), variants)
    book.remember(MINT, created_at=0.0, creator="Dev")
    return book


def _trade(
    engine: OrderFlowEngine,
    book: ShadowVariantBook,
    ts: float,
    mc: float,
    *,
    user: str = "W",
    buy: bool = True,
    sol: float = 0.3,
) -> list[ShadowSignal]:
    engine.record_trade(MINT, buy, sol, user, timestamp=ts)
    return book.evaluate(engine, MINT, now=ts, market_cap_sol=mc)


def test_parse_reads_pullback_kinds_with_defaults() -> None:
    trade, curve = parse_shadow_variants(
        [
            {"name": "pb", "kind": "pullback", "pullback_min_drawdown_pct": 0.4},
            {"name": "pbc", "kind": "PULLBACK_CURVE"},
        ]
    )
    assert trade.kind == "pullback" and curve.kind == "pullback_curve"
    assert trade.pullback["pullback_min_drawdown_pct"] == 0.4
    assert trade.pullback["pullback_min_base_seconds"] == 10.0  # default kept
    data = trade.to_dict()
    assert data["kind"] == "pullback" and data["pullback_min_drawdown_pct"] == 0.4
    assert "kind" not in parse_shadow_variants([{"name": "m"}])[0].to_dict()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"kind": "dip"}, "kind must be one of"),
        ({"pullback_min_drawdown_pct": 0.3}, 'needs "kind"'),
        ({"kind": "pullback", "pullback_min_drawdown_pct": "x"}, "must be a number"),
        ({"kind": "pullback", "pullback_min_drawdown_pct": True}, "must be a number"),
        ({"kind": "pullback", "pullback_window_seconds": -1}, "must not be negative"),
        ({"kind": "pullback", "momentum_min_unique_buyers": 5}, "momentum threshold"),
        ({"kind": "pullback", "pullback_max_drawdown_pct": 0.2}, "drawdown_pct <"),
        ({"kind": "pullback", "pullback_max_drawdown_pct": 1.0}, "drawdown_pct <"),
    ],
)
def test_parse_refuses_invalid_pullback_variants(
    raw: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_shadow_variants([{"name": "bad", **raw}])


def test_pullback_fires_after_the_dump_once_a_base_holds_and_buying_returns() -> None:
    engine = OrderFlowEngine()
    book = _pullback_book()
    assert _trade(engine, book, 10.0, 30.0) == []
    assert _trade(engine, book, 20.0, 60.0) == []  # the pump: new peak
    assert _trade(engine, book, 21.0, 38.0, user="S", buy=False, sol=2.0) == []
    assert _trade(engine, book, 22.0, 36.0, user="S", buy=False, sol=0.5) == []
    # Off the low but the base is only 8 s old.
    assert _trade(engine, book, 30.0, 38.0, user="A") == []
    # Base held, but the 15 s window still holds the dump: net outflow.
    assert _trade(engine, book, 36.0, 38.0, user="B") == []
    # 5% off the low, 0.9 SOL in from 3 wallets over the last 15 s: fires.
    fired = _trade(engine, book, 40.0, 38.0, user="C")
    assert len(fired) == 1
    metrics = fired[0].entry_metrics
    assert metrics["kind"] == "pullback"
    assert metrics["peak_market_cap_sol"] == 60.0
    assert metrics["low_market_cap_sol"] == 36.0
    assert metrics["drawdown_pct"] == pytest.approx(1 - 38.0 / 60.0, abs=1e-4)
    assert metrics["base_seconds"] == 18.0
    assert metrics["unique_buyers"] == 3
    assert "burst_share" in metrics and "top_buyer_share" in metrics
    # Fires once per mint.
    assert _trade(engine, book, 41.0, 38.0, user="D") == []


@pytest.mark.parametrize(
    ("rule", "fires"),
    [
        ({}, True),  # control: the same path fires with the defaults
        ({"pullback_min_peak_market_cap_sol": 70.0}, False),  # pump too small
        ({"pullback_min_drawdown_pct": 0.5}, False),  # not deep enough
        ({"pullback_min_drawdown_pct": 0.1, "pullback_max_drawdown_pct": 0.3}, False),
        ({"pullback_min_net_inflow_sol": 5.0}, False),  # no demand back
        ({"pullback_min_unique_buyers": 9}, False),
        ({"pullback_max_token_age_seconds": 30.0}, False),  # too old
        ({"pullback_min_rebound_pct": 0.5}, False),  # still on the low
        ({"pullback_min_base_seconds": 30.0}, False),  # base too short
    ],
)
def test_pullback_needs_every_condition(rule: dict[str, float], fires: bool) -> None:
    engine = OrderFlowEngine()
    book = _pullback_book(**rule)
    _trade(engine, book, 20.0, 60.0)
    _trade(engine, book, 22.0, 36.0, user="S", buy=False, sol=2.0)
    signals: list[ShadowSignal] = []
    for ts, user in ((30.0, "A"), (36.0, "B"), (40.0, "C")):
        signals += _trade(engine, book, ts, 38.0, user=user)
    assert bool(signals) is fires


def test_pullback_curve_runs_on_curve_reads_only() -> None:
    variants = parse_shadow_variants(
        [
            {"name": "baseline"},
            {
                "name": "pbc",
                "kind": "pullback_curve",
                "pullback_min_token_age_seconds": 0,
                "pullback_window_seconds": 6,
            },
        ]
    )
    engine = OrderFlowEngine()
    book = ShadowVariantBook(_config(), variants)
    book.remember(MINT, created_at=0.0, creator=None)
    # A trade never evaluates the curve variant.
    engine.record_trade(MINT, True, 0.5, "W", timestamp=5.0)
    assert book.evaluate(engine, MINT, now=5.0, market_cap_sol=60.0) == []
    reads = [(10.0, 36.0, 10.0), (14.0, 36.0, 10.0), (18.0, 37.0, 10.2)]
    for ts, mc, real in reads:
        assert (
            book.evaluate(engine, MINT, now=ts, market_cap_sol=mc, real_sol=real) == []
        )
    fired = book.evaluate(engine, MINT, now=22.0, market_cap_sol=38.0, real_sol=10.6)
    assert [s.variant.name for s in fired] == ["pbc"]
    metrics = fired[0].entry_metrics
    assert metrics["kind"] == "pullback_curve"
    assert metrics["curve_inflow_sol"] == pytest.approx(0.6)
    assert "unique_buyers" not in metrics


def test_curve_history_is_bounded_and_needs_the_full_window() -> None:
    variants = parse_shadow_variants(
        [{"name": "pbc", "kind": "pullback_curve", "pullback_min_token_age_seconds": 0}]
    )
    book = ShadowVariantBook(_config(), variants)
    book.remember(MINT, created_at=0.0, creator=None)
    context = book._mints[MINT]
    assert context.curve_inflow(15.0, 0.0) is None
    for ts in range(0, 400, 10):
        context.observe_curve(float(ts), float(ts))
    assert context.curve[0][0] >= 390 - 300
    assert context.curve_inflow(15.0, 390.0) == pytest.approx(20.0)
    assert context.curve_inflow(1_000.0, 390.0) is None


@pytest.mark.parametrize(
    ("filters", "fires"),
    [
        ({"max_burst_share": 0.5}, False),  # all buys inside 5 s
        ({"min_buy_gap_cv": 5.0}, False),
        ({"min_buy_size_cv": 0.5}, False),  # identical sizes: a bot
        ({"max_small_buy_share": 0.5}, True),
        ({"max_early_holders": 2}, False),
        ({"max_early_holder_pct": 0.5}, True),
    ],
)
def test_timing_and_bundle_filters_gate_a_variant(
    filters: dict[str, float], fires: bool
) -> None:
    variants = parse_shadow_variants([{"name": "f", **filters}])
    engine = OrderFlowEngine()
    book = ShadowVariantBook(_config(), variants)
    book.remember(
        MINT,
        created_at=0.0,
        creator=None,
        static_metrics={"early_holders": 4, "early_holder_pct": 0.2},
    )
    end = _buys(engine, ["A", "B", "C"])
    signals = book.evaluate(engine, MINT, now=end, market_cap_sol=40.0)
    assert bool(signals) is fires
    if fires:
        assert signals[0].entry_metrics["early_holders"] == 4


def test_missing_metrics_leave_their_filter_unapplied() -> None:
    variants = parse_shadow_variants(
        [{"name": "f", "min_buy_gap_cv": 0.5, "max_early_holder_pct": 0.1}]
    )
    engine = OrderFlowEngine()
    book = ShadowVariantBook(_config(momentum_min_unique_buyers=2), variants)
    book.remember(MINT, created_at=0.0, creator=None)
    end = _buys(engine, ["A", "B"])  # two buys: no gap statistics, no holders
    assert len(book.evaluate(engine, MINT, now=end, market_cap_sol=40.0)) == 1


def test_shadow_fill_record_names_the_kind_of_non_momentum_variants() -> None:
    variant = parse_shadow_variants([{"name": "pb", "kind": "pullback"}])[0]
    signal = ShadowSignal(
        variant=variant,
        mint=MINT,
        signal_time=1.0,
        signal_market_cap_sol=40.0,
        entry_metrics={},
    )
    record = shadow_fill_record(signal, fill_market_cap_sol=41.0, fill_time=2.5)
    assert record["kind"] == "pullback" and record["variant"] == "pb"
