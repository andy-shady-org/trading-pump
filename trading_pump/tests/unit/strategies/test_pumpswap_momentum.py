"""Unit tests for ``strategies/pumpswap_momentum.py`` (FEAT-76)."""

from __future__ import annotations

from typing import Any

import pytest
from trading_core.strategy.pipeline import Candidate

from trading_pump.config.settings import (
    ExecutionSettings,
    GraduationSettings,
    InstantLaneSettings,
    LaneSettings,
)
from trading_pump.graduates import GraduateTracker
from trading_pump.market import PoolReading
from trading_pump.strategies.filters import TokenScreeningVerdict
from trading_pump.strategies.pumpswap_momentum import (
    LANE,
    LANE_INSTANT,
    GraduationScout,
    Lanes,
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


# -- rc11: the instant lane (FEAT-78) and per-lane settings ----------------------
INSTANT = InstantLaneSettings(enabled=True)


def _instant_reading(mint: str, at: float, scale: float = 1.0) -> PoolReading:
    """A bot-launched graduate's pool: ~145 SOL against ~121M tokens, a first
    market cap near 1,200 SOL; ``scale`` multiplies the price."""
    quote, base = 145_000_000_000, 120_800_000_000_000
    root = scale**0.5
    return PoolReading(
        mint=mint, at=at, base_reserve=int(base / root), quote_reserve=int(quote * root)
    )


def _instant(tracker: GraduateTracker, mint: str = MINT, ratio: float = 1.05) -> None:
    tracker.add(mint, now=0.0)
    tracker.update(_instant_reading(mint, 2.0))
    tracker.update(_instant_reading(mint, 61.0, scale=ratio))


def test_lanes_classify_each_graduate_by_its_first_reading() -> None:
    tracker = _tracker()
    _instant(tracker, MINT)
    _graduate(tracker, SAMPLE_PUMP_MINT)
    lanes = Lanes(LaneSettings(), INSTANT)
    instant, standard = tracker.get(MINT), tracker.get(SAMPLE_PUMP_MINT)
    assert instant is not None and standard is not None
    assert instant.first is not None and 1_150 < instant.first.market_cap_sol < 1_250
    assert lanes.classify(instant) == LANE_INSTANT
    assert lanes.classify(standard) == LANE
    assert [name for name, _ in lanes.named()] == [LANE_INSTANT, LANE]
    assert lanes.settings(LANE_INSTANT) is INSTANT
    assert lanes.settings("anything else") is lanes.standard
    # The instant lane off: everything is the standard lane's.
    off = Lanes(LaneSettings(), InstantLaneSettings())
    assert off.classify(instant) == LANE and off.instant is None
    assert off.settings(LANE_INSTANT) is off.standard
    # The standard lane off: only the instant band is proposed.
    only = Lanes(LaneSettings(enabled=False), INSTANT)
    assert only.classify(standard) is None and only.classify(instant) == LANE_INSTANT
    assert [name for name, _ in only.named()] == [LANE_INSTANT]
    assert Lanes.of(lanes) is lanes


async def test_the_scout_tags_each_candidate_with_its_lane() -> None:
    tracker = _tracker()
    _instant(tracker, MINT)
    _graduate(tracker, SAMPLE_PUMP_MINT)
    scout = GraduationScout(
        tracker, Lanes(LaneSettings(enabled=False), INSTANT), clock=Clock(62.0)
    )
    [candidate] = await scout.discover()
    assert candidate.instrument_id == MINT and candidate.data["lane"] == LANE_INSTANT
    assert scout.stats == {"proposed_pumpswap_instant": 1, "no_lane": 1}


async def test_the_pool_filter_checks_the_candidates_own_lane_bands() -> None:
    tracker = _tracker()
    _instant(tracker, MINT)
    screen = StandardPoolFilter(tracker, Lanes(LaneSettings(), INSTANT))
    ok = await screen.screen(Candidate(MINT, data={"lane": LANE_INSTANT}))
    assert ok.passed
    # Judged as a standard graduation, the same pool is outside the band.
    standard = await screen.screen(Candidate(MINT, data={"lane": LANE}))
    assert "first market cap" in standard.reason
    narrow = StandardPoolFilter(
        tracker,
        Lanes(
            LaneSettings(), InstantLaneSettings(enabled=True, first_pool_max_sol=140)
        ),
    )
    pool = await narrow.screen(Candidate(MINT, data={"lane": LANE_INSTANT}))
    assert not pool.passed and "first pool 145.0 SOL outside" in pool.reason


@pytest.mark.parametrize(
    ("ratio", "signals"), [(0.99, False), (1.0, True), (1.09, True), (1.11, False)]
)
async def test_the_instant_lane_buys_inside_its_ratio_band_only(
    ratio: float, signals: bool
) -> None:
    tracker = _tracker()
    _instant(tracker, MINT, ratio=ratio)
    analyst = MomentumAnalyst(
        tracker, Lanes(LaneSettings(), INSTANT), ExecutionSettings(slippage_bps=500)
    )
    signal = await analyst.evaluate(Candidate(MINT, data={"lane": LANE_INSTANT}), {})
    assert (signal is not None) is signals
    if signal is not None:
        assert signal.strategy == LANE_INSTANT
        assert signal.reason.startswith("pumpswap_instant: ")


async def test_a_lane_slippage_overrides_the_execution_setting() -> None:
    tracker = _tracker()
    _graduate(tracker, signal_scale=1.3)
    lanes = Lanes(LaneSettings(slippage_bps=1_000))
    analyst = MomentumAnalyst(tracker, lanes, ExecutionSettings(slippage_bps=500))
    signal = await analyst.evaluate(Candidate(MINT), {})
    graduate = tracker.get(MINT)
    assert signal is not None and graduate is not None
    assert graduate.signal_reading is not None
    assert signal.limit_price == pytest.approx(graduate.signal_reading.price * 1.10)
    assert signal.strategy == LANE


def test_screening_applies_when_either_lane_asks_for_it() -> None:
    enricher: Any = FakeEnricher(TokenScreeningVerdict(MINT, True, 0.0))
    lanes = Lanes(
        LaneSettings(enabled=False),
        InstantLaneSettings(enabled=True, screen_entries=True),
    )
    pipeline = build_pipeline(_tracker(), lanes, ExecutionSettings(), enricher=enricher)
    assert "anti_rug" in pipeline.describe()


async def test_the_token_name_travels_from_the_graduate_to_the_signal() -> None:
    from trading_pump.names import TokenName

    tracker = _tracker()
    clock = Clock(62.0)
    scout = GraduationScout(tracker, LaneSettings(), clock=clock)
    _graduate(tracker, MINT)
    _graduate(tracker, SAMPLE_PUMP_MINT)
    tracker.named([MINT], {MINT: TokenName("Fomo Family", "FOMO")})

    named, unnamed = await scout.discover()
    assert (named.instrument_id, named.name) == (MINT, "Fomo Family (FOMO)")
    assert unnamed.name is None  # not read yet: the address is shown

    analyst = MomentumAnalyst(tracker, LaneSettings(), ExecutionSettings())
    signal = await analyst.evaluate(named, {})
    assert signal is not None and signal.name == "Fomo Family (FOMO)"
