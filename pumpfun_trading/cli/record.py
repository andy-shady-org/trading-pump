"""Market stream recorder and historical dataset generator CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.recorder import ReplayRecorder
from pumpfun_trading.engines.generators import (
    RestHistoryExporter,
    SyntheticReplayGenerator,
)
from pumpfun_trading.ops.logging import get_configured_console
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)

logger = logging.getLogger(__name__)
console = get_configured_console()


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
        default="market_replay.jsonl",
        help="Destination path for .jsonl replay dataset (default: market_replay.jsonl)",
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
    return parser


def run_record_cli(args: argparse.Namespace) -> None:
    """Execute the record CLI handler."""
    output_path = Path(args.output)

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
                                        "is_buy": True,
                                        "signal": "buy",
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

        # Run selected stream task
        stream_task = asyncio.create_task(
            _stream_geyser() if geyser_endpoint else _stream_websocket_or_polling()
        )

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
