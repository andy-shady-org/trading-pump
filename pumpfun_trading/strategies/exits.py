from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pumpfun_trading.strategies.base import TradingBotConfig

# A decision that was emitted but not yet confirmed filled blocks re-emission of
# the same tier for this many seconds; after that it is retried (BUG-42).
PENDING_EXIT_TTL_SECONDS = 60.0


def _tier_key(tier: int | str | None) -> str | None:
    if tier is None:
        return None
    if isinstance(tier, int):
        return f"tier_{tier}"
    return str(tier)


def _first_present(data: dict[str, Any], keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return int(value)
    return default


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
    executed_pre_grad_tranches: set[int] = field(default_factory=set)
    pending_exit_tiers: dict[str, float] = field(default_factory=dict)
    entry_time: float = field(default_factory=time.time)
    last_price_change_at: float = field(default_factory=time.time)
    last_price: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    # Momentum entries (FEAT-52): last buy >= stagnant_min_buy_sol by another
    # wallet, and whether the break-even floor has been armed.
    last_qualifying_buy_at: float | None = None
    breakeven_floor_active: bool = False

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

    def update_price(
        self,
        market_cap: float,
        *,
        now: float | None = None,
        threshold_pct: float = 0.005,
    ) -> None:
        mc = max(0.0, float(market_cap))
        current_time = now if now is not None else time.time()

        ref_price = (
            self.last_price
            if self.last_price > 0
            else (
                self.current_market_cap
                if self.current_market_cap > 0
                else self.entry_market_cap
            )
        )
        if ref_price > 0 and mc > 0:
            rel_delta = abs(mc - ref_price) / ref_price
            if rel_delta >= threshold_pct:
                self.last_price = mc
                self.last_price_change_at = current_time
        elif self.last_price <= 0 and mc > 0:
            self.last_price = mc

        self.current_market_cap = mc
        if mc > self.peak_market_cap:
            self.peak_market_cap = mc

    def is_exit_pending(self, tier: int | str, now: float) -> bool:
        key = _tier_key(tier)
        emitted_at = self.pending_exit_tiers.get(key) if key else None
        if emitted_at is None:
            return False
        if now - emitted_at >= PENDING_EXIT_TTL_SECONDS or now < emitted_at:
            self.pending_exit_tiers.pop(str(key), None)
            return False
        return True

    def mark_exit_pending(self, tier: int | str, now: float) -> None:
        key = _tier_key(tier)
        if key:
            self.pending_exit_tiers[key] = now

    def clear_exit_pending(self, tier: int | str | None) -> None:
        key = _tier_key(tier)
        if key:
            self.pending_exit_tiers.pop(key, None)

    def record_partial_exit(self, tier: int | str | None, sold_tokens: int) -> None:
        self.remaining_token_amount = max(0, self.remaining_token_amount - sold_tokens)
        self.clear_exit_pending(tier)
        if tier == 1:
            self.tier_1_executed = True
        elif tier == 2:
            self.tier_2_executed = True
            self.moonbag_active = True
        elif isinstance(tier, str) and tier.startswith("pre_grad_"):
            self.executed_pre_grad_tranches.add(int(tier.rsplit("_", 1)[1]) - 1)

    def write_back(self, data: dict[str, Any]) -> None:
        """Persists mutable exit-tracking state back into a position dict."""
        data["entry_market_cap"] = self.entry_market_cap
        data["peak_market_cap"] = self.peak_market_cap
        data["trailing_stop_active"] = self.trailing_stop_active
        data["tier_1_executed"] = self.tier_1_executed
        data["tier_2_executed"] = self.tier_2_executed
        data["moonbag_active"] = self.moonbag_active
        data["executed_pre_grad_tranches"] = list(self.executed_pre_grad_tranches)
        data["pending_exit_tiers"] = dict(self.pending_exit_tiers)
        data["last_price_change_at"] = self.last_price_change_at
        data["last_price"] = self.last_price
        data["breakeven_floor_active"] = self.breakeven_floor_active

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
            "executed_pre_grad_tranches": list(self.executed_pre_grad_tranches),
            "pending_exit_tiers": dict(self.pending_exit_tiers),
            "performance": self.performance,
            "peak_performance": self.peak_performance,
            "drawdown_from_peak": self.drawdown_from_peak,
            "entry_time": self.entry_time,
            "last_price_change_at": self.last_price_change_at,
            "last_price": self.last_price,
            "last_qualifying_buy_at": self.last_qualifying_buy_at,
            "breakeven_floor_active": self.breakeven_floor_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionExitState:
        entry_mc = float(data.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(data.get("current_market_cap", entry_mc) or entry_mc)
        peak_mc = float(
            data.get("peak_market_cap", max(entry_mc, curr_mc))
            or max(entry_mc, curr_mc)
        )
        initial_tokens = _first_present(
            data, ("initial_token_amount", "token_amount", "initial_units"), 0
        )
        remaining_tokens = _first_present(
            data,
            ("remaining_token_amount", "token_amount", "remaining_units"),
            initial_tokens,
        )
        now_ts = time.time()
        entry_t = float(data.get("entry_time") or data.get("first_seen") or now_ts)
        last_change_t = float(data.get("last_price_change_at") or entry_t)
        last_p = float(data.get("last_price") or curr_mc or entry_mc)
        raw_tranches = data.get("executed_pre_grad_tranches") or set()
        tranches_set = (
            set(raw_tranches) if isinstance(raw_tranches, (set, list, tuple)) else set()
        )
        raw_buy_at = data.get("last_qualifying_buy_at")
        raw_pending = data.get("pending_exit_tiers") or {}
        pending = (
            {str(k): float(v) for k, v in raw_pending.items()}
            if isinstance(raw_pending, dict)
            else {}
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
            executed_pre_grad_tranches=tranches_set,
            pending_exit_tiers=pending,
            entry_time=entry_t,
            last_price_change_at=last_change_t,
            last_price=last_p,
            last_qualifying_buy_at=(
                float(raw_buy_at) if isinstance(raw_buy_at, (int, float)) else None
            ),
            breakeven_floor_active=bool(data.get("breakeven_floor_active", False)),
        )


@dataclass(frozen=True)
class ExitDecision:
    action: ExitAction
    sell_fraction: float = 0.0
    sell_tokens: int = 0
    reason: str = "hold"
    exit_type: str = "none"
    target_tier: int | str | None = None


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
    *,
    now: float | None = None,
    curve_progress_pct: float | None = None,
) -> ExitDecision:
    if current_market_cap is not None:
        state.update_price(
            current_market_cap,
            now=now,
            threshold_pct=config.stagnant_price_delta_threshold_pct,
        )

    current_time = now if now is not None else time.time()

    # Without an entry baseline stop-loss / take-profit can never fire (BUG-76).
    if state.entry_market_cap <= 0 and state.current_market_cap > 0:
        state.entry_market_cap = state.current_market_cap
        state.peak_market_cap = max(state.peak_market_cap, state.current_market_cap)

    if token_balance is None and state.remaining_token_amount <= 0:
        # Never invent a size for a position with nothing left to sell (BUG-65).
        return ExitDecision(
            action=ExitAction.HOLD,
            reason="no_remaining_balance",
            exit_type="none",
        )
    effective_balance = (
        token_balance if token_balance is not None else state.remaining_token_amount
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

    # 1.5 Pre-Graduation Staged Take-Profit Tranches Check
    if (
        getattr(config, "enable_pre_graduation_harvesting", False)
        and curve_progress_pct is not None
    ):
        tranches = getattr(config, "pre_graduation_tranches", ())
        # curve_progress_pct is always a 0-100 percentage (GraduationCandidate);
        # tranche targets are 0-1 fractions (BUG-38).
        progress_ratio = float(curve_progress_pct) / 100.0
        for idx, tranche in enumerate(tranches):
            tranche_tier = f"pre_grad_{idx + 1}"
            if idx in state.executed_pre_grad_tranches or state.is_exit_pending(
                tranche_tier, current_time
            ):
                continue
            target_prog = float(tranche.get("progress_pct", 1.0))
            if target_prog > 1.0:
                target_prog /= 100.0
            sell_frac = float(tranche.get("sell_fraction", 0.30))
            if progress_ratio >= target_prog:
                state.mark_exit_pending(tranche_tier, current_time)
                base_tokens = (
                    state.initial_token_amount
                    if state.initial_token_amount > 0
                    else effective_balance
                )
                target_sell = int(base_tokens * sell_frac)
                target_sell = max(1, min(target_sell, effective_balance))
                rem = effective_balance - target_sell
                # Confirmed entries (FEAT-53): the last tranche sells what is left,
                # so nothing is held into migration even when the fractions don't
                # add up to 100%. Launch mode keeps its runner unchanged.
                final_tranche = idx == len(tranches) - 1 and (
                    getattr(config, "entry_mode", "launch") == "confirmed"
                )
                if rem <= config.min_sell_balance or final_tranche:
                    return ExitDecision(
                        action=ExitAction.FULL_EXIT,
                        sell_fraction=1.0,
                        sell_tokens=effective_balance,
                        reason=f"pre_graduation_tranche_{idx + 1}_full ({progress_ratio:.1%} >= {target_prog:.1%})",
                        exit_type="pre_graduation_tranche",
                        target_tier=tranche_tier,
                    )
                return ExitDecision(
                    action=ExitAction.PARTIAL_EXIT,
                    sell_fraction=sell_frac,
                    sell_tokens=target_sell,
                    reason=f"pre_graduation_tranche_{idx + 1} ({progress_ratio:.1%} >= {target_prog:.1%})",
                    exit_type="pre_graduation_tranche",
                    target_tier=tranche_tier,
                )

    # 1.7 Momentum entries (FEAT-52): exits built for confirmed buys.
    if getattr(config, "entry_mode", "launch") == "confirmed":
        momentum_exit = _momentum_entry_exit(
            config, state, perf, effective_balance, current_time
        )
        if momentum_exit is not None:
            return momentum_exit

    # 2. Stagnant Curve Inactivity Timeout Check
    if config.enable_stagnant_exit:
        time_since_change = max(0.0, current_time - state.last_price_change_at)
        if time_since_change >= config.stagnant_timeout_seconds:
            return ExitDecision(
                action=ExitAction.FULL_EXIT,
                sell_fraction=1.0,
                sell_tokens=effective_balance,
                reason=f"stagnant_curve_timeout ({time_since_change:.1f}s >= {config.stagnant_timeout_seconds:.1f}s without price movement)",
                exit_type="stagnant_timeout",
            )

    # 3. Maximum Holding Duration Timeout Check
    if config.enable_max_hold_timeout:
        total_hold_time = max(0.0, current_time - state.entry_time)
        if total_hold_time >= config.max_hold_time_seconds:
            return ExitDecision(
                action=ExitAction.FULL_EXIT,
                sell_fraction=1.0,
                sell_tokens=effective_balance,
                reason=f"max_hold_time_exceeded ({total_hold_time:.1f}s >= {config.max_hold_time_seconds:.1f}s max hold limit)",
                exit_type="max_hold_timeout",
            )

    # 4. Multi-Tier Take-Profit Scale-Out Check
    if config.enable_tiered_take_profit:
        # Tier 1 (e.g., 2.0x -> +100% gain, sell 50% of position)
        if (
            not state.tier_1_executed
            and perf >= config.tier_1_take_profit
            and not state.is_exit_pending(1, current_time)
        ):
            state.mark_exit_pending(1, current_time)
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
            and not state.is_exit_pending(2, current_time)
        ):
            state.mark_exit_pending(2, current_time)
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


def _momentum_entry_exit(
    config: TradingBotConfig,
    state: PositionExitState,
    perf: float,
    balance: int,
    now: float,
) -> ExitDecision | None:
    """Break-even ratchet and buy-flow stagnation for confirmed entries.

    Once the peak gain reaches ``breakeven_ratchet_activation_pct`` the floor
    moves to entry + ``breakeven_buffer_pct``. With no buy of at least
    ``stagnant_min_buy_sol`` within ``stagnant_timeout_seconds`` (since entry or
    the last such buy) the demand that justified the entry is gone.
    """
    activation = float(getattr(config, "breakeven_ratchet_activation_pct", 0.0))
    if activation > 0 and state.peak_performance >= 1.0 + activation:
        state.breakeven_floor_active = True
    floor = 1.0 + float(getattr(config, "breakeven_buffer_pct", 0.0))
    if state.breakeven_floor_active and perf <= floor:
        return ExitDecision(
            action=ExitAction.FULL_EXIT,
            sell_fraction=1.0,
            sell_tokens=balance,
            reason=f"breakeven_ratchet ({perf:.2f}x <= {floor:.2f}x floor)",
            exit_type="breakeven_ratchet",
        )
    if (
        config.enable_stagnant_exit
        and float(getattr(config, "stagnant_min_buy_sol", 0.0)) > 0
    ):
        last_demand = max(state.entry_time, state.last_qualifying_buy_at or 0.0)
        idle = max(0.0, now - last_demand)
        if idle >= config.stagnant_timeout_seconds:
            return ExitDecision(
                action=ExitAction.FULL_EXIT,
                sell_fraction=1.0,
                sell_tokens=balance,
                reason=(
                    f"stagnant_buy_flow ({idle:.1f}s without a buy >= "
                    f"{config.stagnant_min_buy_sol:.3f} SOL)"
                ),
                exit_type="stagnant_buy_flow",
            )
    return None


def should_exit_position(
    config: TradingBotConfig,
    *,
    performance: float,
    token_balance: int,
    position: dict[str, Any] | PositionExitState | None = None,
    current_market_cap: float | None = None,
    now: float | None = None,
    curve_progress_pct: float | None = None,
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
        config,
        state,
        current_market_cap=mc,
        token_balance=token_balance,
        now=now,
        curve_progress_pct=curve_progress_pct,
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
