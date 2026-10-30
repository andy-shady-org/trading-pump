"""The graduate lanes: ``pumpswap_momentum`` (FEAT-76) and ``pumpswap_instant``
(FEAT-78), one pipeline for both.

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

**Two lanes (rc11).** Each graduate belongs to one lane, by its first
reading: the ``instant`` lane's band (coins launched and graduated in one go
by their bots: first pool ~145 SOL, market cap ~1,200 SOL) is checked first,
everything else goes to the standard lane, whose filter rejects what is not
a standard graduation as before. Both lanes decide at the same signal
reading; each has its own ratio band, slippage and exits (FEAT-79), and its
signals carry its name as ``strategy``, so each is judged on its own.

Exits: a lane with exit rules sells on them (``PumpModule.should_exit``);
one without falls back to trading-core's generic ``exits``. Every
candidate's metrics (rejected ones included, as ``screening`` events) are
recorded so ``trading-core-audit cuts`` can test any refinement against a
random cut afterwards.
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
from trading_pump.market import PoolReading
from trading_pump.strategies.enrichment import TokenEnricher

LANE = "pumpswap_momentum"
LANE_INSTANT = "pumpswap_instant"


class Lanes:
    """The enabled lanes by name, and which one a graduate belongs to."""

    def __init__(
        self, standard: LaneSettings, instant: LaneSettings | None = None
    ) -> None:
        self.standard = standard
        self.instant = instant if instant is not None and instant.enabled else None

    @classmethod
    def of(cls, settings: LaneSettings | Lanes) -> Lanes:
        return settings if isinstance(settings, Lanes) else cls(settings)

    def settings(self, name: object) -> LaneSettings:
        if name == LANE_INSTANT and self.instant is not None:
            return self.instant
        return self.standard

    def classify(self, graduate: Graduate) -> str | None:
        """The lane a graduate belongs to (``None``: no enabled lane)."""
        first = graduate.first
        if (
            self.instant is not None
            and first is not None
            and self.instant.accepts_first(first.market_cap_sol, first.pool_sol)
        ):
            return LANE_INSTANT
        return LANE if self.standard.enabled else None

    def named(self) -> list[tuple[str, LaneSettings]]:
        found = [(LANE_INSTANT, self.instant)] if self.instant is not None else []
        if self.standard.enabled:
            found.append((LANE, self.standard))
        return [(name, lane) for name, lane in found if lane is not None]


def candidate_metrics(
    graduate: Graduate, now: float, lane: str = LANE
) -> dict[str, Any]:
    """What the lane decided on, recorded on the candidate and the buy."""
    first = graduate.first
    signal = graduate.signal_reading
    metrics: dict[str, Any] = {
        "lane": lane,
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
        settings: LaneSettings | Lanes,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.tracker = tracker
        self.lanes = Lanes.of(settings)
        self.settings = self.lanes.standard
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
            lane = self.lanes.classify(graduate)
            if lane is None:
                self._count("no_lane")
                continue
            self._count("proposed" if lane == LANE else f"proposed_{lane}")
            found.append(
                Candidate(
                    graduate.mint,
                    source=self.name,
                    data=candidate_metrics(graduate, now, lane),
                )
            )
        return found


class StandardPoolFilter(Filter):
    """The candidate's lane bands on its first reading (standard graduations:
    a first market cap near 410.88 SOL), and a live pool at the signal."""

    name = "standard_pool"

    def __init__(
        self, tracker: GraduateTracker, settings: LaneSettings | Lanes
    ) -> None:
        self.tracker = tracker
        self.lanes = Lanes.of(settings)
        self.settings = self.lanes.standard

    async def screen(self, candidate: Candidate) -> Screening:
        graduate = self.tracker.get(candidate.instrument_id)
        if (
            graduate is None
            or graduate.first is None
            or graduate.signal_reading is None
        ):
            return Screening.reject("no pool readings")
        lane = self.lanes.settings(candidate.data.get("lane"))
        band = _band_rejection(graduate.first, lane)
        if band is not None:
            return band
        signal = graduate.signal_reading
        if signal.drained:
            return Screening.reject("pool drained")
        if signal.pool_sol < float(lane.min_pool_sol):
            return Screening.reject(
                f"pool {signal.pool_sol:.2f} SOL below {lane.min_pool_sol:g}",
                signal_pool_sol=round(signal.pool_sol, 9),
            )
        return Screening.accept()


def _band_rejection(first: PoolReading, lane: LaneSettings) -> Screening | None:
    """Why a first reading is outside the lane's bands (``None``: inside)."""
    low, high = lane.market_cap_band()
    cap = first.market_cap_sol
    if not low <= cap <= high:
        return Screening.reject(
            f"first market cap {cap:.1f} SOL outside {low:.1f}-{high:.1f}",
            first_market_cap_sol=round(cap, 6),
        )
    if not lane.accepts_first(cap, first.pool_sol):
        return Screening.reject(
            f"first pool {first.pool_sol:.1f} SOL outside the lane's band",
            first_pool_sol=round(first.pool_sol, 9),
        )
    return None


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
        settings: LaneSettings | Lanes,
        execution: ExecutionSettings,
    ) -> None:
        self.tracker = tracker
        self.lanes = Lanes.of(settings)
        self.settings = self.lanes.standard
        self.execution = execution

    async def evaluate(
        self, candidate: Candidate, metrics: Mapping[str, Any]
    ) -> Signal | None:
        graduate = self.tracker.get(candidate.instrument_id)
        if graduate is None or graduate.signal_reading is None:
            return None
        name = str(candidate.data.get("lane") or LANE)
        lane = self.lanes.settings(name)
        ratio = graduate.ratio(graduate.signal_reading)
        if not _in_ratio_band(ratio, lane):
            return None
        assert ratio is not None
        price = graduate.signal_reading.price
        slippage = (
            self.execution.slippage_bps
            if lane.slippage_bps is None
            else lane.slippage_bps
        )
        return Signal(
            candidate.instrument_id,
            reason=f"{name}: {ratio:.2f}x the first pool price after "
            f"{graduate.signal_reading.at - graduate.migrated_at:.0f}s",
            limit_price=price * (1.0 + int(slippage) / 10_000.0),
            # Orders competing signals only: the stronger move first.
            confidence=min(1.0, max(0.0, ratio - 1.0)),
            edge=ratio - 1.0,
            strategy=name,
            metrics={**candidate.data, **metrics},
        )


def _in_ratio_band(ratio: float | None, lane: LaneSettings) -> bool:
    """``min_ratio`` <= ratio, and below ``max_ratio`` when one is set."""
    if ratio is None or ratio < float(lane.min_ratio):
        return False
    return not (lane.max_ratio and ratio >= float(lane.max_ratio))


def build_pipeline(
    tracker: GraduateTracker,
    settings: LaneSettings | Lanes,
    execution: ExecutionSettings,
    *,
    clock: Callable[[], float] = time.time,
    enricher: TokenEnricher | None = None,
) -> StrategyPipeline:
    lanes = Lanes.of(settings)
    filters: list[Filter] = [StandardPoolFilter(tracker, lanes)]
    if any(lane.screen_entries for _, lane in lanes.named()):
        if enricher is None:
            raise ValueError("lane.screen_entries needs a screening enricher")
        filters.append(ScreeningFilter(enricher))
    return StrategyPipeline(
        scouts=[GraduationScout(tracker, lanes, clock=clock)],
        filters=filters,
        analyst=MomentumAnalyst(tracker, lanes, execution),
    )


__all__ = [
    "LANE",
    "LANE_INSTANT",
    "Lanes",
    "GraduationScout",
    "MomentumAnalyst",
    "ScreeningFilter",
    "StandardPoolFilter",
    "build_pipeline",
    "candidate_metrics",
]
