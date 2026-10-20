"""Tests for the watch-list poller (`bot/handlers/watch.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.bot.handlers import watch
from pumpfun_trading.tests.support.constants import SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot


def test_watch_list_status_reports_mode_budget_and_counters(tmp_path: Path) -> None:
    bot = make_bot(
        tmp_path,
        entry_mode="confirmed",
        watch_max_mints=12,
        watch_max_trade_subscriptions=3,
    )
    bot._count_watch("watched", 2)
    status = watch.watch_list_status(bot)
    assert status == {
        "entry_mode": "confirmed",
        "watched": 0,
        "subscribed": 0,
        "near_graduation": 0,
        "max_mints": 12,
        "subscription_budget": 3,
        "stats": {"watched": 2},
    }
    # A copy: the dashboard can't mutate the live counters.
    status["stats"]["watched"] = 99
    assert bot._watch_stats["watched"] == 2


def test_unwatched_or_ordinary_mints_are_always_due(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    assert watch.watch_poll_due(bot, SAMPLE_PUMP_MINT, now=0.0) is True


def test_record_curve_poll_writes_a_capture_row(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    recorder = MagicMock()
    bot.replay_recorder = recorder
    watch.record_curve_poll(
        bot, SAMPLE_PUMP_MINT, 0.0, ts=1.0, source="watch_poll"
    )  # no price: nothing recorded
    recorder.record_snapshot.assert_not_called()

    watch.record_curve_poll(
        bot,
        SAMPLE_PUMP_MINT,
        42.0,
        ts=2.0,
        source="watch_poll",
        real_sol=1.5,
        virtual_sol=31.5,
    )
    row = recorder.record_snapshot.call_args.args[0]
    assert row["event"] == "curve_poll"
    assert row["market_cap_sol"] == 42.0
    assert row["price"] == pytest.approx(42.0 / 1e9)
    assert row["real_sol_reserves"] == 1.5
    assert row["virtual_sol_reserves"] == 31.5


async def test_watch_poll_loop_only_runs_in_confirmed_mode(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, entry_mode="launch")
    bot._poll_watch_list = AsyncMock()  # type: ignore[method-assign]
    await watch.run_watch_poll_loop(bot)
    bot._poll_watch_list.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "function", "args"),
    [
        ("_run_watch_poll_loop", "run_watch_poll_loop", ()),
        ("_poll_watch_list", "poll_watch_list", ()),
        ("_promote_watched_mints", "promote_watched_mints", ()),
    ],
)
async def test_async_bot_methods_delegate_to_watch_handlers(
    tmp_path: Path, method: str, function: str, args: tuple[Any, ...]
) -> None:
    bot = make_bot(tmp_path)
    handler = AsyncMock()
    with patch.object(watch, function, handler):
        await getattr(bot, method)(*args)
    handler.assert_awaited_once_with(bot, *args)


def test_sync_bot_methods_delegate_to_watch_handlers(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    with patch.object(watch, "watch_list_status", MagicMock(return_value={"x": 1})):
        assert bot.watch_list_status() == {"x": 1}
    with patch.object(watch, "watch_poll_due", MagicMock(return_value=False)) as due:
        assert bot._watch_poll_due(SAMPLE_PUMP_MINT, 5.0) is False
    due.assert_called_once_with(bot, SAMPLE_PUMP_MINT, 5.0)
    with patch.object(watch, "record_curve_poll", MagicMock()) as poll:
        bot._record_curve_poll(SAMPLE_PUMP_MINT, 40.0, ts=1.0, source="s")
    poll.assert_called_once_with(
        bot,
        SAMPLE_PUMP_MINT,
        40.0,
        ts=1.0,
        source="s",
        real_sol=None,
        virtual_sol=None,
    )
