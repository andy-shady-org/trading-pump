"""Bot runtime CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio

from trading_pump.bot.run import TradingBot
from trading_pump.bot.strategy import TradingBotConfig, resolve_strategy_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Pump.fun trading bot")
    parser.add_argument(
        "--preset",
        choices=["conservative", "balanced", "aggressive", "momentum"],
        default="balanced",
        help="Trading strategy preset",
    )
    parser.add_argument(
        "--buy-amount-sol",
        type=float,
        default=None,
        help="SOL to spend per buy (overrides preset)",
    )
    parser.add_argument(
        "--take-profit",
        type=float,
        default=None,
        help="Take-profit multiplier (overrides preset)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Stop-loss multiplier (overrides preset)",
    )
    parser.add_argument(
        "--min-market-cap-sol",
        type=float,
        default=None,
        help="Minimum launch market cap to buy",
    )
    parser.add_argument(
        "--min-balance-sol",
        type=float,
        default=None,
        help="Minimum wallet balance required to trade",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not submit real transactions"
    )
    parser.add_argument(
        "--paper-trade", action="store_true", help="Run in paper-trading mode"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headlessly without interactive terminal UI",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to a JSON bot config file"
    )
    parser.add_argument(
        "--record-replay",
        type=str,
        default=None,
        metavar="PATH",
        help="Record market quote stream and trades to a JSONL replay dataset",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    async def _run_bot() -> bool:
        config = None
        if args.config:
            config = TradingBotConfig.from_file(args.config)
        if config is None:
            config = resolve_strategy_config(
                args.preset,
                overrides={
                    "buy_amount_sol": args.buy_amount_sol,
                    "take_profit": args.take_profit,
                    "stop_loss": args.stop_loss,
                    "min_market_cap_sol": args.min_market_cap_sol,
                    "min_balance_sol": args.min_balance_sol,
                },
            )

        bot = TradingBot.from_env(
            config=config,
            dry_run=args.dry_run,
            paper_trade=args.paper_trade,
            headless=args.headless,
            replay_log_path=args.record_replay,
        )
        bot.config_path = args.config
        try:
            await bot.start()
        finally:
            await bot.close()
        return bool(bot._stop_requested)

    try:
        stopped_on_request = asyncio.run(_run_bot())
    except (KeyboardInterrupt, SystemExit):
        return
    if stopped_on_request is False:
        # The stream loop ended on its own: exit non-zero so a supervisor
        # (systemd / launchd, RUNBOOK §8) restarts the bot (Sprint 24D).
        raise SystemExit(1)


if __name__ == "__main__":
    main()
