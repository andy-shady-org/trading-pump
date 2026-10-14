"""Real-time Raydium migration and graduation momentum engine for Pump.fun tokens.

This module monitors bonding curve SOL accumulation, flags tokens approaching
graduation (~85 SOL in real reserves or ~95% curve progress), tracks on-chain
completion events, and stores Raydium AMM v4 liquidity pool keys for rapid
post-migration sniping.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


@dataclass(slots=True)
class RaydiumPoolKeys:
    """Raydium AMM v4 pool account keys and OpenBook / Serum market state."""

    amm_id: str
    amm_authority: str
    amm_open_orders: str
    amm_target_orders: str
    pool_coin_token_account: str
    pool_pc_token_account: str
    serum_program_id: str
    serum_market: str
    serum_bids: str
    serum_asks: str
    serum_event_queue: str
    serum_coin_vault: str
    serum_pc_vault: str
    serum_vault_signer: str
    coin_mint: str
    pc_mint: str
    lp_mint: str

    def to_dict(self) -> dict[str, str]:
        """Convert pool keys to a dictionary."""
        return {
            "amm_id": self.amm_id,
            "amm_authority": self.amm_authority,
            "amm_open_orders": self.amm_open_orders,
            "amm_target_orders": self.amm_target_orders,
            "pool_coin_token_account": self.pool_coin_token_account,
            "pool_pc_token_account": self.pool_pc_token_account,
            "serum_program_id": self.serum_program_id,
            "serum_market": self.serum_market,
            "serum_bids": self.serum_bids,
            "serum_asks": self.serum_asks,
            "serum_event_queue": self.serum_event_queue,
            "serum_coin_vault": self.serum_coin_vault,
            "serum_pc_vault": self.serum_pc_vault,
            "serum_vault_signer": self.serum_vault_signer,
            "coin_mint": self.coin_mint,
            "pc_mint": self.pc_mint,
            "lp_mint": self.lp_mint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RaydiumPoolKeys:
        """Construct RaydiumPoolKeys from a dictionary."""
        return cls(
            amm_id=str(data.get("amm_id", "")),
            amm_authority=str(data.get("amm_authority", "")),
            amm_open_orders=str(data.get("amm_open_orders", "")),
            amm_target_orders=str(data.get("amm_target_orders", "")),
            pool_coin_token_account=str(data.get("pool_coin_token_account", "")),
            pool_pc_token_account=str(data.get("pool_pc_token_account", "")),
            serum_program_id=str(data.get("serum_program_id", "")),
            serum_market=str(data.get("serum_market", "")),
            serum_bids=str(data.get("serum_bids", "")),
            serum_asks=str(data.get("serum_asks", "")),
            serum_event_queue=str(data.get("serum_event_queue", "")),
            serum_coin_vault=str(data.get("serum_coin_vault", "")),
            serum_pc_vault=str(data.get("serum_pc_vault", "")),
            serum_vault_signer=str(data.get("serum_vault_signer", "")),
            coin_mint=str(data.get("coin_mint", "")),
            pc_mint=str(data.get("pc_mint", "")),
            lp_mint=str(data.get("lp_mint", "")),
        )


@dataclass(slots=True)
class GraduationCandidate:
    """State tracking for a token bonding curve approaching or undergoing graduation."""

    mint: str
    bonding_curve: str
    real_sol_reserves: float
    virtual_sol_reserves: float
    market_cap_sol: float
    progress_pct: float
    is_completed: bool = False
    completed_at: float = 0.0
    raydium_pool_id: Optional[str] = None
    pool_keys: Optional[RaydiumPoolKeys] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert graduation candidate state to dictionary for auditing."""
        return {
            "mint": self.mint,
            "bonding_curve": self.bonding_curve,
            "real_sol_reserves": self.real_sol_reserves,
            "virtual_sol_reserves": self.virtual_sol_reserves,
            "market_cap_sol": self.market_cap_sol,
            "progress_pct": self.progress_pct,
            "is_completed": self.is_completed,
            "completed_at": self.completed_at,
            "raydium_pool_id": self.raydium_pool_id,
            "pool_keys": self.pool_keys.to_dict() if self.pool_keys else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class GraduationTrajectory:
    """Classified trajectory and acceleration dynamics for a bonding curve nearing graduation."""

    mint: str
    progress_pct: float
    acceleration_sol_per_sec2: float
    velocity_sol_per_sec: float
    trajectory_type: str  # "organic" | "syndicate_sweep" | "exhaustion"
    recommended_action: str  # "pre_grad_entry" | "hold" | "stage_exit" | "avoid"
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraduationSignal:
    """Evaluation result for graduation momentum or Raydium migration sniping."""

    triggered: bool
    mint: str
    stage: str  # "pre_graduation" | "graduated" | "raydium_pool_ready" | "none"
    market_cap_sol: float
    real_sol_reserves: float
    pool_keys: Optional[RaydiumPoolKeys] = None
    reason: str = ""
    trajectory: Optional[GraduationTrajectory] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert graduation signal to dictionary for telemetry and logging."""
        return {
            "triggered": self.triggered,
            "mint": self.mint,
            "stage": self.stage,
            "market_cap_sol": self.market_cap_sol,
            "real_sol_reserves": self.real_sol_reserves,
            "pool_keys": self.pool_keys.to_dict() if self.pool_keys else None,
            "reason": self.reason,
            "trajectory": (
                {
                    "progress_pct": self.trajectory.progress_pct,
                    "acceleration": self.trajectory.acceleration_sol_per_sec2,
                    "velocity": self.trajectory.velocity_sol_per_sec,
                    "type": self.trajectory.trajectory_type,
                    "action": self.trajectory.recommended_action,
                }
                if self.trajectory
                else None
            ),
        }


class GraduationTracker:
    """Manages lifecycle, reserve transitions, and Raydium pool state for a single token."""

    __slots__ = ("candidate", "target_graduation_sol", "_history")

    def __init__(
        self,
        mint: str,
        bonding_curve: str = "",
        real_sol_reserves: float = 0.0,
        virtual_sol_reserves: float = 30.0,
        market_cap_sol: float = 30.0,
        target_graduation_sol: float = 85.0,
        timestamp: Optional[float] = None,
    ) -> None:
        self.target_graduation_sol = max(target_graduation_sol, 1.0)
        now = float(timestamp if timestamp is not None else time.time())
        progress_pct = round(
            min(100.0, (real_sol_reserves / self.target_graduation_sol) * 100.0), 2
        )
        self.candidate = GraduationCandidate(
            mint=mint,
            bonding_curve=bonding_curve,
            real_sol_reserves=real_sol_reserves,
            virtual_sol_reserves=virtual_sol_reserves,
            market_cap_sol=market_cap_sol,
            progress_pct=progress_pct,
            created_at=now,
            updated_at=now,
        )
        self._history: deque[Tuple[float, float]] = deque(maxlen=50)
        self._history.append((now, float(real_sol_reserves)))

    def update_reserves(
        self,
        real_sol_reserves: float,
        virtual_sol_reserves: float,
        market_cap_sol: float,
        bonding_curve: str = "",
        complete: bool = False,
        timestamp: Optional[float] = None,
    ) -> GraduationCandidate:
        """Update bonding curve reserve levels and progress percentage."""
        now = float(timestamp if timestamp is not None else time.time())
        real_sol = max(0.0, float(real_sol_reserves))
        self.candidate.real_sol_reserves = real_sol
        self.candidate.virtual_sol_reserves = float(virtual_sol_reserves)
        self.candidate.market_cap_sol = float(market_cap_sol)
        if bonding_curve:
            self.candidate.bonding_curve = bonding_curve
        self.candidate.progress_pct = round(
            min(100.0, (real_sol / self.target_graduation_sol) * 100.0), 2
        )
        self.candidate.updated_at = now
        self._history.append((now, real_sol))
        if complete and not self.candidate.is_completed:
            self.candidate.is_completed = True
            self.candidate.completed_at = now
        return self.candidate

    def calculate_acceleration(
        self, window_seconds: float = 30.0, current_time: Optional[float] = None
    ) -> tuple[float, float]:
        """Compute SOL inflow velocity (SOL/s) and reserve accumulation acceleration (SOL/s^2)."""
        now = float(current_time if current_time is not None else time.time())
        cutoff = now - max(1.0, float(window_seconds))
        pts = [(t, s) for t, s in self._history if t >= cutoff]
        if len(pts) < 2:
            return (0.0, 0.0)

        dt_total = pts[-1][0] - pts[0][0]
        if dt_total <= 1e-4:
            return (0.0, 0.0)

        overall_velocity = (pts[-1][1] - pts[0][1]) / dt_total

        if len(pts) < 3:
            return (overall_velocity, 0.0)

        mid_idx = len(pts) // 2
        p_first_half = pts[: mid_idx + 1]
        p_second_half = pts[mid_idx:]

        dt1 = p_first_half[-1][0] - p_first_half[0][0]
        dt2 = p_second_half[-1][0] - p_second_half[0][0]

        v1 = (
            (p_first_half[-1][1] - p_first_half[0][1]) / dt1
            if dt1 > 1e-4
            else overall_velocity
        )
        v2 = (
            (p_second_half[-1][1] - p_second_half[0][1]) / dt2
            if dt2 > 1e-4
            else overall_velocity
        )

        dt_mid = ((p_second_half[0][0] + p_second_half[-1][0]) / 2.0) - (
            (p_first_half[0][0] + p_first_half[-1][0]) / 2.0
        )
        acceleration = (v2 - v1) / dt_mid if dt_mid > 1e-4 else 0.0

        return (float(overall_velocity), float(acceleration))

    def classify_trajectory(
        self, current_time: Optional[float] = None, unique_buyers: int = 1
    ) -> GraduationTrajectory:
        """Classify bonding curve trajectory as organic, syndicate sweep, or volume exhaustion."""
        velocity, accel = self.calculate_acceleration(
            window_seconds=30.0, current_time=current_time
        )
        progress = self.candidate.progress_pct

        if (velocity < -0.01 or accel < -0.05) and progress < 88.0:
            traj_type = "exhaustion"
            rec_action = "avoid"
        elif velocity > 3.0 and unique_buyers <= 1:
            traj_type = "syndicate_sweep"
            rec_action = "stage_exit" if progress >= 90.0 else "pre_grad_entry"
        elif accel >= 0.0 and progress >= 65.0:
            traj_type = "organic"
            rec_action = "pre_grad_entry" if progress <= 88.0 else "stage_exit"
        else:
            traj_type = "organic"
            rec_action = "hold"

        return GraduationTrajectory(
            mint=self.candidate.mint,
            progress_pct=progress,
            acceleration_sol_per_sec2=accel,
            velocity_sol_per_sec=velocity,
            trajectory_type=traj_type,
            recommended_action=rec_action,
            metrics={
                "velocity": velocity,
                "acceleration": accel,
                "real_sol_reserves": self.candidate.real_sol_reserves,
            },
        )

    def mark_completed(self, timestamp: Optional[float] = None) -> GraduationCandidate:
        """Mark bonding curve as graduated/completed."""
        now = float(timestamp if timestamp is not None else time.time())
        self.candidate.is_completed = True
        self.candidate.progress_pct = 100.0
        if not self.candidate.completed_at:
            self.candidate.completed_at = now
        self.candidate.updated_at = now
        return self.candidate

    def set_raydium_pool(
        self, pool_keys: RaydiumPoolKeys, timestamp: Optional[float] = None
    ) -> GraduationCandidate:
        """Associate Raydium AMM v4 pool keys with the candidate."""
        now = float(timestamp if timestamp is not None else time.time())
        self.candidate.pool_keys = pool_keys
        self.candidate.raydium_pool_id = pool_keys.amm_id
        self.candidate.updated_at = now
        return self.candidate

    def evaluate_signal(
        self,
        pre_migration_threshold_sol: float = 80.0,
        require_pool_ready: bool = False,
        current_time: Optional[float] = None,
    ) -> GraduationSignal:
        """Evaluate graduation signal against configured criteria."""
        cand = self.candidate

        # 1. Check if Raydium pool is ready
        if cand.pool_keys is not None:
            return GraduationSignal(
                triggered=True,
                mint=cand.mint,
                stage="raydium_pool_ready",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                pool_keys=cand.pool_keys,
                reason="raydium_pool_initialized",
            )

        # If pool ready is strictly required but pool not ready yet:
        if require_pool_ready:
            stage = "graduated" if cand.is_completed else "pre_graduation"
            return GraduationSignal(
                triggered=False,
                mint=cand.mint,
                stage=stage,
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                pool_keys=None,
                reason="awaiting_raydium_pool",
            )

        # 2. Check if bonding curve completed
        if cand.is_completed:
            return GraduationSignal(
                triggered=True,
                mint=cand.mint,
                stage="graduated",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                pool_keys=None,
                reason="bonding_curve_completed",
            )

        # 3. Check if pre-migration threshold reached
        if cand.real_sol_reserves >= pre_migration_threshold_sol:
            return GraduationSignal(
                triggered=True,
                mint=cand.mint,
                stage="pre_graduation",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                pool_keys=None,
                reason=f"pre_migration_reserves_{cand.real_sol_reserves:.2f}_ge_{pre_migration_threshold_sol:.2f}",
            )

        return GraduationSignal(
            triggered=False,
            mint=cand.mint,
            stage="none",
            market_cap_sol=cand.market_cap_sol,
            real_sol_reserves=cand.real_sol_reserves,
            pool_keys=None,
            reason=f"reserves_{cand.real_sol_reserves:.2f}_below_{pre_migration_threshold_sol:.2f}",
        )


class GraduationEngine:
    """Multi-token graduation and Raydium migration tracker engine."""

    def __init__(
        self,
        target_graduation_sol: float = 85.0,
        candidate_ttl_seconds: int = 1800,
        pre_migration_threshold_sol: float = 80.0,
    ) -> None:
        self.target_graduation_sol = target_graduation_sol
        self.candidate_ttl_seconds = candidate_ttl_seconds
        self.pre_migration_threshold_sol = pre_migration_threshold_sol
        self._trackers: dict[str, GraduationTracker] = {}

    @property
    def tracked_candidate_count(self) -> int:
        """Total number of tracked graduation candidates in memory."""
        return len(self._trackers)

    def get_or_create_tracker(
        self,
        mint: str,
        bonding_curve: str = "",
        real_sol_reserves: float = 0.0,
        virtual_sol_reserves: float = 30.0,
        market_cap_sol: float = 30.0,
        timestamp: Optional[float] = None,
    ) -> GraduationTracker:
        """Retrieve existing tracker or initialize a new one for token mint."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            tracker = GraduationTracker(
                mint=mint,
                bonding_curve=bonding_curve,
                real_sol_reserves=real_sol_reserves,
                virtual_sol_reserves=virtual_sol_reserves,
                market_cap_sol=market_cap_sol,
                target_graduation_sol=self.target_graduation_sol,
                timestamp=timestamp,
            )
            self._trackers[mint] = tracker
        return tracker

    def update_bonding_curve(
        self,
        mint: str,
        bonding_curve: str,
        real_sol_reserves: float,
        virtual_sol_reserves: float,
        market_cap_sol: float,
        complete: bool = False,
        timestamp: Optional[float] = None,
    ) -> GraduationCandidate:
        """Update candidate reserves and return the updated candidate state."""
        tracker = self.get_or_create_tracker(
            mint=mint,
            bonding_curve=bonding_curve,
            real_sol_reserves=real_sol_reserves,
            virtual_sol_reserves=virtual_sol_reserves,
            market_cap_sol=market_cap_sol,
            timestamp=timestamp,
        )
        return tracker.update_reserves(
            real_sol_reserves=real_sol_reserves,
            virtual_sol_reserves=virtual_sol_reserves,
            market_cap_sol=market_cap_sol,
            bonding_curve=bonding_curve,
            complete=complete,
            timestamp=timestamp,
        )

    def record_complete_event(
        self,
        mint: str,
        bonding_curve: str = "",
        timestamp: Optional[float] = None,
    ) -> GraduationCandidate:
        """Record bonding curve completion event."""
        tracker = self.get_or_create_tracker(
            mint=mint,
            bonding_curve=bonding_curve,
            timestamp=timestamp,
        )
        return tracker.mark_completed(timestamp=timestamp)

    def record_graduation(
        self,
        mint: str,
        bonding_curve: str = "",
        timestamp: Optional[float] = None,
    ) -> GraduationCandidate:
        """Alias for record_complete_event."""
        return self.record_complete_event(
            mint=mint,
            bonding_curve=bonding_curve,
            timestamp=timestamp,
        )

    def record_raydium_pool(
        self,
        mint: str,
        pool_keys: RaydiumPoolKeys,
        timestamp: Optional[float] = None,
    ) -> GraduationCandidate:
        """Associate discovered Raydium AMM v4 pool keys with the candidate."""
        tracker = self.get_or_create_tracker(
            mint=mint,
            timestamp=timestamp,
        )
        return tracker.set_raydium_pool(pool_keys=pool_keys, timestamp=timestamp)

    def evaluate_graduation_signal(
        self,
        mint: str,
        pre_migration_threshold_sol: Optional[float] = None,
        require_pool_ready: bool = False,
        current_time: Optional[float] = None,
    ) -> GraduationSignal:
        """Evaluate graduation signal for a given token mint."""
        tracker = self._trackers.get(mint)
        threshold = (
            pre_migration_threshold_sol
            if pre_migration_threshold_sol is not None
            else self.pre_migration_threshold_sol
        )
        if tracker is None:
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="none",
                market_cap_sol=0.0,
                real_sol_reserves=0.0,
                pool_keys=None,
                reason="candidate_not_tracked",
            )
        return tracker.evaluate_signal(
            pre_migration_threshold_sol=threshold,
            require_pool_ready=require_pool_ready,
            current_time=current_time,
        )

    def evaluate_graduation_trajectory(
        self,
        mint: str,
        current_time: Optional[float] = None,
        unique_buyers: int = 1,
    ) -> Optional[GraduationTrajectory]:
        """Classify and return graduation trajectory for token mint."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            return None
        return tracker.classify_trajectory(
            current_time=current_time, unique_buyers=unique_buyers
        )

    def evaluate_pre_graduation_harvesting_entry(
        self,
        mint: str,
        *,
        min_progress_pct: float = 70.0,
        max_progress_pct: float = 85.0,
        min_acceleration: float = 0.0,
        current_time: Optional[float] = None,
        unique_buyers: int = 1,
    ) -> GraduationSignal:
        """Evaluate pre-graduation acceleration harvesting entry signal."""
        tracker = self._trackers.get(mint)
        if tracker is None:
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="none",
                market_cap_sol=0.0,
                real_sol_reserves=0.0,
                pool_keys=None,
                reason="candidate_not_tracked",
            )

        trajectory = tracker.classify_trajectory(
            current_time=current_time, unique_buyers=unique_buyers
        )
        cand = tracker.candidate

        if cand.is_completed or cand.pool_keys is not None:
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="graduated" if cand.is_completed else "raydium_pool_ready",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                pool_keys=cand.pool_keys,
                reason="already_graduated",
                trajectory=trajectory,
            )

        if trajectory.trajectory_type == "exhaustion":
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="pre_graduation",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                reason="rejected_trajectory_exhaustion",
                trajectory=trajectory,
            )

        if not (min_progress_pct <= cand.progress_pct <= max_progress_pct):
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="pre_graduation",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                reason=f"progress_outside_window ({cand.progress_pct:.1f}% not in [{min_progress_pct:.1f}%, {max_progress_pct:.1f}%])",
                trajectory=trajectory,
            )

        if trajectory.acceleration_sol_per_sec2 < min_acceleration:
            return GraduationSignal(
                triggered=False,
                mint=mint,
                stage="pre_graduation",
                market_cap_sol=cand.market_cap_sol,
                real_sol_reserves=cand.real_sol_reserves,
                reason=f"insufficient_acceleration ({trajectory.acceleration_sol_per_sec2:.4f} < {min_acceleration:.4f})",
                trajectory=trajectory,
            )

        return GraduationSignal(
            triggered=True,
            mint=mint,
            stage="pre_graduation",
            market_cap_sol=cand.market_cap_sol,
            real_sol_reserves=cand.real_sol_reserves,
            reason=f"pre_graduation_acceleration_surge (progress={cand.progress_pct:.1f}%, a={trajectory.acceleration_sol_per_sec2:.4f})",
            trajectory=trajectory,
        )

    def get_candidate(self, mint: str) -> Optional[GraduationCandidate]:
        """Get candidate state by mint address."""
        tracker = self._trackers.get(mint)
        return tracker.candidate if tracker else None

    def get_all_candidates(
        self, include_completed: bool = True
    ) -> list[GraduationCandidate]:
        """Return list of all tracked candidates."""
        if include_completed:
            return [t.candidate for t in self._trackers.values()]
        return [
            t.candidate for t in self._trackers.values() if not t.candidate.is_completed
        ]

    def cleanup_expired_candidates(
        self,
        ttl_seconds: Optional[int] = None,
        current_time: Optional[float] = None,
    ) -> int:
        """Remove candidates that have had no updates within the TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.candidate_ttl_seconds
        now = float(current_time if current_time is not None else time.time())
        cutoff = now - ttl

        expired_mints = [
            mint
            for mint, tracker in self._trackers.items()
            if tracker.candidate.updated_at < cutoff
        ]
        for mint in expired_mints:
            del self._trackers[mint]

        return len(expired_mints)

    def clear(self) -> None:
        """Clear all tracked candidates."""
        self._trackers.clear()


__all__ = [
    "GraduationCandidate",
    "RaydiumPoolKeys",
    "GraduationSignal",
    "GraduationTracker",
    "GraduationTrajectory",
    "GraduationEngine",
]
