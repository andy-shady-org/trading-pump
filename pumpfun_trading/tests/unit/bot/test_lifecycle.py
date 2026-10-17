"""Unit tests for ``bot/lifecycle.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from pumpfun_trading.bot.lifecycle import (
    TradingBotState,
    is_valid_transition,
    settled_state,
)
from pumpfun_trading.tests.support.factories import make_bot


def test_lifecycle_transitions():
    assert is_valid_transition(TradingBotState.IDLE, TradingBotState.MONITORING)
    assert is_valid_transition(TradingBotState.IDLE, TradingBotState.SHUTDOWN)
    assert not is_valid_transition(TradingBotState.IDLE, TradingBotState.BUYING)

    assert is_valid_transition(TradingBotState.MONITORING, TradingBotState.BUYING)
    assert is_valid_transition(TradingBotState.MONITORING, TradingBotState.HOLDING)
    assert is_valid_transition(TradingBotState.MONITORING, TradingBotState.SHUTDOWN)

    assert is_valid_transition(TradingBotState.BUYING, TradingBotState.HOLDING)
    assert is_valid_transition(TradingBotState.BUYING, TradingBotState.MONITORING)

    assert is_valid_transition(TradingBotState.HOLDING, TradingBotState.SELLING)
    assert is_valid_transition(TradingBotState.HOLDING, TradingBotState.MONITORING)

    assert is_valid_transition(TradingBotState.SELLING, TradingBotState.MONITORING)
    assert is_valid_transition(TradingBotState.SELLING, TradingBotState.HOLDING)

    assert not is_valid_transition(TradingBotState.SHUTDOWN, TradingBotState.IDLE)


@pytest.mark.regression("BUG-106")
def test_holding_to_buying_is_valid_for_concurrent_positions() -> None:
    assert is_valid_transition(TradingBotState.HOLDING, TradingBotState.BUYING)


@pytest.mark.parametrize(
    "current, holds, expected",
    [
        (TradingBotState.BUYING, True, TradingBotState.HOLDING),
        (TradingBotState.SELLING, True, TradingBotState.HOLDING),
        (TradingBotState.BUYING, False, TradingBotState.MONITORING),
        (TradingBotState.SELLING, False, TradingBotState.MONITORING),
        (TradingBotState.IDLE, True, TradingBotState.MONITORING),
    ],
)
def test_settled_state_holds_while_positions_are_open(
    current: TradingBotState, holds: bool, expected: TradingBotState
) -> None:
    assert (
        settled_state(current, TradingBotState.MONITORING, holds_positions=holds)
        == expected
    )


@pytest.mark.regression("BUG-106")
async def test_second_buy_while_holding_logs_no_invalid_transition(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bot = make_bot(tmp_path)
    bot.position_manager.record_buy(
        mint="HeldMint", token_amount=1, cost_sol=0.01, entry_market_cap=30.0
    )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.state = TradingBotState.HOLDING

    with caplog.at_level("WARNING"):
        bot._transition_to(TradingBotState.BUYING, reason="buying NewMint")
        assert bot.state == TradingBotState.BUYING
        # A failed buy returns to HOLDING, not MONITORING, while a position is open.
        bot._transition_to(TradingBotState.MONITORING, reason="buy_failed NewMint")

    assert bot.state == TradingBotState.HOLDING
    assert "Ignored invalid state transition" not in caplog.text
    await bot.close()
