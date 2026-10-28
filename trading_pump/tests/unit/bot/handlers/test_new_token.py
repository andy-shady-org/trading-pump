"""Tests for the new-token handlers (`bot/handlers/new_token.py`)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_pump.bot.enrichment import TokenScreeningVerdict
from trading_pump.bot.handlers import new_token
from trading_pump.sdk.curve import COMPLETE_CURVE_MARKET_CAP_SOL
from trading_pump.tests.support.constants import SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_bot


def _verdict() -> TokenScreeningVerdict:
    return TokenScreeningVerdict(mint=SAMPLE_PUMP_MINT, passed=True, risk_score=0.0)


def test_watch_token_puts_a_screened_launch_on_the_watch_list(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    data = {
        "vSolInBondingCurve": 31.5,
        "timestamp": 1_700_000_000_000,  # milliseconds
        "traderPublicKey": "Creator111",
    }
    new_token.watch_token(bot, SAMPLE_PUMP_MINT, data, 29.0, _verdict())

    entry = bot.order_flow_engine.get_watch(SAMPLE_PUMP_MINT)
    assert entry is not None
    assert entry.created_at == 1_700_000_000.0
    assert entry.creator == "Creator111"
    assert bot.watch_list_status()["stats"]["watched"] == 1
    assert bot._last_event == f"watching {SAMPLE_PUMP_MINT[:8]}"


async def test_new_token_event_without_mint_or_after_shutdown_is_ignored(
    tmp_path: Path,
) -> None:
    bot = make_bot(tmp_path)
    seen = bot._observed_tokens_count
    await new_token.handle_new_token_event(bot, {"name": "no mint"})
    assert bot._observed_tokens_count == seen

    bot._stop_requested = True
    await new_token.handle_new_token_event(bot, {"mint": SAMPLE_PUMP_MINT})
    assert bot._observed_tokens_count == seen


async def test_bot_methods_delegate_to_new_token_handlers(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)
    data = {"mint": SAMPLE_PUMP_MINT}
    ws = object()
    handler = AsyncMock()
    with patch.object(new_token, "handle_new_token_event", handler):
        await bot._handle_new_token_event(data, ws)
    handler.assert_awaited_once_with(bot, data, ws)

    verdict = _verdict()
    watch = MagicMock()
    with patch.object(new_token, "watch_token", watch):
        bot._watch_token(SAMPLE_PUMP_MINT, data, 30.0, verdict)
    watch.assert_called_once_with(bot, SAMPLE_PUMP_MINT, data, 30.0, verdict)


@pytest.mark.regression("BUG-146")
async def test_launch_complete_at_creation_is_never_bought(tmp_path: Path) -> None:
    # rc.5 bought 26 coins whose creator filled the whole curve in the create
    # transaction (410.88 SOL), then "sold" them at 9x on the fresh pool.
    bot = make_bot(tmp_path, enable_anti_rug_filters=False, require_trade_feed=False)
    bot._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
    await new_token.handle_new_token_event(
        bot,
        {"mint": SAMPLE_PUMP_MINT, "pool": "pump", "marketCapSol": 410.8801681200643},
    )
    bot._buy_token.assert_not_awaited()
    assert bot._last_event == f"complete_at_create {SAMPLE_PUMP_MINT[:8]}"
    assert bot._entry_refusals == {"complete_at_create": 1}
    assert bot._is_recently_seen(SAMPLE_PUMP_MINT)
    assert bot.get_status_snapshot()["entry_refusals"] == {"complete_at_create": 1}


@pytest.mark.regression("BUG-146")
async def test_launch_short_of_a_full_curve_is_still_screened(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, enable_anti_rug_filters=False, require_trade_feed=False)
    bot._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
    await new_token.handle_new_token_event(
        bot, {"mint": SAMPLE_PUMP_MINT, "pool": "pump", "marketCapSol": 374.8}
    )
    bot._buy_token.assert_awaited_once()


def test_complete_at_create_threshold() -> None:
    assert COMPLETE_CURVE_MARKET_CAP_SOL == pytest.approx(410.88, abs=0.01)
    assert new_token.complete_at_create(COMPLETE_CURVE_MARKET_CAP_SOL)
    assert new_token.complete_at_create(407.0)
    assert not new_token.complete_at_create(406.0)
    assert not new_token.complete_at_create(27.96)


async def test_launch_with_a_tiny_creator_buy_is_skipped_when_configured(
    tmp_path: Path,
) -> None:
    # FEAT-75: creator buys under 0.05 SOL were dead within 30 s in 86% (rc.6)
    # and 97% (rc.7) of sampled launches.
    def event(sol: object) -> dict[str, object]:
        data: dict[str, object] = {
            "mint": SAMPLE_PUMP_MINT,
            "pool": "pump",
            "marketCapSol": 28.0,
        }
        if sol is not None:
            data["solAmount"] = sol
        return data

    bot = make_bot(
        tmp_path,
        enable_anti_rug_filters=False,
        require_trade_feed=False,
        launch_skip_creator_buy_below_sol=0.05,
    )
    bot._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
    await new_token.handle_new_token_event(bot, event(0.000987653))
    bot._buy_token.assert_not_awaited()
    assert bot._entry_refusals == {"tiny_creator_buy": 1}
    assert bot._last_event == f"tiny_creator_buy {SAMPLE_PUMP_MINT[:8]}"
    assert bot._is_recently_seen(SAMPLE_PUMP_MINT)

    # No creator buy, a missing or odd field, or a real buy: not skipped.
    for sol in (0.0, None, "n/a", 0.05, 0.2963):
        fresh = make_bot(
            tmp_path,
            enable_anti_rug_filters=False,
            require_trade_feed=False,
            launch_skip_creator_buy_below_sol=0.05,
        )
        fresh._buy_token = AsyncMock(return_value=True)  # type: ignore[method-assign]
        await new_token.handle_new_token_event(fresh, event(sol))
        fresh._buy_token.assert_awaited_once()

    # Off by default, and never applied to confirmed (watched) entries.
    assert new_token.tiny_creator_buy(make_bot(tmp_path), {"solAmount": 0.001}) is None
    confirmed = make_bot(
        tmp_path,
        entry_mode="confirmed",
        enable_anti_rug_filters=False,
        launch_skip_creator_buy_below_sol=0.05,
    )
    confirmed._watch_token = MagicMock()  # type: ignore[method-assign]
    await new_token.handle_new_token_event(confirmed, event(0.001))
    assert "tiny_creator_buy" not in confirmed._entry_refusals
