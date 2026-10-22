"""Unit tests for ``engines/optimizer.py`` search spaces, fitness and optimizers."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest

from pumpfun_trading.engines import optimizer as optimizer_module
from pumpfun_trading.engines.optimizer import (
    BaseOptimizer,
    BoolParam,
    CategoricalParam,
    FitnessScore,
    FloatParam,
    GeneticOptimizer,
    GridSearchOptimizer,
    Hyperparameter,
    IntParam,
    OptimizationResult,
    OptimizationTrial,
    ParameterSpace,
    RandomSearchOptimizer,
    StrategyOptimizer,
    WalkForwardValidator,
    build_default_strategy_search_space,
    calculate_calmar_ratio,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    evaluate_fitness,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config
from pumpfun_trading.tests.support.factories import make_config


def _fitness(value: float) -> FitnessScore:
    return FitnessScore(value, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)


def _fake_evaluate(
    trial_id: int,
    parameters: dict[str, Any],
    train_snapshots: Sequence[dict[str, Any]],
    test_snapshots: Sequence[dict[str, Any]] | None = None,
    objective: str = "composite",
    base_config: TradingBotConfig | None = None,
) -> OptimizationTrial:
    """Scores a trial by its ``x`` parameter so the best trial is predictable."""
    return OptimizationTrial(
        trial_id, dict(parameters), _fitness(float(parameters.get("x", 0)))
    )


@pytest.fixture
def fake_evaluate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(optimizer_module, "evaluate_trial_on_snapshots", _fake_evaluate)


# --- abstract contracts ---------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda p, rng: Hyperparameter.sample(p, rng),
        lambda p, rng: Hyperparameter.perturb(p, 1.0, rng),
        lambda p, rng: Hyperparameter.clamp(p, 1.0),
        lambda p, rng: Hyperparameter.grid_values(p),
    ],
)
def test_hyperparameter_abstract_methods_raise_not_implemented(
    call: Callable[[Hyperparameter, random.Random], Any],
) -> None:
    with pytest.raises(NotImplementedError):
        call(FloatParam(name="x"), random.Random(0))


def test_base_optimizer_abstract_optimize_raises_not_implemented() -> None:
    random_search = RandomSearchOptimizer(ParameterSpace(), iterations=1, seed=0)

    with pytest.raises(NotImplementedError):
        BaseOptimizer.optimize(random_search, [])


# --- parameter domains ----------------------------------------------------------


def test_float_param_grid_single_step_returns_clamped_midpoint() -> None:
    param = FloatParam(name="x", min_val=1.0, max_val=2.0, step=0.3)

    assert param.grid_values(steps=1) == [1.6]


def test_float_param_grid_with_few_step_values_returns_all() -> None:
    param = FloatParam(name="x", min_val=0.0, max_val=1.0, step=0.5)

    assert param.grid_values(steps=5) == [0.0, 0.5, 1.0]


def test_float_param_grid_with_many_step_values_is_subsampled() -> None:
    param = FloatParam(name="x", min_val=0.0, max_val=1.0, step=0.1)

    values = param.grid_values(steps=3)

    assert len(values) == 3
    assert values[0] == 0.0
    assert all(0.0 <= v <= 1.0 for v in values)


def test_int_param_grid_smaller_than_steps_returns_full_range() -> None:
    assert IntParam(name="n", min_val=1, max_val=3).grid_values(steps=5) == [1, 2, 3]


def test_categorical_perturb_always_mutating_picks_other_choice() -> None:
    param = CategoricalParam(name="c", choices=("a", "b", "c"))
    rng = random.Random(1)

    picks = {param.perturb("a", rng, scale=1.0) for _ in range(20)}

    assert picks <= {"b", "c"}
    assert picks


def test_categorical_perturb_duplicate_choices_falls_back_to_first() -> None:
    param = CategoricalParam(name="c", choices=("a", "a"))

    assert param.perturb("a", random.Random(0), scale=1.0) == "a"


@pytest.mark.parametrize(("value", "expected"), [(True, False), (False, True)])
def test_bool_param_perturb_full_scale_flips_value(value: bool, expected: bool) -> None:
    assert BoolParam(name="b").perturb(value, random.Random(0), scale=1.0) is expected


def test_bool_param_perturb_zero_scale_keeps_value() -> None:
    assert BoolParam(name="b").perturb(True, random.Random(0), scale=0.0) is True


# --- ParameterSpace -------------------------------------------------------------


def test_clamp_configuration_missing_values_use_default_or_seeded_sample() -> None:
    space = ParameterSpace(
        [
            IntParam(name="with_default", min_val=1, max_val=10, default=50),
            IntParam(name="no_default", min_val=1, max_val=10),
            FloatParam(name="given", min_val=0.0, max_val=1.0),
        ]
    )

    clamped = space.clamp_configuration({"given": 3.0})

    assert clamped["with_default"] == 10
    assert clamped["given"] == 1.0
    assert clamped["no_default"] == IntParam(
        name="no_default", min_val=1, max_val=10
    ).sample(random.Random(42))
    assert space.clamp_configuration({"given": 3.0}) == clamped


def test_generate_grid_empty_space_returns_single_empty_config() -> None:
    assert ParameterSpace().generate_grid() == [{}]


def test_generate_grid_respects_max_combinations() -> None:
    space = ParameterSpace(
        [
            IntParam(name="a", min_val=1, max_val=3),
            IntParam(name="b", min_val=1, max_val=3),
        ]
    )

    assert len(space.generate_grid(max_combinations=4, steps_per_param=3)) == 4


# --- fitness --------------------------------------------------------------------


@pytest.mark.regression("BUG-135")
def test_sortino_ratio_with_downside_returns_scaled_ratio() -> None:
    ratio = calculate_sortino_ratio([0.5, -0.5])

    # mean 0, downside std = sqrt(0.25 / 1) = 0.5
    assert ratio == pytest.approx(0.0)
    # Per trade, no sqrt(n) factor (BUG-135).
    assert calculate_sortino_ratio([1.0, -0.5]) == pytest.approx(0.25 / 0.5)


SUMMARY: dict[str, Any] = {
    "total_return": 0.2,
    "max_drawdown": 0.1,
    "profit_factor": 3.0,
    "win_rate": 0.5,
    "total_trades": 2,
    "initial_cash": 100.0,
    "final_equity": 120.0,
}
TRADES: list[dict[str, Any]] = [
    {"action": "buy"},
    {"action": "sell", "return_pct": 0.5},
    {"action": "sell", "return_pct": -0.1},
]


@pytest.mark.parametrize(
    ("objective", "attribute"),
    [
        ("sortino", "sortino_ratio"),
        ("calmar", "calmar_ratio"),
        ("win_rate", "win_rate"),
        ("profit_factor", "profit_factor"),
        ("sharpe", "sharpe_ratio"),
    ],
)
def test_evaluate_fitness_named_objective_selects_metric(
    objective: str, attribute: str
) -> None:
    score = evaluate_fitness(SUMMARY, TRADES, objective=objective)

    assert score.objective_value == pytest.approx(getattr(score, attribute), abs=1e-4)
    assert score.net_pnl == pytest.approx(20.0)


def test_evaluate_fitness_custom_weights_override_composite() -> None:
    zeroed = {
        "sharpe": 0.0,
        "profit_factor": 0.0,
        "total_return": 1.0,
        "sortino": 0.0,
        "calmar": 0.0,
        "drawdown_penalty": 0.0,
    }

    score = evaluate_fitness(SUMMARY, TRADES, weights=zeroed)

    assert score.objective_value == pytest.approx(0.2)


def test_evaluate_fitness_single_sell_applies_activity_penalty() -> None:
    trades = [{"action": "sell", "return_pct": 0.3}]

    score = evaluate_fitness(SUMMARY, trades, objective="return")

    assert score.objective_value == pytest.approx(0.2 - 1.0)


def test_optimization_trial_validation_score_without_holdout_is_none() -> None:
    trial = OptimizationTrial(1, {}, _fitness(1.0))

    assert trial.validation_score is None
    assert trial.composite_score == 1.0


def test_optimization_trial_validation_score_penalises_overfit() -> None:
    trial = OptimizationTrial(1, {}, _fitness(2.0), _fitness(1.0), overfit_delta=1.0)

    assert trial.validation_score == pytest.approx(0.5)


# --- optimizers -----------------------------------------------------------------


def test_random_search_zero_iterations_raises(fake_evaluate: None) -> None:
    search = RandomSearchOptimizer(
        ParameterSpace([IntParam(name="x")]), iterations=1, seed=0
    )
    search.iterations = 0

    with pytest.raises(ValueError, match="No trials"):
        search.optimize([{}])


def test_grid_search_reports_progress_and_picks_best(fake_evaluate: None) -> None:
    space = ParameterSpace([IntParam(name="x", min_val=1, max_val=3)])
    progress: list[tuple[int, int, int]] = []

    result = GridSearchOptimizer(space, steps_per_param=3, seed=0).optimize(
        [{}],
        progress_callback=lambda i, n, t: progress.append((i, n, t.parameters["x"])),
    )

    assert progress == [(1, 3, 1), (2, 3, 2), (3, 3, 3)]
    assert result.best_trial.parameters == {"x": 3}
    assert result.search_method == "grid"
    assert result.total_evaluations == 3


def test_grid_search_empty_grid_raises(
    fake_evaluate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    space = ParameterSpace([IntParam(name="x")])
    monkeypatch.setattr(space, "generate_grid", lambda **_: [])

    with pytest.raises(ValueError, match="No grid configurations"):
        GridSearchOptimizer(space, seed=0).optimize([{}])


@pytest.mark.regression("BUG-61")
def test_trial_fitness_responds_to_live_exit_parameters() -> None:
    """BUG-61: exit-stack parameters change the simulated result."""
    snapshots = [
        {"mint": "A", "price": 1.0, "timestamp": 0.0, "buy_signal": True},
        {"mint": "A", "price": 1.6, "timestamp": 10.0},
        {"mint": "A", "price": 1.4, "timestamp": 20.0},
        {"mint": "A", "price": 0.5, "timestamp": 30.0},
    ]
    base = make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        max_position_size_sol=0.01,
        max_total_exposure_sol=0.03,
        max_token_concentration_pct=1.0,
        reserve_balance_sol=0.0,
        enable_momentum_signals=False,
        enable_tiered_take_profit=False,
        take_profit=10.0,
        trailing_stop_activation_pct=0.3,
    )

    tight = optimizer_module.evaluate_trial_on_snapshots(
        1, {"trailing_stop_drop_pct": 0.1}, snapshots, base_config=base
    )
    loose = optimizer_module.evaluate_trial_on_snapshots(
        2, {"trailing_stop_drop_pct": 0.3}, snapshots, base_config=base
    )

    # Tight trailing stop sells at 1.4x; loose one rides down to the stop-loss.
    assert tight.train_fitness.net_pnl > 0 > loose.train_fitness.net_pnl
    assert tight.train_fitness.total_return > 0 > loose.train_fitness.total_return


def test_trial_bankroll_scales_with_live_caps() -> None:
    cfg = make_config(
        dry_run=False,
        buy_amount_sol=0.01,
        max_total_exposure_sol=0.03,
        reserve_balance_sol=0.15,
    )
    assert optimizer_module.trial_bankroll_sol(cfg) == pytest.approx(0.21)


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


@pytest.mark.regression("BUG-61")
def test_build_default_strategy_search_space():
    cfg = make_config(dry_run=False, take_profit=1.8, max_active_positions=5)
    space = build_default_strategy_search_space(cfg)
    # Only knobs the live-fidelity replay reads are searched (BUG-61): the live
    # exit stack is back in the space, sizing and risk caps are not.
    assert set(space.names) == {
        "max_active_positions",
        "momentum_min_z_score",
        "momentum_min_buy_ratio",
        "momentum_min_unique_buyers",
        "momentum_window_seconds",
        "stop_loss_pct",
        "take_profit",
        "tier_1_take_profit",
        "tier_1_sell_fraction",
        "tier_2_take_profit",
        "tier_2_sell_fraction",
        "moonbag_trailing_floor",
        "trailing_stop_activation_pct",
        "trailing_stop_drop_pct",
        "stagnant_timeout_seconds",
        "max_hold_time_seconds",
    }
    for unused in (
        "buy_amount_sol",
        "take_profit_tier1_multiplier",
        "max_daily_drawdown_pct",
        "max_total_exposure_sol",
    ):
        assert unused not in space.names

    tp = space.get("take_profit")
    assert tp is not None
    assert tp.default == 1.8
    assert "watch_promote_min_sol_growth" not in space.names


def test_search_space_adds_confirmed_entry_keys_for_confirmed_mode():
    cfg = resolve_strategy_config("momentum", overrides={"min_market_cap_sol": 40.0})
    space = build_default_strategy_search_space(cfg)
    confirmed_keys = {
        "watch_promote_min_sol_growth",
        "momentum_min_net_inflow_sol",
        "momentum_min_token_age_seconds",
        "min_market_cap_sol",
        "momentum_max_market_cap_sol",
        "stagnant_min_buy_sol",
        "breakeven_ratchet_activation_pct",
    }
    assert confirmed_keys <= set(space.names)
    floor = space.get("min_market_cap_sol")
    ceiling = space.get("momentum_max_market_cap_sol")
    ratchet = space.get("breakeven_ratchet_activation_pct")
    assert floor is not None and ceiling is not None and ratchet is not None
    assert floor.default == 40.0
    # Every sampled combination stays a valid confirmed-entry config.
    assert floor.max_val < ceiling.min_val
    assert ratchet.min_val > cfg.breakeven_buffer_pct
    rng = random.Random(7)
    for _ in range(20):
        sample = space.sample_configuration(rng)
        resolve_strategy_config("momentum", overrides=sample)


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
    # No drawdown: floored at 1%, not a flat 10x bonus (BUG-135).
    assert calculate_calmar_ratio(0.50, 0.0) == pytest.approx(50.0)
    assert calculate_calmar_ratio(-0.20, 0.0) == pytest.approx(-20.0)


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
    assert fit_sharpe.objective_value == pytest.approx(
        fit_sharpe.sharpe_ratio, abs=1e-4
    )

    fit_pf = evaluate_fitness(summary, trades, objective="profit_factor")
    assert fit_pf.objective_value == fit_pf.profit_factor

    fit_ret = evaluate_fitness(summary, trades, objective="total_return")
    assert fit_ret.objective_value == fit_ret.total_return

    # Zero trades penalty check
    fit_zero = evaluate_fitness({"total_return": 0.0}, [], objective="composite")
    assert fit_zero.objective_value < 0.0


@pytest.mark.regression("BUG-60")
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


@pytest.mark.regression("BUG-61")
def test_optimizer_parameter_space_and_params():
    import random

    rng = random.Random(42)
    space = build_default_strategy_search_space()
    assert len(space) > 0
    # Only parameters replay simulates are searched (BUG-61).
    assert "buy_amount_sol" not in space.names
    assert "take_profit" in space.names

    sampled = space.sample_configuration(rng)
    assert isinstance(sampled, dict)
    assert "take_profit" in sampled

    # Parameter types
    fp = FloatParam(name="float_p", min_val=0.1, max_val=1.0, step=0.1, default=0.5)
    assert fp.clamp(1.5) == 1.0
    assert fp.clamp(0.05) == 0.1
    assert fp.sample(rng) >= 0.1
    assert fp.perturb(0.5, rng) >= 0.1
    assert len(fp.grid_values(5)) == 5

    ip = IntParam(name="int_p", min_val=1, max_val=10, default=5)
    assert ip.clamp(15) == 10
    assert ip.sample(rng) >= 1
    assert ip.perturb(5, rng) >= 1
    assert len(ip.grid_values(5)) == 5

    cp = CategoricalParam(name="cat_p", choices=("a", "b", "c"), default="a")
    assert cp.sample(rng) in ("a", "b", "c")
    assert cp.perturb("a", rng) in ("a", "b", "c")
    assert len(cp.grid_values(2)) == 2

    bp = BoolParam(name="bool_p", default=True)
    assert bp.sample(rng) in (True, False)
    assert bp.perturb(True, rng) in (True, False)
    assert bp.clamp(1) is True
    assert bp.grid_values() == [True, False]

    # Space grid, mutate, crossover
    custom_space = ParameterSpace([fp, ip, cp, bp])
    grid = custom_space.generate_grid(max_combinations=5, steps_per_param=2)
    assert len(grid) <= 5

    mut = custom_space.mutate(sampled, mutation_rate=0.5, rng=rng)
    assert isinstance(mut, dict)

    child = custom_space.crossover(sampled, mut, rng=rng)
    assert isinstance(child, dict)


def test_optimizer_algorithms_and_validation(tmp_path: Path):
    from pumpfun_trading.engines.optimizer import (
        GeneticOptimizer,
        GridSearchOptimizer,
        OptimizationResult,
        RandomSearchOptimizer,
        WalkForwardValidator,
    )

    snapshots = [
        {
            "timestamp": 1000.0,
            "mint": "m1",
            "market_cap_sol": 30.0,
            "is_buy": True,
            "sol_amount": 0.1,
        },
        {
            "timestamp": 1005.0,
            "mint": "m1",
            "market_cap_sol": 45.0,
            "is_buy": True,
            "sol_amount": 0.5,
        },
        {
            "timestamp": 1010.0,
            "mint": "m1",
            "market_cap_sol": 60.0,
            "is_buy": False,
            "sol_amount": 0.2,
        },
    ]

    validator = WalkForwardValidator(train_split=0.66)
    train, test = validator.split_snapshots(snapshots)
    assert len(train) >= 1
    assert len(test) >= 1

    space = build_default_strategy_search_space()

    # 1. Random search optimizer
    rand_opt = RandomSearchOptimizer(
        space, iterations=2, objective="composite", seed=42
    )
    rand_res = rand_opt.optimize(train, test)
    assert isinstance(rand_res, OptimizationResult)
    assert len(rand_res.all_trials) == 2

    # 2. Grid search optimizer
    grid_opt = GridSearchOptimizer(space, max_combinations=2, objective="sharpe")
    grid_res = grid_opt.optimize(train)
    assert isinstance(grid_res, OptimizationResult)

    # 3. Genetic optimizer
    gen_opt = GeneticOptimizer(
        space,
        population_size=4,
        generations=1,
        mutation_rate=0.2,
        crossover_rate=0.8,
        elite_count=1,
        objective="composite",
        seed=42,
    )
    gen_res = gen_opt.optimize(train)
    assert isinstance(gen_res, OptimizationResult)

    # Export to json
    out_file = tmp_path / "opt_out.json"
    gen_res.export_config_json(out_file)
    assert out_file.exists()


@pytest.mark.regression("BUG-135")
def test_sharpe_is_per_trade_so_splits_of_any_size_compare() -> None:
    returns = [0.10, -0.05, 0.20, 0.0, 0.05]
    # The same distribution, repeated: a bigger sample is not a better edge.
    assert calculate_sharpe_ratio(returns * 7) == pytest.approx(
        calculate_sharpe_ratio(returns * 3), rel=0.1
    )


@pytest.mark.regression("BUG-135")
def test_fitness_scores_positions_not_individual_sells() -> None:
    # One position: tier 1 sells half at +50%, the rest stops out at -40%.
    trades: list[dict[str, Any]] = [
        {"action": "buy", "mint": "A"},
        {"action": "sell", "mint": "A", "partial": True, "cost": 0.01, "pnl": 0.005},
        {"action": "sell", "mint": "A", "partial": False, "cost": 0.01, "pnl": -0.004},
        {"action": "buy", "mint": "B"},
        {"action": "sell", "mint": "B", "cost": 0.02, "pnl": -0.002},
        {"action": "sell", "mint": "C", "return_pct": 0.3},  # legacy record
    ]
    from pumpfun_trading.engines.optimizer import position_returns

    assert position_returns(trades) == pytest.approx([0.05, -0.1, 0.3])
    score = evaluate_fitness(SUMMARY, trades, objective="sharpe")
    assert score.sharpe_ratio == pytest.approx(
        calculate_sharpe_ratio([0.05, -0.1, 0.3]), abs=1e-4
    )
