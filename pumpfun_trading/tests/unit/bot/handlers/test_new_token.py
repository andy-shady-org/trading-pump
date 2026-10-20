"""Tests for the new-token handlers (`bot/handlers/new_token.py`)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pumpfun_trading.bot.enrichment import TokenScreeningVerdict
from pumpfun_trading.bot.handlers import new_token
from pumpfun_trading.tests.support.constants import SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot


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
