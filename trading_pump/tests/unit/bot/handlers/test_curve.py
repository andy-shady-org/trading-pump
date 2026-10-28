"""Tests for the bonding-curve handlers (`bot/handlers/curve.py`)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from trading_pump.bot.handlers import curve
from trading_pump.streams.geyser import CompleteEventUpdate
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_bot, make_position
from trading_pump.tests.support.fakes import FakeCurves


def _launch_curve() -> dict[str, Any]:
    v_sol = 30_000_000_000
    return {
        "virtual_sol_reserves": v_sol,
        "virtual_token_reserves": int(32_190_000_000 * 1e15 / v_sol),
        "real_sol_reserves": 0,
        "complete": False,
    }


def test_curve_market_cap_handles_complete_and_raw_curves() -> None:
    assert curve.curve_market_cap(None) is None
    assert curve.curve_market_cap({"complete": True, "market_cap_sol": 5.0}) is None
    assert curve.curve_market_cap({"market_cap_sol": 42.0}) == 42.0
    # 30 SOL / 1.073e9 tokens at launch: ~28 SOL market cap.
    assert curve.curve_market_cap(_launch_curve()) == pytest.approx(27.96, rel=0.01)
    assert curve.curve_market_cap({"virtual_sol_reserves": 0}) is None


async def test_complete_event_marks_held_mint_migrating_and_sells(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._exit_retry_queue[SAMPLE_MINT] = {"reason": "stale"}  # type: ignore[assignment]
    bot._sell_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
    update = CompleteEventUpdate(
        mint=SAMPLE_MINT,
        bonding_curve="curve111",
        user="creator",
        timestamp=int(time.time()),
        slot=1,
    )

    await curve.handle_complete_event_update(bot, update)

    assert SAMPLE_MINT in bot._migrating_mints
    assert SAMPLE_MINT not in bot._exit_retry_queue
    bot._sell_token.assert_awaited_once_with(
        SAMPLE_MINT, reason="bonding_curve_graduated"
    )
    assert bot._last_event == f"graduated {SAMPLE_MINT[:8]}"


async def test_complete_event_is_ignored_after_shutdown(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._stop_requested = True
    bot._sell_token = AsyncMock()  # type: ignore[method-assign]
    update = CompleteEventUpdate(
        mint=SAMPLE_MINT, bonding_curve="c", user="u", timestamp=1, slot=1
    )
    await curve.handle_complete_event_update(bot, update)
    bot._sell_token.assert_not_awaited()
    assert SAMPLE_MINT not in bot._migrating_mints


async def test_refresh_exits_a_held_curve_that_completed(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
        return_value={SAMPLE_MINT: {"complete": True}}
    )
    bot._exit_graduated_position = AsyncMock(  # type: ignore[method-assign]
        return_value=True
    )
    await curve.refresh_active_positions_market_caps(bot)
    bot._exit_graduated_position.assert_awaited_once_with(SAMPLE_MINT)


async def test_refresh_notes_the_first_stop_crossing_only_when_asked(
    tmp_path: Path,
) -> None:
    for record in (False, True):
        bot = make_bot(tmp_path, stop_loss=0.95, record_stop_crossings=record)
        make_position(bot, SAMPLE_MINT, entry_market_cap=30.0)
        bot.active_positions = bot.position_manager.get_all_positions()
        bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
            return_value={SAMPLE_MINT: _launch_curve()}  # ~27.96 SOL: 93% of entry
        )
        bot._evaluate_and_execute_exit = AsyncMock()  # type: ignore[method-assign]
        await curve.refresh_active_positions_market_caps(bot)
        bot._evaluate_and_execute_exit.assert_awaited_once()
        crossings = bot.active_positions[SAMPLE_MINT].get("stop_crossings")
        if record:
            assert crossings is not None
            assert crossings["refresh"]["ratio"] == pytest.approx(0.932, rel=0.01)
        else:
            assert crossings is None


@pytest.mark.regression("BUG-151")
async def test_refresh_reads_every_held_curve_in_one_batch(tmp_path: Path) -> None:
    # Ten held mints were ten getAccountInfo calls a second per bot.
    bot = make_bot(tmp_path)
    mints = [f"{i}{SAMPLE_MINT[1:]}" for i in range(1, 6)]
    for mint in mints:
        make_position(bot, mint, entry_market_cap=30.0)
    migrating = mints[-1]
    bot._migrating_mints.add(migrating)
    bot.active_positions = bot.position_manager.get_all_positions()
    curves = FakeCurves(default_market_cap=31.0)
    batch = AsyncMock(side_effect=curves.get_bonding_curve_states)
    single = AsyncMock(side_effect=AssertionError("no single reads"))
    bot.execution.get_bonding_curve_states = batch  # type: ignore[method-assign]
    bot.execution.get_bonding_curve_state = single  # type: ignore[method-assign]
    bot._evaluate_and_execute_exit = AsyncMock(return_value=False)  # type: ignore[method-assign]
    bot._exit_graduated_position = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await curve.refresh_active_positions_market_caps(bot)

    batch.assert_awaited_once()
    assert batch.await_args is not None
    assert sorted(batch.await_args.args[0]) == sorted(mints[:-1])
    single.assert_not_awaited()
    assert bot._evaluate_and_execute_exit.await_count == 4
    bot._exit_graduated_position.assert_awaited_once_with(migrating)


@pytest.mark.regression("BUG-151")
async def test_refresh_keeps_last_prices_when_the_batch_fails(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT, entry_market_cap=30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.active_positions[SAMPLE_MINT]["current_market_cap"] = 33.0
    bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("HTTP 429")
    )
    single = AsyncMock()
    bot.execution.get_bonding_curve_state = single  # type: ignore[method-assign]
    bot._evaluate_and_execute_exit = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await curve.refresh_active_positions_market_caps(bot)

    # No per-mint retry storm on a failed batch: exits run on the last price.
    single.assert_not_awaited()
    bot._evaluate_and_execute_exit.assert_awaited_once_with(SAMPLE_MINT, 33.0)
    assert bot._watch_stats["position_refresh_errors"] == 1


async def test_refresh_reads_mint_by_mint_without_a_batch_read(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT, entry_market_cap=30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    curves = FakeCurves(default_market_cap=31.0)
    # A client whose batch read is not a coroutine (a plain mock).
    bot.execution.get_bonding_curve_states = lambda *_a, **_k: None  # type: ignore[method-assign,assignment]
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        side_effect=[curves.curve(SAMPLE_MINT)]
    )
    bot._evaluate_and_execute_exit = AsyncMock(return_value=False)  # type: ignore[method-assign]

    await curve.refresh_active_positions_market_caps(bot)

    bot._evaluate_and_execute_exit.assert_awaited_once()
    exit_call = bot._evaluate_and_execute_exit.await_args
    assert exit_call is not None
    assert exit_call.args[1] == pytest.approx(31.0)


def test_note_stop_crossing_ignores_mints_not_held(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, record_stop_crossings=True)
    curve.note_stop_crossing(bot, SAMPLE_MINT, 1.0, source="trade_feed")
    assert SAMPLE_MINT not in bot.active_positions


@pytest.mark.parametrize(
    ("method", "function", "args", "kwargs"),
    [
        (
            "_handle_bonding_curve_state_update",
            "handle_bonding_curve_state_update",
            ("u",),
            {},
        ),
        ("_handle_complete_event_update", "handle_complete_event_update", ("u",), {}),
        (
            "_maybe_buy_pre_graduation",
            "maybe_buy_pre_graduation",
            (SAMPLE_MINT, 50.0),
            {"now": 1.0, "min_samples": 3},
        ),
        (
            "_refresh_active_positions_market_caps",
            "refresh_active_positions_market_caps",
            (),
            {},
        ),
    ],
)
async def test_bot_methods_delegate_to_curve_handlers(
    tmp_path: Path,
    method: str,
    function: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    bot = make_bot(tmp_path)
    handler = AsyncMock(return_value="result")
    with patch.object(curve, function, handler):
        result = await getattr(bot, method)(*args, **kwargs)
    handler.assert_awaited_once_with(bot, *args, **kwargs)
    # Only the pre-graduation entry returns a value (handled or not).
    if method == "_maybe_buy_pre_graduation":
        assert result == "result"


async def test_held_curve_reads_without_a_batch_or_with_failing_single_reads(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    bot = make_bot(tmp_path)
    reads = AsyncMock(side_effect=[RuntimeError("down"), {"complete": True}, None])
    bot.execution = SimpleNamespace(get_bonding_curve_state=reads)  # type: ignore[assignment]
    curves = await curve.read_held_curves(bot, ["A", "B", "C"])
    assert curves == {"A": None, "B": {"complete": True}, "C": None}
    assert await curve.read_held_curves(bot, []) == {}


async def test_refresh_prices_from_reserves_and_survives_a_failing_exit(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT, entry_market_cap=30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.active_positions[SAMPLE_MINT]["current_market_cap"] = 30.0
    bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
        return_value={
            SAMPLE_MINT: {
                "virtual_sol_reserves": 40_000_000_000,
                "virtual_token_reserves": 1_000_000_000_000_000,
            }
        }
    )
    calls: list[float] = []

    async def failing_exit(mint: str, mc: float) -> bool:
        calls.append(mc)
        raise RuntimeError("exit failed")

    bot._evaluate_and_execute_exit = failing_exit  # type: ignore[method-assign,assignment]
    await curve.refresh_active_positions_market_caps(bot)
    # The fresh price first, then the last known one after the failure.
    assert calls == [pytest.approx(40.0), 30.0]

    # A curve with no reserves at all keeps the last price.
    bot.execution.get_bonding_curve_states = AsyncMock(  # type: ignore[method-assign]
        return_value={
            SAMPLE_MINT: {"virtual_sol_reserves": 0, "virtual_token_reserves": 0}
        }
    )
    calls.clear()
    await curve.refresh_active_positions_market_caps(bot)
    assert calls == [30.0, 30.0]
