"""Replay a capture through trading-core's engine with the module attached.

A capture holds every migration and every graduate's pool readings
(``trading_pump.graduates``; pumpfun-trading rc.8 captures have the same
rows). :func:`replay_capture` plays it back on a simulated clock:

* migrations reach the tracker at their recorded time;
* the poller reads due pools from :class:`CapturePoolSource`, which answers
  with the latest *recorded* reading at or before the simulated time (never
  a later one: no look-ahead);
* the engine cycles every ``cycle_seconds`` with its real risk gate, exits,
  circuit breaker and net-PnL accounting, writing a normal audit trail;
* a paper buy waits ``paper_entry_delay_seconds`` of simulated time before
  it reads the pool, as a live buy does (AGENTS.md: model the latency you
  pay). A live paper fill reads the pool afresh at that moment, and that
  read is not in the capture; :class:`CaptureFillSource` answers the fill
  with the recorded reading *nearest* that moment, at most
  ``FILL_LOOK_AHEAD_SECONDS`` after it, rather than the last one before it,
  which on 2 s reads was often the signal's own reading (BUG-164). The
  poller still never looks ahead.

Fees in a replay are fixed (``fee_bps``): a capture does not record the fee
tier at each moment.

Engine and module settings come from the same settings file as a paper run,
so a replay judges exactly the configuration that would run.
"""

from __future__ import annotations

import bisect
import gzip
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from trading_core.config.settings import EngineSettings
from trading_core.engine.engine import TradingEngine
from trading_core.ops.alerts import AlertDispatcher

from trading_pump.config.env import Credentials
from trading_pump.graduates import MIGRATION_EVENT
from trading_pump.market import (
    FEE_SOURCE_REPLAY,
    PoolReading,
    SwapFee,
)
from trading_pump.module import PumpModule
from trading_pump.names import TokenName
from trading_pump.strategies.observation import (
    GRADUATION_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
)

# A conservative default for replays: the AMM global config charges 30 bps;
# the fee tiers by market cap may charge more (docs/dev/TODO.md).
DEFAULT_REPLAY_FEE_BPS = 125


def read_rows(paths: Iterable[str | Path]) -> Iterator[dict[str, Any]]:
    """JSON rows of capture files (``.gz`` parts too); bad lines are skipped."""
    for path in paths:
        name = str(path)
        opener: Any = gzip.open if name.endswith(".gz") else open
        with opener(name, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row


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
    """The graduation rows of a capture, indexed for playback."""

    migrations: list[tuple[float, str]] = field(default_factory=list)
    readings: dict[str, list[PoolReading]] = field(default_factory=dict)
    _times: dict[str, list[float]] = field(default_factory=dict)

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
                    market.readings.setdefault(mint, []).append(reading)
        market._index()
        return market

    def _index(self) -> None:
        """Sort migrations and readings, and index reading times per mint."""
        self.migrations.sort()
        for mint, series in self.readings.items():
            series.sort(key=lambda r: r.at)
            self._times[mint] = [r.at for r in series]

    @property
    def start(self) -> float | None:
        times = [t for t, _ in self.migrations]
        return min(times) if times else None

    @property
    def end(self) -> float | None:
        last = [series[-1].at for series in self.readings.values() if series]
        return max(last) if last else None

    def reading_near(
        self, mint: str, now: float, look_ahead: float
    ) -> PoolReading | None:
        """The recorded reading nearest ``now``: the latest at or before it,
        or the first after it when that one is closer and at most
        ``look_ahead`` seconds later (BUG-164)."""
        times = self._times.get(mint)
        if not times:
            return None
        index = bisect.bisect_right(times, now)
        before = index - 1
        if index < len(times) and times[index] - now <= look_ahead:
            if before < 0 or times[index] - now < now - times[before]:
                return self.readings[mint][index]
        return self.readings[mint][before] if before >= 0 else None

    def reading_at(self, mint: str, now: float) -> PoolReading | None:
        """The latest recorded reading at or before ``now``."""
        times = self._times.get(mint)
        if not times:
            return None
        index = bisect.bisect_right(times, now) - 1
        if index < 0:
            return None
        return self.readings[mint][index]


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


FILL_LOOK_AHEAD_SECONDS = 3.0


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


class ReplayClock:
    """Simulated time, moved by the driver and by modelled waits."""

    def __init__(self, start: float) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, float(seconds))


@dataclass
class ReplayResult:
    start: float
    end: float
    migrations: int
    cycles: int
    totals: dict[str, Any]
    tracker: dict[str, Any]
    audit_log_path: str | None


def replay_settings(settings: EngineSettings, out_dir: Path) -> EngineSettings:
    """The run's settings with every file in ``out_dir`` and paper forced.

    ``out_dir`` must not hold an earlier replay: the engine would restore its
    status file and mix the two runs.
    """
    for name in ("status.json", "audit.jsonl"):
        if (out_dir / name).exists():
            raise ValueError(
                f"{out_dir} already holds a replay ({name}); use a new one"
            )
    out_dir.mkdir(parents=True, exist_ok=True)
    module_settings = dict(settings.module_settings)
    capture = dict(module_settings.get("capture") or {})
    capture["path"] = None
    module_settings["capture"] = capture
    return replace(
        settings,
        mode="paper",
        status_path=str(out_dir / "status.json"),
        audit_log_path=str(out_dir / "audit.jsonl"),
        event_log_path=None,
        log_file=None,
        daily_summary_hour_utc=None,
        module_settings=module_settings,
    )


async def replay_capture(
    market: CaptureMarket,
    settings: EngineSettings,
    out_dir: str | Path,
    *,
    fee_bps: int = DEFAULT_REPLAY_FEE_BPS,
) -> ReplayResult:
    """Play ``market`` through a fresh engine; see the module docstring."""
    start, end = market.start, market.end
    if start is None:
        raise ValueError("the capture has no graduation rows")
    if end is None:
        raise ValueError(
            f"the capture follows {len(market.migrations)} graduate(s) but holds "
            "no pool readings (curve_poll rows): every pool read failed or "
            "found no pool, so there is nothing to replay"
        )
    run = replay_settings(settings, Path(out_dir))
    clock = ReplayClock(start)
    module = PumpModule(
        source=CapturePoolSource(market, fee_bps=fee_bps),
        fill_source=CaptureFillSource(market, fee_bps=fee_bps),
        credentials=Credentials(),
        clock=clock,
        sleep=clock.sleep,
        live_feeds=False,
        **run.module_settings,
    )
    engine = TradingEngine(
        module,
        run,
        alerts=AlertDispatcher(provider="none"),
        clock=clock,
        monotonic=clock,
    )
    await engine.start()
    tick = min(module.poll_tick, float(run.cycle_seconds))
    next_cycle = start
    cycles = 0
    pending = list(market.migrations)
    index = 0
    try:
        while clock.now <= end:
            while index < len(pending) and pending[index][0] <= clock.now:
                stamp, mint = pending[index]
                module.tracker.add(mint, now=stamp)
                index += 1
            await module.poller.poll_once(clock.now)
            if clock.now >= next_cycle:
                await engine.run_cycle()
                cycles += 1
                next_cycle = clock.now + float(run.cycle_seconds)
            clock.now += tick
    finally:
        await engine.shutdown()
    return ReplayResult(
        start=start,
        end=end,
        migrations=len(pending),
        cycles=cycles,
        totals=engine.totals.to_dict(),
        tracker=module.tracker.snapshot(),
        audit_log_path=run.audit_log_path,
    )


__all__ = [
    "DEFAULT_REPLAY_FEE_BPS",
    "CaptureMarket",
    "FILL_LOOK_AHEAD_SECONDS",
    "CaptureFillSource",
    "CapturePoolSource",
    "ReplayClock",
    "ReplayResult",
    "is_graduation_row",
    "read_rows",
    "replay_capture",
    "replay_settings",
]
