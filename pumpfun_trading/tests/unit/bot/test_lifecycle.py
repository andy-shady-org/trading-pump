"""Unit tests for ``bot/lifecycle.py``."""

from __future__ import annotations

from pumpfun_trading.bot.lifecycle import TradingBotState, is_valid_transition


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
