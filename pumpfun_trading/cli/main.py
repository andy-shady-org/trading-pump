"""Main CLI entrypoint for the Pump.fun trading bot and public tooling."""

from __future__ import annotations

import argparse
import asyncio
import json

from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig, resolve_strategy_config
from pumpfun_trading.cli.arbitrage import build_arbitrage_parser, run_arbitrage_cli
from pumpfun_trading.cli.audit import build_audit_parser, run_audit_cli
from pumpfun_trading.cli.events import build_events_parser, run_events_cli
from pumpfun_trading.cli.optimize import build_optimize_parser, run_optimize_cli
from pumpfun_trading.cli.record import build_record_parser, run_record_cli
from pumpfun_trading.cli.replay import build_replay_parser
from pumpfun_trading.ops.logging import get_configured_console
from pumpfun_trading.ops.retention import LogRetentionManager, RetentionPolicy

console = get_configured_console()


def _coerce_list(payload):
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "coins", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _first_key(record, *keys):
    for key in keys:
        if key in record and record.get(key) is not None:
            return record.get(key)
    return None


def _format_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:,.4f}"
        return f"{value:,}"
    return str(value)


def _render_latest_coins(payload) -> None:
    rows = _coerce_list(payload)
    if not rows:
        console.print("[yellow]No latest coin data returned.[/yellow]")
        return

    table = Table(
        title="Latest Pump.fun Coins", show_lines=False, header_style="bold cyan"
    )
    table.add_column("Name", style="bold")
    table.add_column("Symbol")
    table.add_column("Mint", overflow="fold")
    table.add_column("Market Cap")
    table.add_column("Price")
    table.add_column("Holders")

    for item in rows[:25]:
        name = _first_key(item, "name", "tokenName", "displayName") or "-"
        symbol = _first_key(item, "symbol", "ticker") or "-"
        mint = _first_key(item, "mint", "mintAddress") or "-"
        market_cap = _first_key(
            item, "marketCap", "market_cap", "marketCapSol", "market_cap_sol"
        )
        price = _first_key(item, "price", "priceUsd", "price_usd")
        holders = _first_key(item, "holders", "holderCount", "holdersCount")
        table.add_row(
            str(name),
            str(symbol),
            str(mint),
            _format_value(market_cap),
            _format_value(price),
            _format_value(holders),
        )

    console.print(table)


def _render_market_info(payload) -> None:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        console.print(
            f"[yellow]Unexpected payload type: {type(payload).__name__}[/yellow]"
        )
        return

    title = _first_key(payload, "name", "tokenName", "displayName") or "Pump.fun Coin"
    symbol = _first_key(payload, "symbol", "ticker") or "-"
    mint = _first_key(payload, "mint", "mintAddress") or "-"
    market_cap = _first_key(
        payload, "marketCap", "market_cap", "marketCapSol", "market_cap_sol"
    )
    price = _first_key(payload, "price", "priceUsd", "price_usd")
    volume = _first_key(payload, "volume", "volume24h", "volume_24h")
    holders = _first_key(payload, "holders", "holderCount", "holdersCount")

    summary = (
        f"[bold]{title}[/bold] ([cyan]{symbol}[/cyan])\n"
        f"Mint: {mint}\n"
        f"Market Cap: {_format_value(market_cap)}\n"
        f"Price: {_format_value(price)}\n"
        f"Volume: {_format_value(volume)}\n"
        f"Holders: {_format_value(holders)}"
    )
    console.print(Panel(summary, title="Coin Summary", border_style="green"))

    detail_table = Table(show_header=False, box=None)
    detail_table.add_column("Field", style="bold cyan")
    detail_table.add_column("Value")

    for key, value in payload.items():
        if key in {
            "name",
            "symbol",
            "mint",
            "mintAddress",
            "price",
            "marketCap",
            "market_cap",
            "volume",
            "holders",
        }:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)[:200]
        detail_table.add_row(str(key), str(value))

    if detail_table.rows:
        console.print(Panel(detail_table, title="Details", border_style="blue"))


def build_ops_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "ops", help="Storage retention, compression, and maintenance operations"
        )
    else:
        parser = argparse.ArgumentParser(
            description="Storage retention, compression, and maintenance operations"
        )
    ops_subparsers = parser.add_subparsers(dest="ops_command")

    prune_p = ops_subparsers.add_parser(
        "prune", help="Prune expired log, audit, and replay archives"
    )
    prune_p.add_argument(
        "--target",
        default=".",
        help="Target directory to prune (default: current directory)",
    )
    prune_p.add_argument(
        "--days", type=int, default=30, help="Maximum archive retention in days"
    )
    prune_p.add_argument(
        "--max-files", type=int, default=10, help="Maximum archive file count limit"
    )
    prune_p.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Maximum total storage bytes allowed",
    )
    prune_p.add_argument(
        "--compress",
        action="store_true",
        help="Compress uncompressed rotated files to .gz",
    )

    status_p = ops_subparsers.add_parser(
        "status", help="Inspect storage consumption and archive metrics"
    )
    status_p.add_argument(
        "--target",
        default=".",
        help="Target directory to inspect (default: current directory)",
    )
    status_p.add_argument(
        "--json", action="store_true", help="Emit storage telemetry as JSON"
    )
    return parser


def run_ops_cli(args: argparse.Namespace) -> None:
    ops_cmd = getattr(args, "ops_command", None) or "status"
    target_dir = getattr(args, "target", ".") or "."
    policy = RetentionPolicy(
        max_age_days=getattr(args, "days", 30) or 30,
        max_files=getattr(args, "max_files", 10) or 10,
        total_max_bytes=getattr(args, "max_bytes", None),
        compress_archives=getattr(args, "compress", True),
    )
    manager = LogRetentionManager(target_directory=target_dir, policy=policy)

    if ops_cmd == "prune":
        pruned = manager.prune_expired()
        compressed = []
        if getattr(args, "compress", False):
            compressed = manager.compress_uncompressed_archives()
        console.print(
            f"[green]Successfully pruned {len(pruned)} expired files in {target_dir}.[/green]"
        )
        if compressed:
            console.print(
                f"[cyan]Compressed {len(compressed)} archive files to .gz.[/cyan]"
            )
        return

    if ops_cmd == "status":
        stats = manager.get_storage_stats()
        if getattr(args, "json", False):
            console.print(json.dumps(stats, indent=2, sort_keys=True))
            return
        table = Table(
            title=f"Log Storage Telemetry: {stats['directory']}",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Metric", style="bold")
        table.add_column("Value")
        table.add_row("Directory Exists", str(stats["exists"]))
        table.add_row("Total Files", str(stats["file_count"]))
        table.add_row("Compressed (.gz)", str(stats["compressed_count"]))
        table.add_row("Total Storage", stats["total_human"])
        table.add_row("Total Bytes", f"{stats['total_bytes']:,} B")
        console.print(table)
        return


def _render_raw_json(payload) -> None:
    console.print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pump.fun public market data CLI and trading bot"
    )
    subparsers = parser.add_subparsers(dest="command")
    build_arbitrage_parser(subparsers)
    build_audit_parser(subparsers)
    build_events_parser(subparsers)
    build_optimize_parser(subparsers)
    build_replay_parser(subparsers)
    build_record_parser(subparsers)
    build_ops_parser(subparsers)

    parser.add_argument("--mint", type=str, help="Mint address to inspect")
    parser.add_argument(
        "--limit", type=int, default=20, help="Result limit for latest coin queries"
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Offset for latest coin queries"
    )
    parser.add_argument(
        "--mode",
        choices=["market-info", "latest-coins", "bot", "replay"],
        default="market-info",
        help="market-info: inspect metadata, latest-coins: list coins, bot: run the live launch-monitoring bot, replay: run a historical replay",
    )
    parser.add_argument(
        "--preset",
        choices=["conservative", "balanced", "aggressive", "momentum"],
        default="balanced",
        help="Trading strategy preset",
    )
    parser.add_argument(
        "--buy-amount-sol",
        type=float,
        default=None,
        help="SOL to spend per buy (overrides preset)",
    )
    parser.add_argument(
        "--take-profit",
        type=float,
        default=None,
        help="Take-profit multiplier (overrides preset)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Stop-loss multiplier (overrides preset)",
    )
    parser.add_argument(
        "--min-market-cap-sol",
        type=float,
        default=None,
        help="Minimum launch market cap to buy",
    )
    parser.add_argument(
        "--min-balance-sol",
        type=float,
        default=None,
        help="Minimum wallet balance required to trade",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not submit real transactions"
    )
    parser.add_argument(
        "--paper-trade", action="store_true", help="Run in paper-trading mode"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headlessly without interactive terminal UI",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to a JSON bot config file"
    )
    parser.add_argument(
        "--record-replay",
        type=str,
        default=None,
        metavar="PATH",
        help="Record market quote stream and trades to a JSONL replay dataset",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw JSON payload instead of a Rich-formatted view",
    )
    parser.add_argument(
        "--replay-path", type=str, help="Path to a JSON/JSONL historical replay dataset"
    )
    parser.add_argument(
        "--replay-mode",
        choices=["summary", "trades", "dashboard"],
        default=None,
        help="Historic replay output mode",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.command in {"arb", "arbitrage"}:
        run_arbitrage_cli(args)
        return

    if args.command == "audit":
        run_audit_cli(args)
        return

    if args.command == "events":
        run_events_cli(args)
        return

    if args.command == "optimize":
        run_optimize_cli(args)
        return

    if args.command == "record":
        run_record_cli(args)
        return

    if args.command == "ops":
        run_ops_cli(args)
        return

    if args.command == "replay":
        target_path = getattr(args, "path", None) or getattr(args, "replay_path", None)
        if not target_path:
            raise SystemExit("--path is required when using the replay subcommand")
        from pumpfun_trading.cli.replay import run_replay_cli

        run_replay_cli(args)
        return

    if args.mode == "latest-coins":

        async def _run_latest_coins() -> None:
            client = PumpFunApiClient()
            try:
                payload = await client.get_latest_coins(
                    limit=args.limit, offset=args.offset
                )
                if args.raw:
                    _render_raw_json(payload)
                else:
                    _render_latest_coins(payload)
            finally:
                await client.close()

        asyncio.run(_run_latest_coins())
        return

    if args.mode == "bot":

        async def _run_bot() -> None:
            config = None
            if args.config:
                config = TradingBotConfig.from_file(args.config)
            if config is None:
                config = resolve_strategy_config(
                    args.preset,
                    overrides={
                        "buy_amount_sol": args.buy_amount_sol,
                        "take_profit": args.take_profit,
                        "stop_loss": args.stop_loss,
                        "min_market_cap_sol": args.min_market_cap_sol,
                        "min_balance_sol": args.min_balance_sol,
                    },
                )

            bot = TradingBot.from_env(
                config=config,
                dry_run=args.dry_run,
                paper_trade=args.paper_trade,
                headless=args.headless,
                replay_log_path=args.record_replay,
            )
            bot.config_path = args.config
            try:
                await bot.start()
            finally:
                await bot.close()

        try:
            asyncio.run(_run_bot())
        except (KeyboardInterrupt, SystemExit):
            pass
        return

    if args.mode == "replay":
        if not args.replay_path:
            raise SystemExit("--replay-path is required when --mode replay")
        from pumpfun_trading.cli.replay import run_replay_cli

        run_replay_cli(args)
        return

    async def _run_market_info() -> None:
        client = PumpFunApiClient()
        try:
            if not args.mint:
                raise SystemExit("--mint is required when --mode market-info")
            payload = await client.get_coin(args.mint)
            if args.raw:
                _render_raw_json(payload)
            else:
                _render_market_info(payload)
        finally:
            await client.close()

    asyncio.run(_run_market_info())


if __name__ == "__main__":
    main()
