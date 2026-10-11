"""Replay CLI entrypoints for historical market-data sessions."""

from __future__ import annotations

import argparse

from rich.console import Console

from pumpfun_trading.engines.replay import (
    render_replay_dashboard,
    render_replay_summary,
    render_replay_trades,
    run_replay,
)

console = Console()


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def run_replay_cli(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = build_parser().parse_args()

    if not getattr(args, "path", None):
        raise SystemExit("--path is required")

    summary = run_replay(args.path)
    if args.mode == "summary":
        render_replay_summary(summary, console)
        return
    if args.mode == "trades":
        render_replay_trades(summary.get("trades", []), console)
        return
    render_replay_dashboard(summary, console)


def main() -> None:
    run_replay_cli()


__all__ = ["build_parser", "run_replay_cli", "main"]
