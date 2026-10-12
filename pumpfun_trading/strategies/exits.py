from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pumpfun_trading.strategies.base import TradingBotConfig


class ExitAction(str, Enum):
    HOLD = "HOLD"
    FULL_EXIT = "FULL_EXIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"


@dataclass
class PositionExitState:
    entry_market_cap: float
    current_market_cap: float
    peak_market_cap: float
    initial_token_amount: int
    remaining_token_amount: int
    trailing_stop_active: bool = False
    tier_1_executed: bool = False
    tier_2_executed: bool = False
    moonbag_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def performance(self) -> float:
        if self.entry_market_cap <= 0:
            return 1.0
        return self.current_market_cap / self.entry_market_cap

    @property
    def peak_performance(self) -> float:
        if self.entry_market_cap <= 0:
            return 1.0
        return self.peak_market_cap / self.entry_market_cap

    @property
    def drawdown_from_peak(self) -> float:
        if self.peak_market_cap <= 0:
            return 0.0
        return max(0.0, 1.0 - (self.current_market_cap / self.peak_market_cap))

    def update_price(self, market_cap: float) -> None:
        mc = max(0.0, float(market_cap))
        self.current_market_cap = mc
        if mc > self.peak_market_cap:
            self.peak_market_cap = mc

    def record_partial_exit(self, tier: int, sold_tokens: int) -> None:
        self.remaining_token_amount = max(0, self.remaining_token_amount - sold_tokens)
        if tier == 1:
            self.tier_1_executed = True
        elif tier == 2:
            self.tier_2_executed = True
            self.moonbag_active = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_market_cap": self.entry_market_cap,
            "current_market_cap": self.current_market_cap,
            "peak_market_cap": self.peak_market_cap,
            "initial_token_amount": self.initial_token_amount,
            "remaining_token_amount": self.remaining_token_amount,
            "trailing_stop_active": self.trailing_stop_active,
            "tier_1_executed": self.tier_1_executed,
            "tier_2_executed": self.tier_2_executed,
            "moonbag_active": self.moonbag_active,
            "performance": self.performance,
            "peak_performance": self.peak_performance,
            "drawdown_from_peak": self.drawdown_from_peak,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionExitState:
        entry_mc = float(data.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(data.get("current_market_cap", entry_mc) or entry_mc)
        peak_mc = float(
            data.get("peak_market_cap", max(entry_mc, curr_mc))
            or max(entry_mc, curr_mc)
        )
        initial_tokens = int(
            data.get("initial_token_amount")
            or data.get("token_amount")
            or data.get("initial_units", 0)
            or 100_000_000
        )
        remaining_tokens = int(
            data.get("remaining_token_amount")
            or data.get("token_amount")
            or data.get("remaining_units", initial_tokens)
            or initial_tokens
        )
        return cls(
            entry_market_cap=entry_mc,
            current_market_cap=curr_mc,
            peak_market_cap=peak_mc,
            initial_token_amount=initial_tokens,
            remaining_token_amount=remaining_tokens,
            trailing_stop_active=bool(data.get("trailing_stop_active", False)),
            tier_1_executed=bool(data.get("tier_1_executed", False)),
            tier_2_executed=bool(data.get("tier_2_executed", False)),
            moonbag_active=bool(data.get("moonbag_active", False)),
        )


@dataclass(frozen=True)
class ExitDecision:
    action: ExitAction
    sell_fraction: float = 0.0
    sell_tokens: int = 0
    reason: str = "hold"
    exit_type: str = "none"
    target_tier: int | None = None


def update_position_peak(
    position: dict[str, Any] | PositionExitState, current_market_cap: float
) -> float:
    mc = max(0.0, float(current_market_cap))
    if isinstance(position, PositionExitState):
        position.update_price(mc)
        return position.peak_market_cap

    curr_peak = float(position.get("peak_market_cap", 0.0) or 0.0)
    new_peak = max(curr_peak, mc)
    position["peak_market_cap"] = new_peak
    position["current_market_cap"] = mc
    return new_peak


def evaluate_exit_strategy(
    config: TradingBotConfig,
    state: PositionExitState,
    current_market_cap: float | None = None,
    token_balance: int | None = None,
) -> ExitDecision:
    if current_market_cap is not None:
        state.update_price(current_market_cap)

    effective_balance = (
        token_balance
        if token_balance is not None
        else (
            state.remaining_token_amount
            if state.remaining_token_amount > 0
            else 100_000_000
        )
    )
    if state.initial_token_amount <= 0:
        state.initial_token_amount = effective_balance
    if state.remaining_token_amount <= 0:
        state.remaining_token_amount = effective_balance

    if (
        not config.dry_run
        and token_balance is not None
        and effective_balance <= config.min_sell_balance
    ):
        return ExitDecision(
            action=ExitAction.HOLD,
            reason=f"balance_below_min_sell ({effective_balance} <= {config.min_sell_balance})",
            exit_type="none",
        )

    perf = state.performance

    # 1. Hard Stop-Loss Check
    if perf <= config.stop_loss:
        return ExitDecision(
            action=ExitAction.FULL_EXIT,
            sell_fraction=1.0,
            sell_tokens=effective_balance,
            reason=f"stop_loss_hit ({perf:.2%} <= {config.stop_loss:.2%})",
            exit_type="stop_loss",
        )

    # 2. Multi-Tier Take-Profit Scale-Out Check
    if config.enable_tiered_take_profit:
        # Tier 1 (e.g., 2.0x -> +100% gain, sell 50% of position)
        if not state.tier_1_executed and perf >= config.tier_1_take_profit:
            base_tokens = (
                state.initial_token_amount
                if state.initial_token_amount > 0
                else effective_balance
            )
            target_sell = int(base_tokens * config.tier_1_sell_fraction)
            target_sell = max(1, min(target_sell, effective_balance))
            rem = effective_balance - target_sell

            if rem <= config.min_sell_balance:
                return ExitDecision(
                    action=ExitAction.FULL_EXIT,
                    sell_fraction=1.0,
                    sell_tokens=effective_balance,
                    reason=f"take_profit_tier_1_full ({perf:.2f}x >= {config.tier_1_take_profit:.2f}x)",
                    exit_type="tier_1",
                    target_tier=1,
                )
            return ExitDecision(
                action=ExitAction.PARTIAL_EXIT,
                sell_fraction=config.tier_1_sell_fraction,
                sell_tokens=target_sell,
                reason=f"take_profit_tier_1 ({perf:.2f}x >= {config.tier_1_take_profit:.2f}x)",
                exit_type="tier_1",
                target_tier=1,
            )

        # Tier 2 (e.g., 3.5x -> +250% gain, sell 25% of original position)
        if (
            state.tier_1_executed
            and not state.tier_2_executed
            and perf >= config.tier_2_take_profit
        ):
            base_tokens = (
                state.initial_token_amount
                if state.initial_token_amount > 0
                else effective_balance
            )
            target_sell = int(base_tokens * config.tier_2_sell_fraction)
            target_sell = max(1, min(target_sell, effective_balance))
            rem = effective_balance - target_sell

            if rem <= config.min_sell_balance:
                return ExitDecision(
                    action=ExitAction.FULL_EXIT,
                    sell_fraction=1.0,
                    sell_tokens=effective_balance,
                    reason=f"take_profit_tier_2_full ({perf:.2f}x >= {config.tier_2_take_profit:.2f}x)",
                    exit_type="tier_2",
                    target_tier=2,
                )
            return ExitDecision(
                action=ExitAction.PARTIAL_EXIT,
                sell_fraction=config.tier_2_sell_fraction,
                sell_tokens=target_sell,
                reason=f"take_profit_tier_2 ({perf:.2f}x >= {config.tier_2_take_profit:.2f}x)",
                exit_type="tier_2",
                target_tier=2,
            )

        # Tier 3 Moonbag protection (residual position)
        if state.tier_1_executed and state.tier_2_executed:
            state.moonbag_active = True
            if perf <= config.moonbag_trailing_floor:
                return ExitDecision(
                    action=ExitAction.FULL_EXIT,
                    sell_fraction=1.0,
                    sell_tokens=effective_balance,
                    reason=f"moonbag_floor_hit ({perf:.2f}x <= {config.moonbag_trailing_floor:.2f}x)",
                    exit_type="moonbag_floor",
                    target_tier=3,
                )

    # 3. Dynamic Trailing Stop-Loss
    if config.enable_trailing_stop:
        activation_thresh = 1.0 + config.trailing_stop_activation_pct
        if perf >= activation_thresh:
            state.trailing_stop_active = True

        if state.trailing_stop_active:
            drawdown = state.drawdown_from_peak
            if drawdown >= config.trailing_stop_drop_pct:
                return ExitDecision(
                    action=ExitAction.FULL_EXIT,
                    sell_fraction=1.0,
                    sell_tokens=effective_balance,
                    reason=(
                        f"trailing_stop_hit (drawdown {drawdown:.1%} >= {config.trailing_stop_drop_pct:.1%} "
                        f"from peak {state.peak_performance:.2f}x)"
                    ),
                    exit_type="trailing_stop",
                )

    # 4. Standard Single-Target Take-Profit (fallback when tiered is disabled)
    if not config.enable_tiered_take_profit and perf >= config.take_profit:
        return ExitDecision(
            action=ExitAction.FULL_EXIT,
            sell_fraction=1.0,
            sell_tokens=effective_balance,
            reason=f"take_profit_hit ({perf:.2%} >= {config.take_profit:.2%})",
            exit_type="take_profit",
        )

    return ExitDecision(action=ExitAction.HOLD, reason="holding", exit_type="none")


def should_exit_position(
    config: TradingBotConfig,
    *,
    performance: float,
    token_balance: int,
    position: dict[str, Any] | PositionExitState | None = None,
    current_market_cap: float | None = None,
) -> bool:
    if position is None:
        return token_balance > config.min_sell_balance and (
            performance >= config.take_profit or performance <= config.stop_loss
        )

    state = (
        position
        if isinstance(position, PositionExitState)
        else PositionExitState.from_dict(position)
    )
    mc = (
        current_market_cap
        if current_market_cap is not None
        else state.current_market_cap
    )
    decision = evaluate_exit_strategy(
        config, state, current_market_cap=mc, token_balance=token_balance
    )
    return decision.action in (ExitAction.FULL_EXIT, ExitAction.PARTIAL_EXIT)


__all__ = [
    "ExitAction",
    "ExitDecision",
    "PositionExitState",
    "evaluate_exit_strategy",
    "should_exit_position",
    "update_position_peak",
]
