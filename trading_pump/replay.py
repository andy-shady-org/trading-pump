"""Replay a capture through trading-core's engine with the module attached.

A capture holds every migration and every graduate's pool readings
(``trading_pump.graduates``; pumpfun-trading rc.8 captures have the same
rows). trading-core's replay harness (``trading_core.replay``, FEAT-110:
the clock, the settings of a replay, the engine and its loop) plays it
back; this module gives it what the capture's rows mean:

* migrations reach the tracker at their recorded time
  (:class:`GraduationFeed`, the harness's ``ReplayFeed``);
* the poller reads due pools from :class:`CapturePoolSource`, which answers
  with the latest *recorded* reading at or before the simulated time (never
  a later one: no look-ahead, ``TimeIndex.at``);
* the engine cycles every ``cycle_seconds`` with its real risk gate, exits,
  circuit breaker and net-PnL accounting, writing a normal audit trail; the
  clock advances by the smaller of the poll tick and the cycle;
* a paper buy waits ``paper_entry_delay_seconds`` of simulated time before
  it reads the pool, as a live buy does (AGENTS.md: model the latency you
  pay). A live paper fill reads the pool afresh at that moment, and that
  read is not in the capture; :class:`CaptureFillSource` answers the fill
  with the recorded reading *nearest* that moment, at most
  ``FILL_LOOK_AHEAD_SECONDS`` after it, rather than the last one before it,
  which on 2 s reads was often the signal's own reading (BUG-164,
  ``TimeIndex.near``). The poller still never looks ahead.

Fees in a replay are fixed (``fee_bps``): a capture does not record the fee
tier at each moment.

Engine and module settings come from the same settings file as a paper run,
so a replay judges exactly the configuration that would run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_core.config.settings import EngineSettings
from trading_core.replay import (
    FILL_LOOK_AHEAD_SECONDS,
    ReplayClock,
    TimeIndex,
    replay_engine,
    replay_settings,
    run_replay,
)
from trading_solana.mints import TokenName

from trading_pump.config.env import Credentials
from trading_pump.graduates import MIGRATION_EVENT
from trading_pump.market import (
    FEE_SOURCE_REPLAY,
    PoolReading,
    SwapFee,
)
from trading_pump.module import PumpModule
from trading_pump.strategies.observation import (
    GRADUATION_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
)

# A conservative default for replays: the AMM global config charges 30 bps;
# the fee tiers by market cap may charge more (docs/dev/TODO.md).
DEFAULT_REPLAY_FEE_BPS = 125


def is_graduation_row(row: Mapping[str, Any]) -> bool:
    event = row.get("event")
    if event == MIGRATION_EVENT:
        return True
    return row.get("source") == GRADUATION_SOURCE and event in (
        OBSERVATION_START_EVENT,
        OBSERVATION_END_EVENT,
        "curve_poll",
    )


def _graduation_key(row: Mapping[str, Any]) -> tuple[str, float] | None:
    """``(mint, timestamp)`` of a usable graduation row, else ``None``."""
    if not is_graduation_row(row):
        return None
    mint = row.get("mint")
    if not isinstance(mint, str) or not mint:
        return None
    try:
        return mint, float(row.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        return None


@dataclass
class CaptureMarket:
    """The graduation rows of a capture, indexed for playback: the
    migrations in time order and each graduate's readings in trading-core's
    :class:`~trading_core.replay.TimeIndex`."""

    migrations: list[tuple[float, str]] = field(default_factory=list)
    readings: TimeIndex[str, PoolReading] = field(default_factory=TimeIndex)

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> CaptureMarket:
        market = cls()
        seen: set[str] = set()
        for row in rows:
            keyed = _graduation_key(row)
            if keyed is None:
                continue
            mint, stamp = keyed
            event = row.get("event")
            if event == OBSERVATION_START_EVENT and mint not in seen:
                seen.add(mint)
                migrated = row.get("migrated_at", stamp)
                market.migrations.append((float(migrated or stamp), mint))
            elif event == "curve_poll":
                reading = PoolReading.from_capture_row(row, mint=mint, at=stamp)
                if reading is not None:
                    market.readings.add(mint, reading.at, reading)
        market.migrations.sort()
        market.readings.index()
        return market

    @property
    def start(self) -> float | None:
        times = [t for t, _ in self.migrations]
        return min(times) if times else None

    @property
    def end(self) -> float | None:
        return self.readings.end

    def reading_near(
        self, mint: str, now: float, look_ahead: float
    ) -> PoolReading | None:
        """The recorded reading nearest ``now``: the latest at or before it,
        or the first after it when that one is closer and at most
        ``look_ahead`` seconds later (BUG-164)."""
        return self.readings.near(mint, now, look_ahead)

    def reading_at(self, mint: str, now: float) -> PoolReading | None:
        """The latest recorded reading at or before ``now``."""
        return self.readings.at(mint, now)


@dataclass
class CapturePoolSource:
    """A ``PoolSource`` that answers from a capture (no look-ahead)."""

    market: CaptureMarket
    fee_bps: int = DEFAULT_REPLAY_FEE_BPS

    async def read_pools(
        self, mints: Sequence[str], *, now: float
    ) -> tuple[dict[str, PoolReading], dict[str, str]]:
        found: dict[str, PoolReading] = {}
        rejected: dict[str, str] = {}
        for mint in mints:
            reading = self.market.reading_at(mint, now)
            if reading is None:
                rejected[mint] = "missing"
            else:
                found[mint] = reading
        return found, rejected

    async def swap_fee(self, reading: PoolReading) -> SwapFee:
        return SwapFee(int(self.fee_bps), FEE_SOURCE_REPLAY)

    async def read_names(self, mints: Sequence[str]) -> dict[str, TokenName]:
        """A capture holds no names: replayed positions show their address."""
        return {}


@dataclass
class CaptureFillSource(CapturePoolSource):
    """The paper executor's source in a replay: each fill takes the recorded
    reading nearest the moment of the order (BUG-164)."""

    look_ahead_seconds: float = FILL_LOOK_AHEAD_SECONDS

    async def read_pools(
        self, mints: Sequence[str], *, now: float
    ) -> tuple[dict[str, PoolReading], dict[str, str]]:
        found: dict[str, PoolReading] = {}
        rejected: dict[str, str] = {}
        for mint in mints:
            reading = self.market.reading_near(mint, now, self.look_ahead_seconds)
            if reading is None:
                rejected[mint] = "missing"
            else:
                found[mint] = reading
        return found, rejected


@dataclass
class GraduationFeed:
    """trading-core's ``ReplayFeed`` for a capture of graduates.

    It runs from the first migration to the last recorded reading, every
    ``poll_tick``; each turn hands the tracker the migrations recorded by
    then, at their recorded time, and lets the poller read the due pools
    from the capture. It implements the protocol rather than subclassing
    ``RowFeed``: a graduate is followed from its ``migrated_at``, not from
    its row's ``timestamp``, and the replay ends at the last reading, as it
    did before 0.5.0 (``RowFeed`` ends one tick after its last row), so a
    replay of the same capture plays the same ticks and cycles.
    """

    market: CaptureMarket
    module: PumpModule
    _next: int = 0

    @property
    def start(self) -> float | None:
        return self.market.start

    @property
    def end(self) -> float | None:
        return self.market.end

    @property
    def tick_seconds(self) -> float:
        return self.module.poll_tick

    async def advance(self, now: float) -> None:
        migrations = self.market.migrations
        while self._next < len(migrations) and migrations[self._next][0] <= now:
            stamp, mint = migrations[self._next]
            self.module.tracker.add(mint, now=stamp)
            self._next += 1
        await self.module.poller.poll_once(now)


@dataclass
class ReplayResult:
    start: float
    end: float
    migrations: int
    cycles: int
    totals: dict[str, Any]
    tracker: dict[str, Any]
    audit_log_path: str | None


def _check(market: CaptureMarket) -> None:
    """Refuse a capture with nothing to replay, saying why."""
    if market.start is None:
        raise ValueError("the capture has no graduation rows")
    if market.end is None:
        raise ValueError(
            f"the capture follows {len(market.migrations)} graduate(s) but holds "
            "no pool readings (curve_poll rows): every pool read failed or "
            "found no pool, so there is nothing to replay"
        )


async def replay_capture(
    market: CaptureMarket,
    settings: EngineSettings,
    out_dir: str | Path,
    *,
    fee_bps: int = DEFAULT_REPLAY_FEE_BPS,
) -> ReplayResult:
    """Play ``market`` through a fresh engine; see the module docstring."""
    _check(market)
    run = replay_settings(settings, Path(out_dir))
    clock = ReplayClock(float(market.start or 0.0))
    module = PumpModule(
        source=CapturePoolSource(market, fee_bps=fee_bps),
        fill_source=CaptureFillSource(market, fee_bps=fee_bps),
        credentials=Credentials(),
        clock=clock,
        sleep=clock.sleep,
        live_feeds=False,
        **run.module_settings,
    )
    result = await run_replay(
        replay_engine(module, run, clock),
        GraduationFeed(market, module),
        clock,
        run,
    )
    return ReplayResult(
        start=result.start,
        end=result.end,
        migrations=len(market.migrations),
        cycles=result.cycles,
        totals=result.totals,
        tracker=module.tracker.snapshot(),
        audit_log_path=result.audit_log_path,
    )


__all__ = [
    "DEFAULT_REPLAY_FEE_BPS",
    "CaptureFillSource",
    "CaptureMarket",
    "CapturePoolSource",
    "GraduationFeed",
    "ReplayResult",
    "is_graduation_row",
    "replay_capture",
]
