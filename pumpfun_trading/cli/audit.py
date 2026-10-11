"""CLI commands for audit trail inspection and export."""

from __future__ import annotations

import argparse
import json

from pumpfun_trading.bot.audit import (
    export_audit_records,
    filter_audit_records,
    load_audit_records,
    render_audit_table,
    summarize_audit_records,
)
from pumpfun_trading.ops.logging import get_configured_console

console = get_configured_console()


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "audit", description="Inspect the JSONL audit trail"
        )
    else:
        parser = argparse.ArgumentParser(description="Inspect the JSONL audit trail")
    parser.add_argument("--path", required=True, help="Path to the JSONL audit file")
    parser.add_argument("--record-type", default=None, help="Filter by record type")
    parser.add_argument("--state", default=None, help="Filter by state")
    parser.add_argument("--date-from", default=None, help="Start timestamp or ISO date")
    parser.add_argument("--date-to", default=None, help="End timestamp or ISO date")
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
    parser.add_argument("--reason", default=None, help="Filter by trade reason")
    parser.add_argument(
        "--status", default=None, help="Filter by record outcome/status"
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
    return parser


def build_audit_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def run_audit_cli(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = build_parser().parse_args()

    records = load_audit_records(args.path)
    filtered = filter_audit_records(
        records,
        record_type=args.record_type,
        state=args.state,
        date_from=args.date_from,
        date_to=args.date_to,
        mint=args.mint,
        token_name=args.token_name,
        reason=args.reason,
        status=args.status,
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


def main() -> None:
    run_audit_cli()


__all__ = ["build_parser", "run_audit_cli", "main"]
