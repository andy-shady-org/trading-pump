"""Unit tests for ``cli/bot.py``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pumpfun_trading.cli.bot as cli_bot


def test_cli_bot_main(tmp_path):
    cfg_file = tmp_path / "bot_cfg.json"
    cfg_file.write_text("{}", encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "pumpfun-bot",
            "--preset",
            "aggressive",
            "--buy-amount-sol",
            "0.1",
            "--take-profit",
            "2.0",
            "--stop-loss",
            "0.8",
            "--min-market-cap-sol",
            "20",
            "--min-balance-sol",
            "0.5",
            "--dry-run",
            "--config",
            str(cfg_file),
        ],
    ):
        mock_bot = MagicMock()
        mock_bot.start = AsyncMock()
        mock_bot.close = AsyncMock()

        with patch(
            "pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot
        ):
            with patch("asyncio.run", side_effect=lambda coro: coro.close()):
                cli_bot.main()


def _run_main_with_bot(stop_requested: bool) -> None:
    bot = MagicMock()
    bot.start = AsyncMock()
    bot.close = AsyncMock()
    bot._stop_requested = stop_requested
    with (
        patch("sys.argv", ["pumpbot", "--dry-run", "--headless"]),
        patch("pumpfun_trading.cli.bot.TradingBot.from_env", return_value=bot),
    ):
        cli_bot.main()
    bot.close.assert_awaited_once_with()


def test_cli_bot_main_requested_shutdown_exits_zero() -> None:
    _run_main_with_bot(stop_requested=True)


def test_cli_bot_main_stream_loop_ending_exits_non_zero() -> None:
    """Sprint 24D: a supervisor must see an unrequested stop as a failure."""
    with pytest.raises(SystemExit) as exc:
        _run_main_with_bot(stop_requested=False)

    assert exc.value.code == 1


def test_cli_bot_main_keyboard_interrupt_is_quiet() -> None:
    with (
        patch("sys.argv", ["pumpbot", "--dry-run"]),
        patch("asyncio.run", side_effect=KeyboardInterrupt),
    ):
        cli_bot.main()
