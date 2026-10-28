"""Unit tests for ``cli/optimize.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pumpfun_trading.engines.optimizer import (
    FitnessScore,
    OptimizationResult,
    OptimizationTrial,
)


def test_optimize_cli_execution(tmp_path: Path, capsys):
    from rich.console import Console

    from pumpfun_trading.cli.main import main as main_cli
    from pumpfun_trading.cli.optimize import (
        build_parser,
        render_optimization_results,
        run_optimize_cli,
    )

    # 1. Parser construction
    parser = build_parser()
    args = parser.parse_args(
        ["--dataset", "test.jsonl", "--method", "random", "--iterations", "10"]
    )
    assert args.dataset == "test.jsonl"
    assert args.method == "random"
    assert args.iterations == 10

    # 2. Prepare sample dataset file
    dataset_file = tmp_path / "replay_sample.jsonl"
    records = [
        {
            "mint": "MINT1",
            "price": 10.0,
            "timestamp": 1000.0,
            "txType": "buy",
            "sol_amount": 0.5,
        },
        {
            "mint": "MINT1",
            "price": 18.0,
            "timestamp": 1010.0,
            "txType": "buy",
            "sol_amount": 0.5,
        },
        {
            "mint": "MINT1",
            "price": 25.0,
            "timestamp": 1020.0,
            "txType": "sell",
            "sol_amount": 0.5,
        },
    ]
    with open(dataset_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    export_file = tmp_path / "tuned_bot.json"

    # 3. Run CLI with export and json flag
    cli_args = parser.parse_args(
        [
            "--dataset",
            str(dataset_file),
            "--method",
            "random",
            "--iterations",
            "3",
            "--export-config",
            str(export_file),
            "--seed",
            "42",
            "--json",
        ]
    )
    run_optimize_cli(cli_args)
    assert export_file.exists()

    # 4. Run CLI table rendering mode
    cli_table_args = parser.parse_args(
        [
            "--dataset",
            str(dataset_file),
            "--method",
            "genetic",
            "--population-size",
            "4",
            "--generations",
            "2",
            "--preset",
            "balanced",
            "--top-k",
            "3",
            "--seed",
            "42",
        ]
    )
    run_optimize_cli(cli_table_args)

    # 5. Missing dataset error handling
    with pytest.raises(SystemExit):
        run_optimize_cli(parser.parse_args([]))

    with pytest.raises(SystemExit):
        run_optimize_cli(
            parser.parse_args(["--dataset", str(tmp_path / "nonexistent.jsonl")])
        )

    # 6. Render optimization results helper
    mock_score = FitnessScore(1.0, 1.0, 1.0, 1.0, 0.1, 0.05, 0.5, 2.0, 2)
    mock_trial = OptimizationTrial(
        1, {"buy_amount_sol": 0.01}, mock_score, mock_score, 0.0, 0.1
    )
    mock_res = OptimizationResult(
        mock_trial, [mock_trial], "composite", "random", 0.5, 1
    )
    test_console = Console(record=True, width=120)
    render_optimization_results(mock_res, top_k=2, target_console=test_console)
    output = test_console.export_text()
    assert "Hyperparameter Optimization Summary" in output
    assert "Top 1 Strategy Configurations" in output

    # 7. Main CLI integration with subcommand
    import sys

    orig_argv = sys.argv
    try:
        sys.argv = [
            "pumpfun",
            "optimize",
            "--dataset",
            str(dataset_file),
            "--method",
            "random",
            "--iterations",
            "2",
        ]
        main_cli()
    finally:
        sys.argv = orig_argv
