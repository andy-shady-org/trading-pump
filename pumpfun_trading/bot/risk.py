"""Risk checks, exposure limits, and kill-switch validation for the bot runtime."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


@dataclass
class DailyEquityTracker:
    """
    Tracks portfolio starting baseline equity, real-time peak equity,
    daily realized/unrealized PnL, UTC midnight rollovers, and circuit breaker lock states.
    """

    starting_equity_sol: float = 0.0
    peak_daily_equity_sol: float = 0.0
    realized_daily_pnl_sol: float = 0.0
    last_reset_date_utc: str = ""
    circuit_breaker_engaged: bool = False
    locked_at_timestamp: float | None = None
    lock_reason: str = ""
    total_lock_count: int = 0

    @classmethod
    def get_current_utc_date(cls, dt: datetime.datetime | None = None) -> str:
        """Returns the current date in UTC as a YYYY-MM-DD string."""
        if dt is None:
            dt = datetime.datetime.now(datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d")

    def initialize_or_rollover(
        self,
        current_wallet_balance_sol: float,
        open_positions_valuation_sol: float = 0.0,
        now_utc: datetime.datetime | None = None,
    ) -> bool:
        """Initializes or resets baseline equity at 00:00 UTC midnight boundary."""
        today_utc = self.get_current_utc_date(now_utc)
        current_equity = max(
            0.0, float(current_wallet_balance_sol) + float(open_positions_valuation_sol)
        )

        if not self.last_reset_date_utc or self.last_reset_date_utc != today_utc:
            self.last_reset_date_utc = today_utc
            self.starting_equity_sol = current_equity
            self.peak_daily_equity_sol = current_equity
            self.realized_daily_pnl_sol = 0.0
            return True
        return False

    def update_valuation(
        self,
        current_wallet_balance_sol: float,
        open_positions_valuation_sol: float = 0.0,
        now_utc: datetime.datetime | None = None,
    ) -> tuple[float, float]:
        """Updates real-time equity valuation and returns (current_equity, drawdown_pct)."""
        self.initialize_or_rollover(
            current_wallet_balance_sol, open_positions_valuation_sol, now_utc
        )
        current_equity = max(
            0.0, float(current_wallet_balance_sol) + float(open_positions_valuation_sol)
        )
        if current_equity > self.peak_daily_equity_sol:
            self.peak_daily_equity_sol = current_equity

        drawdown_pct = self.calculate_drawdown(
            current_wallet_balance_sol, open_positions_valuation_sol, now_utc
        )
        return current_equity, drawdown_pct

    def record_realized_trade(self, pnl_sol: float) -> float:
        """Records realized profit or loss from a closed trade."""
        self.realized_daily_pnl_sol += float(pnl_sol)
        return self.realized_daily_pnl_sol

    def calculate_drawdown(
        self,
        current_wallet_balance_sol: float,
        open_positions_valuation_sol: float = 0.0,
        now_utc: datetime.datetime | None = None,
    ) -> float:
        """Calculates current drawdown percentage from peak daily equity."""
        self.initialize_or_rollover(
            current_wallet_balance_sol, open_positions_valuation_sol, now_utc
        )
        current_equity = max(
            0.0, float(current_wallet_balance_sol) + float(open_positions_valuation_sol)
        )
        if self.peak_daily_equity_sol <= 0:
            return 0.0

        drawdown_amount = self.peak_daily_equity_sol - current_equity
        if drawdown_amount <= 0:
            return 0.0
        return drawdown_amount / self.peak_daily_equity_sol

    def evaluate_circuit_breaker(
        self,
        *,
        max_daily_drawdown_pct: float,
        emergency_hard_lock_hours: float,
        current_wallet_balance_sol: float,
        open_positions_valuation_sol: float = 0.0,
        now_timestamp: float | None = None,
        now_utc: datetime.datetime | None = None,
    ) -> tuple[bool, str]:
        """
        Evaluates portfolio drawdown against threshold.
        Returns (is_locked, reason).
        Handles auto-unlock if hard lock duration has elapsed.
        """
        if now_timestamp is None:
            now_timestamp = datetime.datetime.now(datetime.timezone.utc).timestamp()

        # Check if currently locked
        if self.circuit_breaker_engaged:
            lock_duration_seconds = max(0.0, float(emergency_hard_lock_hours)) * 3600.0
            if (
                self.locked_at_timestamp is not None
                and lock_duration_seconds > 0
                and (now_timestamp - self.locked_at_timestamp) >= lock_duration_seconds
            ):
                # Lockout period elapsed -> automatic unlock
                self.circuit_breaker_engaged = False
                self.locked_at_timestamp = None
                self.lock_reason = ""
                # Re-initialize baseline on automatic unlock
                self.starting_equity_sol = max(
                    0.0,
                    float(current_wallet_balance_sol)
                    + float(open_positions_valuation_sol),
                )
                self.peak_daily_equity_sol = self.starting_equity_sol
            else:
                return True, self.lock_reason or "portfolio circuit breaker active"

        # Update valuation & calculate drawdown
        current_equity, drawdown_pct = self.update_valuation(
            current_wallet_balance_sol, open_positions_valuation_sol, now_utc
        )

        if drawdown_pct > max_daily_drawdown_pct:
            self.circuit_breaker_engaged = True
            self.locked_at_timestamp = now_timestamp
            self.total_lock_count += 1
            self.lock_reason = (
                f"portfolio drawdown {drawdown_pct:.2%} exceeded maximum allowed limit {max_daily_drawdown_pct:.2%} "
                f"(peak: {self.peak_daily_equity_sol:.4f} SOL, current: {current_equity:.4f} SOL, "
                f"baseline: {self.starting_equity_sol:.4f} SOL)"
            )
            return True, self.lock_reason

        return False, ""

    def reset_circuit_breaker(
        self,
        *,
        force: bool = True,
        new_baseline_sol: float | None = None,
    ) -> None:
        """Manually unlocks the circuit breaker and resets lock state."""
        self.circuit_breaker_engaged = False
        self.locked_at_timestamp = None
        self.lock_reason = ""
        if new_baseline_sol is not None and new_baseline_sol > 0:
            self.starting_equity_sol = float(new_baseline_sol)
            self.peak_daily_equity_sol = float(new_baseline_sol)

    def to_dict(self) -> dict[str, Any]:
        """Serializes equity tracker state for durable JSON snapshot storage."""
        return {
            "starting_equity_sol": self.starting_equity_sol,
            "peak_daily_equity_sol": self.peak_daily_equity_sol,
            "realized_daily_pnl_sol": self.realized_daily_pnl_sol,
            "last_reset_date_utc": self.last_reset_date_utc,
            "circuit_breaker_engaged": self.circuit_breaker_engaged,
            "locked_at_timestamp": self.locked_at_timestamp,
            "lock_reason": self.lock_reason,
            "total_lock_count": self.total_lock_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyEquityTracker":
        """Deserializes equity tracker state from dictionary."""
        return cls(
            starting_equity_sol=float(data.get("starting_equity_sol", 0.0) or 0.0),
            peak_daily_equity_sol=float(data.get("peak_daily_equity_sol", 0.0) or 0.0),
            realized_daily_pnl_sol=float(
                data.get("realized_daily_pnl_sol", 0.0) or 0.0
            ),
            last_reset_date_utc=str(data.get("last_reset_date_utc", "") or ""),
            circuit_breaker_engaged=bool(data.get("circuit_breaker_engaged", False)),
            locked_at_timestamp=data.get("locked_at_timestamp"),
            lock_reason=str(data.get("lock_reason", "") or ""),
            total_lock_count=int(data.get("total_lock_count", 0) or 0),
        )


def evaluate_portfolio_circuit_breaker(bot: Any) -> tuple[bool, str]:
    """
    Evaluates portfolio-level daily equity loss limits and circuit breaker status.
    Returns (is_breached, reason).
    """
    tracker: DailyEquityTracker | None = getattr(bot, "daily_equity_tracker", None)
    if tracker is None or not isinstance(tracker, DailyEquityTracker):
        return False, ""

    wallet_sol = float(getattr(bot, "wallet_balance_sol", 0.0) or 0.0)
    pos_mgr = getattr(bot, "position_manager", None)
    if pos_mgr is not None and hasattr(pos_mgr, "calculate_total_open_value"):
        open_val_sol = float(pos_mgr.calculate_total_open_value() or 0.0)
    else:
        open_positions = getattr(bot, "active_positions", {}) or {}
        default_cost = float(
            getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0
        )
        open_val_sol = 0.0
        for pos in open_positions.values():
            cost = _extract_position_cost(pos, default_cost)
            if isinstance(pos, dict):
                entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
                if pos.get("current_market_cap") is not None:
                    curr_mc = float(pos.get("current_market_cap", 0.0) or 0.0)
                else:
                    curr_mc = entry_mc
            else:
                entry_mc = float(getattr(pos, "entry_market_cap", 0.0) or 0.0)
                curr_val = getattr(pos, "current_market_cap", None)
                curr_mc = float(curr_val if curr_val is not None else entry_mc)

            if entry_mc > 0:
                open_val_sol += cost * (curr_mc / entry_mc)
            else:
                open_val_sol += cost

    max_drawdown = float(getattr(bot.config, "max_daily_drawdown_pct", 0.15))
    lock_hours = float(getattr(bot.config, "emergency_hard_lock_hours", 24.0))

    is_locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=max_drawdown,
        emergency_hard_lock_hours=lock_hours,
        current_wallet_balance_sol=wallet_sol,
        open_positions_valuation_sol=open_val_sol,
    )
    if is_locked and reason:
        bot._last_event = f"circuit breaker: {reason}"
    return is_locked, reason


def _extract_position_cost(pos: Any, default_cost: float = 0.0) -> float:
    """Extracts capital cost outlay (cost_sol or entry_sol) for a position."""
    if isinstance(pos, dict):
        cost = pos.get("cost_sol")
        if cost is None:
            cost = pos.get("entry_sol")
        if cost is None:
            cost = default_cost
        return float(cost or 0.0)
    cost = getattr(pos, "cost_sol", None)
    if cost is None:
        cost = getattr(pos, "entry_sol", None)
    if cost is None:
        cost = default_cost
    return float(cost or 0.0)


def check_risk_limits(
    bot: Any,
    *,
    mint: str,
    proposed_entry_sol: float,
    current_positions: dict[str, dict[str, Any]],
) -> bool:
    default_cost = float(getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0)
    total_exposure = sum(
        _extract_position_cost(pos, default_cost)
        for pos in current_positions.values()
    )
    if total_exposure + proposed_entry_sol > bot.config.max_total_exposure_sol:
        bot._last_event = (
            f"risk limit: max exposure {bot.config.max_total_exposure_sol:.2f} SOL"
        )
        return False
    if proposed_entry_sol > bot.config.max_position_size_sol:
        bot._last_event = (
            f"risk limit: position cap {bot.config.max_position_size_sol:.2f} SOL"
        )
        return False
    if mint in current_positions:
        bot._last_event = f"risk limit: mint already active {mint[:8]}..."
        return False

    if current_positions:
        max_per_token_ratio = (
            max(
                _extract_position_cost(pos, default_cost)
                / bot.config.max_total_exposure_sol
                for pos in current_positions.values()
            )
            if bot.config.max_total_exposure_sol > 0
            else 0.0
        )
        if max_per_token_ratio > float(
            getattr(bot.config, "max_token_concentration_pct", 0.35)
        ):
            bot._last_event = (
                "risk limit: per-token concentration cap reached "
                f"({max_per_token_ratio:.2%} > {float(getattr(bot.config, 'max_token_concentration_pct', 0.35)):.2%})"
            )
            return False

    return True


def check_daily_drawdown(bot: Any) -> bool:
    tracker: DailyEquityTracker | None = getattr(bot, "daily_equity_tracker", None)
    if tracker is not None and isinstance(tracker, DailyEquityTracker):
        is_locked, _ = evaluate_portfolio_circuit_breaker(bot)
        return not is_locked

    if not bot.active_positions:
        return True

    default_cost = float(getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0)
    total_equity = sum(
        _extract_position_cost(pos, default_cost)
        for pos in bot.active_positions.values()
    )
    if total_equity <= 0:
        return True

    current_val = 0.0
    for pos in bot.active_positions.values():
        cost = _extract_position_cost(pos, default_cost)
        if isinstance(pos, dict):
            entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
            curr_mc = float(pos.get("current_market_cap", entry_mc) or entry_mc)
        else:
            entry_mc = float(getattr(pos, "entry_market_cap", 0.0) or 0.0)
            curr_mc = float(getattr(pos, "current_market_cap", entry_mc) or entry_mc)

        if entry_mc > 0:
            current_val += cost * (curr_mc / entry_mc)
        else:
            current_val += cost

    drawdown = 1.0 - (current_val / total_equity)
    if drawdown > bot.config.max_daily_drawdown_pct:
        bot._last_event = (
            f"risk limit: daily drawdown {drawdown:.2%} exceeds "
            f"{bot.config.max_daily_drawdown_pct:.2%}"
        )
        return False
    return True


def check_loss_per_trade(
    bot: Any, *, mint: str, current_market_cap: float | None = None
) -> bool:
    position = bot.active_positions.get(mint)
    if position is None:
        return True

    if current_market_cap is None:
        current_market_cap = float(position.get("current_market_cap", 0.0) or 0.0)
    entry_market_cap = float(position.get("entry_market_cap", 0.0) or 0.0)
    if entry_market_cap <= 0:
        return True

    loss_ratio = 1.0 - (current_market_cap / entry_market_cap)
    if loss_ratio > bot.config.max_loss_per_trade_sol / bot.config.buy_amount_sol:
        bot._last_event = (
            f"risk limit: trade loss {loss_ratio:.2%} exceeds max "
            f"{bot.config.max_loss_per_trade_sol / bot.config.buy_amount_sol:.2%}"
        )
        return False
    return True


def track_position_peak(
    bot: Any,
    *,
    mint: str,
    current_market_cap: float,
) -> float:
    position = bot.active_positions.get(mint)
    if position is None:
        return current_market_cap
    mc = max(0.0, float(current_market_cap))
    curr_peak = float(position.get("peak_market_cap", 0.0) or 0.0)
    new_peak = max(curr_peak, mc)
    position["peak_market_cap"] = new_peak
    position["current_market_cap"] = mc
    return new_peak


__all__ = [
    "DailyEquityTracker",
    "check_daily_drawdown",
    "check_loss_per_trade",
    "check_risk_limits",
    "evaluate_portfolio_circuit_breaker",
    "track_position_peak",
]
