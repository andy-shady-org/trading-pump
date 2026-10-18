from __future__ import annotations

import itertools
import json
import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.replay import PaperTradingEngine
from pumpfun_trading.strategies.base import TradingBotConfig


@dataclass(frozen=True)
class Hyperparameter(ABC):
    """Abstract base class for hyperparameter domain definitions."""

    name: str
    param_type: str
    default: Any = None

    @abstractmethod
    def sample(self, rng: random.Random) -> Any:
        """Sample a valid random value from the domain."""
        raise NotImplementedError

    @abstractmethod
    def perturb(self, value: Any, rng: random.Random, scale: float = 0.15) -> Any:
        """Perturb a value slightly for mutation while respecting domain bounds."""
        raise NotImplementedError

    @abstractmethod
    def clamp(self, value: Any) -> Any:
        """Clamp or validate an arbitrary value to the domain bounds."""
        raise NotImplementedError

    @abstractmethod
    def grid_values(self, steps: int = 5) -> list[Any]:
        """Generate a discrete sequence of values for grid search."""
        raise NotImplementedError


@dataclass(frozen=True)
class FloatParam(Hyperparameter):
    """Continuous float hyperparameter with optional logarithmic scaling."""

    min_val: float = 0.0
    max_val: float = 1.0
    step: float | None = None
    log_scale: bool = False
    param_type: str = "float"

    def __post_init__(self) -> None:
        if self.min_val >= self.max_val:
            raise ValueError(
                f"FloatParam {self.name}: min_val ({self.min_val}) must be < max_val ({self.max_val})"
            )
        if self.log_scale and self.min_val <= 0:
            raise ValueError(
                f"FloatParam {self.name}: log_scale requires min_val > 0, got {self.min_val}"
            )

    def sample(self, rng: random.Random) -> float:
        if self.log_scale:
            log_min = math.log(self.min_val)
            log_max = math.log(self.max_val)
            val = math.exp(rng.uniform(log_min, log_max))
        else:
            val = rng.uniform(self.min_val, self.max_val)

        if self.step is not None and self.step > 0:
            val = round((val - self.min_val) / self.step) * self.step + self.min_val
        return self.clamp(val)

    def perturb(self, value: Any, rng: random.Random, scale: float = 0.15) -> float:
        current = (
            float(value)
            if value is not None
            else (self.default or (self.min_val + self.max_val) / 2.0)
        )
        span = self.max_val - self.min_val
        delta = rng.gauss(0, span * scale)
        new_val = current + delta
        if self.step is not None and self.step > 0:
            new_val = (
                round((new_val - self.min_val) / self.step) * self.step + self.min_val
            )
        return self.clamp(new_val)

    def clamp(self, value: Any) -> float:
        v = float(value)
        v = max(self.min_val, min(self.max_val, v))
        if self.step is not None and self.step > 0:
            v = round((v - self.min_val) / self.step) * self.step + self.min_val
            v = max(self.min_val, min(self.max_val, v))
        return round(v, 6)

    def grid_values(self, steps: int = 5) -> list[Any]:
        if steps <= 1:
            return [self.clamp((self.min_val + self.max_val) / 2.0)]
        if self.step is not None and self.step > 0:
            vals: list[float] = []
            curr = self.min_val
            while curr <= self.max_val + 1e-9:
                vals.append(round(curr, 6))
                curr += self.step
            if len(vals) > steps:
                step_idx = len(vals) / (steps - 1)
                return [
                    vals[min(int(round(i * step_idx)), len(vals) - 1)]
                    for i in range(steps)
                ]
            return vals
        if self.log_scale:
            log_min = math.log(self.min_val)
            log_max = math.log(self.max_val)
            return [
                round(math.exp(log_min + (log_max - log_min) * (i / (steps - 1))), 6)
                for i in range(steps)
            ]
        return [
            round(self.min_val + (self.max_val - self.min_val) * (i / (steps - 1)), 6)
            for i in range(steps)
        ]


@dataclass(frozen=True)
class IntParam(Hyperparameter):
    """Discrete integer hyperparameter with bounded range and step intervals."""

    min_val: int = 1
    max_val: int = 10
    step: int = 1
    param_type: str = "int"

    def __post_init__(self) -> None:
        if self.min_val > self.max_val:
            raise ValueError(
                f"IntParam {self.name}: min_val ({self.min_val}) must be <= max_val ({self.max_val})"
            )
        if self.step <= 0:
            raise ValueError(f"IntParam {self.name}: step must be > 0, got {self.step}")

    def sample(self, rng: random.Random) -> int:
        num_steps = (self.max_val - self.min_val) // self.step
        idx = rng.randint(0, max(0, num_steps))
        val = self.min_val + idx * self.step
        return self.clamp(val)

    def perturb(self, value: Any, rng: random.Random, scale: float = 0.15) -> int:
        current = (
            int(value)
            if value is not None
            else (self.default or (self.min_val + self.max_val) // 2)
        )
        span = max(1, self.max_val - self.min_val)
        delta_steps = int(round(rng.gauss(0, max(1.0, (span / self.step) * scale))))
        new_val = current + delta_steps * self.step
        return self.clamp(new_val)

    def clamp(self, value: Any) -> int:
        v = int(round(float(value)))
        v = max(self.min_val, min(self.max_val, v))
        remainder = (v - self.min_val) % self.step
        if remainder != 0:
            v -= remainder
        return max(self.min_val, min(self.max_val, v))

    def grid_values(self, steps: int = 5) -> list[Any]:
        all_vals = list(range(self.min_val, self.max_val + 1, self.step))
        if len(all_vals) <= steps:
            return all_vals
        step_idx = len(all_vals) / (steps - 1)
        indices = sorted(
            {min(int(round(i * step_idx)), len(all_vals) - 1) for i in range(steps)}
        )
        return [all_vals[idx] for idx in indices]


@dataclass(frozen=True)
class CategoricalParam(Hyperparameter):
    """Categorical discrete hyperparameter selecting from a fixed set of choices."""

    choices: tuple[Any, ...] = ()
    param_type: str = "categorical"

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError(
                f"CategoricalParam {self.name}: choices tuple cannot be empty"
            )

    def sample(self, rng: random.Random) -> Any:
        return rng.choice(self.choices)

    def perturb(self, value: Any, rng: random.Random, scale: float = 0.15) -> Any:
        if len(self.choices) <= 1 or rng.random() > scale:
            return value if value in self.choices else self.choices[0]
        other_choices = [c for c in self.choices if c != value]
        return rng.choice(other_choices) if other_choices else self.choices[0]

    def clamp(self, value: Any) -> Any:
        if value in self.choices:
            return value
        return self.default if self.default in self.choices else self.choices[0]

    def grid_values(self, steps: int = 5) -> list[Any]:
        return list(self.choices[:steps])


@dataclass(frozen=True)
class BoolParam(Hyperparameter):
    """Boolean hyperparameter."""

    param_type: str = "bool"

    def sample(self, rng: random.Random) -> bool:
        return rng.choice([True, False])

    def perturb(self, value: Any, rng: random.Random, scale: float = 0.15) -> bool:
        if rng.random() < scale:
            return not bool(value)
        return bool(value)

    def clamp(self, value: Any) -> bool:
        return bool(value)

    def grid_values(self, steps: int = 5) -> list[Any]:
        return [True, False]


class ParameterSpace:
    """Container managing declarative hyperparameter search spaces."""

    def __init__(self, parameters: Sequence[Hyperparameter] | None = None) -> None:
        self._parameters: dict[str, Hyperparameter] = {}
        if parameters:
            for p in parameters:
                self.add_parameter(p)

    def add_parameter(self, param: Hyperparameter) -> None:
        self._parameters[param.name] = param

    def get(self, name: str) -> Hyperparameter | None:
        return self._parameters.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._parameters.keys())

    def __len__(self) -> int:
        return len(self._parameters)

    def __iter__(self):
        return iter(self._parameters.values())

    def sample_configuration(self, rng: random.Random) -> dict[str, Any]:
        """Generate a random parameter dictionary across all domains."""
        return {p.name: p.sample(rng) for p in self._parameters.values()}

    def clamp_configuration(self, config: dict[str, Any]) -> dict[str, Any]:
        """Ensure all parameter values conform to bounded domain limits."""
        clamped: dict[str, Any] = {}
        for name, param in self._parameters.items():
            if name in config:
                clamped[name] = param.clamp(config[name])
            elif param.default is not None:
                clamped[name] = param.clamp(param.default)
            else:
                clamped[name] = param.sample(random.Random(42))
        return clamped

    def generate_grid(
        self, max_combinations: int = 1000, steps_per_param: int = 3
    ) -> list[dict[str, Any]]:
        """Generate combinatorial grid of parameter combinations."""
        if not self._parameters:
            return [{}]

        keys = list(self._parameters.keys())
        grids = [self._parameters[k].grid_values(steps=steps_per_param) for k in keys]
        combinations: list[dict[str, Any]] = []

        for combo in itertools.product(*grids):
            combinations.append(dict(zip(keys, combo)))
            if len(combinations) >= max_combinations:
                break
        return combinations

    def mutate(
        self,
        config: dict[str, Any],
        mutation_rate: float,
        rng: random.Random,
        scale: float = 0.15,
    ) -> dict[str, Any]:
        """Mutate parameters with a given probability per parameter."""
        mutated: dict[str, Any] = dict(config)
        for name, param in self._parameters.items():
            if rng.random() < mutation_rate:
                val = mutated.get(name, param.default)
                mutated[name] = param.perturb(val, rng, scale=scale)
            else:
                if name not in mutated:
                    mutated[name] = param.sample(rng)
        return self.clamp_configuration(mutated)

    def crossover(
        self,
        parent_a: dict[str, Any],
        parent_b: dict[str, Any],
        rng: random.Random,
        blend_alpha: float = 0.5,
    ) -> dict[str, Any]:
        """Perform uniform blend crossover between two parameter configurations."""
        child: dict[str, Any] = {}
        for name, param in self._parameters.items():
            val_a = parent_a.get(name, param.default)
            val_b = parent_b.get(name, param.default)

            if (
                isinstance(param, FloatParam)
                and val_a is not None
                and val_b is not None
            ):
                # Blend crossover with random weight
                weight = rng.uniform(0.0, 1.0)
                blended = weight * float(val_a) + (1.0 - weight) * float(val_b)
                child[name] = param.clamp(blended)
            elif (
                isinstance(param, IntParam) and val_a is not None and val_b is not None
            ):
                chosen = val_a if rng.random() < blend_alpha else val_b
                child[name] = param.clamp(chosen)
            else:
                chosen = val_a if rng.random() < blend_alpha else val_b
                child[name] = param.clamp(chosen)
        return self.clamp_configuration(child)


def build_default_strategy_search_space(
    base_config: TradingBotConfig | None = None,
) -> ParameterSpace:
    """Search space limited to parameters the live-fidelity replay reads.

    Trials replay with the live exit stack and modelled costs (Sprint 24C), so
    the tiered take-profits, moonbag floor, trailing stop and stagnant/max-hold
    timeouts are searched again (BUG-61). Sizing (``buy_amount_sol``) and the
    risk caps stay operator choices, and the anti-rug / social / holder screens
    are not searched because a capture does not record the enrichment data.
    """
    cfg = base_config or TradingBotConfig()
    space = ParameterSpace()

    # 1. Concurrency
    space.add_parameter(
        IntParam(
            name="max_active_positions",
            min_val=1,
            max_val=8,
            step=1,
            default=getattr(cfg, "max_active_positions", 4),
        )
    )

    # 2. Momentum & Order Flow Filtering
    space.add_parameter(
        FloatParam(
            name="momentum_min_z_score",
            min_val=1.0,
            max_val=5.0,
            step=0.1,
            default=getattr(cfg, "momentum_min_z_score", 2.0),
        )
    )
    space.add_parameter(
        FloatParam(
            name="momentum_min_buy_ratio",
            min_val=1.2,
            max_val=6.0,
            step=0.1,
            default=getattr(cfg, "momentum_min_buy_ratio", 2.0),
        )
    )
    space.add_parameter(
        IntParam(
            name="momentum_min_unique_buyers",
            min_val=2,
            max_val=8,
            step=1,
            default=getattr(cfg, "momentum_min_unique_buyers", 3),
        )
    )
    space.add_parameter(
        FloatParam(
            name="momentum_window_seconds",
            min_val=10.0,
            max_val=120.0,
            step=5.0,
            default=getattr(cfg, "momentum_window_seconds", 30.0),
        )
    )

    # 3. Stop-loss and single-target take-profit (used when tiers are off)
    space.add_parameter(
        FloatParam(
            name="stop_loss_pct",
            min_val=0.70,
            max_val=0.95,
            step=0.01,
            default=getattr(cfg, "stop_loss_pct", 0.85),
        )
    )

    space.add_parameter(
        FloatParam(
            name="take_profit",
            min_val=1.15,
            max_val=3.00,
            step=0.05,
            default=getattr(cfg, "take_profit", 1.5),
        )
    )

    # 4. Live exit stack (strategies/exits.py), honoured by live-fidelity replay
    for name, low, high, step, fallback in (
        ("tier_1_take_profit", 1.3, 3.0, 0.1, 2.0),
        ("tier_1_sell_fraction", 0.2, 0.8, 0.05, 0.5),
        ("tier_2_take_profit", 2.0, 5.0, 0.1, 3.5),
        ("tier_2_sell_fraction", 0.1, 0.5, 0.05, 0.25),
        ("moonbag_trailing_floor", 1.2, 3.0, 0.1, 2.5),
        ("trailing_stop_activation_pct", 0.1, 1.0, 0.05, 0.5),
        ("trailing_stop_drop_pct", 0.05, 0.35, 0.01, 0.15),
        ("stagnant_timeout_seconds", 30.0, 600.0, 15.0, 120.0),
        ("max_hold_time_seconds", 120.0, 1800.0, 60.0, 600.0),
    ):
        default = float(getattr(cfg, name, fallback))
        space.add_parameter(
            FloatParam(
                name=name,
                min_val=low,
                max_val=high,
                step=step,
                default=min(high, max(low, default)),
            )
        )

    # 5. Confirmed entries (FEAT-51/52): watch promotion, entry band and the
    # momentum exits. Only searched when the base config replays that path.
    if getattr(cfg, "entry_mode", "launch") == "confirmed":
        for name, low, high, step, fallback in (
            ("watch_promote_min_sol_growth", 0.0, 10.0, 0.5, 1.5),
            ("momentum_min_net_inflow_sol", 0.0, 5.0, 0.25, 0.5),
            ("momentum_min_token_age_seconds", 0.0, 300.0, 10.0, 60.0),
            ("min_market_cap_sol", 28.0, 60.0, 1.0, 35.0),
            # Ranges keep the band and ratchet valid for any combination.
            ("momentum_max_market_cap_sol", 65.0, 85.0, 5.0, 75.0),
            ("stagnant_min_buy_sol", 0.0, 1.0, 0.05, 0.1),
            ("breakeven_ratchet_activation_pct", 0.1, 1.0, 0.05, 0.25),
        ):
            default = float(getattr(cfg, name, fallback))
            space.add_parameter(
                FloatParam(
                    name=name,
                    min_val=low,
                    max_val=high,
                    step=step,
                    default=min(high, max(low, default)),
                )
            )

    return space


@dataclass
class FitnessScore:
    """Multi-objective fitness metrics evaluation for backtest results."""

    objective_value: float
    sharpe_ratio: float
    sortino_ratio: float
    profit_factor: float
    total_return: float
    max_drawdown: float
    win_rate: float
    calmar_ratio: float
    total_trades: int
    net_pnl: float = 0.0


def calculate_sharpe_ratio(
    returns: Sequence[float], risk_free_rate: float = 0.0
) -> float:
    """Calculates annualizable Sharpe Ratio from a sequence of trade percentage returns."""
    if not returns or len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev <= 1e-9:
        return (
            1.0
            if mean_ret > risk_free_rate
            else (0.0 if mean_ret == risk_free_rate else -1.0)
        )
    # Scale by square root of trade count to normalize sample size
    return ((mean_ret - risk_free_rate) / std_dev) * math.sqrt(len(returns))


def calculate_sortino_ratio(
    returns: Sequence[float], risk_free_rate: float = 0.0
) -> float:
    """Calculates Sortino Ratio penalizing only downside volatility."""
    if not returns or len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    downside_diffs = [min(0.0, r - risk_free_rate) ** 2 for r in returns]
    downside_variance = sum(downside_diffs) / (len(returns) - 1)
    downside_std = math.sqrt(downside_variance)
    if downside_std <= 1e-9:
        return (
            2.0
            if mean_ret > risk_free_rate
            else (0.0 if mean_ret == risk_free_rate else -1.0)
        )
    return ((mean_ret - risk_free_rate) / downside_std) * math.sqrt(len(returns))


def calculate_calmar_ratio(total_return: float, max_drawdown: float) -> float:
    """Calculates Calmar Ratio as return divided by maximum drawdown."""
    if max_drawdown <= 1e-9:
        return (
            total_return * 10.0
            if total_return > 0
            else (0.0 if total_return == 0 else -10.0)
        )
    return total_return / max_drawdown


def evaluate_fitness(
    summary: dict[str, Any],
    trades: Sequence[dict[str, Any]],
    objective: str = "composite",
    weights: dict[str, float] | None = None,
) -> FitnessScore:
    """
    Evaluates multi-objective fitness score from replay simulation outputs.
    """
    sell_returns = [
        float(t["return_pct"])
        for t in trades
        if t.get("action") == "sell" and "return_pct" in t
    ]

    total_return = float(summary.get("total_return", 0.0))
    max_drawdown = float(summary.get("max_drawdown", 0.0))
    raw_profit_factor = summary.get("profit_factor", 0.0)
    profit_factor = float(raw_profit_factor) if raw_profit_factor != math.inf else 10.0
    profit_factor = min(20.0, max(0.0, profit_factor))
    win_rate = float(summary.get("win_rate", 0.0))
    total_trades = int(summary.get("total_trades", len(trades)))
    final_equity = float(
        summary.get("final_equity", summary.get("initial_cash", 100.0))
    )
    initial_cash = float(summary.get("initial_cash", 100.0))
    net_pnl = final_equity - initial_cash

    sharpe = calculate_sharpe_ratio(sell_returns)
    sortino = calculate_sortino_ratio(sell_returns)
    calmar = calculate_calmar_ratio(total_return, max_drawdown)

    default_weights = {
        "sharpe": 1.5,
        "profit_factor": 1.2,
        "total_return": 2.0,
        "sortino": 1.0,
        "calmar": 0.5,
        "drawdown_penalty": 3.0,
    }
    w = dict(default_weights)
    if weights:
        w.update(weights)

    # Calculate target objective value
    obj_clean = objective.lower().strip()
    if obj_clean == "sharpe":
        obj_val = sharpe
    elif obj_clean == "sortino":
        obj_val = sortino
    elif obj_clean == "profit_factor":
        obj_val = profit_factor
    elif obj_clean == "calmar":
        obj_val = calmar
    elif obj_clean in ("total_return", "return"):
        obj_val = total_return
    elif obj_clean == "win_rate":
        obj_val = win_rate
    else:  # "composite"
        obj_val = (
            w["sharpe"] * sharpe
            + w["profit_factor"] * (profit_factor - 1.0)
            + w["total_return"] * total_return
            + w["sortino"] * sortino
            + w["calmar"] * calmar
            - w["drawdown_penalty"] * max_drawdown
        )

    # Activity penalty: penalize zero or single-trade runs that artificially avoid drawdown
    if len(sell_returns) == 0:
        obj_val -= 2.0
    elif len(sell_returns) == 1:
        obj_val -= 1.0

    return FitnessScore(
        objective_value=round(obj_val, 6),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        profit_factor=round(profit_factor, 4),
        total_return=round(total_return, 4),
        max_drawdown=round(max_drawdown, 4),
        win_rate=round(win_rate, 4),
        calmar_ratio=round(calmar, 4),
        total_trades=total_trades,
        net_pnl=round(net_pnl, 6),
    )


@dataclass
class OptimizationTrial:
    """Individual trial configuration, backtest fitness, and validation metrics."""

    trial_id: int
    parameters: dict[str, Any]
    train_fitness: FitnessScore
    test_fitness: FitnessScore | None = None
    overfit_delta: float = 0.0
    duration_seconds: float = 0.0

    @property
    def composite_score(self) -> float:
        """Selection score: in-sample (train) objective only.

        Holdout metrics must never drive selection, otherwise the out-of-sample
        score is no longer unseen (BUG-60). See `validation_score` for reporting.
        """
        return self.train_fitness.objective_value

    @property
    def validation_score(self) -> float | None:
        """Out-of-sample objective minus overfit penalty; reporting only."""
        if self.test_fitness is None:
            return None
        return self.test_fitness.objective_value - (0.5 * max(0.0, self.overfit_delta))


@dataclass
class OptimizationResult:
    """Aggregated optimization result containing top trials and configuration exporter."""

    best_trial: OptimizationTrial
    all_trials: list[OptimizationTrial]
    objective_name: str
    search_method: str
    total_duration_seconds: float
    total_evaluations: int

    @property
    def top_trials(self) -> list[OptimizationTrial]:
        return sorted(self.all_trials, key=lambda t: t.composite_score, reverse=True)

    def to_trading_bot_config(
        self, base_config: TradingBotConfig | None = None
    ) -> TradingBotConfig:
        """Instantiate a ready-to-run TradingBotConfig using the best parameters."""
        base = base_config or TradingBotConfig()
        cfg_dict = asdict(base) if hasattr(base, "__dataclass_fields__") else {}
        from pumpfun_trading.strategies.presets import normalize_config_dict

        normalized_params = normalize_config_dict(self.best_trial.parameters)
        cfg_dict.update(normalized_params)

        valid_fields = set(TradingBotConfig.__dataclass_fields__.keys())
        filtered_params = {k: v for k, v in cfg_dict.items() if k in valid_fields}
        return TradingBotConfig(**filtered_params)

    def export_config_json(
        self,
        path: Path | str,
        base_config: TradingBotConfig | None = None,
    ) -> Path:
        """Saves the best parameter configuration to a TradingBotConfig JSON file."""
        config = self.to_trading_bot_config(base_config)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, indent=2)
        return out_path

    def export_preset_dict(self) -> dict[str, Any]:
        """Returns clean dictionary representation of best trial parameters."""
        return dict(self.best_trial.parameters)


class WalkForwardValidator:
    """Splits dataset into in-sample (train) and out-of-sample (test) segments."""

    def __init__(self, train_split: float = 0.70) -> None:
        self.train_split = max(0.1, min(0.95, float(train_split)))

    def split_snapshots(
        self, snapshots: Sequence[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not snapshots:
            return [], []
        split_idx = int(round(len(snapshots) * self.train_split))
        split_idx = (
            max(1, min(len(snapshots) - 1, split_idx)) if len(snapshots) > 1 else 1
        )
        return list(snapshots[:split_idx]), list(snapshots[split_idx:])


def trial_bankroll_sol(config: TradingBotConfig) -> float:
    """Starting cash for a trial: the reserve plus twice the deployable exposure.

    Returns, drawdown and Sharpe are measured against capital the live caps can
    actually put at risk; a fixed 100 SOL made 0.01 SOL trades look flat.
    """
    exposure = max(float(config.max_total_exposure_sol), float(config.buy_amount_sol))
    return max(0.0, float(config.reserve_balance_sol)) + 2.0 * max(exposure, 0.0)


def evaluate_trial_on_snapshots(
    trial_id: int,
    parameters: dict[str, Any],
    train_snapshots: Sequence[dict[str, Any]],
    test_snapshots: Sequence[dict[str, Any]] | None = None,
    objective: str = "composite",
    base_config: TradingBotConfig | None = None,
) -> OptimizationTrial:
    """Executes paper-trading simulation over in-sample and optional out-of-sample datasets."""
    start_t = time.monotonic()
    base = base_config or TradingBotConfig()
    cfg_dict = asdict(base) if hasattr(base, "__dataclass_fields__") else {}
    from pumpfun_trading.strategies.presets import normalize_config_dict

    normalized_params = normalize_config_dict(parameters)
    cfg_dict.update(normalized_params)
    valid_fields = set(TradingBotConfig.__dataclass_fields__.keys())
    active_config = TradingBotConfig(
        **{k: v for k, v in cfg_dict.items() if k in valid_fields}
    )

    # Fitness is scored on profit after modelled fees, tips and rent (Sprint 24C).
    cost_model = ReplayCostModel.from_env(
        close_token_account_on_full_exit=active_config.close_token_account_on_full_exit
    )

    bankroll = trial_bankroll_sol(active_config)

    # 1. Train Evaluation
    engine_train = PaperTradingEngine(
        initial_cash=bankroll,
        max_positions=active_config.max_active_positions,
        strategy_config=active_config,
        live_fidelity=True,
        cost_model=cost_model,
    )
    summary_train = engine_train.run_simulation(train_snapshots)
    train_fitness = evaluate_fitness(
        summary_train, engine_train.trades, objective=objective
    )

    # 2. Test Evaluation (if test snapshots exist)
    test_fitness: FitnessScore | None = None
    overfit_delta = 0.0
    if test_snapshots and len(test_snapshots) > 0:
        engine_test = PaperTradingEngine(
            initial_cash=bankroll,
            max_positions=active_config.max_active_positions,
            strategy_config=active_config,
            live_fidelity=True,
            cost_model=cost_model,
        )
        summary_test = engine_test.run_simulation(test_snapshots)
        test_fitness = evaluate_fitness(
            summary_test, engine_test.trades, objective=objective
        )
        overfit_delta = max(
            0.0, train_fitness.objective_value - test_fitness.objective_value
        )

    duration = time.monotonic() - start_t
    return OptimizationTrial(
        trial_id=trial_id,
        parameters=parameters,
        train_fitness=train_fitness,
        test_fitness=test_fitness,
        overfit_delta=round(overfit_delta, 6),
        duration_seconds=round(duration, 4),
    )


class BaseOptimizer(ABC):
    """Abstract optimizer algorithm base class."""

    def __init__(
        self,
        parameter_space: ParameterSpace,
        objective: str = "composite",
        seed: int | None = None,
    ) -> None:
        self.parameter_space = parameter_space
        self.objective = objective
        self.seed = seed
        self.rng = random.Random(seed)

    @abstractmethod
    def optimize(
        self,
        train_snapshots: Sequence[dict[str, Any]],
        test_snapshots: Sequence[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int, OptimizationTrial], None] | None = None,
        base_config: TradingBotConfig | None = None,
    ) -> OptimizationResult:
        raise NotImplementedError


class RandomSearchOptimizer(BaseOptimizer):
    """Stochastic random sampling optimizer over N trials."""

    def __init__(
        self,
        parameter_space: ParameterSpace,
        iterations: int = 30,
        objective: str = "composite",
        seed: int | None = None,
    ) -> None:
        super().__init__(parameter_space, objective=objective, seed=seed)
        self.iterations = max(1, iterations)

    def optimize(
        self,
        train_snapshots: Sequence[dict[str, Any]],
        test_snapshots: Sequence[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int, OptimizationTrial], None] | None = None,
        base_config: TradingBotConfig | None = None,
    ) -> OptimizationResult:
        start_time = time.monotonic()
        trials: list[OptimizationTrial] = []

        for idx in range(1, self.iterations + 1):
            config = self.parameter_space.sample_configuration(self.rng)
            trial = evaluate_trial_on_snapshots(
                trial_id=idx,
                parameters=config,
                train_snapshots=train_snapshots,
                test_snapshots=test_snapshots,
                objective=self.objective,
                base_config=base_config,
            )
            trials.append(trial)
            if progress_callback:
                progress_callback(idx, self.iterations, trial)

        best_trial = max(trials, key=lambda t: t.composite_score) if trials else None
        if best_trial is None:
            raise ValueError("No trials were evaluated")

        total_duration = time.monotonic() - start_time
        return OptimizationResult(
            best_trial=best_trial,
            all_trials=trials,
            objective_name=self.objective,
            search_method="random",
            total_duration_seconds=round(total_duration, 3),
            total_evaluations=len(trials),
        )


class GridSearchOptimizer(BaseOptimizer):
    """Deterministic grid search explorer across discrete parameter combinations."""

    def __init__(
        self,
        parameter_space: ParameterSpace,
        max_combinations: int = 100,
        steps_per_param: int = 3,
        objective: str = "composite",
        seed: int | None = None,
    ) -> None:
        super().__init__(parameter_space, objective=objective, seed=seed)
        self.max_combinations = max(1, max_combinations)
        self.steps_per_param = max(2, steps_per_param)

    def optimize(
        self,
        train_snapshots: Sequence[dict[str, Any]],
        test_snapshots: Sequence[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int, OptimizationTrial], None] | None = None,
        base_config: TradingBotConfig | None = None,
    ) -> OptimizationResult:
        start_time = time.monotonic()
        grid = self.parameter_space.generate_grid(
            max_combinations=self.max_combinations,
            steps_per_param=self.steps_per_param,
        )
        trials: list[OptimizationTrial] = []

        for idx, config in enumerate(grid, start=1):
            trial = evaluate_trial_on_snapshots(
                trial_id=idx,
                parameters=config,
                train_snapshots=train_snapshots,
                test_snapshots=test_snapshots,
                objective=self.objective,
                base_config=base_config,
            )
            trials.append(trial)
            if progress_callback:
                progress_callback(idx, len(grid), trial)

        best_trial = max(trials, key=lambda t: t.composite_score) if trials else None
        if best_trial is None:
            raise ValueError("No grid configurations were evaluated")

        total_duration = time.monotonic() - start_time
        return OptimizationResult(
            best_trial=best_trial,
            all_trials=trials,
            objective_name=self.objective,
            search_method="grid",
            total_duration_seconds=round(total_duration, 3),
            total_evaluations=len(trials),
        )


class GeneticOptimizer(BaseOptimizer):
    """Evolutionary genetic algorithm with tournament selection, blend crossover, and elitism."""

    def __init__(
        self,
        parameter_space: ParameterSpace,
        population_size: int = 20,
        generations: int = 5,
        crossover_rate: float = 0.80,
        mutation_rate: float = 0.20,
        elite_count: int = 2,
        tournament_size: int = 3,
        objective: str = "composite",
        seed: int | None = None,
    ) -> None:
        super().__init__(parameter_space, objective=objective, seed=seed)
        self.population_size = max(4, population_size)
        self.generations = max(1, generations)
        self.crossover_rate = max(0.0, min(1.0, crossover_rate))
        self.mutation_rate = max(0.0, min(1.0, mutation_rate))
        self.elite_count = max(1, min(self.population_size // 2, elite_count))
        self.tournament_size = max(2, min(self.population_size, tournament_size))

    def _tournament_select(
        self, population: list[OptimizationTrial]
    ) -> OptimizationTrial:
        sample = self.rng.sample(population, min(self.tournament_size, len(population)))
        return max(sample, key=lambda t: t.composite_score)

    def optimize(
        self,
        train_snapshots: Sequence[dict[str, Any]],
        test_snapshots: Sequence[dict[str, Any]] | None = None,
        progress_callback: Callable[[int, int, OptimizationTrial], None] | None = None,
        base_config: TradingBotConfig | None = None,
    ) -> OptimizationResult:
        start_time = time.monotonic()
        total_evaluations = self.population_size * self.generations
        all_trials: list[OptimizationTrial] = []
        trial_counter = 1

        # 1. Initialize Generation 0 Population
        current_pop_trials: list[OptimizationTrial] = []
        for _ in range(self.population_size):
            cfg = self.parameter_space.sample_configuration(self.rng)
            trial = evaluate_trial_on_snapshots(
                trial_id=trial_counter,
                parameters=cfg,
                train_snapshots=train_snapshots,
                test_snapshots=test_snapshots,
                objective=self.objective,
                base_config=base_config,
            )
            all_trials.append(trial)
            current_pop_trials.append(trial)
            if progress_callback:
                progress_callback(trial_counter, total_evaluations, trial)
            trial_counter += 1

        # 2. Iterate Generations
        for gen in range(1, self.generations):
            current_pop_trials.sort(key=lambda t: t.composite_score, reverse=True)
            next_generation_configs: list[dict[str, Any]] = []

            # Elitism: retain top N parameter configs from previous generation
            for elite_trial in current_pop_trials[: self.elite_count]:
                next_generation_configs.append(dict(elite_trial.parameters))

            # Breed remaining population slots
            while len(next_generation_configs) < self.population_size:
                parent_a = self._tournament_select(current_pop_trials)
                parent_b = self._tournament_select(current_pop_trials)

                # Crossover
                if self.rng.random() < self.crossover_rate:
                    child = self.parameter_space.crossover(
                        parent_a.parameters, parent_b.parameters, self.rng
                    )
                else:
                    child = dict(
                        parent_a.parameters
                        if self.rng.random() < 0.5
                        else parent_b.parameters
                    )

                # Mutation
                child = self.parameter_space.mutate(
                    child, mutation_rate=self.mutation_rate, rng=self.rng
                )
                next_generation_configs.append(child)

            # Evaluate next generation
            next_pop_trials: list[OptimizationTrial] = []
            for cfg in next_generation_configs:
                trial = evaluate_trial_on_snapshots(
                    trial_id=trial_counter,
                    parameters=cfg,
                    train_snapshots=train_snapshots,
                    test_snapshots=test_snapshots,
                    objective=self.objective,
                    base_config=base_config,
                )
                all_trials.append(trial)
                next_pop_trials.append(trial)
                if progress_callback:
                    progress_callback(trial_counter, total_evaluations, trial)
                trial_counter += 1

            current_pop_trials = next_pop_trials

        best_trial = max(all_trials, key=lambda t: t.composite_score)
        total_duration = time.monotonic() - start_time
        return OptimizationResult(
            best_trial=best_trial,
            all_trials=all_trials,
            objective_name=self.objective,
            search_method="genetic",
            total_duration_seconds=round(total_duration, 3),
            total_evaluations=len(all_trials),
        )


class StrategyOptimizer:
    """Unified facade coordinating parameter space optimization across search methods."""

    def __init__(
        self,
        parameter_space: ParameterSpace | None = None,
        method: str = "genetic",
        objective: str = "composite",
        iterations: int = 30,
        population_size: int = 20,
        generations: int = 5,
        max_grid_combinations: int = 100,
        train_split: float = 0.70,
        seed: int | None = None,
        base_config: TradingBotConfig | None = None,
    ) -> None:
        self.base_config = base_config or TradingBotConfig()
        self.parameter_space = parameter_space or build_default_strategy_search_space(
            self.base_config
        )
        self.method = method.lower().strip()
        self.objective = objective.lower().strip()
        self.iterations = iterations
        self.population_size = population_size
        self.generations = generations
        self.max_grid_combinations = max_grid_combinations
        self.train_split = train_split
        self.seed = seed
        self.validator = WalkForwardValidator(train_split=train_split)

    def optimize(
        self,
        snapshots: Sequence[dict[str, Any]],
        progress_callback: Callable[[int, int, OptimizationTrial], None] | None = None,
    ) -> OptimizationResult:
        """Executes hyperparameter optimization over the provided historical snapshot sequence."""
        if not snapshots:
            # Fallback with baseline default config
            fallback_params = {
                p.name: (
                    p.default if p.default is not None else p.sample(random.Random(42))
                )
                for p in self.parameter_space
            }
            dummy_score = FitnessScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
            dummy_trial = OptimizationTrial(
                1, fallback_params, dummy_score, dummy_score, 0.0, 0.0
            )
            return OptimizationResult(
                best_trial=dummy_trial,
                all_trials=[dummy_trial],
                objective_name=self.objective,
                search_method=self.method,
                total_duration_seconds=0.0,
                total_evaluations=1,
            )

        train_snaps, test_snaps = self.validator.split_snapshots(snapshots)

        optimizer: BaseOptimizer
        if self.method == "random":
            optimizer = RandomSearchOptimizer(
                parameter_space=self.parameter_space,
                iterations=self.iterations,
                objective=self.objective,
                seed=self.seed,
            )
        elif self.method == "grid":
            optimizer = GridSearchOptimizer(
                parameter_space=self.parameter_space,
                max_combinations=self.max_grid_combinations,
                objective=self.objective,
                seed=self.seed,
            )
        else:  # default "genetic"
            optimizer = GeneticOptimizer(
                parameter_space=self.parameter_space,
                population_size=self.population_size,
                generations=self.generations,
                objective=self.objective,
                seed=self.seed,
            )

        return optimizer.optimize(
            train_snapshots=train_snaps,
            test_snapshots=test_snaps,
            progress_callback=progress_callback,
            base_config=self.base_config,
        )
