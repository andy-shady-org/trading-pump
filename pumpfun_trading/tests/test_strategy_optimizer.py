from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from pumpfun_trading.engines.optimizer import (
    BoolParam,
    CategoricalParam,
    FitnessScore,
    FloatParam,
    GeneticOptimizer,
    IntParam,
    OptimizationResult,
    OptimizationTrial,
    ParameterSpace,
    StrategyOptimizer,
    WalkForwardValidator,
    build_default_strategy_search_space,
    calculate_calmar_ratio,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    evaluate_fitness,
)
from pumpfun_trading.strategies.base import TradingBotConfig


def test_float_param_sampling_and_clamping():
    rng = random.Random(42)
    p = FloatParam(
        name="test_float", min_val=0.01, max_val=0.10, step=0.01, default=0.05
    )

    # Sampling
    samples = [p.sample(rng) for _ in range(50)]
    for s in samples:
        assert 0.01 <= s <= 0.10
        assert round(s, 2) == s

    # Clamping
    assert p.clamp(0.005) == 0.01
    assert p.clamp(0.20) == 0.10
    assert p.clamp(0.043) == 0.04

    # Perturbation
    perturbed = p.perturb(0.05, rng, scale=0.1)
    assert 0.01 <= perturbed <= 0.10

    # Grid values
    grid = p.grid_values(steps=5)
    assert len(grid) == 5
    assert grid[0] == 0.01
    assert grid[-1] == 0.10


def test_float_param_log_scale():
    rng = random.Random(42)
    p = FloatParam(name="log_param", min_val=0.001, max_val=1.0, log_scale=True)
    samples = [p.sample(rng) for _ in range(100)]
    for s in samples:
        assert 0.001 <= s <= 1.0

    grid = p.grid_values(steps=4)
    assert len(grid) == 4
    assert grid[0] == 0.001
    assert grid[-1] == 1.0


def test_param_validation_errors():
    with pytest.raises(ValueError, match="min_val .* must be < max_val"):
        FloatParam(name="invalid", min_val=1.0, max_val=0.5)

    with pytest.raises(ValueError, match="log_scale requires min_val > 0"):
        FloatParam(name="invalid_log", min_val=0.0, max_val=1.0, log_scale=True)

    with pytest.raises(ValueError, match="min_val .* must be <= max_val"):
        IntParam(name="invalid_int", min_val=10, max_val=5)

    with pytest.raises(ValueError, match="step must be > 0"):
        IntParam(name="invalid_int_step", min_val=1, max_val=10, step=0)

    with pytest.raises(ValueError, match="choices tuple cannot be empty"):
        CategoricalParam(name="empty_choices", choices=())


def test_int_param_sampling_and_grid():
    rng = random.Random(42)
    p = IntParam(name="int_p", min_val=2, max_val=10, step=2, default=4)
    samples = [p.sample(rng) for _ in range(50)]
    for s in samples:
        assert s in (2, 4, 6, 8, 10)

    assert p.clamp(1) == 2
    assert p.clamp(12) == 10
    assert p.clamp(5) == 4

    perturbed = p.perturb(4, rng, scale=0.2)
    assert perturbed in (2, 4, 6, 8, 10)

    grid = p.grid_values(steps=3)
    assert len(grid) == 3
    assert all(val in (2, 4, 6, 8, 10) for val in grid)


def test_categorical_and_bool_params():
    rng = random.Random(42)
    cat = CategoricalParam(
        name="mode",
        choices=("conservative", "balanced", "aggressive"),
        default="balanced",
    )
    samples = {cat.sample(rng) for _ in range(30)}
    assert samples.issubset({"conservative", "balanced", "aggressive"})
    assert cat.clamp("unknown") == "balanced"
    assert cat.clamp("aggressive") == "aggressive"

    bp = BoolParam(name="flag", default=True)
    bool_samples = {bp.sample(rng) for _ in range(20)}
    assert bool_samples == {True, False}
    assert bp.clamp(1) is True
    assert bp.clamp(0) is False
    assert bp.grid_values() == [True, False]


def test_parameter_space_operations():
    rng = random.Random(42)
    space = ParameterSpace()
    space.add_parameter(FloatParam(name="f1", min_val=0.1, max_val=1.0))
    space.add_parameter(IntParam(name="i1", min_val=1, max_val=5))
    space.add_parameter(
        CategoricalParam(name="c1", choices=("A", "B", "C"), default="A")
    )

    assert len(space) == 3
    assert space.names == ["f1", "i1", "c1"]
    assert space.get("f1") is not None
    assert space.get("nonexistent") is None

    cfg = space.sample_configuration(rng)
    assert 0.1 <= cfg["f1"] <= 1.0
    assert 1 <= cfg["i1"] <= 5
    assert cfg["c1"] in ("A", "B", "C")

    # Grid generation
    grid = space.generate_grid(max_combinations=20, steps_per_param=2)
    assert 1 <= len(grid) <= 20

    # Crossover
    parent_a = {"f1": 0.2, "i1": 1, "c1": "A"}
    parent_b = {"f1": 0.8, "i1": 5, "c1": "C"}
    child = space.crossover(parent_a, parent_b, rng)
    assert 0.1 <= child["f1"] <= 1.0
    assert child["i1"] in (1, 5)
    assert child["c1"] in ("A", "C")

    # Mutation
    mutated = space.mutate(child, mutation_rate=1.0, rng=rng)
    assert 0.1 <= mutated["f1"] <= 1.0
    assert 1 <= mutated["i1"] <= 5


def test_build_default_strategy_search_space():
    cfg = TradingBotConfig(take_profit=1.8, max_active_positions=5)
    space = build_default_strategy_search_space(cfg)
    # Only knobs PaperTradingEngine reads are searched (BUG-61).
    assert set(space.names) == {
        "max_active_positions",
        "momentum_min_z_score",
        "momentum_min_buy_ratio",
        "momentum_min_unique_buyers",
        "momentum_window_seconds",
        "stop_loss_pct",
        "take_profit",
    }
    for unused in (
        "buy_amount_sol",
        "take_profit_tier1_multiplier",
        "trailing_stop_drop_pct",
        "max_daily_drawdown_pct",
    ):
        assert unused not in space.names

    tp = space.get("take_profit")
    assert tp is not None
    assert tp.default == 1.8


def test_fitness_metrics_calculation():
    # Sharpe Ratio
    returns_pos = [0.10, 0.15, 0.08, 0.12, 0.20]
    sharpe_pos = calculate_sharpe_ratio(returns_pos)
    assert sharpe_pos > 0

    returns_flat = [0.05, 0.05, 0.05]
    sharpe_flat = calculate_sharpe_ratio(returns_flat)
    assert sharpe_flat == 1.0

    assert calculate_sharpe_ratio([]) == 0.0
    assert calculate_sharpe_ratio([0.1]) == 0.0

    # Sortino Ratio
    sortino = calculate_sortino_ratio(returns_pos)
    assert sortino > 0
    assert calculate_sortino_ratio([]) == 0.0

    # Calmar Ratio
    calmar = calculate_calmar_ratio(0.50, 0.10)
    assert calmar == pytest.approx(5.0)
    assert calculate_calmar_ratio(0.50, 0.0) == pytest.approx(5.0)
    assert calculate_calmar_ratio(-0.20, 0.0) == -10.0


def test_evaluate_fitness_function():
    summary = {
        "initial_cash": 100.0,
        "final_cash": 120.0,
        "final_equity": 120.0,
        "total_trades": 4,
        "profit_factor": 2.5,
        "max_drawdown": 0.08,
        "win_rate": 0.75,
        "total_return": 0.20,
    }
    trades = [
        {"action": "buy", "mint": "tokenA"},
        {"action": "sell", "mint": "tokenA", "return_pct": 0.15},
        {"action": "buy", "mint": "tokenB"},
        {"action": "sell", "mint": "tokenB", "return_pct": 0.10},
    ]

    fit_composite = evaluate_fitness(summary, trades, objective="composite")
    assert isinstance(fit_composite, FitnessScore)
    assert fit_composite.total_trades == 4
    assert fit_composite.win_rate == 0.75
    assert fit_composite.total_return == 0.20
    assert fit_composite.objective_value != 0.0

    # Test single objectives
    fit_sharpe = evaluate_fitness(summary, trades, objective="sharpe")
    assert fit_sharpe.objective_value == fit_sharpe.sharpe_ratio

    fit_pf = evaluate_fitness(summary, trades, objective="profit_factor")
    assert fit_pf.objective_value == fit_pf.profit_factor

    fit_ret = evaluate_fitness(summary, trades, objective="total_return")
    assert fit_ret.objective_value == fit_ret.total_return

    # Zero trades penalty check
    fit_zero = evaluate_fitness({"total_return": 0.0}, [], objective="composite")
    assert fit_zero.objective_value < 0.0


def test_optimization_trial_and_result_export(tmp_path: Path):
    score = FitnessScore(
        objective_value=3.5,
        sharpe_ratio=2.1,
        sortino_ratio=2.8,
        profit_factor=2.0,
        total_return=0.35,
        max_drawdown=0.05,
        win_rate=0.80,
        calmar_ratio=7.0,
        total_trades=10,
        net_pnl=35.0,
    )
    test_score = FitnessScore(
        objective_value=3.0,
        sharpe_ratio=1.8,
        sortino_ratio=2.2,
        profit_factor=1.8,
        total_return=0.28,
        max_drawdown=0.06,
        win_rate=0.70,
        calmar_ratio=4.6,
        total_trades=8,
        net_pnl=28.0,
    )
    trial = OptimizationTrial(
        trial_id=1,
        parameters={"buy_amount_sol": 0.008, "max_active_positions": 3},
        train_fitness=score,
        test_fitness=test_score,
        overfit_delta=0.5,
        duration_seconds=0.05,
    )
    # Selection uses train fitness only; holdout is reporting-only (BUG-60).
    assert trial.composite_score == pytest.approx(3.5)
    assert trial.validation_score == pytest.approx(3.0 - 0.25)

    res = OptimizationResult(
        best_trial=trial,
        all_trials=[trial],
        objective_name="composite",
        search_method="genetic",
        total_duration_seconds=1.2,
        total_evaluations=1,
    )

    cfg = res.to_trading_bot_config()
    assert isinstance(cfg, TradingBotConfig)
    assert cfg.buy_amount_sol == 0.008
    assert cfg.max_active_positions == 3

    out_file = tmp_path / "tuned_config.json"
    exported_path = res.export_config_json(out_file)
    assert exported_path.exists()

    with open(exported_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["buy_amount_sol"] == 0.008
    assert data["max_active_positions"] == 3

    preset = res.export_preset_dict()
    assert preset["buy_amount_sol"] == 0.008


def test_walk_forward_validator():
    snaps = [{"mint": f"token_{i}", "price": float(i)} for i in range(100)]
    validator = WalkForwardValidator(train_split=0.70)
    train_snaps, test_snaps = validator.split_snapshots(snaps)
    assert len(train_snaps) == 70
    assert len(test_snaps) == 30

    empty_train, empty_test = validator.split_snapshots([])
    assert empty_train == []
    assert empty_test == []


def test_strategy_optimizers_end_to_end():
    # Build synthetic replay snapshot series
    snapshots = []
    base_ts = 1700000000.0
    for idx in range(1, 40):
        # Generate alternating token prices to trigger simulated entries/exits
        price = 10.0 + (math.sin(idx / 3.0) * 8.0)
        snapshots.append(
            {
                "mint": f"token_MINT_{idx % 3}",
                "name": f"Token_{idx % 3}",
                "price": max(1.0, price),
                "market_cap": max(1.0, price),
                "timestamp": base_ts + idx * 5.0,
                "txType": "buy",
                "sol_amount": 0.5,
                "user": "trader_1",
            }
        )

    # 1. Random Search Optimizer
    opt_random = StrategyOptimizer(
        method="random",
        iterations=5,
        objective="composite",
        train_split=0.70,
        seed=42,
    )
    res_random = opt_random.optimize(snapshots)
    assert len(res_random.all_trials) == 5
    assert res_random.search_method == "random"
    assert res_random.best_trial is not None

    # 2. Grid Search Optimizer
    opt_grid = StrategyOptimizer(
        method="grid",
        max_grid_combinations=4,
        objective="total_return",
        train_split=0.70,
        seed=42,
    )
    res_grid = opt_grid.optimize(snapshots)
    assert len(res_grid.all_trials) <= 4
    assert res_grid.search_method == "grid"

    # 3. Genetic Optimizer
    progress_called = []

    def on_progress(current: int, total: int, trial: OptimizationTrial):
        progress_called.append((current, total))

    opt_genetic = StrategyOptimizer(
        method="genetic",
        population_size=4,
        generations=2,
        objective="composite",
        train_split=0.70,
        seed=42,
    )
    res_genetic = opt_genetic.optimize(snapshots, progress_callback=on_progress)
    assert len(res_genetic.all_trials) == 8
    assert res_genetic.search_method == "genetic"
    assert len(progress_called) == 8

    # 4. Empty snapshots fallback
    opt_empty = StrategyOptimizer(method="genetic")
    res_empty = opt_empty.optimize([])
    assert len(res_empty.all_trials) == 1
    assert res_empty.total_evaluations == 1


def test_genetic_optimizer_elitism_and_selection():
    space = ParameterSpace()
    space.add_parameter(
        FloatParam(name="buy_amount_sol", min_val=0.005, max_val=0.05, step=0.005)
    )
    space.add_parameter(IntParam(name="max_active_positions", min_val=1, max_val=5))

    optimizer = GeneticOptimizer(
        parameter_space=space,
        population_size=6,
        generations=3,
        crossover_rate=0.8,
        mutation_rate=0.2,
        elite_count=2,
        tournament_size=3,
        seed=123,
    )

    snapshots = [
        {
            "mint": "mintA",
            "price": 10.0,
            "timestamp": 1000.0,
            "txType": "buy",
            "sol_amount": 0.5,
        },
        {
            "mint": "mintA",
            "price": 15.0,
            "timestamp": 1010.0,
            "txType": "buy",
            "sol_amount": 0.5,
        },
        {
            "mint": "mintA",
            "price": 20.0,
            "timestamp": 1020.0,
            "txType": "sell",
            "sol_amount": 0.5,
        },
    ]

    res = optimizer.optimize(train_snapshots=snapshots, test_snapshots=snapshots)
    assert len(res.all_trials) == 18
    assert res.best_trial is not None
    assert len(res.top_trials) == 18
    # Top trial score should be >= worst trial score
    assert res.top_trials[0].composite_score >= res.top_trials[-1].composite_score


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
