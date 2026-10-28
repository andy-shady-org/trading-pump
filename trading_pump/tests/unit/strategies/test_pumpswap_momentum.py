"""Unit tests for ``strategies/pumpswap_momentum.py`` (FEAT-76)."""

from __future__ import annotations

from typing import Any

import pytest
from trading_core.strategy.pipeline import Candidate

from trading_pump.config.settings import (
    ExecutionSettings,
    GraduationSettings,
    LaneSettings,
)
from trading_pump.graduates import GraduateTracker
from trading_pump.strategies.filters import TokenScreeningVerdict
from trading_pump.strategies.pumpswap_momentum import (
    LANE,
    GraduationScout,
    MomentumAnalyst,
    ScreeningFilter,
    StandardPoolFilter,
    build_pipeline,
    candidate_metrics,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading

MINT = SAMPLE_MINT


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _tracker() -> GraduateTracker:
    return GraduateTracker(GraduationSettings(), signal_after_seconds=60.0)


def _graduate(
    tracker: GraduateTracker,
    mint: str = MINT,
    *,
    first_scale: float = 1.0,
    signal_scale: float = 1.3,
    signal_at: float = 61.0,
) -> None:
    tracker.add(mint, now=0.0)
    tracker.update(make_reading(mint, at=2.0, scale=first_scale))
    tracker.update(make_reading(mint, at=signal_at, scale=first_scale * signal_scale))


async def test_the_scout_proposes_each_graduate_once_its_signal_reading_is_in() -> None:
    tracker = _tracker()
    clock = Clock(30.0)
    scout = GraduationScout(tracker, LaneSettings(), clock=clock)
    tracker.add(MINT, now=0.0)
    tracker.update(make_reading(MINT, at=2.0))

    assert await scout.discover() == []
    tracker.update(make_reading(MINT, at=61.0, scale=1.3))
    clock.now = 62.0
    [candidate] = await scout.discover()

    assert candidate.instrument_id == MINT and candidate.source == "graduations"
    assert candidate.data["ratio"] == pytest.approx(1.3, rel=1e-6)
    assert candidate.data["signal_delay_seconds"] == 61.0
    assert candidate.data["first_reading_delay_seconds"] == 2.0
    assert candidate.data["lane"] == LANE
    assert await scout.discover() == []  # decided once
    assert scout.stats == {"proposed": 1}


async def test_no_reading_in_the_window_or_a_late_one_means_no_decision() -> None:
    tracker = _tracker()
    clock = Clock(0.0)
    settings = LaneSettings(signal_window_seconds=10.0)
    scout = GraduationScout(tracker, settings, clock=clock)
    tracker.add(MINT, now=0.0)
    clock.now = 71.0
    assert await scout.discover() == []
    assert scout.stats == {"no_reading_in_window": 1}

    tracker.add(SAMPLE_PUMP_MINT, now=0.0)
    tracker.update(make_reading(SAMPLE_PUMP_MINT, at=2.0))
    tracker.update(make_reading(SAMPLE_PUMP_MINT, at=75.0, scale=2.0))
    assert await scout.discover() == []
    assert scout.stats["reading_too_late"] == 1


async def test_a_graduate_without_a_lane_signal_time_is_never_proposed() -> None:
    tracker = GraduateTracker(GraduationSettings())
    tracker.add(MINT, now=0.0)
    scout = GraduationScout(tracker, LaneSettings(), clock=Clock(1_000.0))
    assert await scout.discover() == []


@pytest.mark.parametrize(
    ("first_scale", "message"),
    [(0.3, "first market cap 123.2 SOL outside"), (3.0, "outside")],
)
async def test_the_standard_pool_filter_rejects_odd_graduations(
    first_scale: float, message: str
) -> None:
    tracker = _tracker()
    _graduate(tracker, first_scale=first_scale)
    verdict = await StandardPoolFilter(tracker, LaneSettings()).screen(Candidate(MINT))
    assert not verdict.passed and message in verdict.reason


async def test_the_standard_pool_filter_needs_readings_a_live_pool_and_its_sol() -> (
    None
):
    tracker = _tracker()
    screen = StandardPoolFilter(tracker, LaneSettings(min_pool_sol=100.0))
    assert (await screen.screen(Candidate(MINT))).reason == "no pool readings"

    _graduate(tracker)
    low = await screen.screen(Candidate(MINT))
    assert not low.passed and "below 100" in low.reason

    ok = await StandardPoolFilter(tracker, LaneSettings()).screen(Candidate(MINT))
    assert ok.passed

    graduate = tracker.get(MINT)
    assert graduate is not None and graduate.signal_reading is not None
    graduate.signal_reading = make_reading(MINT, at=61.0, base=0)
    drained = await StandardPoolFilter(tracker, LaneSettings()).screen(Candidate(MINT))
    assert drained.reason == "pool drained"


async def test_the_analyst_signals_at_the_ratio_with_a_slippage_limit() -> None:
    tracker = _tracker()
    _graduate(tracker, signal_scale=1.3)
    analyst = MomentumAnalyst(
        tracker, LaneSettings(), ExecutionSettings(slippage_bps=500)
    )
    signal = await analyst.evaluate(Candidate(MINT, data={"ratio": 1.3}), {"m": 1})

    graduate = tracker.get(MINT)
    assert signal is not None and graduate is not None
    assert graduate.signal_reading is not None
    assert signal.limit_price == pytest.approx(graduate.signal_reading.price * 1.05)
    assert signal.strategy == LANE
    assert signal.edge == pytest.approx(0.3, rel=1e-5)
    assert signal.confidence == pytest.approx(0.3, rel=1e-5)
    assert signal.metrics == {"ratio": 1.3, "m": 1}
    assert "1.30x the first pool price after 61s" in signal.reason


async def test_the_analyst_holds_below_the_ratio_or_without_data() -> None:
    tracker = _tracker()
    _graduate(tracker, signal_scale=1.1)
    analyst = MomentumAnalyst(tracker, LaneSettings(), ExecutionSettings())
    assert await analyst.evaluate(Candidate(MINT), {}) is None
    assert await analyst.evaluate(Candidate(SAMPLE_PUMP_MINT), {}) is None
    graduate = tracker.get(MINT)
    assert graduate is not None
    graduate.first = None
    assert await analyst.evaluate(Candidate(MINT), {}) is None


class FakeEnricher:
    def __init__(self, verdict: TokenScreeningVerdict) -> None:
        self.verdict = verdict
        self.mints: list[str] = []

    async def enrich_and_screen(self, mint: str) -> TokenScreeningVerdict:
        self.mints.append(mint)
        return self.verdict


async def test_the_screening_filter_passes_and_rejects_with_the_risk_score() -> None:
    passed = FakeEnricher(TokenScreeningVerdict(MINT, passed=True, risk_score=12.0))
    ok = await ScreeningFilter(passed).screen(Candidate(MINT))  # type: ignore[arg-type]
    assert ok.passed and ok.metrics == {"risk_score": 12.0}

    failed = FakeEnricher(
        TokenScreeningVerdict(MINT, passed=False, risk_score=80.0, reasons=["a", "b"])
    )
    screen: Any = ScreeningFilter
    bad = await screen(failed).screen(Candidate(MINT))
    assert not bad.passed and bad.reason == "a; b"
    silent = FakeEnricher(TokenScreeningVerdict(MINT, passed=False, risk_score=80.0))
    assert (
        await ScreeningFilter(silent).screen(Candidate(MINT))  # type: ignore[arg-type]
    ).reason == "screen rejected"


async def test_the_pipeline_end_to_end() -> None:
    tracker = _tracker()
    clock = Clock(62.0)
    _graduate(tracker, MINT, signal_scale=1.3)
    _graduate(tracker, SAMPLE_PUMP_MINT, signal_scale=1.05)
    pipeline = build_pipeline(tracker, LaneSettings(), ExecutionSettings(), clock=clock)

    result = await pipeline.run()

    assert [s.instrument_id for s in result.signals] == [MINT]
    assert [(r.instrument_id, r.stage) for r in result.rejections] == [
        (SAMPLE_PUMP_MINT, "momentum")
    ]
    assert pipeline.describe() == "graduations -> standard_pool -> momentum"


def test_screening_in_the_pipeline_needs_an_enricher() -> None:
    settings = LaneSettings(screen_entries=True)
    with pytest.raises(ValueError, match="needs a screening enricher"):
        build_pipeline(_tracker(), settings, ExecutionSettings())
    enricher: Any = FakeEnricher(TokenScreeningVerdict(MINT, True, 0.0))
    pipeline = build_pipeline(
        _tracker(), settings, ExecutionSettings(), enricher=enricher
    )
    assert "anti_rug" in pipeline.describe()


def test_candidate_metrics_without_readings() -> None:
    tracker = _tracker()
    graduate = tracker.add(MINT, now=0.0)
    assert graduate is not None
    assert candidate_metrics(graduate, 5.0) == {
        "lane": LANE,
        "migrated_at": 0.0,
        "age_seconds": 5.0,
    }
