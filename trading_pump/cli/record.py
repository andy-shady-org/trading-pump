"""``trading-pump record``: the record-only research recorders.

Two recorders, each in its own process and files, none of them trading:

* ``--jupiter-quotes`` (FEAT-65 phase 0): Jupiter round-trip quotes;
* ``--backfill-bars`` (FEAT-65 phase 0): one-off OHLCV downloads.

The cross-chain market recorder (``--market``, FEAT-74) moved to
trading-scout on 2026-10-30 (the ``scout`` module for trading-core); the
flag is kept only to say so.

pumpfun-recorder's stream harvester, synthetic scenarios and REST trade
export fed the pumpbot replay engine and were not ported (docs/dev/TODO.md,
"Not ported").
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table
from trading_core.ops.logging import get_configured_console
from trading_core.ops.redact import redact_url
from trading_core.ops.retention import RetentionPolicy

from trading_pump.recorder import ReplayRecorder
from trading_pump.services import slow_lane

logger = logging.getLogger(__name__)
console = get_configured_console()

# FEAT-65 rows live in their own directory, never next to a Pump.fun capture.
DEFAULT_QUOTES_OUTPUT = "slow_lane/jupiter_quotes.jsonl"
DEFAULT_BARS_OUTPUT = "slow_lane/bars.jsonl"
# A one-off backfill is one file: the recorder's 50 MB rotation would move the
# oldest bars into a `.1.gz` part (a full Binance download is about 100 MB).
BACKFILL_RETENTION = RetentionPolicy(
    max_bytes=0, max_files=1, max_age_days=0, compress_archives=False
)
# Binance bars get their own file, so the two venues' rows never mix.
DEFAULT_BINANCE_BARS_OUTPUT = "slow_lane/binance_bars.jsonl"
MARKET_MOVED = (
    "--market moved to trading-scout (FEAT-74, 2026-10-30): run it as the "
    '"scout" module with trading-core run (trading-scout docs/USER-GUIDE.md)'
)
BAR_SOURCE_LABELS = {
    slow_lane.BAR_VENUE: "GeckoTerminal",
    slow_lane.BINANCE_VENUE: "Binance",
}


def utc_date(text: str) -> float:
    """``YYYY-MM-DD`` (UTC midnight) as epoch seconds, for ``--bar-since``."""
    try:
        day = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected a UTC date as YYYY-MM-DD, got {text!r}"
        ) from exc
    return day.replace(tzinfo=UTC).timestamp()


def build_record_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    description = "Record market data for research (record-only, no trading)"
    if subparsers is not None:
        parser = subparsers.add_parser("record", description=description)
    else:
        parser = argparse.ArgumentParser(
            prog="trading-pump-recorder", description=description
        )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help=(
            "Destination path for the .jsonl dataset (default: "
            f"{DEFAULT_QUOTES_OUTPUT} with --jupiter-quotes; "
            f"{DEFAULT_BARS_OUTPUT} with --backfill-bars; "
            f"{DEFAULT_BINANCE_BARS_OUTPUT} with --bar-source binance)"
        ),
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=None,
        help="Maximum recording duration in seconds",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size threshold for recorder disk flushes (default: 50)",
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=2.0,
        help="Periodic flush interval in seconds (default: 2.0)",
    )
    slow = parser.add_argument_group(
        "FEAT-65 slow-lane data (record-only, runs next to the engine, never inside it)"
    )
    slow.add_argument(
        "--jupiter-quotes",
        action="store_true",
        help="Sample Jupiter buy/sell quotes, prices and priority fees for a "
        "token list",
    )
    slow.add_argument(
        "--backfill-bars",
        action="store_true",
        help="Download OHLCV bars for the token list (source: --bar-source), then exit",
    )
    slow.add_argument(
        "--tokens",
        type=str,
        default=None,
        help="Token list JSON ({'tokens': [{'symbol', 'mint'}]}); default: "
        "built-in list "
        "(same as configs/slow_lane_tokens.json)",
    )
    slow.add_argument(
        "--quote-interval",
        type=float,
        default=slow_lane.DEFAULT_QUOTE_INTERVAL_SECONDS,
        help="Seconds between quote cycles (default: %(default)s)",
    )
    slow.add_argument(
        "--quote-sizes",
        type=str,
        default=",".join(f"{s:g}" for s in slow_lane.DEFAULT_SIZES_SOL),
        help="Comma-separated quote sizes in SOL (default: %(default)s)",
    )
    slow.add_argument(
        "--request-gap",
        type=float,
        default=None,
        help="Minimum seconds between API requests (default: "
        f"{slow_lane.DEFAULT_QUOTE_REQUEST_GAP_SECONDS:g} for quotes, "
        f"{slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS:g} for GeckoTerminal bars, "
        f"{slow_lane.DEFAULT_BINANCE_REQUEST_GAP_SECONDS:g} for Binance bars)",
    )
    slow.add_argument(
        "--no-fee-samples",
        action="store_true",
        help="Skip getRecentPrioritizationFees samples (otherwise taken when "
        "PUMPFUN_RPC_URL / PUMPFUN_RPC_URLS is set)",
    )
    slow.add_argument(
        "--bar-timeframes",
        type=str,
        default="day,hour",
        help="Comma-separated bar timeframes: day, hour, minute (default: %(default)s)",
    )
    slow.add_argument(
        "--bar-source",
        choices=slow_lane.BAR_SOURCES,
        default=slow_lane.BAR_VENUE,
        help="Bar provider for --backfill-bars: geckoterminal (top Solana pool, "
        "about 6 months public) or binance (<SYMBOL>USDT spot klines since "
        "listing) (default: %(default)s)",
    )
    slow.add_argument(
        "--bar-base-url",
        type=str,
        default=None,
        metavar="URL",
        help="Bar API host override (default: "
        f"{slow_lane.GECKOTERMINAL_URL} or {slow_lane.BINANCE_URL}; e.g. "
        "https://api.binance.com when the market-data host is blocked)",
    )
    slow.add_argument(
        "--bar-max-pages",
        type=int,
        default=None,
        help="Pages of 1,000 bars per token and timeframe (default: "
        f"{slow_lane.DEFAULT_BAR_MAX_PAGES} for GeckoTerminal, "
        f"{slow_lane.DEFAULT_BINANCE_MAX_PAGES} for Binance)",
    )
    slow.add_argument(
        "--bar-since",
        type=utc_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Binance only: first bar date, UTC (default: each pair's listing)",
    )
    parser.add_argument(
        "--market",
        action="store_true",
        help="Moved to trading-scout (FEAT-74): run the scout module instead",
    )
    return parser


def stop_on_signals(stop: asyncio.Event, loop: Any = None) -> None:
    """Set ``stop`` on SIGINT / SIGTERM where the event loop supports it."""
    running = loop or asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            running.add_signal_handler(sig, stop.set)


def _summary(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(title=title, show_lines=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="green")
    for name, value in rows:
        table.add_row(name, value)
    console.print(table)


async def run_jupiter_quotes(args: argparse.Namespace, output_path: Path) -> None:
    """FEAT-65 phase 0: sample quotes until the duration, a signal or Ctrl-C."""
    tokens = slow_lane.load_token_list(getattr(args, "tokens", None))
    sizes = slow_lane.parse_sizes(getattr(args, "quote_sizes", None))
    gap = getattr(args, "request_gap", None)
    http = slow_lane.AiohttpJson()
    rpc_url = (
        None if getattr(args, "no_fee_samples", False) else slow_lane.rpc_url_from_env()
    )
    jupiter = slow_lane.JupiterClient.from_env(http)
    recorder = ReplayRecorder(
        output_path=output_path,
        batch_size=args.batch_size,
        flush_interval_seconds=args.flush_interval,
    )
    quotes = slow_lane.QuoteRecorder(
        jupiter,
        recorder,
        tokens=tokens,
        sizes_sol=sizes,
        request_gap_seconds=(
            slow_lane.DEFAULT_QUOTE_REQUEST_GAP_SECONDS if gap is None else gap
        ),
        rpc_http=http if rpc_url else None,
        rpc_url=rpc_url,
    )
    stop = asyncio.Event()
    stop_on_signals(stop)
    console.print(
        Panel(
            f"[bold cyan]Jupiter Quote Recorder (FEAT-65, record-only)[/bold cyan]\n"
            f"Host: [green]{redact_url(jupiter.base_url)}[/green]"
            f" ({'keyed' if jupiter.keyed else 'keyless'})\n"
            f"Tokens: [yellow]{len(quotes.quote_tokens)}[/yellow] | "
            f"Sizes: [yellow]{', '.join(f'{s:g}' for s in sizes)} SOL[/yellow] | "
            f"Requests/cycle: [yellow]{quotes.requests_per_cycle}[/yellow] | "
            f"Interval: [yellow]{args.quote_interval:g}s[/yellow]\n"
            f"Fee samples: [green]{'on' if rpc_url else 'off'}[/green]\n"
            f"Output: [magenta]{output_path}[/magenta]",
            title="Slow-lane data",
        )
    )
    await recorder.start()
    try:
        stats = await quotes.run(
            interval_seconds=args.quote_interval,
            stop=stop,
            duration_seconds=args.duration,
        )
    finally:
        await recorder.close()
        await http.close()
    _summary(
        "Quote Recorder Summary",
        [
            ("Cycles", str(stats.cycles)),
            ("Quotes", str(stats.quotes)),
            ("Quote errors", str(stats.quote_errors)),
            ("Rate limited", str(stats.rate_limited)),
            ("Price rows", str(stats.price_rows)),
            ("Fee samples", str(stats.fee_samples)),
            ("Rows written", str(recorder.records_written)),
            ("Output File", str(output_path.resolve())),
        ],
    )


@dataclass(frozen=True)
class _BackfillOptions:
    source: str
    binance: bool
    since: Any
    tokens: list[Any]
    timeframes: list[str]
    request_gap: float
    max_pages: int
    base_url: str


def _backfill_options(args: argparse.Namespace) -> _BackfillOptions:
    """The backfill's settings, with each venue's defaults filled in."""
    source = getattr(args, "bar_source", None) or slow_lane.BAR_VENUE
    binance = source == slow_lane.BINANCE_VENUE
    since = getattr(args, "bar_since", None)
    if since is not None and not binance:
        console.print(
            "[red]--bar-since needs --bar-source binance "
            "(GeckoTerminal pages back from today).[/red]"
        )
        raise SystemExit(2)
    gap = getattr(args, "request_gap", None)
    max_pages = getattr(args, "bar_max_pages", None)
    defaults = (
        (
            slow_lane.DEFAULT_BINANCE_REQUEST_GAP_SECONDS,
            slow_lane.DEFAULT_BINANCE_MAX_PAGES,
            slow_lane.BINANCE_URL,
        )
        if binance
        else (
            slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS,
            slow_lane.DEFAULT_BAR_MAX_PAGES,
            slow_lane.GECKOTERMINAL_URL,
        )
    )
    return _BackfillOptions(
        source=source,
        binance=binance,
        since=since,
        tokens=slow_lane.load_token_list(getattr(args, "tokens", None)),
        timeframes=[
            t.strip() for t in str(args.bar_timeframes).split(",") if t.strip()
        ],
        request_gap=defaults[0] if gap is None else gap,
        max_pages=defaults[1] if max_pages is None else max_pages,
        base_url=getattr(args, "bar_base_url", None) or defaults[2],
    )


async def _backfill(
    options: _BackfillOptions, http: Any, recorder: ReplayRecorder
) -> Any:
    if options.binance:
        return await slow_lane.backfill_binance_bars(
            slow_lane.BinanceClient(http, base_url=options.base_url),
            recorder,
            tokens=options.tokens,
            timeframes=options.timeframes,
            max_pages=options.max_pages,
            since=options.since,
            request_gap_seconds=options.request_gap,
        )
    return await slow_lane.backfill_bars(
        slow_lane.GeckoTerminalClient(http, base_url=options.base_url),
        recorder,
        tokens=options.tokens,
        timeframes=options.timeframes,
        max_pages=options.max_pages,
        request_gap_seconds=options.request_gap,
    )


def _backfill_summary(options: _BackfillOptions, stats: Any, output_path: Path) -> None:
    source_rows = (
        [
            ("Pairs missing", str(stats.pairs_missing)),
            ("Skipped (no Binance pair)", str(stats.skipped)),
        ]
        if options.binance
        else [
            ("Pools missing", str(stats.pools_missing)),
        ]
    )
    history_rows = (
        []
        if options.binance
        else [("History limit reached", str(stats.history_limited))]
    )
    _summary(
        "Bar Backfill Summary",
        [
            ("Tokens", str(stats.tokens)),
            *source_rows,
            ("Bars", str(stats.bars)),
            ("Requests", str(stats.requests)),
            *history_rows,
            ("Page limit reached", str(stats.page_limited)),
            ("Errors", str(stats.errors)),
            *(("Failed", failure) for failure in stats.failures),
            ("Output File", str(output_path.resolve())),
        ],
    )
    if stats.page_limited:
        console.print(
            "[yellow]Some series hit --bar-max-pages with bars left; "
            "raise it to fetch the rest.[/yellow]"
        )
    if stats.blocked_status is not None:
        console.print(
            f"[red]Binance refused this host (HTTP {stats.blocked_status}: "
            "403 = firewall, 418 = IP ban after rate limiting, 451 = restricted "
            "region); the run stopped. Try another network or --bar-base-url "
            "(docs/dev/RUNBOOK.md §5.1).[/red]"
        )


async def run_backfill_bars(args: argparse.Namespace, output_path: Path) -> None:
    """FEAT-65 phase 0: one-off OHLCV download for the token list."""
    options = _backfill_options(args)
    http = slow_lane.AiohttpJson()
    recorder = ReplayRecorder(
        output_path=output_path,
        batch_size=max(args.batch_size, 500),
        flush_interval_seconds=args.flush_interval,
        policy=BACKFILL_RETENTION,
    )
    since_text = (
        datetime.fromtimestamp(options.since, tz=UTC).strftime("%Y-%m-%d")
        if options.since is not None
        else "listing"
    )
    console.print(
        Panel(
            f"[bold cyan]{BAR_SOURCE_LABELS[options.source]} Bar Backfill "
            "(FEAT-65)[/bold cyan]\n"
            f"Tokens: [yellow]{len(options.tokens)}[/yellow] | "
            f"Timeframes: [yellow]{', '.join(options.timeframes)}[/yellow] | "
            f"Max pages: [yellow]{options.max_pages}[/yellow]"
            + (f" | Since: [yellow]{since_text}[/yellow]" if options.binance else "")
            + f"\nHost: [magenta]{redact_url(options.base_url)}[/magenta]\n"
            f"Output: [magenta]{output_path}[/magenta]",
            title="Slow-lane data",
        )
    )
    await recorder.start()
    try:
        stats = await _backfill(options, http, recorder)
    finally:
        await recorder.close()
        await http.close()
    _backfill_summary(options, stats, output_path)


def _run_until_interrupted(coroutine: Any) -> None:
    """Run a recorder until it ends; Ctrl-C and any exit end it quietly."""
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(coroutine)


def run_record_cli(args: argparse.Namespace) -> None:
    """Execute the record CLI handler."""
    output = getattr(args, "output", None)
    if getattr(args, "market", False):
        console.print(f"[red]{MARKET_MOVED}[/red]")
        raise SystemExit(2)
    if getattr(args, "jupiter_quotes", False):
        quotes = run_jupiter_quotes(args, Path(output or DEFAULT_QUOTES_OUTPUT))
        _run_until_interrupted(quotes)
        return
    if getattr(args, "backfill_bars", False):
        default_bars = (
            DEFAULT_BINANCE_BARS_OUTPUT
            if getattr(args, "bar_source", None) == slow_lane.BINANCE_VENUE
            else DEFAULT_BARS_OUTPUT
        )
        asyncio.run(run_backfill_bars(args, Path(output or default_bars)))
        return
    console.print("[red]Choose a recorder: --jupiter-quotes or --backfill-bars.[/red]")
    raise SystemExit(2)


def main() -> None:
    parser = build_record_parser()
    args = parser.parse_args()
    run_record_cli(args)


if __name__ == "__main__":  # pragma: no cover
    main()
