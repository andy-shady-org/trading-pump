"""Tests for the trade-stream handlers (`bot/handlers/trade.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.bot.handlers import trade
from pumpfun_trading.strategies.shadow import ShadowSignal, ShadowVariant
from pumpfun_trading.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot, make_position


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
