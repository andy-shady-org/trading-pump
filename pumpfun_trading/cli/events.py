"""CLI commands for diagnostic event telemetry inspection, tailing, and analytics (FEAT-30)."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from pumpfun_trading.ops.events import DiagnosticEvent, EventSeverity
from pumpfun_trading.ops.logging import get_configured_console

console = get_configured_console()


def load_diagnostic_events(path: str | Path) -> list[DiagnosticEvent]:
    """Loads and deserializes diagnostic telemetry events from a JSONL file."""
    target_path = Path(path)
    if not target_path.exists():
        return []

    events: list[DiagnosticEvent] = []
    with open(target_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                events.append(DiagnosticEvent.from_dict(data))
            except Exception:
                continue
    return events


def filter_diagnostic_events(
    events: list[DiagnosticEvent],
    *,
    category: str | None = None,
    severity: str | None = None,
    mint: str | None = None,
    mint_name: str | None = None,
    event_name: str | None = None,
    errors_only: bool = False,
    limit: int | None = None,
) -> list[DiagnosticEvent]:
    """Filters diagnostic events according to operator criteria."""
    filtered: list[DiagnosticEvent] = []

    cat_target = category.lower().strip() if category else None
    sev_target = severity.lower().strip() if severity else None
    mint_target = mint.lower().strip() if mint else None
    name_target = mint_name.lower().strip() if mint_name else None
    evt_target = event_name.lower().strip() if event_name else None

    for evt in events:
        if cat_target and evt.category.value.lower() != cat_target:
            continue
        if sev_target and evt.severity.value.lower() != sev_target:
            continue
        if errors_only and evt.severity not in {
            EventSeverity.WARNING,
            EventSeverity.ERROR,
            EventSeverity.CRITICAL,
        }:
            continue
        if mint_target and (not evt.mint or mint_target not in evt.mint.lower()):
            continue
        if name_target and (
            not evt.mint_name or name_target not in evt.mint_name.lower()
        ):
            continue
        if evt_target and evt_target not in evt.event_name.lower():
            continue

        filtered.append(evt)

    if limit is not None and limit > 0:
        filtered = filtered[-limit:]

    return filtered


def calculate_latency_stats(events: list[DiagnosticEvent]) -> dict[str, Any]:
    """Computes distribution analytics over recorded event latencies."""
    latencies: list[float] = []
    by_category: dict[str, list[float]] = {}
    by_event: dict[str, list[float]] = {}

    for evt in events:
        if evt.latency_ms is not None and evt.latency_ms >= 0:
            val = float(evt.latency_ms)
            latencies.append(val)
            cat_key = evt.category.value
            by_category.setdefault(cat_key, []).append(val)
            by_event.setdefault(evt.event_name, []).append(val)

    if not latencies:
        return {"total_events_with_latency": 0}

    def _stats(arr: list[float]) -> dict[str, float]:
        sorted_arr = sorted(arr)
        n = len(sorted_arr)
        p50 = sorted_arr[int(n * 0.50)]
        p95 = sorted_arr[min(n - 1, int(n * 0.95))]
        p99 = sorted_arr[min(n - 1, int(n * 0.99))]
        return {
            "count": n,
            "min_ms": round(sorted_arr[0], 2),
            "avg_ms": round(sum(sorted_arr) / n, 2),
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "max_ms": round(sorted_arr[-1], 2),
        }

    return {
        "overall": _stats(latencies),
        "by_category": {cat: _stats(vals) for cat, vals in by_category.items()},
        "by_event": {evt: _stats(vals) for evt, vals in by_event.items()},
    }


def render_latency_table(
    stats: dict[str, Any], console_out: Console | None = None
) -> None:
    """Renders formatted Rich tables for latency metrics."""
    c = console_out or console
    if not stats or not stats.get("overall"):
        c.print("[yellow]No latency telemetry recorded in selected events.[/yellow]")
        return

    table = Table(
        title="Diagnostic Telemetry Latency Analytics",
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("Subsystem / Event", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Min (ms)", justify="right")
    table.add_column("Avg (ms)", justify="right")
    table.add_column("P50 (ms)", justify="right")
    table.add_column("P95 (ms)", justify="right")
    table.add_column("P99 (ms)", justify="right")
    table.add_column("Max (ms)", justify="right")

    overall = stats["overall"]
    table.add_row(
        "[bold cyan]Overall Portfolio[/bold cyan]",
        str(overall["count"]),
        str(overall["min_ms"]),
        str(overall["avg_ms"]),
        str(overall["p50_ms"]),
        str(overall["p95_ms"]),
        str(overall["p99_ms"]),
        str(overall["max_ms"]),
    )

    for cat, s in stats.get("by_category", {}).items():
        table.add_row(
            f"Category: {cat}",
            str(s["count"]),
            str(s["min_ms"]),
            str(s["avg_ms"]),
            str(s["p50_ms"]),
            str(s["p95_ms"]),
            str(s["p99_ms"]),
            str(s["max_ms"]),
        )

    for evt, s in stats.get("by_event", {}).items():
        table.add_row(
            f"  {evt}",
            str(s["count"]),
            str(s["min_ms"]),
            str(s["avg_ms"]),
            str(s["p50_ms"]),
            str(s["p95_ms"]),
            str(s["p99_ms"]),
            str(s["max_ms"]),
        )

    c.print(table)


def render_events_table(
    events: list[DiagnosticEvent], console_out: Console | None = None
) -> None:
    """Renders formatted Rich table for diagnostic events."""
    c = console_out or console
    if not events:
        c.print("[yellow]No matching diagnostic events found.[/yellow]")
        return

    table = Table(
        title=f"Diagnostic Telemetry Events ({len(events)} records)",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("Timestamp (UTC)", style="dim")
    table.add_column("Category", style="bold")
    table.add_column("Severity")
    table.add_column("Event Name", style="bold")
    table.add_column("Mint", overflow="fold")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Details", overflow="fold")

    for evt in events:
        # Severity styling
        sev_color = {
            EventSeverity.DEBUG: "dim",
            EventSeverity.INFO: "green",
            EventSeverity.WARNING: "yellow",
            EventSeverity.ERROR: "red bold",
            EventSeverity.CRITICAL: "red bold reverse",
        }.get(evt.severity, "white")

        sev_str = f"[{sev_color}]{evt.severity.value.upper()}[/{sev_color}]"

        # Details formatting
        details_parts = []
        if evt.error_message:
            details_parts.append(f"[red]Error: {evt.error_message}[/red]")
        for k, v in evt.data.items():
            details_parts.append(f"{k}={v}")
        details_str = " | ".join(details_parts) if details_parts else "-"

        mint_display = evt.mint_name or (
            evt.mint[:8] + "..."
            if evt.mint and len(evt.mint) > 8
            else (evt.mint or "-")
        )
        latency_str = f"{evt.latency_ms:.2f}" if evt.latency_ms is not None else "-"

        table.add_row(
            evt.iso_timestamp[:19].replace("T", " "),
            evt.category.value,
            sev_str,
            evt.event_name,
            mint_display,
            latency_str,
            details_str,
        )

    c.print(table)


def build_events_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    """Builds argument parser for the events inspection CLI."""
    if subparsers is not None:
        parser = subparsers.add_parser(
            "events",
            description="Inspect, tail, and analyze runtime diagnostic telemetry events (FEAT-30)",
        )
    else:
        parser = argparse.ArgumentParser(
            description="Inspect, tail, and analyze runtime diagnostic telemetry events (FEAT-30)"
        )

    parser.add_argument(
        "--path",
        default="events.jsonl",
        help="Path to the JSONL diagnostic events file (default: events.jsonl)",
    )
    parser.add_argument(
        "--category",
        choices=["stream", "screening", "strategy", "execution", "risk", "lifecycle"],
        default=None,
        help="Filter by event category subsystem",
    )
    parser.add_argument(
        "--severity",
        choices=["debug", "info", "warning", "error", "critical"],
        default=None,
        help="Filter by severity level",
    )
    parser.add_argument(
        "--mint",
        default=None,
        help="Filter by token mint address",
    )
    parser.add_argument(
        "--mint-name",
        default=None,
        help="Filter by token symbol or display name",
    )
    parser.add_argument(
        "--event-name",
        default=None,
        help="Filter by event action name",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Show only warning, error, and critical severity events",
    )
    parser.add_argument(
        "--latency-stats",
        action="store_true",
        help="Calculate and render latency distribution metrics",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum records to display (default: 50)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit filtered records as JSON to stdout",
    )
    parser.add_argument(
        "--export",
        default=None,
        help="Export filtered records to destination JSON file",
    )
    parser.add_argument(
        "--tail",
        action="store_true",
        help="Follow the events file continuously in real time",
    )
    return parser


def run_events_cli(args: argparse.Namespace | None = None) -> None:
    """Executes the diagnostic events CLI."""
    if args is None:
        args = build_events_parser().parse_args()

    target_path = Path(args.path)

    if args.tail:
        if not target_path.exists():
            console.print(
                f"[yellow]Waiting for events file {target_path} to be created...[/yellow]"
            )
        console.print(f"[cyan]Tailing {target_path}... (Press Ctrl+C to stop)[/cyan]")
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.2)
                        continue
                    try:
                        record = json.loads(line.strip())
                        evt = DiagnosticEvent.from_dict(record)
                        matches = filter_diagnostic_events(
                            [evt],
                            category=args.category,
                            severity=args.severity,
                            mint=args.mint,
                            mint_name=args.mint_name,
                            event_name=args.event_name,
                            errors_only=args.errors_only,
                        )
                        if matches:
                            if args.json:
                                console.print(json.dumps(evt.to_dict()))
                            else:
                                render_events_table([evt])
                    except Exception:
                        pass
        except KeyboardInterrupt:
            console.print("\n[dim]Tailing stopped.[/dim]")
            return
        except Exception as exc:
            console.print(f"[red]Error while tailing file: {exc}[/red]")
            return

    events = load_diagnostic_events(target_path)
    filtered = filter_diagnostic_events(
        events,
        category=args.category,
        severity=args.severity,
        mint=args.mint,
        mint_name=args.mint_name,
        event_name=args.event_name,
        errors_only=args.errors_only,
        limit=args.limit if not (args.latency_stats or args.export) else None,
    )

    if args.latency_stats:
        stats = calculate_latency_stats(filtered)
        if args.json:
            console.print(json.dumps(stats, indent=2))
        else:
            render_latency_table(stats)
        return

    if args.export:
        export_path = Path(args.export)
        payload = [e.to_dict() for e in filtered]
        if export_path.parent:
            os.makedirs(export_path.parent, exist_ok=True)
        export_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(
            f"[green]Exported {len(filtered)} diagnostic events to {export_path}[/green]"
        )
        return

    if args.json:
        console.print(json.dumps([e.to_dict() for e in filtered], indent=2))
        return

    render_events_table(filtered)


def main() -> None:
    """Entry point for standalone pumpfun-events script."""
    run_events_cli()


__all__ = [
    "build_events_parser",
    "calculate_latency_stats",
    "filter_diagnostic_events",
    "load_diagnostic_events",
    "main",
    "render_events_table",
    "render_latency_table",
    "run_events_cli",
]
