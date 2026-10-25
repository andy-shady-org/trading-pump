"""Tests for the trade-stream handlers (`bot/handlers/trade.py`)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.bot.handlers import trade
from pumpfun_trading.strategies.shadow import ShadowSignal, ShadowVariant
from pumpfun_trading.streams.geyser import TradeEventUpdate
from pumpfun_trading.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot, make_position


async def test_geyser_trade_on_a_held_mint_notes_the_stop_crossing(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, stop_loss=0.95, record_stop_crossings=True)
    make_position(bot, SAMPLE_MINT, entry_market_cap=30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._evaluate_and_execute_exit = AsyncMock()  # type: ignore[method-assign]
    bot._check_and_enforce_circuit_breaker = AsyncMock()  # type: ignore[method-assign]
    v_sol = 30_000_000_000  # ~27.96 SOL market cap: 93% of entry
    update = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=100_000_000,
        token_amount=1,
        is_buy=False,
        user="seller",
        timestamp=0,
        virtual_sol_reserves=v_sol,
        virtual_token_reserves=int(32_190_000_000 * 1e15 / v_sol),
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    await trade.handle_trade_event_update(bot, update)
    crossing = bot.active_positions[SAMPLE_MINT]["stop_crossings"]["trade_feed"]
    assert crossing["ratio"] == pytest.approx(0.932, rel=0.01)
    bot._evaluate_and_execute_exit.assert_awaited_once()


def _geyser_buy(mint: str, user: str = "buyer") -> TradeEventUpdate:
    return TradeEventUpdate(
        mint=mint,
        sol_amount_lamports=2_000_000_000,
        token_amount=1,
        is_buy=True,
        user=user,
        timestamp=0,
        virtual_sol_reserves=40_000_000_000,
        virtual_token_reserves=800_000_000_000_000,
        real_sol_reserves=10_000_000_000,
        real_token_reserves=0,
    )


@pytest.mark.regression("BUG-132")
async def test_geyser_trade_in_confirmed_mode_never_takes_the_legacy_spike_entry(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, entry_mode="confirmed", enable_momentum_signals=True)
    bot._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
    bot._maybe_buy_confirmed_momentum = AsyncMock(return_value=False)  # type: ignore[method-assign]
    spike = MagicMock(triggered=True, reason="spike", z_score=9.0)
    with patch.object(
        bot.order_flow_engine, "evaluate_momentum_signal", return_value=spike
    ) as legacy:
        # Not watched: nothing is bought, however strong the flow looks.
        for i in range(5):
            await trade.handle_trade_event_update(
                bot, _geyser_buy(SAMPLE_PUMP_MINT, f"u{i}")
            )
        bot._buy_token.assert_not_awaited()
        bot._maybe_buy_confirmed_momentum.assert_not_awaited()

        # Watched but not promoted yet: still nothing.
        bot.order_flow_engine.watch(SAMPLE_PUMP_MINT, created_at=0.0, now=0.0)
        await trade.handle_trade_event_update(bot, _geyser_buy(SAMPLE_PUMP_MINT))
        bot._maybe_buy_confirmed_momentum.assert_not_awaited()

        # Promoted: the confirmed pipeline decides, never the legacy spike.
        bot.order_flow_engine.mark_watch_subscribed(SAMPLE_PUMP_MINT)
        await trade.handle_trade_event_update(bot, _geyser_buy(SAMPLE_PUMP_MINT))
        bot._maybe_buy_confirmed_momentum.assert_awaited_once()
        legacy.assert_not_called()
    bot._buy_token.assert_not_awaited()
    await bot.close()


@pytest.mark.regression("BUG-132")
async def test_geyser_trade_in_launch_mode_keeps_the_legacy_spike_entry(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, entry_mode="launch", enable_momentum_signals=True)
    bot._maybe_buy_confirmed_momentum = AsyncMock()  # type: ignore[method-assign]
    quiet = MagicMock(triggered=False)
    with patch.object(
        bot.order_flow_engine, "evaluate_momentum_signal", return_value=quiet
    ) as legacy:
        await trade.handle_trade_event_update(bot, _geyser_buy(SAMPLE_PUMP_MINT))
    legacy.assert_called_once()
    bot._maybe_buy_confirmed_momentum.assert_not_awaited()
    await bot.close()


def test_note_follow_on_buy_counts_other_wallets_above_the_floor(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path, stagnant_min_buy_sol=0.1)
    make_position(bot, SAMPLE_MINT)
    bot.active_positions = bot.position_manager.get_all_positions()
    position = bot.active_positions[SAMPLE_MINT]

    trade.note_follow_on_buy(bot, SAMPLE_MINT, False, 5.0, "other", 10.0)
    trade.note_follow_on_buy(bot, SAMPLE_MINT, True, 0.01, "other", 11.0)
    trade.note_follow_on_buy(bot, SAMPLE_MINT, True, 5.0, bot._own_wallet(), 12.0)
    assert "last_qualifying_buy_at" not in position

    trade.note_follow_on_buy(bot, SAMPLE_MINT, True, 0.5, "other", 13.0)
    assert position["last_qualifying_buy_at"] == 13.0


async def test_schedule_shadow_fill_skips_past_the_pending_cap(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    signal = ShadowSignal(
        variant=ShadowVariant(name="v"),
        mint=SAMPLE_PUMP_MINT,
        signal_time=1.0,
        signal_market_cap_sol=30.0,
        entry_metrics={},
    )
    with patch.object(trade, "MAX_PENDING_SHADOW_FILLS", 0):
        trade.schedule_shadow_fill(bot, signal)
    assert bot.watch_list_status()["stats"]["shadow_skipped"] == 1
    assert not getattr(bot, "_shadow_fill_tasks", set())


@pytest.mark.parametrize(
    ("method", "function", "args", "kwargs"),
    [
        ("_handle_trade_event_update", "handle_trade_event_update", ("u",), {}),
        ("_handle_trade_update", "handle_trade_update", ({"mint": "m"}, None), {}),
        (
            "_maybe_buy_confirmed_momentum",
            "maybe_buy_confirmed_momentum",
            (SAMPLE_MINT, 40.0, "Token"),
            {"now": 1.0},
        ),
        ("_record_shadow_fill", "record_shadow_fill", ("shadow",), {}),
    ],
)
async def test_async_bot_methods_delegate_to_trade_handlers(
    tmp_path: Path,
    method: str,
    function: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    bot = make_bot(tmp_path)
    handler = AsyncMock(return_value="result")
    with patch.object(trade, function, handler):
        result = await getattr(bot, method)(*args, **kwargs)
    handler.assert_awaited_once_with(bot, *args, **kwargs)
    if method == "_maybe_buy_confirmed_momentum":
        assert result == "result"


@pytest.mark.parametrize(
    ("method", "function", "args", "kwargs"),
    [
        (
            "_note_follow_on_buy",
            "note_follow_on_buy",
            (SAMPLE_MINT, True, 1.0, "u", 2.0),
            {},
        ),
        (
            "_evaluate_shadow_variants",
            "evaluate_shadow_variants",
            (SAMPLE_MINT, 30.0),
            {"now": 1.0},
        ),
        ("_schedule_shadow_fill", "schedule_shadow_fill", ("shadow",), {}),
    ],
)
def test_sync_bot_methods_delegate_to_trade_handlers(
    tmp_path: Path,
    method: str,
    function: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    bot = make_bot(tmp_path)
    handler = MagicMock()
    with patch.object(trade, function, handler):
        getattr(bot, method)(*args, **kwargs)
    handler.assert_called_once_with(bot, *args, **kwargs)


def _polled(real_sol: float) -> dict[str, Any]:
    real = int(real_sol * 1e9)
    v_sol = 30_000_000_000 + real
    return {
        "virtual_sol_reserves": v_sol,
        "virtual_token_reserves": int(30_000_000_000 * 1_073_000_000_000_000 / v_sol),
        "real_sol_reserves": real,
        "complete": False,
    }


def _shadow_rows(recorder: MagicMock) -> list[dict[str, Any]]:
    return [
        call.args[0]
        for call in recorder.record_snapshot.call_args_list
        if call.args[0].get("event") == "shadow_entry"
    ]


async def test_watch_polls_feed_pullback_curve_variants(tmp_path: Path) -> None:
    from pumpfun_trading.strategies.filters import (
        HolderDistribution,
        TokenScreeningVerdict,
    )

    bot = make_bot(
        tmp_path,
        entry_mode="confirmed",
        paper_entry_delay_seconds=0.0,
        watch_promote_min_sol_growth=500.0,  # no trade subscriptions
        shadow_variants=(
            {
                "name": "pbc",
                "kind": "pullback_curve",
                "pullback_min_token_age_seconds": 0,
                "pullback_window_seconds": 6,
                "pullback_min_peak_market_cap_sol": 35,
            },
        ),
    )
    recorder = MagicMock()
    bot.replay_recorder = recorder
    verdict = TokenScreeningVerdict(
        mint=SAMPLE_PUMP_MINT,
        passed=True,
        risk_score=0.0,
        holder_distribution=HolderDistribution(
            total_supply=100, top_holders=[("A", 10), ("B", 5)]
        ),
    )
    bot.order_flow_engine.watch(
        SAMPLE_PUMP_MINT, created_at=0.0, creator="Dev", verdict=verdict, now=0.0
    )
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value=_polled(10.0)
    )
    # Pump to ~20 SOL real, dump to 8, base for 10 s, then buying returns.
    path = [(10.0, 20.0), (12.0, 8.0), (18.0, 8.1), (22.0, 8.6)]
    for ts, real_sol in path:
        bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
            return_value={SAMPLE_PUMP_MINT: _polled(real_sol)}
        )
        with patch("pumpfun_trading.bot.handlers.watch.time.time", return_value=ts):
            await bot._poll_watch_list()
    await asyncio.gather(*list(getattr(bot, "_shadow_fill_tasks", ())))

    rows = _shadow_rows(recorder)
    assert [row["variant"] for row in rows] == ["pbc"]
    assert rows[0]["kind"] == "pullback_curve"
    assert rows[0]["signal_timestamp"] == 22.0
    metrics = rows[0]["entry_metrics"]
    assert metrics["curve_inflow_sol"] == pytest.approx(0.6, abs=1e-6)
    assert metrics["early_holders"] == 2  # FEAT-61 from the screening verdict


def test_curve_variants_need_a_capture_confirmed_mode_and_a_known_mint(
    tmp_path: Path,
) -> None:
    variants = ({"name": "pbc", "kind": "pullback_curve"},)
    bot = make_bot(tmp_path, entry_mode="confirmed", shadow_variants=variants)
    trade.evaluate_shadow_curve(bot, SAMPLE_PUMP_MINT, 40.0, 10.0, now=1.0)
    assert bot._shadow_book() is None or not bot._shadow_book().knows(  # type: ignore[union-attr]
        SAMPLE_PUMP_MINT
    )

    bot.replay_recorder = MagicMock()
    trade.evaluate_shadow_curve(bot, "never_watched", 40.0, 10.0, now=1.0)
    book = bot._shadow_book()
    assert book is not None and not book.knows("never_watched")

    # A mint seen before stays evaluated after its watch entry is gone.
    bot.order_flow_engine.watch(SAMPLE_PUMP_MINT, created_at=0.0)
    trade.evaluate_shadow_curve(bot, SAMPLE_PUMP_MINT, 40.0, 10.0, now=1.0)
    bot.order_flow_engine.unwatch(SAMPLE_PUMP_MINT)
    trade.evaluate_shadow_curve(bot, SAMPLE_PUMP_MINT, 41.0, 10.1, now=3.0)
    assert book.knows(SAMPLE_PUMP_MINT)
    assert len(book._mints[SAMPLE_PUMP_MINT].curve) == 2

    plain = make_bot(tmp_path, entry_mode="confirmed")
    plain.replay_recorder = MagicMock()
    trade.evaluate_shadow_curve(plain, SAMPLE_PUMP_MINT, 40.0, 10.0, now=1.0)
    assert plain._shadow_book() is None


async def test_momentum_buys_record_buy_timing_and_the_bundle_proxy(
    tmp_path: Path,
) -> None:
    from pumpfun_trading.strategies.filters import (
        HolderDistribution,
        TokenScreeningVerdict,
    )

    bot = make_bot(tmp_path, entry_mode="confirmed")
    verdict = TokenScreeningVerdict(
        mint=SAMPLE_PUMP_MINT,
        passed=True,
        risk_score=0.0,
        holder_distribution=HolderDistribution(
            total_supply=100, top_holders=[("A", 10)]
        ),
    )
    now = 1_000.0
    bot.order_flow_engine.watch(SAMPLE_PUMP_MINT, created_at=now - 120, verdict=verdict)
    for i, user in enumerate(("a", "b", "c")):
        bot.order_flow_engine.record_trade(
            SAMPLE_PUMP_MINT, True, 0.5, user, timestamp=now - 10 + 3 * i
        )
    bot.strategy.should_buy_momentum = MagicMock(return_value=True)  # type: ignore[method-assign]
    bot._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]

    assert await trade.maybe_buy_confirmed_momentum(
        bot, SAMPLE_PUMP_MINT, 50.0, "Tok", now=now
    )

    metrics = bot._buy_token.await_args_list[0].kwargs["entry_metrics"]
    assert metrics["timing_buys"] == 3
    assert metrics["buy_gap_cv"] == 0.0 and metrics["buy_gap_median_seconds"] == 3.0
    assert {"burst_share", "buy_size_cv", "small_buy_share"} <= set(metrics)
    assert metrics["early_holders"] == 1 and metrics["early_holder_pct"] == 0.1


@pytest.mark.regression("BUG-147")
async def test_trade_feed_never_prices_a_migrated_position(tmp_path: Path) -> None:
    # rc.5 showed a coin at 3,603 SOL (+877%) from PumpPortal's post-migration
    # trade market cap while its PumpSwap pool was worth 18 SOL.
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_PUMP_MINT, entry_market_cap=410.88)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._migrating_mints.add(SAMPLE_PUMP_MINT)
    bot._evaluate_and_execute_exit = AsyncMock()  # type: ignore[method-assign]
    bot.execution.get_bonding_curve_state = AsyncMock()  # type: ignore[method-assign]

    await trade.handle_trade_update(
        bot,
        {
            "mint": SAMPLE_PUMP_MINT,
            "txType": "buy",
            "solAmount": 1.0,
            "marketCapSol": 3603.93,
            "traderPublicKey": "Buyer1",
        },
    )

    bot._evaluate_and_execute_exit.assert_not_awaited()
    bot.execution.get_bonding_curve_state.assert_not_awaited()
    position = bot.active_positions[SAMPLE_PUMP_MINT]
    assert float(position.get("current_market_cap") or 0.0) == pytest.approx(410.88)

    update = TradeEventUpdate(
        mint=SAMPLE_PUMP_MINT,
        sol_amount_lamports=100_000_000,
        token_amount=1,
        is_buy=True,
        user="buyer",
        timestamp=0,
        virtual_sol_reserves=40_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    await trade.handle_trade_event_update(bot, update)
    bot._evaluate_and_execute_exit.assert_not_awaited()
