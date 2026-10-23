"""Risk checks, exposure limits, and kill-switch validation for the bot runtime."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CircuitBreakerAction(str, Enum):
    """Tiered action triggered by portfolio risk evaluation."""

    NONE = "none"
    HALT_NEW_BUYS = "halt_new_buys"
    EMERGENCY_LIQUIDATE = "emergency_liquidate"


@dataclass
class DailyEquityTracker:
    """
    Tracks portfolio starting baseline equity, real-time peak equity,
    daily realized/unrealized PnL, UTC midnight rollovers, adaptive realized ratchets,
    and circuit breaker lock states.
    """

    starting_equity_sol: float = 0.0
    peak_daily_equity_sol: float = 0.0
    realized_daily_pnl_sol: float = 0.0
    drawdown_reference_mode: str = "adaptive_ratchet"
    profit_ratchet_ratio: float = 0.50
    # Peak realized gain, as a share of starting equity, that arms the
    # ratchet floor (BUG-144). 0 arms it on any gain.
    profit_ratchet_min_gain_pct: float = 0.0
    profit_drawdown_tolerance_pct: float = 0.35
    circuit_breaker_action: CircuitBreakerAction = CircuitBreakerAction.NONE
    last_reset_date_utc: str = ""
    circuit_breaker_engaged: bool = False
    locked_at_timestamp: float | None = None
    lock_reason: str = ""
    total_lock_count: int = 0
    # Fees, tips and net rent paid today; realized PnL above is net of these.
    realized_daily_costs_sol: float = 0.0
    # Hard-lock length of the last evaluation, so a UTC rollover can tell
    # whether an emergency lock is still running (BUG-128).
    emergency_hard_lock_hours: float = 0.0
    # Equity the cumulative loss cap is measured from: set once, persisted,
    # lowered by withdrawals and reset only by the operator (BUG-128).
    reference_equity_sol: float = 0.0
    cumulative_cap_hit: bool = False
    # Highest net realized PnL so far today: the ratchet floor only moves up,
    # so profit given back through closed trades stays protected (BUG-141).
    peak_realized_daily_pnl_sol: float = 0.0

    @property
    def realized_daily_gross_pnl_sol(self) -> float:
        """Today's realized PnL before transaction costs (FEAT-49)."""
        return self.realized_daily_pnl_sol + self.realized_daily_costs_sol

    @property
    def effective_baseline_sol(self) -> float:
        """
        Calculates the ratcheted baseline equity floor:
        Starting Capital + profit_ratchet_ratio * max(0, peak realized PnL today).
        The peak, not the current realized PnL, so closed losses after a win
        do not lower the floor (BUG-141). The floor stays at the starting
        equity until that peak reaches ``profit_ratchet_min_gain_pct`` of it,
        so a trivial win cannot halt the day (BUG-144). Guaranteed
        >= starting_equity_sol and >= 0.0.
        """
        if self.drawdown_reference_mode == "adaptive_ratchet":
            realized_gain = max(
                0.0,
                float(self.peak_realized_daily_pnl_sol),
                float(self.realized_daily_pnl_sol),
            )
            min_gain = max(0.0, float(self.profit_ratchet_min_gain_pct or 0.0))
            if realized_gain < min_gain * max(0.0, self.starting_equity_sol):
                return max(0.0, self.starting_equity_sol)
            ratchet = (
                self.starting_equity_sol
                + float(self.profit_ratchet_ratio) * realized_gain
            )
            return max(0.0, ratchet)
        return max(0.0, self.starting_equity_sol)

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
        now_timestamp: float | None = None,
    ) -> bool:
        """Initializes or resets baseline equity at 00:00 UTC midnight boundary."""
        today_utc = self.get_current_utc_date(now_utc)
        current_equity = max(
            0.0, float(current_wallet_balance_sol) + float(open_positions_valuation_sol)
        )

        if not self.last_reset_date_utc:
            self.last_reset_date_utc = today_utc
            if self.starting_equity_sol <= 0.0:
                self.starting_equity_sol = current_equity
            if self.peak_daily_equity_sol <= 0.0:
                self.peak_daily_equity_sol = max(
                    self.starting_equity_sol, current_equity
                )
            if self.reference_equity_sol <= 0.0:
                self.reference_equity_sol = self.starting_equity_sol
            return True
        elif self.last_reset_date_utc != today_utc:
            self.last_reset_date_utc = today_utc
            self.starting_equity_sol = current_equity
            self.peak_daily_equity_sol = current_equity
            self.realized_daily_pnl_sol = 0.0
            self.realized_daily_costs_sol = 0.0
            self.peak_realized_daily_pnl_sol = 0.0
            if self.reference_equity_sol <= 0.0:
                self.reference_equity_sol = current_equity
            # A new UTC trading day releases a daily lock (BUG-47), but not an
            # emergency lock whose hard-lock duration is still running: a loss
            # limit hit at 23:55 UTC must not lift five minutes later (BUG-128).
            if not self._hard_lock_running(now_utc, now_timestamp):
                self.circuit_breaker_engaged = False
                self.circuit_breaker_action = CircuitBreakerAction.NONE
                self.locked_at_timestamp = None
                self.lock_reason = ""
            return True
        return False

    def _hard_lock_running(
        self,
        now_utc: datetime.datetime | None = None,
        now_timestamp: float | None = None,
    ) -> bool:
        """An emergency lock that must outlast the UTC rollover (BUG-128)."""
        if (
            not self.circuit_breaker_engaged
            or self.circuit_breaker_action != CircuitBreakerAction.EMERGENCY_LIQUIDATE
            or self.locked_at_timestamp is None
        ):
            return False
        hours = max(0.0, float(self.emergency_hard_lock_hours or 0.0))
        if hours <= 0:
            return False
        if now_timestamp is not None:
            now = float(now_timestamp)
        elif now_utc is not None:
            now = now_utc.timestamp()
        else:
            now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        return now < float(self.locked_at_timestamp) + hours * 3600.0

    def lockout_until(self, emergency_hard_lock_hours: float = 0.0) -> float | None:
        """Epoch time the active lock is released, ``None`` when unlocked (BUG-114).

        An emergency lock with a hard-lock duration lasts that long, across the
        UTC rollover (BUG-128). Any other lock ends at the next 00:00 UTC
        rollover, or earlier when the hard-lock duration elapses first.
        """
        if not self.circuit_breaker_engaged or self.locked_at_timestamp is None:
            return None
        locked_at = float(self.locked_at_timestamp)
        locked_dt = datetime.datetime.fromtimestamp(locked_at, tz=datetime.timezone.utc)
        next_midnight = datetime.datetime.combine(
            locked_dt.date() + datetime.timedelta(days=1),
            datetime.time(0, 0),
            tzinfo=datetime.timezone.utc,
        ).timestamp()
        hours = max(0.0, float(emergency_hard_lock_hours or 0.0))
        if hours > 0:
            if self.circuit_breaker_action == CircuitBreakerAction.EMERGENCY_LIQUIDATE:
                return locked_at + hours * 3600.0
            return min(next_midnight, locked_at + hours * 3600.0)
        return next_midnight

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

    def record_realized_trade(self, pnl_sol: float, costs_sol: float = 0.0) -> float:
        """Records realized PnL of a trade.

        ``pnl_sol`` must be **net** of ``costs_sol`` (fees, tips, net rent) so the
        circuit breaker sees real losses (FEAT-49).
        """
        self.realized_daily_pnl_sol += float(pnl_sol)
        self.realized_daily_costs_sol += float(costs_sol)
        self.peak_realized_daily_pnl_sol = max(
            self.peak_realized_daily_pnl_sol, self.realized_daily_pnl_sol
        )
        return self.realized_daily_pnl_sol

    def record_withdrawal(self, amount_sol: float) -> None:
        """SOL moved out of the wallet on purpose (profit sweep, FEAT-42).

        Lowers the starting and peak equity by the same amount, so the drawdown
        and baseline checks see no loss from it.
        """
        amount = max(0.0, float(amount_sol))
        self.starting_equity_sol = max(0.0, self.starting_equity_sol - amount)
        self.peak_daily_equity_sol = max(0.0, self.peak_daily_equity_sol - amount)
        self.reference_equity_sol = max(0.0, self.reference_equity_sol - amount)

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
        drawdown_reference_mode: str | None = None,
        profit_ratchet_ratio: float | None = None,
        profit_drawdown_tolerance_pct: float | None = None,
        max_cumulative_drawdown_pct: float | None = None,
        profit_ratchet_min_gain_pct: float | None = None,
    ) -> tuple[bool, str]:
        """
        Evaluates portfolio drawdown against threshold using dual-zone risk mechanics.
        Returns (is_locked, reason).
        Handles auto-unlock if hard lock duration has elapsed.

        ``max_cumulative_drawdown_pct`` (0 = off) caps the loss from
        ``reference_equity_sol`` across days and locks (BUG-128).
        """
        if now_timestamp is None:
            now_timestamp = datetime.datetime.now(datetime.timezone.utc).timestamp()
        self.emergency_hard_lock_hours = max(0.0, float(emergency_hard_lock_hours))

        if drawdown_reference_mode is not None:
            self.drawdown_reference_mode = drawdown_reference_mode
        if profit_ratchet_ratio is not None:
            self.profit_ratchet_ratio = profit_ratchet_ratio
        if profit_ratchet_min_gain_pct is not None:
            self.profit_ratchet_min_gain_pct = float(profit_ratchet_min_gain_pct)
        if profit_drawdown_tolerance_pct is not None:
            self.profit_drawdown_tolerance_pct = profit_drawdown_tolerance_pct

        # Roll over on a UTC date change even while latched (BUG-47).
        self.initialize_or_rollover(
            current_wallet_balance_sol,
            open_positions_valuation_sol,
            now_utc,
            now_timestamp=now_timestamp,
        )

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
                self.circuit_breaker_action = CircuitBreakerAction.NONE
                self.locked_at_timestamp = None
                self.lock_reason = ""
                # Re-initialize baseline on automatic unlock
                self.starting_equity_sol = max(
                    0.0,
                    float(current_wallet_balance_sol)
                    + float(open_positions_valuation_sol),
                )
                self.peak_daily_equity_sol = self.starting_equity_sol
                self.realized_daily_pnl_sol = 0.0
                self.realized_daily_costs_sol = 0.0
                self.peak_realized_daily_pnl_sol = 0.0
            else:
                return True, self.lock_reason or "portfolio circuit breaker active"

        # Update valuation & calculate peak drawdown
        current_equity, peak_drawdown_pct = self.update_valuation(
            current_wallet_balance_sol, open_positions_valuation_sol, now_utc
        )

        # Cumulative loss cap (BUG-128): the daily limit re-baselines every UTC
        # day and after every lock, so on its own it allows that loss again and
        # again. This one is measured from a reference only the operator resets.
        cumulative_cap = max(0.0, float(max_cumulative_drawdown_pct or 0.0))
        if self.reference_equity_sol <= 0.0 and self.starting_equity_sol > 0.0:
            # A tracker restored from a pre-BUG-128 status file has no reference.
            self.reference_equity_sol = self.starting_equity_sol
        if cumulative_cap > 0 and self.reference_equity_sol > 0:
            cumulative_loss_pct = (
                self.reference_equity_sol - current_equity
            ) / self.reference_equity_sol
            # A loss of exactly the cap (as floats) is not past it.
            if cumulative_loss_pct > cumulative_cap + 1e-9:
                self.circuit_breaker_engaged = True
                self.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
                self.locked_at_timestamp = now_timestamp
                self.total_lock_count += 1
                self.cumulative_cap_hit = True
                self.lock_reason = (
                    f"cumulative loss {cumulative_loss_pct:.2%} exceeded maximum allowed "
                    f"{cumulative_cap:.2%} (reference: {self.reference_equity_sol:.4f} SOL, "
                    f"current: {current_equity:.4f} SOL); buying stays paused until "
                    "the operator resumes it"
                )
                return True, self.lock_reason

        mode = self.drawdown_reference_mode or "adaptive_ratchet"

        # Mode 1: Baseline Only (Principal loss against starting capital)
        if mode == "baseline":
            principal_loss = self.starting_equity_sol - current_equity
            principal_loss_pct = (
                (principal_loss / self.starting_equity_sol)
                if self.starting_equity_sol > 0
                else 0.0
            )
            if principal_loss_pct > max_daily_drawdown_pct:
                self.circuit_breaker_engaged = True
                self.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
                self.locked_at_timestamp = now_timestamp
                self.total_lock_count += 1
                self.lock_reason = (
                    f"portfolio principal loss {principal_loss_pct:.2%} exceeded maximum allowed limit {max_daily_drawdown_pct:.2%} "
                    f"(starting: {self.starting_equity_sol:.4f} SOL, current: {current_equity:.4f} SOL)"
                )
                return True, self.lock_reason
            self.circuit_breaker_action = CircuitBreakerAction.NONE
            return False, ""

        # Mode 2: Trailing High-Water Mark (Legacy peak-to-trough)
        if mode == "trailing_hwm":
            if peak_drawdown_pct > max_daily_drawdown_pct:
                self.circuit_breaker_engaged = True
                self.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
                self.locked_at_timestamp = now_timestamp
                self.total_lock_count += 1
                self.lock_reason = (
                    f"portfolio drawdown {peak_drawdown_pct:.2%} exceeded maximum allowed limit {max_daily_drawdown_pct:.2%} "
                    f"(peak: {self.peak_daily_equity_sol:.4f} SOL, current: {current_equity:.4f} SOL, "
                    f"baseline: {self.starting_equity_sol:.4f} SOL)"
                )
                return True, self.lock_reason
            self.circuit_breaker_action = CircuitBreakerAction.NONE
            return False, ""

        # Mode 3: Adaptive Realized-Ratchet Dual-Zone (Default)
        # Regime A: Principal Protection Zone (current_equity < starting_equity_sol)
        if current_equity < self.starting_equity_sol:
            principal_loss = self.starting_equity_sol - current_equity
            principal_loss_pct = (
                (principal_loss / self.starting_equity_sol)
                if self.starting_equity_sol > 0
                else 0.0
            )
            if principal_loss_pct > max_daily_drawdown_pct:
                self.circuit_breaker_engaged = True
                self.circuit_breaker_action = CircuitBreakerAction.EMERGENCY_LIQUIDATE
                self.locked_at_timestamp = now_timestamp
                self.total_lock_count += 1
                self.lock_reason = (
                    f"portfolio drawdown {principal_loss_pct:.2%} exceeded maximum allowed limit {max_daily_drawdown_pct:.2%} "
                    f"(starting: {self.starting_equity_sol:.4f} SOL, current: {current_equity:.4f} SOL)"
                )
                return True, self.lock_reason
            self.circuit_breaker_action = CircuitBreakerAction.NONE
            return False, ""

        # Regime B: Profit Run Zone (current_equity >= starting_equity_sol)
        # Operating with house money -> evaluate relaxed trailing tolerance from daily peak
        profit_tolerance = self.profit_drawdown_tolerance_pct
        if peak_drawdown_pct > profit_tolerance:
            self.circuit_breaker_engaged = True
            self.circuit_breaker_action = CircuitBreakerAction.HALT_NEW_BUYS
            self.locked_at_timestamp = now_timestamp
            self.total_lock_count += 1
            self.lock_reason = (
                f"profit run retracement {peak_drawdown_pct:.2%} exceeded tolerance {profit_tolerance:.2%} "
                f"(peak: {self.peak_daily_equity_sol:.4f} SOL, current: {current_equity:.4f} SOL, "
                f"effective baseline: {self.effective_baseline_sol:.4f} SOL)"
            )
            return True, self.lock_reason

        # Realized-profit ratchet (BUG-127): `profit_ratchet_ratio` of today's
        # realized profit is kept. The retracement check above is measured
        # against the whole peak equity, so on its own it only fires once the
        # profit is gone; the floor stops new buys first. Open positions keep
        # exiting on their own rules (soft halt).
        ratchet_floor = self.effective_baseline_sol
        if current_equity < ratchet_floor:
            self.circuit_breaker_engaged = True
            self.circuit_breaker_action = CircuitBreakerAction.HALT_NEW_BUYS
            self.locked_at_timestamp = now_timestamp
            self.total_lock_count += 1
            self.lock_reason = (
                f"profit ratchet floor: equity {current_equity:.4f} SOL fell below "
                f"{ratchet_floor:.4f} SOL (starting {self.starting_equity_sol:.4f} SOL "
                f"+ {self.profit_ratchet_ratio:.0%} of peak realized "
                f"{max(self.peak_realized_daily_pnl_sol, self.realized_daily_pnl_sol):+.4f} SOL, "
                f"now {self.realized_daily_pnl_sol:+.4f} SOL)"
            )
            return True, self.lock_reason

        self.circuit_breaker_action = CircuitBreakerAction.NONE
        return False, ""

    def reset_circuit_breaker(
        self,
        *,
        force: bool = True,
        new_baseline_sol: float | None = None,
    ) -> None:
        """Manually unlocks the circuit breaker and resets lock state."""
        self.circuit_breaker_engaged = False
        self.circuit_breaker_action = CircuitBreakerAction.NONE
        self.locked_at_timestamp = None
        self.lock_reason = ""
        self.cumulative_cap_hit = False
        if new_baseline_sol is not None and new_baseline_sol > 0:
            self.starting_equity_sol = float(new_baseline_sol)
            self.peak_daily_equity_sol = float(new_baseline_sol)
            self.reference_equity_sol = float(new_baseline_sol)

    def to_dict(self) -> dict[str, Any]:
        """Serializes equity tracker state for durable JSON snapshot storage."""
        return {
            "starting_equity_sol": self.starting_equity_sol,
            "peak_daily_equity_sol": self.peak_daily_equity_sol,
            "realized_daily_pnl_sol": self.realized_daily_pnl_sol,
            "realized_daily_costs_sol": self.realized_daily_costs_sol,
            "realized_daily_gross_pnl_sol": self.realized_daily_gross_pnl_sol,
            "peak_realized_daily_pnl_sol": self.peak_realized_daily_pnl_sol,
            "effective_baseline_sol": self.effective_baseline_sol,
            "drawdown_reference_mode": self.drawdown_reference_mode,
            "profit_ratchet_ratio": self.profit_ratchet_ratio,
            "profit_ratchet_min_gain_pct": self.profit_ratchet_min_gain_pct,
            "profit_drawdown_tolerance_pct": self.profit_drawdown_tolerance_pct,
            "circuit_breaker_action": (
                self.circuit_breaker_action.value
                if isinstance(self.circuit_breaker_action, CircuitBreakerAction)
                else str(self.circuit_breaker_action)
            ),
            "last_reset_date_utc": self.last_reset_date_utc,
            "circuit_breaker_engaged": self.circuit_breaker_engaged,
            "locked_at_timestamp": self.locked_at_timestamp,
            "lock_reason": self.lock_reason,
            "total_lock_count": self.total_lock_count,
            "emergency_hard_lock_hours": self.emergency_hard_lock_hours,
            "reference_equity_sol": self.reference_equity_sol,
            "cumulative_cap_hit": self.cumulative_cap_hit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyEquityTracker":
        """Deserializes equity tracker state from dictionary."""
        raw_action = data.get("circuit_breaker_action", "none")
        try:
            action = CircuitBreakerAction(raw_action)
        except ValueError:
            action = CircuitBreakerAction.NONE

        return cls(
            starting_equity_sol=float(data.get("starting_equity_sol", 0.0) or 0.0),
            peak_daily_equity_sol=float(data.get("peak_daily_equity_sol", 0.0) or 0.0),
            realized_daily_pnl_sol=float(
                data.get("realized_daily_pnl_sol", 0.0) or 0.0
            ),
            drawdown_reference_mode=str(
                data.get("drawdown_reference_mode", "adaptive_ratchet")
            ),
            profit_ratchet_ratio=float(data.get("profit_ratchet_ratio", 0.50)),
            profit_ratchet_min_gain_pct=float(
                data.get("profit_ratchet_min_gain_pct", 0.0) or 0.0
            ),
            profit_drawdown_tolerance_pct=float(
                data.get("profit_drawdown_tolerance_pct", 0.35)
            ),
            circuit_breaker_action=action,
            last_reset_date_utc=str(data.get("last_reset_date_utc", "") or ""),
            circuit_breaker_engaged=bool(data.get("circuit_breaker_engaged", False)),
            locked_at_timestamp=data.get("locked_at_timestamp"),
            lock_reason=str(data.get("lock_reason", "") or ""),
            total_lock_count=int(data.get("total_lock_count", 0) or 0),
            realized_daily_costs_sol=float(
                data.get("realized_daily_costs_sol", 0.0) or 0.0
            ),
            emergency_hard_lock_hours=float(
                data.get("emergency_hard_lock_hours", 0.0) or 0.0
            ),
            reference_equity_sol=float(data.get("reference_equity_sol", 0.0) or 0.0),
            cumulative_cap_hit=bool(data.get("cumulative_cap_hit", False)),
            # A status file from before BUG-141 has no peak: start from today's.
            peak_realized_daily_pnl_sol=max(
                float(data.get("peak_realized_daily_pnl_sol", 0.0) or 0.0),
                float(data.get("realized_daily_pnl_sol", 0.0) or 0.0),
            ),
        )


def evaluate_portfolio_circuit_breaker(bot: Any) -> tuple[bool, str]:
    """
    Evaluates portfolio-level daily equity loss limits and circuit breaker status.
    Returns (is_breached, reason).
    """
    tracker: DailyEquityTracker | None = getattr(bot, "daily_equity_tracker", None)
    if tracker is None or not isinstance(tracker, DailyEquityTracker):
        return False, ""
    if not getattr(bot, "dry_run", True) and not getattr(
        bot, "_live_balance_confirmed", True
    ):
        # The wallet figure is still the simulated start balance: block buys,
        # but never let it set the day's baseline (BUG-130).
        return True, "waiting for the first live wallet balance read"

    wallet_sol = float(getattr(bot, "wallet_balance_sol", 0.0) or 0.0)
    pos_mgr = getattr(bot, "position_manager", None)
    exit_value = getattr(bot, "_open_positions_exit_value", None)
    if callable(exit_value):
        # What selling would return, not spot (BUG-136).
        open_val_sol = float(exit_value() or 0.0)
    elif pos_mgr is not None and hasattr(pos_mgr, "calculate_total_open_value"):
        open_val_sol = float(pos_mgr.calculate_total_open_value() or 0.0)
    else:
        open_positions = getattr(bot, "active_positions", {}) or {}
        default_cost = float(
            getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0
        )
        open_val_sol = 0.0
        for pos in open_positions.values():
            cost = _extract_position_cost(pos, default_cost)
            fraction = _extract_position_fraction(pos)
            effective_cost = cost * fraction
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
                open_val_sol += effective_cost * (curr_mc / entry_mc)
            else:
                open_val_sol += effective_cost

    cfg = getattr(bot, "config", None)
    max_drawdown = float(getattr(cfg, "max_daily_drawdown_pct", 0.15))
    lock_hours = float(getattr(cfg, "emergency_hard_lock_hours", 24.0))
    mode = getattr(cfg, "drawdown_reference_mode", None)
    ratchet_ratio = getattr(cfg, "profit_ratchet_ratio", None)
    ratchet_min_gain = getattr(cfg, "profit_ratchet_min_gain_pct", None)
    if not isinstance(ratchet_min_gain, (int, float)) or isinstance(
        ratchet_min_gain, bool
    ):
        ratchet_min_gain = None
    profit_tolerance = getattr(cfg, "profit_drawdown_tolerance_pct", None)
    cumulative_cap = float(getattr(cfg, "max_cumulative_drawdown_pct", 0.0) or 0.0)

    # The bot's clock, so a paper drill can cross midnight (FEAT-69).
    now_fn = getattr(bot, "now_timestamp", None)
    now_ts = now_fn() if callable(now_fn) else None
    if not isinstance(now_ts, (int, float)) or isinstance(now_ts, bool):
        now_ts = None
    is_locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=max_drawdown,
        emergency_hard_lock_hours=lock_hours,
        current_wallet_balance_sol=wallet_sol,
        open_positions_valuation_sol=open_val_sol,
        now_timestamp=now_ts,
        now_utc=(
            datetime.datetime.fromtimestamp(now_ts, tz=datetime.timezone.utc)
            if now_ts is not None
            else None
        ),
        drawdown_reference_mode=mode,
        profit_ratchet_ratio=ratchet_ratio,
        profit_drawdown_tolerance_pct=profit_tolerance,
        max_cumulative_drawdown_pct=cumulative_cap,
        profit_ratchet_min_gain_pct=ratchet_min_gain,
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


def _extract_position_fraction(pos: Any) -> float:
    """Extracts the fraction of tokens remaining (remaining_tokens / initial_tokens)."""
    if isinstance(pos, dict):
        init_tokens = (
            pos.get("initial_token_amount")
            or pos.get("token_amount")
            or pos.get("remaining_token_amount")
            or 0
        )
        if (
            "remaining_token_amount" in pos
            and pos["remaining_token_amount"] is not None
        ):
            rem_tokens = pos["remaining_token_amount"]
        elif "token_amount" in pos and pos["token_amount"] is not None:
            rem_tokens = pos["token_amount"]
        else:
            rem_tokens = init_tokens
    else:
        init_tokens = (
            getattr(pos, "initial_token_amount", 0)
            or getattr(pos, "token_amount", 0)
            or 0
        )
        rem_tokens = getattr(pos, "remaining_token_amount", None)
        if rem_tokens is None:
            rem_tokens = getattr(pos, "token_amount", init_tokens)

    try:
        init_val = float(init_tokens or 0)
    except (TypeError, ValueError):
        init_val = 0.0

    if init_val <= 0:
        return 1.0

    try:
        rem_val = float(rem_tokens if rem_tokens is not None else init_val)
    except (TypeError, ValueError):
        rem_val = init_val

    return max(0.0, min(1.0, rem_val / init_val))


def check_risk_limits(
    bot: Any,
    *,
    mint: str,
    proposed_entry_sol: float,
    current_positions: dict[str, dict[str, Any]],
) -> bool:
    default_cost = float(
        getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0
    )
    # Exposure is the cost still at risk after partial exits (BUG-71).
    total_exposure = sum(
        _extract_position_cost(pos, default_cost) * _extract_position_fraction(pos)
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

    max_concentration_pct = float(
        getattr(bot.config, "max_token_concentration_pct", 0.35)
    )
    if bot.config.max_total_exposure_sol > 0:
        candidate_costs = [
            _extract_position_cost(pos, default_cost) * _extract_position_fraction(pos)
            for pos in current_positions.values()
        ] + [proposed_entry_sol]
        max_per_token_ratio = max(candidate_costs) / bot.config.max_total_exposure_sol
        if max_per_token_ratio > max_concentration_pct:
            bot._last_event = (
                "risk limit: per-token concentration cap reached "
                f"({max_per_token_ratio:.2%} > {max_concentration_pct:.2%})"
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

    default_cost = float(
        getattr(getattr(bot, "config", None), "buy_amount_sol", 0.0) or 0.0
    )
    total_equity = sum(
        _extract_position_cost(pos, default_cost) * _extract_position_fraction(pos)
        for pos in bot.active_positions.values()
    )
    if total_equity <= 0:
        return True

    current_val = 0.0
    for pos in bot.active_positions.values():
        cost = _extract_position_cost(pos, default_cost)
        fraction = _extract_position_fraction(pos)
        effective_cost = cost * fraction
        if isinstance(pos, dict):
            entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
            curr_mc = float(pos.get("current_market_cap", entry_mc) or entry_mc)
        else:
            entry_mc = float(getattr(pos, "entry_market_cap", 0.0) or 0.0)
            curr_mc = float(getattr(pos, "current_market_cap", entry_mc) or entry_mc)

        if entry_mc > 0:
            current_val += effective_cost * (curr_mc / entry_mc)
        else:
            current_val += effective_cost

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

    max_loss_sol = float(getattr(bot.config, "max_loss_per_trade_sol", 0.0) or 0.0)
    if max_loss_sol <= 0:
        return True

    # Compare the SOL at risk, not a market-cap ratio, to the SOL cap (BUG-70).
    default_cost = float(getattr(bot.config, "buy_amount_sol", 0.0) or 0.0)
    effective_cost = _extract_position_cost(
        position, default_cost
    ) * _extract_position_fraction(position)
    loss_ratio = max(0.0, 1.0 - (current_market_cap / entry_market_cap))
    loss_sol = effective_cost * loss_ratio
    if loss_sol > max_loss_sol:
        bot._last_event = (
            f"risk limit: trade loss {loss_sol:.4f} SOL exceeds max "
            f"{max_loss_sol:.4f} SOL"
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
    "CircuitBreakerAction",
    "DailyEquityTracker",
    "check_daily_drawdown",
    "check_loss_per_trade",
    "check_risk_limits",
    "evaluate_portfolio_circuit_breaker",
    "track_position_peak",
]
