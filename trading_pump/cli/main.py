"""``trading-pump``: the module's own tools (the engine is ``trading-core``).

* ``trading-pump record ...``: the record-only research recorders
  (``--jupiter-quotes``, ``--backfill-bars``), as ``trading-pump-recorder``
  (the cross-chain ``--market`` recorder moved to trading-scout);
* ``trading-pump replay --config F --capture C [C ...] --out DIR``: replay
  captures through trading-core's engine with the module (``replay.py``);
* ``trading-pump lane-rows --capture C [C ...] --out FILE``: a capture as
  trading-core's strategy library rows, for ``trading-core-lanes sweep``
  (``lanes.py``, trading-core FEAT-133);
* ``trading-pump env``: which ``PUMPFUN_*`` variables are set and read
  (names only).

Running the module is trading-core's job: ``trading-core run --config F``
with ``"module": "pumpfun"``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from rich.table import Table
from trading_core.config.settings import EngineSettings
from trading_core.lanes.market import ROW_HOLDERS, ROW_LISTING, ROW_READING, ROW_TRADE
from trading_core.ops.logging import get_configured_console

from trading_pump.cli.record import build_record_parser, run_record_cli
from trading_pump.config.env import MODULE_ENV_VARS, unread_env_warnings
from trading_pump.lanes import SOURCES, LaneRowStats, write_lane_rows
from trading_pump.replay import (
    DEFAULT_REPLAY_FEE_BPS,
    CaptureMarket,
    read_rows,
    replay_capture,
)

console = get_configured_console()

EXIT_OK = 0
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-pump", description="Pump.fun / PumpSwap module tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build_record_parser(sub)
    replay = sub.add_parser(
        "replay", description="Replay captures through the engine with the module"
    )
    replay.add_argument("--config", required=True, help="trading-core settings JSON")
    replay.add_argument(
        "--capture", nargs="+", required=True, help="capture files (.jsonl, .gz)"
    )
    replay.add_argument("--out", required=True, help="new directory for the run")
    replay.add_argument(
        "--fee-bps",
        type=int,
        default=DEFAULT_REPLAY_FEE_BPS,
        help="swap fee a side in basis points (default: %(default)s)",
    )
    lane_rows = sub.add_parser(
        "lane-rows",
        description="Write captures as trading-core's strategy library rows",
    )
    lane_rows.add_argument(
        "--capture", nargs="+", required=True, help="capture files (.jsonl, .gz)"
    )
    lane_rows.add_argument(
        "--out", required=True, help="new file for the rows (.jsonl or .jsonl.gz)"
    )
    lane_rows.add_argument(
        "--source",
        nargs="+",
        choices=SOURCES,
        default=list(SOURCES),
        help="which captured pools to write (default: all)",
    )
    sub.add_parser("env", description="PUMPFUN_* variables: set, read, unread")
    return parser


def _stamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d %H:%M")


def run_replay(args: argparse.Namespace) -> int:
    try:
        settings = EngineSettings.from_file(args.config)
        market = CaptureMarket.from_rows(read_rows(args.capture))
        result = asyncio.run(
            replay_capture(market, settings, args.out, fee_bps=args.fee_bps)
        )
    except (OSError, ValueError, TypeError) as exc:
        console.print(f"[red]Cannot replay: {exc}[/red]")
        return EXIT_USAGE
    totals = result.totals
    table = Table(title="Replay")
    table.add_column("", style="bold cyan")
    table.add_column("")
    rows = [
        ("Span (UTC)", f"{_stamp(result.start)} -> {_stamp(result.end)}"),
        ("Migrations", str(result.migrations)),
        ("Engine cycles", str(result.cycles)),
        ("Closed positions", str(totals.get("positions_closed", 0))),
        ("Win rate", f"{float(totals.get('win_rate') or 0.0):.1%}"),
        ("Net PnL", f"{float(totals.get('net_pnl', 0.0)):+.6f} SOL"),
        ("Costs", f"{float(totals.get('costs', 0.0)):.6f} SOL"),
        ("Audit trail", str(result.audit_log_path)),
    ]
    for name, value in rows:
        table.add_row(name, value)
    console.print(table)
    console.print(
        f"Next: trading-core-audit pnl --path {result.audit_log_path} "
        "--group-by reason"
    )
    return EXIT_OK


def run_lane_rows(args: argparse.Namespace) -> int:
    try:
        stats = write_lane_rows(args.capture, args.out, sources=args.source)
    except (OSError, ValueError) as exc:
        console.print(f"[red]Cannot write lane rows: {exc}[/red]")
        return EXIT_USAGE
    console.print(_lane_rows_table(stats))
    console.print(f"Next: trading-core-lanes sweep --capture pump={args.out} --out DIR")
    return EXIT_OK


def _lane_rows_table(stats: LaneRowStats) -> Table:
    table = Table(title="Lane rows")
    table.add_column("Rows", style="bold cyan")
    table.add_column("Count", justify="right")
    for kind in (ROW_LISTING, ROW_READING, ROW_TRADE, ROW_HOLDERS):
        table.add_row(kind, str(stats.written.get(kind, 0)))
    table.add_row("skipped", str(sum(stats.skipped.values())))
    for reason, count in stats.skipped.most_common():
        table.add_row(f"  {reason}", str(count))
    table.add_row("not market data", str(sum(stats.ignored.values())))
    for label, count in stats.ignored.most_common():
        table.add_row(f"  {label}", str(count))
    return table


def run_env() -> int:
    import os

    table = Table(title="trading-pump environment (names only)")
    table.add_column("Variable", style="bold cyan")
    table.add_column("State")
    table.add_column("What")
    for name, (aliases, what) in MODULE_ENV_VARS.items():
        candidates = (name, *aliases)
        set_as = next((n for n in candidates if os.environ.get(n, "").strip()), None)
        state = (
            "unset"
            if set_as is None
            else ("set" if set_as == name else f"set as {set_as}")
        )
        table.add_row(name, state, what)
    console.print(table)
    for warning in unread_env_warnings():
        console.print(f"[yellow]{warning}[/yellow]")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "replay":
        return run_replay(args)
    if args.command == "env":
        return run_env()
    if args.command == "lane-rows":
        return run_lane_rows(args)
    run_record_cli(args)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
