"""Real-time order flow and trade velocity momentum analytics engine for Pump.fun trading.

This module provides sub-millisecond rolling sliding window metrics,
wash-trading filters, and statistical trade velocity Z-score anomaly detection
to detect explosive breakout momentum on active bonding curves.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class TradeRecord:
    """Individual trade execution record."""

    mint: str
    is_buy: bool
    sol_amount: float
    user: str
    timestamp: float


@dataclass(slots=True)
class WindowMetrics:
    """Aggregated order flow metrics for a rolling sliding time window."""

    window_seconds: int
    trade_count: int
    buy_count: int
    sell_count: int
    buy_volume_sol: float
    sell_volume_sol: float
    buy_sell_ratio: float
    net_sol_inflow: float
    unique_buyers: int
    unique_sellers: int
    trade_velocity: float  # transactions per second


@dataclass(slots=True)
class MomentumSignal:
    """Result of real-time momentum breakout evaluation."""

    triggered: bool
    mint: str
    z_score: float
    buy_sell_ratio: float
    net_sol_inflow: float
    unique_buyers: int
    trade_velocity: float
    metrics: WindowMetrics
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert momentum signal to a dictionary for telemetry and auditing."""
        return {
            "triggered": self.triggered,
            "mint": self.mint,
            "z_score": self.z_score,
            "buy_sell_ratio": self.buy_sell_ratio,
            "net_sol_inflow": self.net_sol_inflow,
            "unique_buyers": self.unique_buyers,
            "trade_velocity": self.trade_velocity,
            "reason": self.reason,
            "metrics": {
                "window_seconds": self.metrics.window_seconds,
                "trade_count": self.metrics.trade_count,
                "buy_count": self.metrics.buy_count,
                "sell_count": self.metrics.sell_count,
                "buy_volume_sol": self.metrics.buy_volume_sol,
                "sell_volume_sol": self.metrics.sell_volume_sol,
                "buy_sell_ratio": self.metrics.buy_sell_ratio,
                "net_sol_inflow": self.metrics.net_sol_inflow,
                "unique_buyers": self.metrics.unique_buyers,
                "unique_sellers": self.metrics.unique_sellers,
                "trade_velocity": self.metrics.trade_velocity,
            },
        }


class TokenOrderFlowTracker:
    """Maintains rolling trade history and calculates order flow metrics for a single token."""

    __slots__ = ("mint", "max_retention_seconds", "trades", "last_trade_time")

    def __init__(self, mint: str, max_retention_seconds: int = 600) -> None:
        self.mint = mint
        self.max_retention_seconds = max_retention_seconds
        self.trades: deque[TradeRecord] = deque()
        self.last_trade_time: float = 0.0

    def record_trade(
        self,
        is_buy: bool,
        sol_amount: float,
        user: str,
        timestamp: Optional[float] = None,
    ) -> TradeRecord:
        """Record a single trade and evict expired records beyond max retention."""
        ts = float(timestamp if timestamp is not None else time.time())
        record = TradeRecord(
            mint=self.mint,
            is_buy=is_buy,
            sol_amount=float(sol_amount),
            user=user,
            timestamp=ts,
        )
        self.trades.append(record)
        if ts > self.last_trade_time:
            self.last_trade_time = ts

        # Evict trades older than max retention relative to current trade timestamp
        self.prune_older_than(ts - self.max_retention_seconds)
        return record

    def prune_older_than(self, cutoff_timestamp: float) -> None:
        """Evict trades older than the specified timestamp cutoff."""
        while self.trades and self.trades[0].timestamp < cutoff_timestamp:
            self.trades.popleft()

    def get_window_metrics(
        self,
        window_seconds: int = 30,
        current_time: Optional[float] = None,
    ) -> WindowMetrics:
        """Compute rolling order flow metrics over the specified window in seconds."""
        now = float(current_time if current_time is not None else (self.last_trade_time or time.time()))
        cutoff = now - max(window_seconds, 1)

        trade_count = 0
        buy_count = 0
        sell_count = 0
        buy_volume_sol = 0.0
        sell_volume_sol = 0.0
        unique_buyers: set[str] = set()
        unique_sellers: set[str] = set()

        for trade in reversed(self.trades):
            if trade.timestamp < cutoff:
                break
            trade_count += 1
            if trade.is_buy:
                buy_count += 1
                buy_volume_sol += trade.sol_amount
                unique_buyers.add(trade.user)
            else:
                sell_count += 1
                sell_volume_sol += trade.sol_amount
                unique_sellers.add(trade.user)

        buy_vol_rounded = round(buy_volume_sol, 6)
        sell_vol_rounded = round(sell_volume_sol, 6)
        net_inflow = round(buy_vol_rounded - sell_vol_rounded, 6)

        if sell_vol_rounded > 0.0:
            buy_sell_ratio = round(buy_vol_rounded / sell_vol_rounded, 4)
        elif buy_vol_rounded > 0.0:
            buy_sell_ratio = 999.0
        else:
            buy_sell_ratio = 0.0

        effective_duration = float(max(window_seconds, 1))
        trade_velocity = round(trade_count / effective_duration, 4)

        return WindowMetrics(
            window_seconds=window_seconds,
            trade_count=trade_count,
            buy_count=buy_count,
            sell_count=sell_count,
            buy_volume_sol=buy_vol_rounded,
            sell_volume_sol=sell_vol_rounded,
            buy_sell_ratio=buy_sell_ratio,
            net_sol_inflow=net_inflow,
            unique_buyers=len(unique_buyers),
            unique_sellers=len(unique_sellers),
            trade_velocity=trade_velocity,
        )

    def get_velocity_z_score(
        self,
        window_seconds: int = 30,
        baseline_window_seconds: int = 300,
        current_time: Optional[float] = None,
    ) -> float:
        """Compute statistical trade velocity Z-score against a longer rolling baseline window."""
        now = float(current_time if current_time is not None else (self.last_trade_time or time.time()))
        slice_size = max(window_seconds, 1)
        total_baseline = max(baseline_window_seconds, slice_size)
        num_slices = max(int(total_baseline / slice_size), 2)
        baseline_duration = num_slices * slice_size
        cutoff = now - baseline_duration

        # Compute velocity for each slice in the baseline window
        # Slice 0 is the most recent [now - slice_size, now]
        slice_counts = [0] * num_slices

        for trade in reversed(self.trades):
            if trade.timestamp < cutoff:
                break
            # Calculate which slice this trade falls into
            offset = now - trade.timestamp
            if offset < 0.0:
                slice_idx = 0
            else:
                slice_idx = int(offset // slice_size)
            if 0 <= slice_idx < num_slices:
                slice_counts[slice_idx] += 1

        slice_velocities = [count / float(slice_size) for count in slice_counts]
        current_velocity = slice_velocities[0]

        mean_velocity = sum(slice_velocities) / float(num_slices)
        variance = sum((v - mean_velocity) ** 2 for v in slice_velocities) / float(num_slices)
        std_dev = math.sqrt(variance)

        if std_dev > 1e-6:
            z_score = (current_velocity - mean_velocity) / std_dev
        else:
            if current_velocity > mean_velocity:
                z_score = 999.0
            else:
                z_score = 0.0

        return round(z_score, 4)

    def evaluate_momentum_signal(
        self,
        window_seconds: int = 30,
        min_buy_ratio: float = 3.0,
        min_z_score: float = 2.5,
        min_unique_buyers: int = 3,
        min_net_inflow_sol: float = 0.5,
        baseline_window_seconds: int = 300,
        token_creation_timestamp: Optional[float] = None,
        max_token_age_seconds: Optional[int] = None,
        current_time: Optional[float] = None,
    ) -> MomentumSignal:
        """Evaluate whether token order flow meets momentum breakout entry criteria."""
        now = float(current_time if current_time is not None else (self.last_trade_time or time.time()))

        metrics = self.get_window_metrics(window_seconds=window_seconds, current_time=now)
        z_score = self.get_velocity_z_score(
            window_seconds=window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            current_time=now,
        )

        if token_creation_timestamp is not None and max_token_age_seconds is not None:
            token_age = now - float(token_creation_timestamp)
            if token_age > max_token_age_seconds:
                return MomentumSignal(
                    triggered=False,
                    mint=self.mint,
                    z_score=z_score,
                    buy_sell_ratio=metrics.buy_sell_ratio,
                    net_sol_inflow=metrics.net_sol_inflow,
                    unique_buyers=metrics.unique_buyers,
                    trade_velocity=metrics.trade_velocity,
                    metrics=metrics,
                    reason=f"token_age_exceeded_{token_age:.1f}s_max_{max_token_age_seconds}s",
                )

        if metrics.trade_count == 0:
            return MomentumSignal(
                triggered=False,
                mint=self.mint,
                z_score=0.0,
                buy_sell_ratio=0.0,
                net_sol_inflow=0.0,
                unique_buyers=0,
                trade_velocity=0.0,
                metrics=metrics,
                reason="no_trades_in_window",
            )

        failed_reasons = []
        if z_score < min_z_score:
            failed_reasons.append(f"z_score_{z_score:.2f}_below_{min_z_score:.2f}")
        if metrics.buy_sell_ratio < min_buy_ratio:
            failed_reasons.append(f"buy_ratio_{metrics.buy_sell_ratio:.2f}_below_{min_buy_ratio:.2f}")
        if metrics.unique_buyers < min_unique_buyers:
            failed_reasons.append(f"unique_buyers_{metrics.unique_buyers}_below_{min_unique_buyers}")
        if metrics.net_sol_inflow < min_net_inflow_sol:
            failed_reasons.append(f"net_inflow_{metrics.net_sol_inflow:.2f}_below_{min_net_inflow_sol:.2f}")

        triggered = len(failed_reasons) == 0
        reason = "momentum_spike" if triggered else "; ".join(failed_reasons)

        return MomentumSignal(
            triggered=triggered,
            mint=self.mint,
            z_score=z_score,
            buy_sell_ratio=metrics.buy_sell_ratio,
            net_sol_inflow=metrics.net_sol_inflow,
            unique_buyers=metrics.unique_buyers,
            trade_velocity=metrics.trade_velocity,
            metrics=metrics,
            reason=reason,
        )


class OrderFlowEngine:
    """Multi-token order flow engine managing sliding windows, metrics, and momentum triggers."""

    def __init__(
        self,
        max_retention_seconds: int = 600,
        recent_token_ttl_seconds: int = 600,
    ) -> None:
        self.max_retention_seconds = max_retention_seconds
        self.recent_token_ttl_seconds = recent_token_ttl_seconds
        self._trackers: dict[str, TokenOrderFlowTracker] = {}

    @property
    def tracked_token_count(self) -> int:
        """Number of active token trackers in memory."""
        return len(self._trackers)

    def get_or_create_tracker(self, mint: str) -> TokenOrderFlowTracker:
        """Get or initialize tracker for a token mint."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            tracker = TokenOrderFlowTracker(mint=mint, max_retention_seconds=self.max_retention_seconds)
            self._trackers[mint] = tracker
        return tracker

    def record_trade(
        self,
        mint: str,
        is_buy: bool,
        sol_amount: float,
        user: str,
        timestamp: Optional[float] = None,
    ) -> TradeRecord:
        """Record a trade event for the specified token mint."""
        tracker = self.get_or_create_tracker(mint)
        return tracker.record_trade(
            is_buy=is_buy,
            sol_amount=sol_amount,
            user=user,
            timestamp=timestamp,
        )

    def get_metrics(
        self,
        mint: str,
        window_seconds: int = 30,
        current_time: Optional[float] = None,
    ) -> WindowMetrics:
        """Retrieve rolling order flow metrics for a token."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            return WindowMetrics(
                window_seconds=window_seconds,
                trade_count=0,
                buy_count=0,
                sell_count=0,
                buy_volume_sol=0.0,
                sell_volume_sol=0.0,
                buy_sell_ratio=0.0,
                net_sol_inflow=0.0,
                unique_buyers=0,
                unique_sellers=0,
                trade_velocity=0.0,
            )
        return tracker.get_window_metrics(window_seconds=window_seconds, current_time=current_time)

    def get_velocity_z_score(
        self,
        mint: str,
        window_seconds: int = 30,
        baseline_window_seconds: int = 300,
        current_time: Optional[float] = None,
    ) -> float:
        """Compute trade velocity Z-score for a token."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            return 0.0
        return tracker.get_velocity_z_score(
            window_seconds=window_seconds,
            baseline_window_seconds=baseline_window_seconds,
            current_time=current_time,
        )

    def evaluate_momentum_signal(
        self,
        mint: str,
        window_seconds: int = 30,
        min_buy_ratio: float = 3.0,
        min_z_score: float = 2.5,
        min_unique_buyers: int = 3,
        min_net_inflow_sol: float = 0.5,
        baseline_window_seconds: int = 300,
        token_creation_timestamp: Optional[float] = None,
        max_token_age_seconds: Optional[int] = None,
        current_time: Optional[float] = None,
    ) -> MomentumSignal:
        """Evaluate momentum breakout criteria for a token."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            metrics = WindowMetrics(
                window_seconds=window_seconds,
                trade_count=0,
                buy_count=0,
                sell_count=0,
                buy_volume_sol=0.0,
                sell_volume_sol=0.0,
                buy_sell_ratio=0.0,
                net_sol_inflow=0.0,
                unique_buyers=0,
                unique_sellers=0,
                trade_velocity=0.0,
            )
            return MomentumSignal(
                triggered=False,
                mint=mint,
                z_score=0.0,
                buy_sell_ratio=0.0,
                net_sol_inflow=0.0,
                unique_buyers=0,
                trade_velocity=0.0,
                metrics=metrics,
                reason="token_not_tracked",
            )

        return tracker.evaluate_momentum_signal(
            window_seconds=window_seconds,
            min_buy_ratio=min_buy_ratio,
            min_z_score=min_z_score,
            min_unique_buyers=min_unique_buyers,
            min_net_inflow_sol=min_net_inflow_sol,
            baseline_window_seconds=baseline_window_seconds,
            token_creation_timestamp=token_creation_timestamp,
            max_token_age_seconds=max_token_age_seconds,
            current_time=current_time,
        )

    def cleanup_inactive_tokens(
        self,
        ttl_seconds: Optional[int] = None,
        current_time: Optional[float] = None,
    ) -> int:
        """Evict tokens that have had no trade activity within the TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.recent_token_ttl_seconds
        now = float(current_time if current_time is not None else time.time())
        cutoff = now - ttl

        inactive_mints = [
            mint
            for mint, tracker in self._trackers.items()
            if tracker.last_trade_time < cutoff
        ]
        for mint in inactive_mints:
            del self._trackers[mint]

        return len(inactive_mints)

    def clear(self) -> None:
        """Clear all tracked tokens."""
        self._trackers.clear()


__all__ = [
    "TradeRecord",
    "WindowMetrics",
    "MomentumSignal",
    "TokenOrderFlowTracker",
    "OrderFlowEngine",
]
