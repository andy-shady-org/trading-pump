"""Unit tests for ``cli/bot.py``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
