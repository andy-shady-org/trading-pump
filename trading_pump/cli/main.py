"""``trading-pump``: the module's own tools (the engine is ``trading-core``).

* ``trading-pump replay --config F --capture C [C ...] --out DIR``: replay
  captures through trading-core's engine with the module (``replay.py``);
* ``trading-pump lane-rows --capture C [C ...] --out FILE``: a capture as
  trading-core's strategy library rows, for ``trading-core-lanes sweep``
  (``lanes.py``, trading-core FEAT-133);
* ``trading-pump env``: which ``PUMPFUN_*`` variables are set and read
  (names only);
* ``trading-pump land-probe --modes rpc,priority,jito,fast --count N
  --interval S --out FILE --host NAME``: the landing probe (FEAT-175,
  ``probe.py``): how fast, and at what cost, a transaction lands, sent from
  the probe wallet (``PUMPFUN_PROBE_PRIVATE_KEY``).

Running the module is trading-core's job: ``trading-core run --config F``
with ``"module": "pumpfun"``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.table import Table
from trading_core.config.settings import EngineSettings
from trading_core.lanes.market import ROW_HOLDERS, ROW_LISTING, ROW_READING, ROW_TRADE
from trading_core.ops.logging import get_configured_console
from trading_core.replay import read_rows

from trading_pump.config.env import (
    MODULE_ENV_VARS,
    load_credentials,
    unread_env_warnings,
)
from trading_pump.lanes import SOURCES, LaneRowStats, write_lane_rows
from trading_pump.probe import (
    DEFAULT_MAX_BALANCE_SOL,
    DEFAULT_MAX_SPEND_SOL,
    DEFAULT_MAX_TIP_LAMPORTS,
    DEFAULT_TIP_LAMPORTS,
    ProbeOptions,
    ProbeResult,
    report_cells,
    run_land_probe,
)
from trading_pump.replay import (
    DEFAULT_REPLAY_FEE_BPS,
    CaptureMarket,
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
    _add_land_probe(sub)
    return parser


def _modes(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _add_land_probe(sub: Any) -> None:
    probe = sub.add_parser(
        "land-probe",
        description="Time transactions that trade nothing, per send mode "
        "(FEAT-175), from the probe wallet (PUMPFUN_PROBE_PRIVATE_KEY)",
    )
    probe.add_argument(
        "--modes",
        type=_modes,
        default=("rpc", "priority", "jito", "fast"),
        help="comma-separated: rpc, priority, jito, fast (default: all)",
    )
    probe.add_argument("--count", type=int, required=True, help="probes a mode")
    probe.add_argument(
        "--interval", type=float, required=True, help="seconds between sends"
    )
    probe.add_argument("--out", type=Path, required=True, help="new .jsonl file")
    probe.add_argument("--host", required=True, help="where it runs: home, uk, ...")
    probe.add_argument(
        "--cu-price",
        type=int,
        default=None,
        help="micro-lamports a compute unit for priority and fast "
        "(default: the 75th percentile of recent prioritization fees)",
    )
    probe.add_argument("--tip", type=int, default=DEFAULT_TIP_LAMPORTS)
    probe.add_argument("--max-tip", type=int, default=DEFAULT_MAX_TIP_LAMPORTS)
    probe.add_argument(
        "--max-spend",
        type=float,
        default=DEFAULT_MAX_SPEND_SOL,
        help="SOL; the probe stops before passing it (default: %(default)s)",
    )
    probe.add_argument(
        "--max-balance",
        type=float,
        default=DEFAULT_MAX_BALANCE_SOL,
        help="refuse a wallet holding more SOL than this (default: %(default)s)",
    )
    probe.add_argument("--jito-region", default="frankfurt")
    probe.add_argument("--sender-region", default="lon")
    probe.add_argument(
        "--delays", type=Path, default=None, help="write FEAT-176's delay sample"
    )


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


def _probe_options(args: argparse.Namespace) -> ProbeOptions:
    return ProbeOptions(
        modes=tuple(args.modes),
        count=args.count,
        interval_seconds=args.interval,
        out=args.out,
        host=args.host,
        cu_price_micro_lamports=args.cu_price,
        tip_lamports=args.tip,
        max_tip_lamports=args.max_tip,
        max_spend_sol=args.max_spend,
        max_balance_sol=args.max_balance,
        jito_region=args.jito_region,
        sender_region=args.sender_region,
        delays=args.delays,
    )


def run_probe(args: argparse.Namespace) -> int:
    try:
        options = _probe_options(args)
        result = asyncio.run(run_land_probe(options, load_credentials()))
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Cannot run the landing probe: {exc}[/red]")
        return EXIT_USAGE
    console.print(_probe_table(result))
    console.print(f"Rows: {options.out} · report: {result.report_path}")
    if result.stopped_by_cap:
        console.print("[yellow]Stopped at the spending cap (--max-spend)[/yellow]")
    return EXIT_OK


def _probe_table(result: ProbeResult) -> Table:
    table = Table(
        title=f"Landing probe (compute-unit price {result.cu_price_micro_lamports})"
    )
    for name in (
        "Host",
        "Mode",
        "Landed",
        "Rate",
        "Slots p50 / p90",
        "Seconds p50 / p90",
        "Confirmed p50",
        "Lamports a landing",
    ):
        table.add_column(name)
    for report in result.reports:
        table.add_row(*report_cells(report))
    return table


COMMANDS = {
    "replay": run_replay,
    "lane-rows": run_lane_rows,
    "land-probe": run_probe,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "env":
        return run_env()
    return COMMANDS[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
