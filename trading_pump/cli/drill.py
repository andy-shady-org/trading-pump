"""``pumpfun-drill`` / ``pumpfun ops drill``: scripted risk drills (FEAT-69)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from rich.table import Table

from trading_pump.ops.drills import DRILL_NAMES, DrillReport, run_drills
from trading_pump.ops.logging import get_configured_console

console = get_configured_console()


def add_drill_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--only",
        action="append",
        choices=DRILL_NAMES,
        default=None,
        metavar="DRILL",
        help=f"Run only this drill (repeatable): {', '.join(DRILL_NAMES)}",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Keep each drill's status file, audit trail and log here (default: a temp dir)",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Also write the JSON report here (for the release record)",
    )
    parser.add_argument("--json", action="store_true", help="Print the JSON report")
    parser.add_argument("--list", action="store_true", help="List the drills and exit")
    return parser


def build_parser() -> argparse.ArgumentParser:
    return add_drill_arguments(
        argparse.ArgumentParser(
            description=(
                "Run the scripted risk drills on a paper bot: no network, no wallet, "
                "exit code 1 when a drill fails (FEAT-69)"
            )
        )
    )


def render_drill_report(report: DrillReport, out: Any = None) -> None:
    target = out or console
    for result in report.results:
        table = Table(
            title=f"{result.name}: {result.title}",
            header_style="bold cyan",
            title_justify="left",
        )
        table.add_column("Result")
        table.add_column("Check")
        table.add_column("Detail")
        if result.error:
            table.add_row("[red]ERROR[/red]", "drill raised", result.error)
        for check in result.checks:
            table.add_row(
                "[green]pass[/green]" if check.passed else "[red]FAIL[/red]",
                check.description,
                check.detail,
            )
        target.print(table)
    passed = sum(1 for r in report.results if r.passed)
    colour = "green" if report.passed else "red"
    target.print(
        f"[bold {colour}]{passed} of {len(report.results)} drills passed[/bold {colour}]"
        f"  (files: {report.workdir})"
    )


def run_drill_cli(args: argparse.Namespace) -> None:
    from trading_pump.ops.drills import DRILLS

    if getattr(args, "list", False):
        for name in DRILL_NAMES:
            doc = (DRILLS[name].__doc__ or "").strip()
            console.print(f"{name}{': ' + doc if doc else ''}")
        return
    report = asyncio.run(
        run_drills(getattr(args, "only", None), workdir=getattr(args, "workdir", None))
    )
    data = report.to_dict()
    report_path = getattr(args, "report", None)
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    if getattr(args, "json", False):
        console.print(json.dumps(data, indent=2))
    else:
        render_drill_report(report)
    if not report.passed:
        raise SystemExit(1)


def main() -> None:
    run_drill_cli(build_parser().parse_args())


__all__ = [
    "add_drill_arguments",
    "build_parser",
    "main",
    "render_drill_report",
    "run_drill_cli",
]
