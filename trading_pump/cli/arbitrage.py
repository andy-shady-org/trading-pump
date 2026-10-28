"""CLI tooling for cross-venue arbitrage monitoring and bundle simulation (FEAT-28)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from rich.table import Table

from trading_pump.ops.logging import get_configured_console
from trading_pump.strategies.arbitrage import (
    ArbitrageOpportunity,
    CrossVenueDisparityMonitor,
    OptimalArbitrageCalculator,
)

console = get_configured_console()


def build_arbitrage_parser(
    subparsers: Optional[argparse._SubParsersAction[Any]] = None,
) -> argparse.ArgumentParser:
    """Construct argument parser for pumpfun-arb and pumpfun arb subcommand."""
    if subparsers is not None:
        parser = subparsers.add_parser(
            "arb",
            aliases=["arbitrage"],
            help="Monitor cross-venue spreads and execute/simulate atomic arbitrage",
        )
    else:
        parser = argparse.ArgumentParser(
            prog="pumpfun-arb",
            description="Pump.fun cross-venue spot disparity monitor and Jito arbitrage executor",
        )

    parser.add_argument(
        "--mint",
        type=str,
        default=None,
        help="Target mint address to inspect or evaluate",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Continuously monitor cross-venue disparities in live terminal mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate atomic transactions without broadcasting live on-chain (default: true)",
    )
    parser.add_argument(
        "--live",
        dest="dry_run",
        action="store_false",
        help="Broadcast live atomic arbitrage bundles via private Jito block engines",
    )
    parser.add_argument(
        "--min-spread",
        type=float,
        default=0.015,
        help="Minimum percentage spread hurdle (default: 0.015 = 1.5%%)",
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        default=0.003,
        help="Minimum net SOL profit hurdle after gas and validator tips (default: 0.003 SOL)",
    )
    parser.add_argument(
        "--max-input",
        type=float,
        default=0.50,
        help="Maximum input SOL cap for arbitrage leg (default: 0.50 SOL)",
    )
    parser.add_argument(
        "--min-input",
        type=float,
        default=0.01,
        help="Minimum input SOL threshold (default: 0.01 SOL)",
    )
    parser.add_argument(
        "--tip-share",
        type=float,
        default=0.50,
        help="Jito validator profit share ratio (default: 0.50 = 50%%)",
    )
    parser.add_argument(
        "--export-history",
        type=str,
        default=None,
        help="Path to export detected opportunities and execution records as JSON",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output raw JSON instead of Rich terminal tables",
    )
    return parser


def render_opportunity_table(opportunities: list[ArbitrageOpportunity]) -> None:
    """Render structured table of cross-venue arbitrage opportunities."""
    table = Table(
        title="Cross-Venue Arbitrage Opportunities",
        border_style="magenta",
        header_style="bold cyan",
    )
    table.add_column("Mint", style="yellow")
    table.add_column("Direction", style="bold")
    table.add_column("Pump Spot", justify="right")
    table.add_column("Raydium Spot", justify="right")
    table.add_column("Spread", justify="right", style="bold green")
    table.add_column("Input SOL", justify="right")
    table.add_column("Gross Output", justify="right")
    table.add_column("Jito Tip", justify="right")
    table.add_column("Net Profit", justify="right", style="bold green")

    for opp in opportunities:
        spread_str = f"{opp.spread_pct * 100:.2f}%"
        direction_color = "green" if opp.direction == "pump_to_raydium" else "cyan"
        dir_str = f"[{direction_color}]{opp.direction}[/{direction_color}]"

        table.add_row(
            f"{opp.mint[:10]}...",
            dir_str,
            f"{opp.pump_spot_price:.8f}",
            f"{opp.raydium_spot_price:.8f}",
            spread_str,
            f"{opp.optimal_input_sol:.4f}",
            f"{opp.expected_output_sol:.4f}",
            f"{opp.estimated_jito_tip_sol:.5f}",
            f"{opp.net_profit_sol:+.5f}",
        )

    console.print(table)


def run_arbitrage_cli(args: argparse.Namespace) -> int:
    """Execute arbitrage CLI command.

    Only a demo over hardcoded sample reserves is implemented: there is no live
    reserve feed or bundle execution here, so `--live` is refused and all output
    is labelled as demo data (BUG-90).
    """
    if not getattr(args, "dry_run", True):
        console.print(
            "[red]pumpfun-arb --live is not supported: this command only evaluates "
            "hardcoded demo reserves and cannot execute bundles.[/red]"
        )
        return 2
    if getattr(args, "monitor", False):
        console.print(
            "[yellow]--monitor is not implemented yet; showing demo samples only.[/yellow]"
        )
    calculator = OptimalArbitrageCalculator(
        jito_tip_profit_share_pct=args.tip_share,
    )
    monitor = CrossVenueDisparityMonitor(
        calculator=calculator,
        min_arbitrage_spread_pct=args.min_spread,
        min_arbitrage_profit_sol=args.min_profit,
        max_arbitrage_input_sol=args.max_input,
        min_arbitrage_input_sol=args.min_input,
        jito_tip_profit_share_pct=args.tip_share,
    )

    # Synthetic / Demonstration evaluation if no live stream provided
    sample_opportunities: list[ArbitrageOpportunity] = []

    # Scenario 1: Pump.fun curve is cheaper than Raydium pool (pump_to_raydium)
    opp1 = monitor.evaluate_spread(
        mint=args.mint or "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        pump_virtual_sol=35_000_000_000,
        pump_virtual_token=900_000_000_000_000,
        raydium_sol_reserve=85_000_000_000,
        raydium_token_reserve=180_000_000_000_000,
    )
    if opp1:
        sample_opportunities.append(opp1)

    # Scenario 2: Raydium pool is cheaper than Pump.fun curve (raydium_to_pump)
    opp2 = monitor.evaluate_spread(
        mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        pump_virtual_sol=80_000_000_000,
        pump_virtual_token=250_000_000_000_000,
        raydium_sol_reserve=40_000_000_000,
        raydium_token_reserve=200_000_000_000_000,
    )
    if opp2:
        sample_opportunities.append(opp2)

    demo_rows = [{**o.to_dict(), "demo": True} for o in sample_opportunities]
    if args.raw:
        console.print(json.dumps(demo_rows, indent=2))
    else:
        console.print(
            "[bold yellow]DEMO DATA: hardcoded sample reserves, not live market "
            "opportunities.[/bold yellow]"
        )
        render_opportunity_table(sample_opportunities)

    if args.export_history:
        export_path = Path(args.export_history)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            json.dumps(demo_rows, indent=2),
            encoding="utf-8",
        )
        console.print(
            f"[green]Exported {len(sample_opportunities)} opportunities to {export_path}[/green]"
        )

    return 0


def main() -> None:
    """Standalone entrypoint for pumpfun-arb."""
    parser = build_arbitrage_parser()
    args = parser.parse_args()
    sys.exit(run_arbitrage_cli(args))


__all__ = [
    "build_arbitrage_parser",
    "run_arbitrage_cli",
    "render_opportunity_table",
    "main",
]
