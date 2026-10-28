"""``trading-pump record``: the record-only research recorders.

Three recorders, each in its own process and files, none of them trading:

* ``--market`` (FEAT-74): new pools and momentum lists on several chains;
* ``--jupiter-quotes`` (FEAT-65 phase 0): Jupiter round-trip quotes;
* ``--backfill-bars`` (FEAT-65 phase 0): one-off OHLCV downloads.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table
from trading_core.ops.logging import get_configured_console
from trading_core.ops.redact import redact_url
from trading_core.ops.retention import RetentionPolicy

from trading_pump.recorder import ReplayRecorder
from trading_pump.services import market_recorder, slow_lane

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
# FEAT-74 market rows live in their own directory too.
DEFAULT_MARKET_OUTPUT = "market/market.jsonl"
DEFAULT_MARKET_STATE = "market/state.json"
# About 1 GB of rows a day before compression: 100 MB parts, kept until the
# operator archives them (no age limit; 300 parts).
MARKET_RETENTION = RetentionPolicy(
    max_bytes=100 * 1024 * 1024, max_files=300, max_age_days=0, compress_archives=True
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
            f"{DEFAULT_BINANCE_BARS_OUTPUT} with --bar-source binance; "
            f"{DEFAULT_MARKET_OUTPUT} with --market)"
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
    market = parser.add_argument_group(
        "FEAT-74 cross-chain market data (record-only, runs next to the engine, "
        "never inside it; free public APIs, no RPC credits)"
    )
    market.add_argument(
        "--market",
        action="store_true",
        help="Record new pools and momentum lists on several chains and follow "
        "each pool for up to 7 days (GeckoTerminal + DexScreener)",
    )
    market.add_argument(
        "--market-chains",
        type=str,
        default=",".join(market_recorder.DEFAULT_CHAINS),
        help=f"Comma-separated chains: {', '.join(market_recorder.CHAINS)} "
        "(default: %(default)s)",
    )
    market.add_argument(
        "--market-sample",
        type=str,
        default=None,
        metavar="CHAIN:DEX=SHARE,...",
        help="Share of new pools followed per GeckoTerminal dex id; others are "
        "all followed (default: "
        + ",".join(f"{k}={v:g}" for k, v in market_recorder.DEFAULT_SAMPLE.items())
        + ")",
    )
    market.add_argument(
        "--market-state",
        type=str,
        default=DEFAULT_MARKET_STATE,
        help="Follow-list file, so a restart resumes it (default: %(default)s; "
        "'' = none)",
    )
    market.add_argument(
        "--market-max-followed",
        type=int,
        default=market_recorder.DEFAULT_MAX_FOLLOWED,
        help="Most pools followed at once (default: %(default)s)",
    )
    market.add_argument(
        "--market-no-lists",
        action="store_true",
        help="New pools only: skip the trending / top-volume lists",
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


async def run_market(args: argparse.Namespace, output_path: Path) -> None:
    """FEAT-74: record pools on several chains until the duration, a signal or
    Ctrl-C."""
    try:
        config = market_recorder.MarketRecorderConfig(
            chains=market_recorder.parse_chains(getattr(args, "market_chains", None)),
            sample=market_recorder.parse_sample(getattr(args, "market_sample", None)),
            max_followed=int(
                getattr(args, "market_max_followed", None)
                or market_recorder.DEFAULT_MAX_FOLLOWED
            ),
            lists=not getattr(args, "market_no_lists", False),
        )
    except ValueError as exc:
        console.print(f"[bold red]--market: {exc}[/bold red]")
        raise SystemExit(2) from exc
    state = getattr(args, "market_state", DEFAULT_MARKET_STATE) or None
    http = slow_lane.AiohttpJson()
    recorder = ReplayRecorder(
        output_path=output_path,
        batch_size=args.batch_size,
        flush_interval_seconds=args.flush_interval,
        policy=MARKET_RETENTION,
    )
    market = market_recorder.MarketRecorder(http, recorder, config, state_path=state)
    resumed = market.load_state()
    stop = asyncio.Event()
    stop_on_signals(stop)
    console.print(
        Panel(
            "[bold cyan]Market Recorder (FEAT-74, record-only)[/bold cyan]\n"
            f"Chains: [yellow]{', '.join(config.chains)}[/yellow] | "
            f"Lists: [green]{'on' if config.lists else 'off'}[/green] | "
            "Sampled: [yellow]"
            + (", ".join(f"{k}={v:g}" for k, v in config.sample.items()) or "none")
            + "[/yellow]\n"
            f"Resumed: [yellow]{resumed}[/yellow] pools from "
            f"[magenta]{state or '(no state file)'}[/magenta]\n"
            f"Output: [magenta]{output_path}[/magenta]",
            title="Market data",
        )
    )
    await recorder.start()
    try:
        stats = await market.run(stop=stop, duration_seconds=args.duration)
    finally:
        await recorder.close()
        await http.close()
    _summary(
        "Market Recorder Summary",
        [
            ("New pools seen", str(stats.new_pools)),
            ("Pools followed", str(stats.followed)),
            ("Still following", str(len(market.followed))),
            ("Snapshots written", str(stats.snapshots)),
            ("Unchanged (skipped)", str(stats.snapshots_unchanged)),
            ("Ended", ", ".join(f"{k} {v}" for k, v in stats.ended.items()) or "0"),
            ("Discovery gaps", str(stats.discovery_gaps)),
            ("Errors (429s)", f"{stats.errors} ({stats.rate_limited})"),
            ("Rows written", str(recorder.records_written)),
            ("Output File", str(output_path.resolve())),
        ],
    )


async def run_backfill_bars(args: argparse.Namespace, output_path: Path) -> None:
    """FEAT-65 phase 0: one-off OHLCV download for the token list."""
    source = getattr(args, "bar_source", None) or slow_lane.BAR_VENUE
    binance = source == slow_lane.BINANCE_VENUE
    since = getattr(args, "bar_since", None)
    if since is not None and not binance:
        console.print(
            "[red]--bar-since needs --bar-source binance "
            "(GeckoTerminal pages back from today).[/red]"
        )
        raise SystemExit(2)
    tokens = slow_lane.load_token_list(getattr(args, "tokens", None))
    timeframes = [t.strip() for t in str(args.bar_timeframes).split(",") if t.strip()]
    gap = getattr(args, "request_gap", None)
    max_pages = getattr(args, "bar_max_pages", None)
    if max_pages is None:
        max_pages = (
            slow_lane.DEFAULT_BINANCE_MAX_PAGES
            if binance
            else slow_lane.DEFAULT_BAR_MAX_PAGES
        )
    if gap is None:
        gap = (
            slow_lane.DEFAULT_BINANCE_REQUEST_GAP_SECONDS
            if binance
            else slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS
        )
    base_url = getattr(args, "bar_base_url", None) or (
        slow_lane.BINANCE_URL if binance else slow_lane.GECKOTERMINAL_URL
    )
    http = slow_lane.AiohttpJson()
    recorder = ReplayRecorder(
        output_path=output_path,
        batch_size=max(args.batch_size, 500),
        flush_interval_seconds=args.flush_interval,
        policy=BACKFILL_RETENTION,
    )
    since_text = (
        datetime.fromtimestamp(since, tz=UTC).strftime("%Y-%m-%d")
        if since is not None
        else "listing"
    )
    console.print(
        Panel(
            f"[bold cyan]{BAR_SOURCE_LABELS[source]} Bar Backfill (FEAT-65)[/bold "
            "cyan]\n"
            f"Tokens: [yellow]{len(tokens)}[/yellow] | "
            f"Timeframes: [yellow]{', '.join(timeframes)}[/yellow] | "
            f"Max pages: [yellow]{max_pages}[/yellow]"
            + (f" | Since: [yellow]{since_text}[/yellow]" if binance else "")
            + f"\nHost: [magenta]{redact_url(base_url)}[/magenta]\n"
            f"Output: [magenta]{output_path}[/magenta]",
            title="Slow-lane data",
        )
    )
    await recorder.start()
    try:
        if binance:
            stats = await slow_lane.backfill_binance_bars(
                slow_lane.BinanceClient(http, base_url=base_url),
                recorder,
                tokens=tokens,
                timeframes=timeframes,
                max_pages=max_pages,
                since=since,
                request_gap_seconds=gap,
            )
        else:
            stats = await slow_lane.backfill_bars(
                slow_lane.GeckoTerminalClient(http, base_url=base_url),
                recorder,
                tokens=tokens,
                timeframes=timeframes,
                max_pages=max_pages,
                request_gap_seconds=gap,
            )
    finally:
        await recorder.close()
        await http.close()
    source_rows = (
        [
            ("Pairs missing", str(stats.pairs_missing)),
            ("Skipped (no Binance pair)", str(stats.skipped)),
        ]
        if binance
        else [("Pools missing", str(stats.pools_missing))]
    )
    _summary(
        "Bar Backfill Summary",
        [
            ("Tokens", str(stats.tokens)),
            *source_rows,
            ("Bars", str(stats.bars)),
            ("Requests", str(stats.requests)),
            *(
                []
                if binance
                else [("History limit reached", str(stats.history_limited))]
            ),
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


def run_record_cli(args: argparse.Namespace) -> None:
    """Execute the record CLI handler."""
    output = getattr(args, "output", None)
    if getattr(args, "market", False):
        try:
            asyncio.run(run_market(args, Path(output or DEFAULT_MARKET_OUTPUT)))
        except (KeyboardInterrupt, SystemExit) as exc:
            if isinstance(exc, SystemExit) and exc.code not in (None, 0):
                raise
        return
    if getattr(args, "jupiter_quotes", False):
        path = Path(output or DEFAULT_QUOTES_OUTPUT)
        try:
            asyncio.run(run_jupiter_quotes(args, path))
        except (KeyboardInterrupt, SystemExit):
            pass
        return
    if getattr(args, "backfill_bars", False):
        default_bars = (
            DEFAULT_BINANCE_BARS_OUTPUT
            if getattr(args, "bar_source", None) == slow_lane.BINANCE_VENUE
            else DEFAULT_BARS_OUTPUT
        )
        asyncio.run(run_backfill_bars(args, Path(output or default_bars)))
        return
    console.print(
        "[red]Choose a recorder: --market, --jupiter-quotes or --backfill-bars.[/red]"
    )
    raise SystemExit(2)


def main() -> None:
    parser = build_record_parser()
    args = parser.parse_args()
    run_record_cli(args)


if __name__ == "__main__":  # pragma: no cover
    main()
