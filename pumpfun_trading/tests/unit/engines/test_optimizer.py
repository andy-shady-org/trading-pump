"""Unit tests for ``engines/optimizer.py`` search spaces, fitness and optimizers."""

from __future__ import annotations

import random
from typing import Any, Callable, Sequence

import pytest

from pumpfun_trading.engines import optimizer as optimizer_module
from pumpfun_trading.engines.optimizer import (
    BaseOptimizer,
    BoolParam,
    CategoricalParam,
    FitnessScore,
    FloatParam,
    GridSearchOptimizer,
    Hyperparameter,
    IntParam,
    OptimizationTrial,
    ParameterSpace,
    RandomSearchOptimizer,
    calculate_sortino_ratio,
    evaluate_fitness,
)
from pumpfun_trading.strategies.base import TradingBotConfig


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


def test_sortino_ratio_with_downside_returns_scaled_ratio() -> None:
    ratio = calculate_sortino_ratio([0.5, -0.5])

    # mean 0, downside std = sqrt(0.25 / 1) = 0.5
    assert ratio == pytest.approx(0.0)
    assert calculate_sortino_ratio([1.0, -0.5]) == pytest.approx(
        (0.25 / 0.5) * (2**0.5)
    )


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


def test_trial_fitness_responds_to_live_exit_parameters() -> None:
    """BUG-61: exit-stack parameters change the simulated result."""
    snapshots = [
        {"mint": "A", "price": 1.0, "timestamp": 0.0, "buy_signal": True},
        {"mint": "A", "price": 1.6, "timestamp": 10.0},
        {"mint": "A", "price": 1.4, "timestamp": 20.0},
        {"mint": "A", "price": 0.5, "timestamp": 30.0},
    ]
    base = TradingBotConfig(
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
    cfg = TradingBotConfig(
        buy_amount_sol=0.01, max_total_exposure_sol=0.03, reserve_balance_sol=0.15
    )
    assert optimizer_module.trial_bankroll_sol(cfg) == pytest.approx(0.21)
