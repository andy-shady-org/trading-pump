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
    TradingBotState.IDLE: {
        TradingBotState.MONITORING,
        TradingBotState.HOLDING,
        TradingBotState.SELLING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.MONITORING: {
        TradingBotState.BUYING,
        TradingBotState.HOLDING,
        TradingBotState.SELLING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.BUYING: {
        # A sell can start while a buy waits out its paper entry delay (BUG-111).
        TradingBotState.SELLING,
        TradingBotState.HOLDING,
        TradingBotState.MONITORING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.HOLDING: {
        # A further entry while positions are open (BUG-106).
        TradingBotState.BUYING,
        TradingBotState.SELLING,
        TradingBotState.MONITORING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.SELLING: {
        TradingBotState.BUYING,
        TradingBotState.MONITORING,
        TradingBotState.HOLDING,
        TradingBotState.SHUTDOWN,
    },
    TradingBotState.SHUTDOWN: set(),
}


def is_valid_transition(current: TradingBotState, next_state: TradingBotState) -> bool:
    return next_state in VALID_STATE_TRANSITIONS.get(current, set())


def settled_state(
    current: TradingBotState, next_state: TradingBotState, *, holds_positions: bool
) -> TradingBotState:
    """The state to settle in once a buy or sell finishes.

    The bot has one state but can hold several positions: after a buy or sell
    it is ``HOLDING`` while any position is open, never ``MONITORING`` (BUG-106).
    """
    if (
        next_state == TradingBotState.MONITORING
        and current in (TradingBotState.BUYING, TradingBotState.SELLING)
        and holds_positions
    ):
        return TradingBotState.HOLDING
    return next_state
