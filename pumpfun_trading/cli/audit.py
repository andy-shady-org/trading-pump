"""CLI commands for audit trail inspection and export."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from rich.table import Table

from pumpfun_trading.bot.audit import (
    export_audit_records,
    filter_audit_records,
    load_audit_records,
    render_audit_table,
    summarize_audit_records,
)
from pumpfun_trading.bot.pnl import PNL_GROUPS, summarize_pnl, trade_payloads
from pumpfun_trading.bot.sweep import sweep_payloads
from pumpfun_trading.bot.reconcile import (
    DEFAULT_TOLERANCE_ABS_SOL,
    DEFAULT_TOLERANCE_PCT,
    ReconciliationReport,
    reconcile_status_path,
    reconcile_wallet,
    write_reconciliation_status,
)
from pumpfun_trading.ops.logging import get_configured_console

console = get_configured_console()

AUDIT_COMMANDS = ("pnl", "reconcile")


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "audit", description="Inspect the JSONL audit trail"
        )
    else:
        parser = argparse.ArgumentParser(description="Inspect the JSONL audit trail")
    # ``dest`` must not be ``command``: the unified CLI uses that for its subparsers.
    parser.add_argument(
        "audit_command",
        metavar="command",
        nargs="?",
        choices=AUDIT_COMMANDS,
        default=None,
        help=(
            "pnl: net PnL report (fees, tips, rent); reconcile: compare the audit "
            "trail with the wallet on-chain. Omit to list records."
        ),
    )
    parser.add_argument("--path", required=True, help="Path to the JSONL audit file")
    parser.add_argument("--record-type", default=None, help="Filter by record type")
    parser.add_argument("--state", default=None, help="Filter by state")
    parser.add_argument("--date-from", default=None, help="Start timestamp or ISO date")
    parser.add_argument("--date-to", default=None, help="End timestamp or ISO date")
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--mint-name", default=None, help="Filter by mint name")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
    parser.add_argument("--reason", default=None, help="Filter by trade reason")
    parser.add_argument(
        "--status", default=None, help="Filter by record outcome/status"
    )
    parser.add_argument(
        "--min-buy-price",
        type=float,
        default=None,
        help="Minimum buy price in SOL",
    )
    parser.add_argument(
        "--max-buy-price",
        type=float,
        default=None,
        help="Maximum buy price in SOL",
    )
    parser.add_argument(
        "--min-sell-price",
        type=float,
        default=None,
        help="Minimum sell price in SOL",
    )
    parser.add_argument(
        "--max-sell-price",
        type=float,
        default=None,
        help="Maximum sell price in SOL",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum records to return"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary statistics instead of rows",
    )
    parser.add_argument(
        "--json", action="store_true", help="Export filtered records as JSON to stdout"
    )
    parser.add_argument(
        "--export", default=None, help="Write filtered records to a JSON file"
    )
    parser.add_argument(
        "--group-by",
        choices=PNL_GROUPS,
        default=None,
        help="pnl: break the totals down by day, exit/entry reason, strategy or mint",
    )
    parser.add_argument(
        "--wallet", default=None, help="reconcile: wallet public key to check"
    )
    parser.add_argument(
        "--rpc-url",
        default=None,
        help="reconcile: Solana RPC URL (default: PUMPFUN_RPC_URL / SOLANA_RPC_URL)",
    )
    parser.add_argument(
        "--start-balance",
        type=float,
        default=None,
        help="reconcile: wallet SOL balance at the start of the period (whole-wallet check)",
    )
    parser.add_argument(
        "--tolerance-sol",
        type=float,
        default=DEFAULT_TOLERANCE_ABS_SOL,
        help="reconcile: absolute tolerance in SOL (default: 0.002)",
    )
    parser.add_argument(
        "--tolerance-pct",
        type=float,
        default=DEFAULT_TOLERANCE_PCT,
        help="reconcile: relative tolerance (default: 0.05 = 5%%)",
    )
    parser.add_argument(
        "--no-token-check",
        action="store_true",
        help="reconcile: skip the on-chain token-balance check",
    )
    parser.add_argument(
        "--status-file",
        default=None,
        help=(
            "reconcile: where to store the result for the dashboard "
            "(default: reconcile_status.json next to --path)"
        ),
    )
    parser.add_argument(
        "--no-status-file",
        action="store_true",
        help="reconcile: do not store the result",
    )
    return parser


def build_audit_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def _fmt_sol(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.6f}"


def render_pnl_summary(summary: dict[str, Any]) -> None:
    """Prints the net PnL summary as Rich tables."""
    totals = summary["totals"]
    table = Table(title=f"Net PnL ({summary['trades']} trade records)")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    share = totals.get("cost_share_of_gross")
    for label, value in (
        ("Gross PnL (SOL)", _fmt_sol(totals["gross_pnl_sol"])),
        ("Fees (SOL)", _fmt_sol(totals["fees_sol"])),
        ("Jito tips (SOL)", _fmt_sol(totals["tips_sol"])),
        ("Net rent (SOL)", _fmt_sol(totals["rent_sol"])),
        ("Net PnL (SOL)", _fmt_sol(totals["net_pnl_sol"])),
        ("Buys / sells", f"{totals['buys']} / {totals['sells']}"),
        ("Positions closed", str(totals.get("positions_closed", 0))),
        ("Win rate per position (net)", f"{totals['win_rate']:.1%}"),
        ("Expectancy per position (SOL)", _fmt_sol(totals["expectancy_sol"])),
        ("Win rate per sell (detail)", f"{totals.get('sell_win_rate', 0.0):.1%}"),
        ("Costs / gross", "-" if share is None else f"{share:.1%}"),
    ):
        table.add_row(label, value)
    console.print(table)
    sources = summary.get("cost_sources") or {}
    if sources.get("none"):
        console.print(
            f"[yellow]{sources['none']} record(s) have no cost data (written before "
            "Sprint 24B, or live sells measured from the wallet delta, which is "
            "already net of fee and tip).[/yellow]"
        )
    groups = summary.get("groups")
    if groups:
        breakdown = Table(title=f"By {summary['group_by']}")
        for column in (
            summary["group_by"],
            "Sells",
            "Positions",
            "Gross",
            "Costs",
            "Net",
            "Win",
        ):
            breakdown.add_column(
                column,
                justify="right" if column in ("Sells", "Positions") else "left",
            )
        for key, row in groups.items():
            breakdown.add_row(
                key,
                str(row["sells"]),
                str(row.get("positions_closed", 0)),
                _fmt_sol(row["gross_pnl_sol"]),
                _fmt_sol(row["costs_sol"]),
                _fmt_sol(row["net_pnl_sol"]),
                f"{row['win_rate']:.0%}",
            )
        console.print(breakdown)


def render_reconciliation(report: ReconciliationReport) -> None:
    status = "[green]OK[/green]" if report.ok else "[red]GAP[/red]"
    console.print(f"Reconciliation for {report.wallet}: {status}")
    console.print(
        f"  trades verified: {report.trades_checked} "
        f"(skipped paper/unsigned: {report.trades_skipped})"
    )
    console.print(
        f"  cash flow audit {_fmt_sol(report.recorded_cash_flow_sol)} SOL vs "
        f"chain {_fmt_sol(report.onchain_cash_flow_sol)} SOL "
        f"(gap {_fmt_sol(report.cash_flow_gap_sol)}, "
        f"tolerance {report.tolerance_sol:.6f})"
    )
    console.print(f"  open cost basis: {report.open_cost_basis_sol:.6f} SOL")
    if report.wallet_gap_sol is not None:
        console.print(
            f"  wallet {report.wallet_balance_sol:.6f} SOL, started "
            f"{report.start_balance_sol:.6f} SOL, unexplained {_fmt_sol(report.wallet_gap_sol)}"
        )
        if report.swept_sol:
            console.print(f"  profit sweeps: {report.swept_sol:.6f} SOL (fees incl.)")
    for mint, amount in report.lost_positions.items():
        console.print(f"  [red]lost position[/red] {mint}: {amount} raw tokens")
    for mint in report.phantom_positions:
        console.print(f"  [red]phantom position[/red] {mint}: no tokens on-chain")
    for check in report.unreadable_trades:
        console.print(f"  [red]unverified[/red] {check.signature}: {check.error}")
    for check in report.trade_mismatches:
        console.print(
            f"  [yellow]trade differs[/yellow] {check.action} {check.signature}: "
            f"audit {_fmt_sol(check.recorded_sol)} vs chain {_fmt_sol(check.onchain_sol)}"
        )
    for problem in report.problems:
        console.print(f"  [red]- {problem}[/red]")
    for warning in report.warnings:
        console.print(f"  [yellow]- {warning}[/yellow]")


async def _run_reconcile(
    args: argparse.Namespace,
    trades: list[dict[str, Any]],
    sweeps: list[dict[str, Any]] | None = None,
) -> ReconciliationReport:
    from pumpfun_trading.infra.rpc_pool import RpcConnectionPool

    rpc_url = (
        args.rpc_url
        or os.getenv("PUMPFUN_RPC_URL")
        or os.getenv("SOLANA_RPC_URL")
        or "https://api.mainnet-beta.solana.com"
    )
    pool = RpcConnectionPool(endpoints=(rpc_url,))

    async def rpc(payload: dict[str, Any]) -> dict[str, Any]:
        return await pool.request(payload, max_retries=2, timeout_seconds=10.0)

    try:
        return await reconcile_wallet(
            trades,
            wallet=args.wallet,
            rpc=rpc,
            tolerance_abs_sol=args.tolerance_sol,
            tolerance_pct=args.tolerance_pct,
            start_balance_sol=args.start_balance,
            check_tokens=not args.no_token_check,
            sweeps=sweeps or (),
        )
    finally:
        await pool.close()


def run_audit_cli(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = build_parser().parse_args()

    records = load_audit_records(args.path)
    command = getattr(args, "audit_command", None)
    if command in AUDIT_COMMANDS:
        _run_audit_command(args, records, command)
        return
    filtered = filter_audit_records(
        records,
        record_type=args.record_type,
        state=args.state,
        date_from=args.date_from,
        date_to=args.date_to,
        mint=args.mint,
        token_name=args.token_name,
        mint_name=getattr(args, "mint_name", None),
        reason=args.reason,
        status=args.status,
        min_buy_price=getattr(args, "min_buy_price", None),
        max_buy_price=getattr(args, "max_buy_price", None),
        min_sell_price=getattr(args, "min_sell_price", None),
        max_sell_price=getattr(args, "max_sell_price", None),
        limit=args.limit,
    )

    if args.summary:
        summary = summarize_audit_records(filtered)
        console.print(json.dumps(summary, indent=2, sort_keys=True))
        return

    if args.export:
        exported = export_audit_records(filtered, args.export)
        console.print(f"[green]Exported {len(filtered)} records to {exported}[/green]")
        return

    if args.json:
        console.print(json.dumps(filtered, indent=2, ensure_ascii=False, default=str))
        return

    if not filtered:
        console.print("[yellow]No matching audit records found.[/yellow]")
        return

    render_audit_table(filtered, console)


def _run_audit_command(
    args: argparse.Namespace, records: list[dict[str, Any]], command: str
) -> None:
    trade_records = filter_audit_records(
        records,
        record_type="trade",
        date_from=args.date_from,
        date_to=args.date_to,
        mint=args.mint,
        reason=args.reason,
    )
    trades = trade_payloads(trade_records)
    if command == "pnl":
        summary = summarize_pnl(trades, group_by=getattr(args, "group_by", None))
        if args.json:
            console.print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            render_pnl_summary(summary)
        return

    if not args.wallet:
        console.print("[red]reconcile needs --wallet <pubkey>[/red]")
        raise SystemExit(2)
    # Profit sweeps leave the wallet on purpose; the wallet check counts them.
    report = asyncio.run(_run_reconcile(args, trades, sweep_payloads(records)))
    if not getattr(args, "no_status_file", False):
        status_path = getattr(args, "status_file", None) or reconcile_status_path(
            args.path
        )
        if status_path is not None:
            try:
                write_reconciliation_status(report, status_path)
            except OSError as exc:
                console.print(
                    f"[yellow]Could not store reconciliation status: {exc}[/yellow]"
                )
    if args.json:
        console.print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        render_reconciliation(report)
    if not report.ok:
        # Non-zero exit so cron/systemd checks flag the gap (RELEASE-GATE §3.4).
        raise SystemExit(1)


def main() -> None:
    run_audit_cli()


__all__ = [
    "build_parser",
    "main",
    "render_pnl_summary",
    "render_reconciliation",
    "run_audit_cli",
]
