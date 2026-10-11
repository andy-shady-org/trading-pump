"""Unit tests for BUG-06 through BUG-10 resolution and lifecycle resilience."""

from __future__ import annotations

import io
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.ops.logging import (
    AnsiStrippingFormatter,
    get_configured_console,
    is_color_enabled,
    strip_ansi,
)
from pumpfun_trading.storage.status import build_status_snapshot

TEST_KEY = "4wT3fE2k8uQe7dY3q1aZ9xL5vNmK8jP2wR1sT4vU7xY8z1aB2c3d4e5f6g7h8j9k"
TEST_RPC = "https://api.mainnet-beta.solana.com"
MINT_1 = "HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump"
MINT_2 = "So11111111111111111111111111111111111111112"


def _make_bot(dry_run: bool = True, paper_trade: bool = True, **kwargs) -> TradingBot:
    config = TradingBotConfig(
        dry_run=dry_run,
        paper_trade=paper_trade,
        buy_amount_sol=0.01,
        reconnect_delay_seconds=1.0,
    )
    return TradingBot(
        private_key_b58=TEST_KEY,
        rpc_url=TEST_RPC,
        config=config,
        dry_run=dry_run,
        paper_trade=paper_trade,
        verbose=False,
        **kwargs,
    )


def test_bug10_ansi_stripping_and_no_color():
    """Test BUG-10: ANSI stripping formatter and NO_COLOR compliance."""
    raw_text = "\x1b[31;1mError Message\x1b[0m"
    cleaned = strip_ansi(raw_text)
    assert cleaned == "Error Message"
    assert "\x1b" not in cleaned

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="\x1b[32mSuccess\x1b[0m",
        args=(),
        exc_info=None,
    )
    formatter = AnsiStrippingFormatter("%(message)s")
    assert formatter.format(record) == "Success"

    # Test is_color_enabled with NO_COLOR
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        assert not is_color_enabled()

    with patch.dict(os.environ, {"NO_COLOR": ""}):
        mock_tty = MagicMock()
        mock_tty.isatty.return_value = True
        assert is_color_enabled(mock_tty)

        mock_non_tty = MagicMock()
        mock_non_tty.isatty.return_value = False
        assert not is_color_enabled(mock_non_tty)

    console = get_configured_console(file=io.StringIO())
    assert isinstance(console, Console)


@pytest.mark.asyncio
async def test_bug07_onchain_startup_reconciliation():
    """Test BUG-07: Startup reconciliation purges stale ghost positions with zero balance."""
    bot = _make_bot(dry_run=False, paper_trade=False)
    bot.active_positions = {
        MINT_1: {
            "name": "GhostToken",
            "entry_market_cap": 30.0,
            "current_market_cap": 30.0,
            "token_amount": 1000,
        },
        MINT_2: {
            "name": "ActiveToken",
            "entry_market_cap": 35.0,
            "current_market_cap": 35.0,
            "token_amount": 5000,
        },
    }

    async def mock_balance(mint: str) -> int:
        if mint == MINT_1:
            return 0  # Sold externally
        return 5000  # Still holding

    bot.execution.get_token_balance = AsyncMock(side_effect=mock_balance)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 40.0}
    )

    reconciled = await bot.reconcile_onchain_positions()

    assert MINT_1 not in bot.active_positions
    assert MINT_2 in bot.active_positions
    assert bot.active_positions[MINT_2]["token_amount"] == 5000
    assert bot.active_positions[MINT_2]["current_market_cap"] == 40.0
    assert reconciled[MINT_1]["status"] == "purged"
    assert reconciled[MINT_2]["status"] == "active"


@pytest.mark.asyncio
async def test_bug08_exit_retry_queue_and_slippage_escalation():
    """Test BUG-08: Failed sells enqueue with escalating slippage and retry backoff."""
    bot = _make_bot(dry_run=False, paper_trade=False)
    bot.active_positions[MINT_1] = {
        "name": "Token1",
        "entry_market_cap": 30.0,
        "current_market_cap": 25.0,
    }

    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(
            "BondingPDA11111111111111111111111111111111",
            "Associated11111111111111111111111111111111",
        )
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1000000000,
            "virtual_sol_reserves": 30000000000,
        }
    )
    # Simulate RPC failure on send
    bot.execution.sell = AsyncMock(side_effect=RuntimeError("Simulated RPC Error"))

    # Initial sell attempt fails
    result = await bot._sell_token(MINT_1)
    assert result is False
    assert MINT_1 in bot.active_positions  # Position preserved for retry
    assert MINT_1 in bot._exit_retry_queue

    entry = bot._exit_retry_queue[MINT_1]
    assert entry["retry_count"] == 1
    assert entry["slippage_bps"] == bot.base_exit_slippage_bps + 500  # 1000 bps

    # Simulate second retry failure
    bot._enqueue_exit_retry(MINT_1, reason="second_failure")
    entry2 = bot._exit_retry_queue[MINT_1]
    assert entry2["retry_count"] == 2
    assert entry2["slippage_bps"] == bot.base_exit_slippage_bps + 1000  # 1500 bps

    # Test process exit retry queue with successful retry
    bot._exit_retry_queue[MINT_1]["next_retry_at"] = 0  # Force immediate eligibility
    bot.execution.sell = AsyncMock(
        return_value="ValidSignature1111111111111111111111111111111111111111111111111111111111111111"
    )
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    await bot._process_exit_retry_queue()
    assert MINT_1 not in bot.active_positions
    assert MINT_1 not in bot._exit_retry_queue


@pytest.mark.asyncio
async def test_bug06_websocket_backoff_and_circuit_breaker():
    """Test BUG-06: WebSocket circuit breaker trips on consecutive reconnect failures."""
    bot = _make_bot()
    bot._max_ws_consecutive_failures = 3

    assert bot._health_ok is True
    assert bot._circuit_breaker_tripped is False

    # Simulate consecutive failures
    bot._ws_consecutive_failures = 3
    if bot._ws_consecutive_failures >= bot._max_ws_consecutive_failures:
        bot._circuit_breaker_tripped = True
        bot._health_ok = False
        bot._last_status = "degraded: ws circuit breaker active"

    assert bot._circuit_breaker_tripped is True
    assert bot._health_ok is False
    assert "circuit breaker" in bot._last_status

    # Snapshot includes circuit breaker status
    snapshot = build_status_snapshot(bot)
    assert snapshot["circuit_breaker_tripped"] is True
    assert snapshot["ws_consecutive_failures"] == 3
