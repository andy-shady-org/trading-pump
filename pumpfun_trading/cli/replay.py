"""Replay CLI entrypoints for historical market-data sessions."""

from __future__ import annotations

import argparse
from typing import Any

from rich.table import Table

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
        choices=["conservative", "balanced", "aggressive", "momentum"],
        default=None,
        help="Trading strategy preset",
    )
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--mint-name", default=None, help="Filter by mint name")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
    parser.add_argument(
        "--simple-exits",
        action="store_true",
        help=(
            "With --config/--preset, use the legacy take-profit/stop-loss replay "
            "instead of the live sizing and exit stack"
        ),
    )
    parser.add_argument(
        "--no-costs",
        action="store_true",
        help="Live-fidelity replay without modelled fees, tips and rent (gross PnL)",
    )
    parser.add_argument(
        "--tip-lamports",
        type=int,
        default=None,
        help="Modelled Jito tip per trade (default: PUMPFUN_JITO_TIP_LAMPORTS, 0 if PUMPFUN_USE_JITO=false)",
    )
    parser.add_argument(
        "--priority-fee-lamports",
        type=int,
        default=0,
        help="Modelled priority fee per trade in lamports",
    )
    parser.add_argument(
        "--compare-audit",
        default=None,
        metavar="AUDIT_PATH",
        help=(
            "Compare the live-fidelity replay with this audit trail (replay-vs-live "
            "parity); exits 1 when net PnL differs by more than the tolerance"
        ),
    )
    parser.add_argument(
        "--parity-tolerance-sol",
        type=float,
        default=0.002,
        help="Absolute net PnL tolerance for --compare-audit (SOL)",
    )
    parser.add_argument(
        "--parity-tolerance-pct",
        type=float,
        default=0.10,
        help="Relative net PnL tolerance for --compare-audit (fraction of live net PnL)",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100.0,
        help="Initial cash balance in SOL",
    )
    parser.add_argument(
        "--shadow-report",
        action="store_true",
        help=(
            "Read out the capture's shadow variants (FEAT-58): signals, fill drift, "
            "refusals and a modelled net PnL per variant against a random cut of "
            "the baseline variant; needs --config (the capture's config)"
        ),
    )
    parser.add_argument(
        "--split-at",
        default=None,
        metavar="mid|TIMESTAMP",
        help="--shadow-report: also report halves A/B split at this time ('mid' = middle)",
    )
    parser.add_argument(
        "--shadow-baseline",
        default="baseline",
        help="--shadow-report: variant the random cut is taken from (default: baseline)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="--shadow-report: print the report as JSON",
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

    if getattr(args, "shadow_report", False):
        _run_shadow_report(target_path, config, args)
        return

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
        # A config/preset replays with the live sizing and exit stack (BUG-61)
        # and, unless --no-costs, books modelled fees, tips and rent.
        live = config is not None and not getattr(args, "simple_exits", False)
        cost_model = None
        if live and config is not None and not getattr(args, "no_costs", False):
            from pumpfun_trading.engines.costs import ReplayCostModel

            cost_model = ReplayCostModel.from_env(
                close_token_account_on_full_exit=config.close_token_account_on_full_exit,
                priority_fee_lamports=getattr(args, "priority_fee_lamports", 0),
                tip_lamports=getattr(args, "tip_lamports", None),
            )
        engine = PaperTradingEngine(
            initial_cash=initial_cash,
            take_profit=take_profit,
            stop_loss=stop_loss,
            max_positions=max_positions,
            strategy_config=config,
            live_fidelity=live,
            cost_model=cost_model,
        )

    summary = run_replay(
        target_path,
        engine=engine,
        mint=getattr(args, "mint", None),
        mint_name=getattr(args, "mint_name", None),
        token_name=getattr(args, "token_name", None),
    )
    audit_path = getattr(args, "compare_audit", None)
    if audit_path:
        _run_parity(summary, audit_path, args)
        return
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


def _run_shadow_report(target_path: str, config: Any, args: argparse.Namespace) -> None:
    """Print the shadow-variant read-out of a paper capture (FEAT-58)."""
    import json

    from pumpfun_trading.engines.replay import PaperTradingEngine
    from pumpfun_trading.engines.shadow_report import (
        build_shadow_report,
        render_shadow_report,
    )

    if config is None:
        raise SystemExit(
            "--shadow-report needs --config (the config the capture ran with) or "
            "--preset, for the exits and the paper entry penalty"
        )
    cost_model = None
    if not getattr(args, "no_costs", False):
        from pumpfun_trading.engines.costs import ReplayCostModel

        cost_model = ReplayCostModel.from_env(
            close_token_account_on_full_exit=config.close_token_account_on_full_exit,
            priority_fee_lamports=getattr(args, "priority_fee_lamports", 0),
            tip_lamports=getattr(args, "tip_lamports", None),
        )
    try:
        report = build_shadow_report(
            PaperTradingEngine.load_history(target_path),
            config,
            cost_model=cost_model,
            split_at=getattr(args, "split_at", None),
            baseline=getattr(args, "shadow_baseline", None) or "baseline",
        )
    except ValueError as exc:
        raise SystemExit(f"--shadow-report: {exc}") from exc
    if getattr(args, "json", False):
        console.print_json(json.dumps(report, default=str))
        return
    render_shadow_report(report, console)


def _run_parity(
    summary: dict[str, Any], audit_path: str, args: argparse.Namespace
) -> None:
    """Print the replay-vs-live parity report; exit 1 outside the tolerance."""
    from pumpfun_trading.bot.audit import load_audit_records
    from pumpfun_trading.bot.pnl import trade_payloads
    from pumpfun_trading.engines.parity import compare_replay_to_audit

    if not summary.get("live_fidelity"):
        raise SystemExit(
            "--compare-audit needs a live-fidelity replay: pass --config or --preset "
            "and don't use --simple-exits"
        )
    report = compare_replay_to_audit(
        summary.get("trades", []),
        trade_payloads(load_audit_records(audit_path)),
        tolerance_sol=float(getattr(args, "parity_tolerance_sol", 0.002)),
        tolerance_pct=float(getattr(args, "parity_tolerance_pct", 0.10)),
    )
    table = Table(title="Replay vs live (per mint)", header_style="bold cyan")
    for column in (
        "Mint",
        "Status",
        "Live exits",
        "Replay exits",
        "Live net",
        "Replay net",
    ):
        table.add_column(column)
    for row in report["mints"]:
        if row["status"] == "no_entry":
            continue
        table.add_row(
            str(row["mint"])[:12],
            row["status"]
            + (
                ""
                if row["exit_match"] or row["status"] != "both"
                else " (exit differs)"
            ),
            ", ".join(row["live_exits"]) or "-",
            ", ".join(row["replay_exits"]) or "-",
            f"{row['live_net_pnl_sol']:.6f}",
            f"{row['replay_net_pnl_sol']:.6f}",
        )
    console.print(table)
    counts = report["counts"]
    verdict = "PASS" if report["within_tolerance"] else "GAP"
    console.print(
        f"Entries in both: {counts['both']} (same exit: {counts['exit_match']}), "
        f"live only: {counts['live_only']}, replay only: {counts['replay_only']}\n"
        f"Net PnL live {report['live_net_pnl_sol']:.6f} SOL, replay "
        f"{report['replay_net_pnl_sol']:.6f} SOL, gap {report['gap_sol']:+.6f} "
        f"(allowed ±{report['allowed_gap_sol']:.6f}): {verdict}"
    )
    if not report["within_tolerance"]:
        raise SystemExit(1)


def main() -> None:
    run_replay_cli()


__all__ = ["build_parser", "run_replay_cli", "main"]
