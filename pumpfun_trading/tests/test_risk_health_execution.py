from __future__ import annotations

import time
from unittest.mock import MagicMock


from pumpfun_trading.bot.health import (
    health_ok_for_trading,
    mark_health_check,
    update_health_state,
)
from pumpfun_trading.bot.lifecycle import (
    TradingBotState,
    is_valid_transition,
)
from pumpfun_trading.bot.risk import (
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
)
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.execution.builder import ExecutionBuilder, build_execution_client
from pumpfun_trading.strategies.risk_validation import validate_risk_limits


def test_risk_limits_checks():
    bot = MagicMock()
    bot.config = TradingBotConfig(
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.3,
        buy_amount_sol=0.1,
        max_loss_per_trade_sol=0.05,
        max_daily_drawdown_pct=0.20,
    )
    bot._last_event = ""

    current_positions = {
        "Mint1": {"entry_market_cap": 0.2, "current_market_cap": 0.2},
    }

    # 1. Successful check
    assert check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )

    # 2. Exceeds max total exposure
    assert not check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.9,
        current_positions=current_positions,
    )
    assert "max exposure" in bot._last_event

    # 3. Exceeds max position size
    assert not check_risk_limits(
        bot,
        mint="Mint2",
        proposed_entry_sol=0.4,
        current_positions=current_positions,
    )
    assert "position cap" in bot._last_event

    # 4. Mint already active
    assert not check_risk_limits(
        bot,
        mint="Mint1",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )
    assert "already active" in bot._last_event

    # 5. Token concentration cap breached
    bot.config = TradingBotConfig(
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.3,
        buy_amount_sol=0.1,
        max_token_concentration_pct=0.15,
    )
    assert not check_risk_limits(
        bot,
        mint="Mint3",
        proposed_entry_sol=0.1,
        current_positions=current_positions,
    )
    assert "concentration cap reached" in bot._last_event


def test_daily_drawdown_and_trade_loss():
    bot = MagicMock()
    bot.config = TradingBotConfig(
        max_daily_drawdown_pct=0.25,
        max_loss_per_trade_sol=0.05,
        buy_amount_sol=0.1,
    )
    bot.active_positions = {}

    # Empty positions
    assert check_daily_drawdown(bot)

    # Zero equity positions
    bot.active_positions = {"MintZero": {"entry_market_cap": 0.0}}
    assert check_daily_drawdown(bot)

    # Drawdown within acceptable limit (10% drop < 25%)
    bot.active_positions = {
        "Mint1": {"entry_market_cap": 1.0, "current_market_cap": 0.9}
    }
    assert check_daily_drawdown(bot)

    # Drawdown breached (40% drop > 25%)
    bot.active_positions = {
        "Mint1": {"entry_market_cap": 1.0, "current_market_cap": 0.6}
    }
    assert not check_daily_drawdown(bot)
    assert "daily drawdown" in bot._last_event

    # check_loss_per_trade
    # Non-existent mint
    assert check_loss_per_trade(bot, mint="NonExistent")

    # Entry market cap <= 0
    bot.active_positions = {"MintZero": {"entry_market_cap": 0.0}}
    assert check_loss_per_trade(bot, mint="MintZero")

    # Trade loss within limits (loss ratio 0.2 < 0.05/0.1 = 0.5)
    bot.active_positions = {
        "MintPos": {"entry_market_cap": 1.0, "current_market_cap": 0.8}
    }
    assert check_loss_per_trade(bot, mint="MintPos")

    # Trade loss exceeds max limit (loss ratio 0.6 > 0.5)
    bot.active_positions = {
        "MintPos": {"entry_market_cap": 1.0, "current_market_cap": 0.4}
    }
    assert not check_loss_per_trade(bot, mint="MintPos")
    assert "trade loss" in bot._last_event


def test_health_checks():
    bot = MagicMock()
    bot._stop_requested = False
    bot._risk_killed = False
    bot._health_ok = True
    bot._last_health_check = time.monotonic()
    bot.config = MagicMock()
    bot.config.health_check_timeout_seconds = 10.0

    # Healthy state
    assert health_ok_for_trading(bot)

    # Stop requested
    bot._stop_requested = True
    assert not health_ok_for_trading(bot)
    bot._stop_requested = False

    # Risk killed
    bot._risk_killed = True
    assert not health_ok_for_trading(bot)
    bot._risk_killed = False

    # Not health ok
    bot._health_ok = False
    assert not health_ok_for_trading(bot)
    bot._health_ok = True

    # Timeout
    bot._last_health_check = time.monotonic() - 20.0
    assert not health_ok_for_trading(bot)
    assert bot._risk_killed is True

    # mark_health_check
    mark_health_check(bot)
    assert bot._health_ok is True

    # update_health_state when stop requested
    bot._stop_requested = True
    update_health_state(bot)
    bot._stop_requested = False

    # update_health_state when stale
    bot._last_message_at = time.monotonic() - 30.0
    bot._health_ok = True
    update_health_state(bot)
    assert bot._health_ok is False
    assert bot._risk_killed is True

    # update_health_state when fresh
    bot._last_message_at = time.monotonic()
    update_health_state(bot)
    assert bot._health_ok is True


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


def test_execution_builder():
    pk = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
    rpc = "https://api.mainnet-beta.solana.com"

    builder = ExecutionBuilder(pk, rpc, default_slippage_bps=200)
    client1 = builder.build()
    assert client1.rpc_url == rpc

    client2 = build_execution_client(pk, rpc)
    assert client2.rpc_url == rpc


def test_strategy_risk_validation():
    config = TradingBotConfig(
        max_active_positions=2,
        reserve_balance_sol=0.1,
    )

    # Valid
    assert validate_risk_limits(
        config,
        current_positions={"Mint1": {}},
        proposed_entry_sol=0.2,
        wallet_balance_sol=0.5,
    )

    # max_active_positions < 1
    config_zero = TradingBotConfig(
        max_active_positions=0,
        reserve_balance_sol=0.1,
    )
    assert not validate_risk_limits(
        config_zero,
        current_positions={},
        proposed_entry_sol=0.1,
    )

    # Active positions full
    assert not validate_risk_limits(
        config,
        current_positions={"Mint1": {}, "Mint2": {}},
        proposed_entry_sol=0.1,
    )

    # Insufficient wallet balance after reserve
    assert not validate_risk_limits(
        config,
        current_positions={"Mint1": {}},
        proposed_entry_sol=0.3,
        wallet_balance_sol=0.35,  # 0.35 - 0.1 = 0.25 < 0.3
    )
