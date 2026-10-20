"""Tests for the bonding-curve handlers (`bot/handlers/curve.py`)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.handlers import curve
from pumpfun_trading.streams.geyser import CompleteEventUpdate
from pumpfun_trading.tests.support.constants import SAMPLE_MINT
from pumpfun_trading.tests.support.factories import make_bot, make_position


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
    bot.execution.get_bonding_curve_state = AsyncMock(  # type: ignore[method-assign]
        return_value={"complete": True}
    )
    bot._exit_graduated_position = AsyncMock(  # type: ignore[method-assign]
        return_value=True
    )
    await curve.refresh_active_positions_market_caps(bot)
    bot._exit_graduated_position.assert_awaited_once_with(SAMPLE_MINT)


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
