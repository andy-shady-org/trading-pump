"""Hyperparameter optimizer CLI entrypoint for backtest strategy parameter calibration."""

from __future__ import annotations

import argparse
import json

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from pumpfun_trading.engines.optimizer import (
    OptimizationResult,
    OptimizationTrial,
    StrategyOptimizer,
)
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.ops.logging import get_configured_console
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config

console = get_configured_console()


def build_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    if subparsers is not None:
        parser = subparsers.add_parser(
            "optimize",
            description="Run hyperparameter optimization and parameter auto-tuning across historical datasets",
        )
    else:
        parser = argparse.ArgumentParser(
            description="Run hyperparameter optimization and parameter auto-tuning across historical datasets"
        )

    parser.add_argument(
        "--dataset",
        "--path",
        dest="dataset",
        default=None,
        help="Path to historical replay dataset (.jsonl, .jsonl.gz, or directory)",
    )
    parser.add_argument(
        "--method",
        choices=["genetic", "random", "grid"],
        default="genetic",
        help="Optimization algorithm (default: genetic)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=30,
        help="Search budget iterations for random search (default: 30)",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=20,
        help="Population size per generation for genetic search (default: 20)",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=5,
        help="Number of evolutionary generations for genetic search (default: 5)",
    )
    parser.add_argument(
        "--max-grid-combinations",
        type=int,
        default=50,
        help="Maximum parameter combinations for grid search (default: 50)",
    )
    parser.add_argument(
        "--objective",
        choices=[
            "composite",
            "sharpe",
            "profit_factor",
            "sortino",
            "calmar",
            "total_return",
            "win_rate",
        ],
        default="composite",
        help="Target fitness objective to maximize (default: composite)",
    )
    parser.add_argument(
        "--train-split",
        type=float,
        default=0.70,
        help="In-sample training split fraction (default: 0.70)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to base JSON configuration to calibrate against",
    )
    parser.add_argument(
        "--preset",
        "--export-preset",
        dest="preset",
        choices=["conservative", "balanced", "aggressive", "momentum"],
        default=None,
        help="Baseline strategy preset to use as starting defaults",
    )
    parser.add_argument(
        "--export-config",
        type=str,
        default=None,
        help="Path to export calibrated TradingBotConfig JSON file",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of top candidate rankings to display (default: 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Deterministic random seed for reproducibility",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output optimization summary and top parameters as JSON",
    )
    return parser


def build_optimize_parser(
    subparsers: argparse._SubParsersAction | None = None,
) -> argparse.ArgumentParser:
    return build_parser(subparsers)


def render_optimization_results(
    result: OptimizationResult,
    top_k: int = 5,
    target_console: Console | None = None,
) -> None:
    c = target_console or console
    best = result.best_trial

    # 1. Summary Overview Panel
    summary_table = Table.grid(expand=True)
    summary_table.add_column(style="bold cyan", justify="left")
    summary_table.add_column(justify="right")

    summary_table.add_row("Search Method", result.search_method.upper())
    summary_table.add_row("Fitness Objective", result.objective_name.upper())
    summary_table.add_row("Total Evaluations", f"{result.total_evaluations:,}")
    summary_table.add_row(
        "Optimization Duration", f"{result.total_duration_seconds:.2f}s"
    )
    summary_table.add_row(
        "Best In-Sample Score", f"{best.train_fitness.objective_value:.4f}"
    )
    if best.test_fitness is not None:
        summary_table.add_row(
            "Best Out-of-Sample Score", f"{best.test_fitness.objective_value:.4f}"
        )
        summary_table.add_row("Overfitting Delta", f"{best.overfit_delta:.4f}")
    summary_table.add_row("Best Sharpe Ratio", f"{best.train_fitness.sharpe_ratio:.2f}")
    summary_table.add_row(
        "Best Profit Factor", f"{best.train_fitness.profit_factor:.2f}"
    )
    summary_table.add_row(
        "Best Total Return", f"{best.train_fitness.total_return * 100.0:+.2f}%"
    )
    summary_table.add_row(
        "Best Win Rate", f"{best.train_fitness.win_rate * 100.0:.1f}%"
    )
    summary_table.add_row(
        "Best Max Drawdown", f"{best.train_fitness.max_drawdown * 100.0:.2f}%"
    )

    panel = Panel(
        summary_table,
        title="[bold green]Hyperparameter Optimization Summary[/bold green]",
        border_style="green",
    )
    c.print(panel)

    # 2. Top-K Parameter Ranking Table
    ranking_table = Table(
        title=f"Top {min(top_k, len(result.top_trials))} Strategy Configurations",
        header_style="bold cyan",
        show_lines=False,
    )
    ranking_table.add_column("Rank", style="bold", justify="center")
    ranking_table.add_column("Score", justify="right")
    ranking_table.add_column("Sharpe", justify="right")
    ranking_table.add_column("PF", justify="right")
    ranking_table.add_column("Return", justify="right")
    ranking_table.add_column("Max DD", justify="right")
    ranking_table.add_column("Trades", justify="right")
    ranking_table.add_column("Key Calibrated Parameters", overflow="fold")

    for rank, trial in enumerate(result.top_trials[:top_k], start=1):
        fit = trial.train_fitness
        key_params = []
        for k in (
            "buy_amount_sol",
            "max_active_positions",
            "take_profit_tier1_multiplier",
            "take_profit_tier2_multiplier",
            "trailing_stop_drop_pct",
            "stagnant_curve_timeout_seconds",
            "max_daily_drawdown_pct",
        ):
            if k in trial.parameters:
                val = trial.parameters[k]
                val_str = f"{val:.3f}" if isinstance(val, float) else str(val)
                key_params.append(f"{k}={val_str}")

        param_str = ", ".join(key_params[:4]) + ("..." if len(key_params) > 4 else "")
        ranking_table.add_row(
            f"#{rank}",
            f"{trial.composite_score:.4f}",
            f"{fit.sharpe_ratio:.2f}",
            f"{fit.profit_factor:.2f}",
            f"{fit.total_return * 100.0:+.1f}%",
            f"{fit.max_drawdown * 100.0:.1f}%",
            str(fit.total_trades),
            param_str,
        )

    c.print(ranking_table)


def run_optimize_cli(args: argparse.Namespace | None = None) -> None:
    if args is None:
        args = build_parser().parse_args()

    dataset_path = getattr(args, "dataset", None)
    if not dataset_path:
        console.print(
            "[bold red]Error:[/bold red] --dataset (or --path) is required to run optimizer."
        )
        raise SystemExit(1)

    # Load baseline config
    base_config: TradingBotConfig | None = None
    if getattr(args, "config", None):
        base_config = TradingBotConfig.from_file(args.config)
    elif getattr(args, "preset", None):
        base_config = resolve_strategy_config(args.preset)

    # Ingest historical dataset snapshots
    snapshots = PaperTradingEngine.load_history(dataset_path)
    if not snapshots:
        console.print(
            f"[bold red]Error:[/bold red] No valid market replay snapshots found at {dataset_path}."
        )
        raise SystemExit(1)

    console.print(
        f"[cyan]Loaded {len(snapshots):,} snapshots from {dataset_path}. Initializing {args.method.upper()} optimizer...[/cyan]"
    )

    optimizer = StrategyOptimizer(
        method=getattr(args, "method", "genetic"),
        objective=getattr(args, "objective", "composite"),
        iterations=getattr(args, "iterations", 30),
        population_size=getattr(args, "population_size", 20),
        generations=getattr(args, "generations", 5),
        max_grid_combinations=getattr(args, "max_grid_combinations", 50),
        train_split=getattr(args, "train_split", 0.70),
        seed=getattr(args, "seed", None),
        base_config=base_config,
    )

    result: OptimizationResult
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Optimizing ({args.method})...", total=100)

        def on_progress(current: int, total: int, trial: OptimizationTrial) -> None:
            pct = (current / total) * 100.0 if total > 0 else 100.0
            progress.update(
                task,
                completed=pct,
                description=f"Trial {current}/{total} | Score: {trial.composite_score:.3f}",
            )

        result = optimizer.optimize(snapshots, progress_callback=on_progress)
        progress.update(task, completed=100.0, description="Optimization Complete")

    # JSON output mode
    if getattr(args, "json", False):
        payload = {
            "search_method": result.search_method,
            "objective": result.objective_name,
            "total_evaluations": result.total_evaluations,
            "duration_seconds": result.total_duration_seconds,
            "best_trial": {
                "trial_id": result.best_trial.trial_id,
                "composite_score": result.best_trial.composite_score,
                "parameters": result.best_trial.parameters,
                "train_fitness": {
                    "objective_value": result.best_trial.train_fitness.objective_value,
                    "sharpe_ratio": result.best_trial.train_fitness.sharpe_ratio,
                    "profit_factor": result.best_trial.train_fitness.profit_factor,
                    "total_return": result.best_trial.train_fitness.total_return,
                    "max_drawdown": result.best_trial.train_fitness.max_drawdown,
                    "win_rate": result.best_trial.train_fitness.win_rate,
                    "total_trades": result.best_trial.train_fitness.total_trades,
                },
            },
        }
        console.print(json.dumps(payload, indent=2))
    else:
        render_optimization_results(
            result, top_k=getattr(args, "top_k", 5), target_console=console
        )

    # Export config if requested
    export_path = getattr(args, "export_config", None)
    if export_path:
        out = result.export_config_json(export_path, base_config=base_config)
        console.print(
            f"[bold green]✓ Exported calibrated TradingBotConfig to:[/bold green] {out}"
        )


def main() -> None:
    run_optimize_cli()


__all__ = [
    "build_parser",
    "build_optimize_parser",
    "run_optimize_cli",
    "render_optimization_results",
    "main",
]
