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
        "--path", required=True, help="Path to a JSON/JSONL replay dataset"
    )
    parser.add_argument(
        "--mode",
        choices=["summary", "trades", "dashboard"],
        default="dashboard",
        help="Historic replay output mode",
    )
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--mint-name", default=None, help="Filter by mint name")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
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
        raise SystemExit("--path is required")

    summary = run_replay(
        target_path,
        mint=getattr(args, "mint", None),
        mint_name=getattr(args, "mint_name", None),
        token_name=getattr(args, "token_name", None),
    )
    mode = getattr(args, "mode", None) or getattr(args, "replay_mode", "dashboard")
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
