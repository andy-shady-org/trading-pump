"""Lifecycle definitions and transition validation for the trading bot."""

from __future__ import annotations

from enum import Enum


class TradingBotState(str, Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    BUYING = "buying"
    HOLDING = "holding"
    SELLING = "selling"
    SHUTDOWN = "shutdown"


VALID_STATE_TRANSITIONS: dict[TradingBotState, set[TradingBotState]] = {
    TradingBotState.IDLE: {TradingBotState.MONITORING, TradingBotState.SHUTDOWN},
    TradingBotState.MONITORING: {
        TradingBotState.BUYING,
        TradingBotState.HOLDING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.BUYING: {
        TradingBotState.HOLDING,
        TradingBotState.MONITORING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.HOLDING: {
        TradingBotState.SELLING,
        TradingBotState.MONITORING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.SELLING: {
        TradingBotState.MONITORING,
        TradingBotState.HOLDING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.SHUTDOWN: set(),
}


def is_valid_transition(current: TradingBotState, next_state: TradingBotState) -> bool:
    return next_state in VALID_STATE_TRANSITIONS.get(current, set())
