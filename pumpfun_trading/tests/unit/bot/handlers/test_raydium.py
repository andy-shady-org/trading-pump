"""Tests for the graduation handlers (`bot/handlers/raydium.py`)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.handlers import raydium
from pumpfun_trading.tests.support.constants import SAMPLE_MINT
from pumpfun_trading.tests.support.factories import make_bot, make_position


async def test_exit_graduated_position_marks_once_and_sells(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    bot._sell_token = AsyncMock(return_value=False)  # type: ignore[method-assign]
    # Not held: nothing to exit.
    assert await raydium.exit_graduated_position(bot, SAMPLE_MINT) is False
    bot._sell_token.assert_not_awaited()

    make_position(bot, SAMPLE_MINT)
    bot.active_positions = bot.position_manager.get_all_positions()
    assert await raydium.exit_graduated_position(bot, SAMPLE_MINT) is False
    assert await raydium.exit_graduated_position(bot, SAMPLE_MINT) is False
    assert SAMPLE_MINT in bot._migrating_mints
    # The pool may not exist yet: every pass retries the sell, the event once.
    assert bot._sell_token.await_count == 2
    held = [e for e in bot._recent_events if "graduated while held" in e]
    assert len(held) == 1


async def test_pumpswap_exit_market_cap_reads_the_pool_or_gives_none(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    bot.execution = SimpleNamespace()  # type: ignore[assignment]
    assert await raydium.pumpswap_exit_market_cap(bot, SAMPLE_MINT) is None

    bot.execution = SimpleNamespace(
        get_pumpswap_market_state=AsyncMock(return_value={"market_cap_sol": 80.0})
    )  # type: ignore[assignment]
    assert await raydium.pumpswap_exit_market_cap(bot, SAMPLE_MINT) == 80.0

    bot.execution = SimpleNamespace(
        get_pumpswap_market_state=AsyncMock(side_effect=RuntimeError("no pool"))
    )  # type: ignore[assignment]
    assert await raydium.pumpswap_exit_market_cap(bot, SAMPLE_MINT) is None


async def test_ws_migration_drops_watched_mint_and_exits_held_one(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    make_position(bot, SAMPLE_MINT)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._exit_graduated_position = AsyncMock(  # type: ignore[method-assign]
        return_value=True
    )
    await raydium.handle_ws_migration(bot, SAMPLE_MINT)
    bot._exit_graduated_position.assert_awaited_once_with(SAMPLE_MINT)


@pytest.mark.parametrize(
    ("method", "function", "args"),
    [
        ("_handle_raydium_pool_update", "handle_raydium_pool_update", ("pool",)),
        ("_arbitrage_costs", "arbitrage_costs", ("opp", "sig")),
        (
            "_evaluate_and_execute_arbitrage",
            "evaluate_and_execute_arbitrage",
            (SAMPLE_MINT, 1, 2, 0.5, False),
        ),
        ("_pumpswap_exit_market_cap", "pumpswap_exit_market_cap", (SAMPLE_MINT,)),
        ("_exit_graduated_position", "exit_graduated_position", (SAMPLE_MINT,)),
        ("_handle_ws_migration", "handle_ws_migration", (SAMPLE_MINT,)),
        ("_graduation_backfill_pass", "graduation_backfill_pass", ()),
        ("_run_graduation_backfill_loop", "run_graduation_backfill_loop", ()),
    ],
)
async def test_bot_methods_delegate_to_raydium_handlers(
    tmp_path: Path, method: str, function: str, args: tuple[Any, ...]
) -> None:
    bot = make_bot(tmp_path)
    handler = AsyncMock(return_value="result")
    with patch.object(raydium, function, handler):
        result = await getattr(bot, method)(*args)
    handler.assert_awaited_once_with(bot, *args)
    if method in (
        "_arbitrage_costs",
        "_pumpswap_exit_market_cap",
        "_exit_graduated_position",
        "_graduation_backfill_pass",
    ):
        assert result == "result"
