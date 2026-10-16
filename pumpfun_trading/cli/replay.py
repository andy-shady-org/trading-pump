"""Replay CLI entrypoints for historical market-data sessions."""

from __future__ import annotations

import argparse

from pumpfun_trading.engines.replay import (
    render_replay_dashboard,
    render_replay_summary,
    render_replay_trades,
    run_replay,
)
from pumpfun_trading.ops.logging import get_configured_console

console = get_configured_console()


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "replay", description="Run historical replay analysis"
        )
    else:
        parser = argparse.ArgumentParser(description="Run historical replay analysis")
    parser.add_argument(
        "--path", default=None, help="Path to a JSON/JSONL replay dataset"
    )
    parser.add_argument(
        "--replay-path",
        default=None,
        help="Path to a JSON/JSONL replay dataset (alias for --path)",
    )
    parser.add_argument(
        "--mode",
        dest="replay_output",
        choices=["summary", "trades", "dashboard"],
        default=None,
        help="Historic replay output mode (default: dashboard)",
    )
    # Distinct dest so the unified CLI's top-level `--mode` cannot collide (BUG-85).
    parser.add_argument(
        "--replay-mode",
        dest="replay_output",
        choices=["summary", "trades", "dashboard"],
        default=None,
        help="Historic replay output mode (alias for --mode)",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to a JSON bot config file"
    )
    parser.add_argument(
        "--preset",
        choices=["conservative", "balanced", "aggressive"],
        default=None,
        help="Trading strategy preset",
    )
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--mint-name", default=None, help="Filter by mint name")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100.0,
        help="Initial cash balance in SOL",
    )
    return parser


def build_replay_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def run_replay_cli(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = build_parser().parse_args()

    target_path = getattr(args, "path", None) or getattr(args, "replay_path", None)
    if not target_path:
        raise SystemExit("--path (or --replay-path) is required")

    config = None
    config_path = getattr(args, "config", None)
    preset = getattr(args, "preset", None)
    if config_path:
        from pumpfun_trading.strategies.base import TradingBotConfig

        config = TradingBotConfig.from_file(config_path)
    elif preset:
        from pumpfun_trading.strategies.presets import resolve_strategy_config

        config = resolve_strategy_config(preset)

    initial_cash_val = getattr(args, "initial_cash", None)

    from pumpfun_trading.engines.replay import PaperTradingEngine

    engine: PaperTradingEngine | None = None
    if config is not None or initial_cash_val is not None:
        initial_cash = (
            float(initial_cash_val) if initial_cash_val is not None else 100.0
        )
        take_profit = config.take_profit if config is not None else 1.5
        stop_loss = config.stop_loss if config is not None else 0.85
        max_positions = config.max_active_positions if config is not None else 1
        engine = PaperTradingEngine(
            initial_cash=initial_cash,
            take_profit=take_profit,
            stop_loss=stop_loss,
            max_positions=max_positions,
            strategy_config=config,
        )

    summary = run_replay(
        target_path,
        engine=engine,
        mint=getattr(args, "mint", None),
        mint_name=getattr(args, "mint_name", None),
        token_name=getattr(args, "token_name", None),
    )
    mode = getattr(args, "replay_output", None) or getattr(args, "replay_mode", None)
    if mode is None:
        legacy = getattr(args, "mode", None)
        mode = legacy if legacy in {"summary", "trades", "dashboard"} else "dashboard"
    if mode == "summary":
        render_replay_summary(summary, console)
        return
    if mode == "trades":
        render_replay_trades(summary.get("trades", []), console)
        return
    render_replay_dashboard(summary, console)


def main() -> None:
    run_replay_cli()


__all__ = ["build_parser", "run_replay_cli", "main"]
