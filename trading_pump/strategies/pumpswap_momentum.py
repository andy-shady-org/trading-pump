"""The ``pumpswap_momentum`` lane (FEAT-76): buy graduates that keep rising.

The one signal that did not lose in rc.5 to rc.8 (STRATEGY-PIVOT.md §6.13):
a coin that has just graduated to PumpSwap and is still at least 1.1-1.2x
its first pool price 60-120 s after the migration, bought at the next
reading, out at 1.2x (stop 0.85). On 16.6 h of rc.8 data that was +1.3% to
+5.7% per trade at 2% cost a side in both halves, but n = 42-72 and every
90% interval included 0, so the lane runs on paper with a pre-registered
verdict before anything else.

The pipeline follows trading-core's Scout -> Filters -> Analyst shape:

* :class:`GraduationScout` proposes each graduate once, when its signal
  reading (the first at or after ``signal_after_seconds``) is in;
* :class:`StandardPoolFilter` keeps standard graduations (first market cap
  0.5-2x of 410.88 SOL, a pool that is not drained, ``min_pool_sol``);
* :class:`ScreeningFilter` (off by default, ``lane.screen_entries``) runs
  the anti-rug screen on the graduate;
* :class:`MomentumAnalyst` signals when the signal price is at least
  ``min_ratio`` times the first, with a limit ``slippage_bps`` above it.

Exits are trading-core's generic rules (``exits`` in the engine settings:
``take_profit_pct`` 0.2, ``stop_loss_pct`` 0.15, ``max_hold_seconds``),
marked on the same pool reads. Every candidate's metrics (rejected ones
included, as ``screening`` events) are recorded so ``trading-core-audit
cuts`` can test any refinement against a random cut afterwards.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from trading_core.strategy.pipeline import (
    Analyst,
    Candidate,
    Filter,
    Scout,
    Screening,
    Signal,
    StrategyPipeline,
)

from trading_pump.config.settings import ExecutionSettings, LaneSettings
from trading_pump.graduates import Graduate, GraduateTracker
from trading_pump.strategies.enrichment import TokenEnricher

LANE = "pumpswap_momentum"


def candidate_metrics(graduate: Graduate, now: float) -> dict[str, Any]:
    """What the lane decided on, recorded on the candidate and the buy."""
    first = graduate.first
    signal = graduate.signal_reading
    metrics: dict[str, Any] = {
        "lane": LANE,
        "migrated_at": graduate.migrated_at,
        "age_seconds": round(graduate.age(now), 1),
    }
    if first is not None:
        metrics.update(
            first_market_cap_sol=round(first.market_cap_sol, 6),
            first_pool_sol=round(first.pool_sol, 9),
            first_reading_delay_seconds=round(first.at - graduate.migrated_at, 1),
        )
    if signal is not None:
        ratio = graduate.ratio(signal)
        metrics.update(
            signal_market_cap_sol=round(signal.market_cap_sol, 6),
            signal_pool_sol=round(signal.pool_sol, 9),
            signal_price=signal.price,
            signal_delay_seconds=round(signal.at - graduate.migrated_at, 1),
            ratio=None if ratio is None else round(ratio, 6),
        )
    return metrics


class GraduationScout(Scout):
    """Each graduate once, when its signal reading has arrived."""

    name = "graduations"

    def __init__(
        self,
        tracker: GraduateTracker,
        settings: LaneSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.tracker = tracker
        self.settings = settings
        self.clock = clock
        self.stats: dict[str, int] = {}

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    async def discover(self) -> Sequence[Candidate]:
        now = self.clock()
        found: list[Candidate] = []
        for graduate in list(self.tracker.graduates.values()):
            if graduate.decided:
                continue
            signal = graduate.signal_reading
            if signal is None or graduate.signal_time is None:
                if (
                    graduate.signal_time is not None
                    and now
                    > graduate.signal_time + float(self.settings.signal_window_seconds)
                ):
                    graduate.decided = True
                    self._count("no_reading_in_window")
                continue
            graduate.decided = True
            if signal.at - graduate.signal_time > float(
                self.settings.signal_window_seconds
            ):
                self._count("reading_too_late")
                continue
            self._count("proposed")
            found.append(
                Candidate(
                    graduate.mint,
                    source=self.name,
                    data=candidate_metrics(graduate, now),
                )
            )
        return found


class StandardPoolFilter(Filter):
    """Standard graduations only: a first market cap near 410.88 SOL, a live pool."""

    name = "standard_pool"

    def __init__(self, tracker: GraduateTracker, settings: LaneSettings) -> None:
        self.tracker = tracker
        self.settings = settings

    async def screen(self, candidate: Candidate) -> Screening:
        graduate = self.tracker.get(candidate.instrument_id)
        if (
            graduate is None
            or graduate.first is None
            or graduate.signal_reading is None
        ):
            return Screening.reject("no pool readings")
        first = graduate.first.market_cap_sol
        if not (
            self.settings.first_market_cap_min_sol
            <= first
            <= self.settings.first_market_cap_max_sol
        ):
            return Screening.reject(
                f"first market cap {first:.1f} SOL outside "
                f"{self.settings.first_market_cap_min_sol:.1f}-"
                f"{self.settings.first_market_cap_max_sol:.1f}",
                first_market_cap_sol=round(first, 6),
            )
        signal = graduate.signal_reading
        if signal.drained:
            return Screening.reject("pool drained")
        if signal.pool_sol < float(self.settings.min_pool_sol):
            return Screening.reject(
                f"pool {signal.pool_sol:.2f} SOL below {self.settings.min_pool_sol:g}",
                signal_pool_sol=round(signal.pool_sol, 9),
            )
        return Screening.accept()


class ScreeningFilter(Filter):
    """The anti-rug screen (FEAT-04 / FEAT-26) on a graduate; fails closed."""

    name = "anti_rug"

    def __init__(self, enricher: TokenEnricher) -> None:
        self.enricher = enricher

    async def screen(self, candidate: Candidate) -> Screening:
        verdict = await self.enricher.enrich_and_screen(candidate.instrument_id)
        metrics = {"risk_score": round(float(verdict.risk_score), 3)}
        if not verdict.passed:
            reason = "; ".join(verdict.reasons[:3]) or "screen rejected"
            return Screening.reject(reason, **metrics)
        return Screening.accept(**metrics)


class MomentumAnalyst(Analyst):
    """Signal when the graduate still trades at ``min_ratio`` x its first price."""

    name = "momentum"

    def __init__(
        self,
        tracker: GraduateTracker,
        settings: LaneSettings,
        execution: ExecutionSettings,
    ) -> None:
        self.tracker = tracker
        self.settings = settings
        self.execution = execution

    async def evaluate(
        self, candidate: Candidate, metrics: Mapping[str, Any]
    ) -> Signal | None:
        graduate = self.tracker.get(candidate.instrument_id)
        if graduate is None or graduate.signal_reading is None:
            return None
        ratio = graduate.ratio(graduate.signal_reading)
        if ratio is None or ratio < float(self.settings.min_ratio):
            return None
        price = graduate.signal_reading.price
        limit = price * (1.0 + int(self.execution.slippage_bps) / 10_000.0)
        return Signal(
            candidate.instrument_id,
            reason=f"{LANE}: {ratio:.2f}x the first pool price after "
            f"{graduate.signal_reading.at - graduate.migrated_at:.0f}s",
            limit_price=limit,
            # Orders competing signals only: the stronger move first.
            confidence=min(1.0, max(0.0, ratio - 1.0)),
            edge=ratio - 1.0,
            strategy=LANE,
            metrics={**candidate.data, **metrics},
        )


def build_pipeline(
    tracker: GraduateTracker,
    settings: LaneSettings,
    execution: ExecutionSettings,
    *,
    clock: Callable[[], float] = time.time,
    enricher: TokenEnricher | None = None,
) -> StrategyPipeline:
    filters: list[Filter] = [StandardPoolFilter(tracker, settings)]
    if settings.screen_entries:
        if enricher is None:
            raise ValueError("lane.screen_entries needs a screening enricher")
        filters.append(ScreeningFilter(enricher))
    return StrategyPipeline(
        scouts=[GraduationScout(tracker, settings, clock=clock)],
        filters=filters,
        analyst=MomentumAnalyst(tracker, settings, execution),
    )


__all__ = [
    "LANE",
    "GraduationScout",
    "MomentumAnalyst",
    "ScreeningFilter",
    "StandardPoolFilter",
    "build_pipeline",
    "candidate_metrics",
]
