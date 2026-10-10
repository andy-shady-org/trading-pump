import argparse
import asyncio
import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig, resolve_strategy_config
from pumpfun_trading.audit import (
    export_audit_records,
    filter_audit_records,
    load_audit_records,
    render_audit_table,
    summarize_audit_records,
)

console = Console()


def _coerce_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "coins", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _first_key(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record.get(key) is not None:
            return record.get(key)
    return None


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:,.4f}"
        return f"{value:,}"
    return str(value)


def _render_latest_coins(payload: Any) -> None:
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


def _render_market_info(payload: Any) -> None:
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


def _render_raw_json(payload: Any) -> None:
    console.print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _build_audit_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("audit", help="Inspect the JSONL audit trail")
    parser.add_argument("--path", required=True, help="Path to the JSONL audit file")
    parser.add_argument("--record-type", default=None, help="Filter by record type")
    parser.add_argument("--state", default=None, help="Filter by state")
    parser.add_argument("--date-from", default=None, help="Start timestamp or ISO date")
    parser.add_argument("--date-to", default=None, help="End timestamp or ISO date")
    parser.add_argument("--mint", default=None, help="Filter by mint address")
    parser.add_argument("--token-name", default=None, help="Filter by token name")
    parser.add_argument("--reason", default=None, help="Filter by trade reason")
    parser.add_argument("--status", default=None, help="Filter by record outcome/status")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records to return")
    parser.add_argument("--summary", action="store_true", help="Print summary statistics instead of rows")
    parser.add_argument("--json", action="store_true", help="Export filtered records as JSON to stdout")
    parser.add_argument("--export", default=None, help="Write filtered records to a JSON file")


def _run_audit_tool(args: argparse.Namespace) -> None:
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pump.fun public market data CLI and trading bot"
    )
    subparsers = parser.add_subparsers(dest="command")
    _build_audit_parser(subparsers)

    parser.add_argument("--mint", type=str, help="Mint address to inspect")
    parser.add_argument(
        "--limit", type=int, default=20, help="Result limit for latest coin queries"
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Offset for latest coin queries"
    )
    parser.add_argument(
        "--mode",
        choices=["market-info", "latest-coins", "bot"],
        default="market-info",
        help="market-info: inspect metadata, latest-coins: list coins, bot: run the live launch-monitoring bot",
    )
    parser.add_argument(
        "--preset",
        choices=["conservative", "balanced", "aggressive"],
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
        "--config", type=str, default=None, help="Path to a JSON bot config file"
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw JSON payload instead of a Rich-formatted view",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.command == "audit":
        _run_audit_tool(args)
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
            )
            try:
                await bot.start()
            finally:
                await bot.close()

        asyncio.run(_run_bot())
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
