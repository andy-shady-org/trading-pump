"""Market stream recorder and historical dataset generator CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.recorder import ReplayRecorder
from pumpfun_trading.engines.generators import (
    RestHistoryExporter,
    SyntheticReplayGenerator,
)
from pumpfun_trading.ops.logging import get_configured_console
from pumpfun_trading.ops.redact import redact_url
from pumpfun_trading.services import slow_lane
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)

logger = logging.getLogger(__name__)
console = get_configured_console()

# FEAT-65 rows live in their own directory, never next to a Pump.fun capture.
DEFAULT_QUOTES_OUTPUT = "slow_lane/jupiter_quotes.jsonl"
DEFAULT_BARS_OUTPUT = "slow_lane/bars.jsonl"


def build_record_parser(
    subparsers: argparse._SubParsersAction | None = None,
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "record",
            description="Record live Pump.fun market streams or generate synthetic/historical datasets",
        )
    elif parser is None:
        parser = argparse.ArgumentParser(
            description="Record live Pump.fun market streams or generate synthetic/historical datasets"
        )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help=(
            "Destination path for the .jsonl dataset (default: market_replay.jsonl; "
            f"{DEFAULT_QUOTES_OUTPUT} with --jupiter-quotes; "
            f"{DEFAULT_BARS_OUTPUT} with --backfill-bars)"
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
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to capture before terminating",
    )
    parser.add_argument(
        "--from-mint",
        type=str,
        default=None,
        help="Export historical trades for a specific token mint via REST API",
    )
    parser.add_argument(
        "--synthetic",
        type=str,
        choices=[
            "pump_and_dump",
            "stagnant_curve",
            "multi_tier_take_profit",
            "gradual_grind",
            "flash_rug",
        ],
        default=None,
        help="Generate a deterministic synthetic price trajectory dataset",
    )
    parser.add_argument(
        "--synthetic-steps",
        type=int,
        default=60,
        help="Number of price update steps to generate for synthetic scenarios (default: 60)",
    )
    parser.add_argument(
        "--geyser-endpoint",
        type=str,
        default=None,
        help="Yellowstone Geyser gRPC endpoint for on-chain streaming (overrides env)",
    )
    parser.add_argument(
        "--ws-url",
        type=str,
        default=None,
        help="PumpPortal / WebSocket stream URL (default: wss://pumpportal.fun/api/data)",
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
        "FEAT-65 slow-lane data (record-only, runs next to pumpbot, never inside it)"
    )
    slow.add_argument(
        "--jupiter-quotes",
        action="store_true",
        help="Sample Jupiter buy/sell quotes, prices and priority fees for a token list",
    )
    slow.add_argument(
        "--backfill-bars",
        action="store_true",
        help="Download OHLCV bars from GeckoTerminal for the token list, then exit",
    )
    slow.add_argument(
        "--tokens",
        type=str,
        default=None,
        help="Token list JSON ({'tokens': [{'symbol', 'mint'}]}); default: built-in list "
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
        f"{slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS:g} for bars)",
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
        "--bar-max-pages",
        type=int,
        default=6,
        help="Pages of 1,000 bars per token and timeframe (default: %(default)s)",
    )
    return parser


def ws_message_to_snapshot(payload: Any, now: float) -> dict[str, Any] | None:
    """Convert a PumpPortal WS message into a replay snapshot without inventing signals."""
    if not isinstance(payload, dict):
        return None
    mint = payload.get("mint")
    if not mint:
        return None
    snapshot: dict[str, Any] = {
        "timestamp": payload.get("timestamp") or now,
        "mint": str(mint),
        "name": str(payload.get("name") or mint),
        "source": "websocket",
    }
    for src, dst in (
        ("marketCapSol", "market_cap_sol"),
        ("vSolInBondingCurve", "virtual_sol_reserves"),
        ("vTokensInBondingCurve", "virtual_token_reserves"),
        ("solAmount", "sol_amount"),
        ("tokenAmount", "token_amount"),
        ("traderPublicKey", "trader"),
    ):
        if payload.get(src) is not None:
            snapshot[dst] = payload[src]
    tx_type = str(payload.get("txType") or "").lower()
    if tx_type:
        snapshot["txType"] = tx_type
    if tx_type in {"buy", "sell"}:
        # Only real trades carry a side; still not a strategy entry signal.
        snapshot["is_buy"] = tx_type == "buy"
    return snapshot


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
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
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


async def run_backfill_bars(args: argparse.Namespace, output_path: Path) -> None:
    """FEAT-65 phase 0: one-off OHLCV download for the token list."""
    tokens = slow_lane.load_token_list(getattr(args, "tokens", None))
    timeframes = [t.strip() for t in str(args.bar_timeframes).split(",") if t.strip()]
    gap = getattr(args, "request_gap", None)
    http = slow_lane.AiohttpJson()
    recorder = ReplayRecorder(
        output_path=output_path,
        batch_size=max(args.batch_size, 500),
        flush_interval_seconds=args.flush_interval,
    )
    console.print(
        Panel(
            f"[bold cyan]GeckoTerminal Bar Backfill (FEAT-65)[/bold cyan]\n"
            f"Tokens: [yellow]{len(tokens)}[/yellow] | "
            f"Timeframes: [yellow]{', '.join(timeframes)}[/yellow] | "
            f"Max pages: [yellow]{args.bar_max_pages}[/yellow]\n"
            f"Output: [magenta]{output_path}[/magenta]",
            title="Slow-lane data",
        )
    )
    await recorder.start()
    try:
        stats = await slow_lane.backfill_bars(
            slow_lane.GeckoTerminalClient(http),
            recorder,
            tokens=tokens,
            timeframes=timeframes,
            max_pages=args.bar_max_pages,
            request_gap_seconds=(
                slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS if gap is None else gap
            ),
        )
    finally:
        await recorder.close()
        await http.close()
    _summary(
        "Bar Backfill Summary",
        [
            ("Tokens", str(stats.tokens)),
            ("Pools missing", str(stats.pools_missing)),
            ("Bars", str(stats.bars)),
            ("Requests", str(stats.requests)),
            ("History limit reached", str(stats.history_limited)),
            ("Errors", str(stats.errors)),
            *(("Failed", failure) for failure in stats.failures),
            ("Output File", str(output_path.resolve())),
        ],
    )


def run_record_cli(args: argparse.Namespace) -> None:
    """Execute the record CLI handler."""
    output = getattr(args, "output", None)
    if getattr(args, "jupiter_quotes", False):
        path = Path(output or DEFAULT_QUOTES_OUTPUT)
        try:
            asyncio.run(run_jupiter_quotes(args, path))
        except (KeyboardInterrupt, SystemExit):
            pass
        return
    if getattr(args, "backfill_bars", False):
        asyncio.run(run_backfill_bars(args, Path(output or DEFAULT_BARS_OUTPUT)))
        return
    output_path = Path(output or "market_replay.jsonl")

    # 1. Synthetic Scenario Generation
    if args.synthetic:
        console.print(
            Panel(
                f"[bold cyan]Generating Synthetic Replay Scenario[/bold cyan]\n"
                f"Scenario: [green]{args.synthetic}[/green]\n"
                f"Steps: [yellow]{args.synthetic_steps}[/yellow]\n"
                f"Output: [magenta]{output_path}[/magenta]",
                title="Synthetic Generator",
            )
        )
        count = SyntheticReplayGenerator.generate_to_file(
            path=output_path,
            scenario=args.synthetic,
            steps=args.synthetic_steps,
        )
        table = Table(title="Synthetic Dataset Created", show_lines=False)
        table.add_column("Property", style="bold cyan")
        table.add_column("Value", style="green")
        table.add_row("Scenario", args.synthetic)
        table.add_row("Steps / Records", str(count))
        table.add_row("Destination", str(output_path.resolve()))
        console.print(table)
        return

    # 2. REST API Historical Trade Export
    if args.from_mint:
        mint = args.from_mint.strip()
        limit = args.limit or 200

        async def _run_export() -> None:
            console.print(
                Panel(
                    f"[bold cyan]Exporting Historical REST Trades[/bold cyan]\n"
                    f"Mint: [green]{mint}[/green]\n"
                    f"Max Trades: [yellow]{limit}[/yellow]\n"
                    f"Output: [magenta]{output_path}[/magenta]",
                    title="REST Exporter",
                )
            )
            async with PumpFunApiClient() as client:
                count = await RestHistoryExporter.export_token_trades_to_file(
                    client=client,
                    mint=mint,
                    output_path=output_path,
                    limit=limit,
                )
                table = Table(title="REST Export Complete", show_lines=False)
                table.add_column("Property", style="bold cyan")
                table.add_column("Value", style="green")
                table.add_row("Mint", mint)
                table.add_row("Exported Records", str(count))
                table.add_row("Destination", str(output_path.resolve()))
                console.print(table)

        asyncio.run(_run_export())
        return

    # 3. Live Market Streaming Harvester
    async def _run_harvester() -> None:
        recorder = ReplayRecorder(
            output_path=output_path,
            batch_size=args.batch_size,
            flush_interval_seconds=args.flush_interval,
        )
        await recorder.start()

        geyser_endpoint = args.geyser_endpoint or os.getenv("PUMPFUN_GEYSER_ENDPOINT")

        start_time = time.monotonic()
        stop_requested = asyncio.Event()
        unique_mints: set[str] = set()
        enqueued_count = 0

        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_requested.set)
            except (NotImplementedError, RuntimeError):
                pass

        console.print(
            Panel(
                f"[bold cyan]Market Stream Harvester Active[/bold cyan]\n"
                f"Output: [magenta]{output_path}[/magenta]\n"
                f"Source: [green]{'Yellowstone Geyser' if geyser_endpoint else 'WebSocket / REST'}[/green]\n"
                f"Batch Size: [yellow]{args.batch_size}[/yellow] | Flush: [yellow]{args.flush_interval}s[/yellow]",
                title="Harvester",
            )
        )

        async def _stream_geyser() -> None:
            nonlocal enqueued_count
            if not geyser_endpoint:
                return
            client = YellowstoneGeyserClient(endpoint=str(geyser_endpoint))
            await client.start()
            try:
                async for event in client.listen():
                    if stop_requested.is_set():
                        break
                    if isinstance(event, BondingCurveStateUpdate):
                        unique_mints.add(event.mint)
                        enqueued_count += 1
                        recorder.record_snapshot(
                            {
                                "timestamp": event.timestamp,
                                "mint": event.mint,
                                "name": f"{event.mint[:8]}...",
                                "price": event.price_sol,
                                "market_cap_sol": event.market_cap_sol,
                                "volume": event.real_sol_reserves / 1_000_000_000.0,
                            }
                        )
                    elif isinstance(event, TradeEventUpdate):
                        unique_mints.add(event.mint)
                        enqueued_count += 1
                        recorder.record_snapshot(
                            {
                                "timestamp": event.timestamp or time.time(),
                                "mint": event.mint,
                                "price": event.price_sol,
                                "is_buy": event.is_buy,
                                "sol_amount": event.sol_amount,
                                "token_amount": float(event.token_amount),
                                "user": event.user,
                                "signal": "buy" if event.is_buy else "sell",
                            }
                        )
                    elif isinstance(event, CompleteEventUpdate):
                        unique_mints.add(event.mint)
                        enqueued_count += 1
                        recorder.record_snapshot(
                            {
                                "timestamp": event.timestamp or time.time(),
                                "mint": event.mint,
                                "signal": "graduated",
                            }
                        )

                    if args.limit and enqueued_count >= args.limit:
                        stop_requested.set()
                        break
            finally:
                await client.stop()

        async def _stream_websocket_or_polling() -> None:
            nonlocal enqueued_count
            async with PumpFunApiClient() as api_client:
                while not stop_requested.is_set():
                    try:
                        coins = await api_client.get_latest_coins(limit=50)
                        now = time.time()
                        if isinstance(coins, list):
                            for c in coins:
                                if not isinstance(c, dict):
                                    continue
                                mint = c.get("mint") or c.get("mintAddress")
                                if not mint:
                                    continue
                                unique_mints.add(str(mint))
                                enqueued_count += 1
                                mc = float(
                                    c.get("market_cap", 0.0)
                                    or c.get("marketCapSol", 0.0)
                                    or 0.0
                                )
                                price = float(
                                    c.get("price", 0.0)
                                    or (mc / 1_000_000_000.0 if mc > 0 else 0.0)
                                )
                                recorder.record_snapshot(
                                    {
                                        "timestamp": now,
                                        "mint": str(mint),
                                        "name": str(c.get("name") or mint),
                                        "price": price,
                                        "market_cap_sol": mc,
                                        "volume": float(c.get("volume", 0.0) or 0.0),
                                        # A poll is a quote, not a trade: no fabricated
                                        # buy signal (BUG-86).
                                        "source": "poll",
                                    }
                                )
                                if args.limit and enqueued_count >= args.limit:
                                    stop_requested.set()
                                    break
                    except Exception as err:
                        logger.debug("Harvester polling error: %s", err)

                    if args.limit and enqueued_count >= args.limit:
                        break

                    # Sleep briefly between polls or check duration
                    for _ in range(20):
                        if stop_requested.is_set():
                            break
                        if (
                            args.duration
                            and (time.monotonic() - start_time) >= args.duration
                        ):
                            stop_requested.set()
                            break
                        await asyncio.sleep(0.1)

        async def _stream_websocket(ws_url: str) -> None:
            nonlocal enqueued_count
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=None, sock_read=60.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(ws_url) as ws:
                    await ws.send_json({"method": "subscribeNewToken"})
                    async for msg in ws:
                        if stop_requested.is_set():
                            break
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            payload = json.loads(msg.data)
                        except (TypeError, ValueError):
                            continue
                        snapshot = ws_message_to_snapshot(payload, time.time())
                        if snapshot is None:
                            continue
                        unique_mints.add(snapshot["mint"])
                        enqueued_count += 1
                        recorder.record_snapshot(snapshot)
                        if args.limit and enqueued_count >= args.limit:
                            stop_requested.set()
                            break

        # Run selected stream task (`--ws-url` selects the WebSocket feed, BUG-86)
        ws_url = getattr(args, "ws_url", None)
        if geyser_endpoint:
            stream_coro = _stream_geyser()
        elif ws_url:
            stream_coro = _stream_websocket(ws_url)
        else:
            stream_coro = _stream_websocket_or_polling()
        stream_task = asyncio.create_task(stream_coro)

        try:
            while not stop_requested.is_set():
                elapsed = time.monotonic() - start_time
                if args.duration and elapsed >= args.duration:
                    stop_requested.set()
                    break
                await asyncio.sleep(0.25)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            stop_requested.set()
            stream_task.cancel()
            try:
                await stream_task
            except (asyncio.CancelledError, Exception):
                pass
            await recorder.close()

            elapsed = max(0.01, time.monotonic() - start_time)
            table = Table(title="Market Harvesting Summary", show_lines=False)
            table.add_column("Metric", style="bold cyan")
            table.add_column("Value", style="green")
            table.add_row("Elapsed Duration", f"{elapsed:.1f}s")
            table.add_row("Snapshots Recorded", str(recorder.records_written))
            table.add_row("Unique Tokens Observed", str(len(unique_mints)))
            table.add_row("Output File", str(output_path.resolve()))
            console.print(table)

    try:
        asyncio.run(_run_harvester())
    except (KeyboardInterrupt, SystemExit):
        pass


def main() -> None:
    parser = build_record_parser()
    args = parser.parse_args()
    run_record_cli(args)


if __name__ == "__main__":
    main()
