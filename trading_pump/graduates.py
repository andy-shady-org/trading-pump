"""Graduation tracking (FEAT-73): follow every migrated coin's PumpSwap pool.

PumpPortal's free ``subscribeMigration`` feed says when a bonding curve
completes and its coin moves to the canonical PumpSwap pool. The tracker
starts following the pool at that moment: read every 2 s for the first
5 minutes, then every 10 s, for 4 hours (``GraduationSettings``). It keeps,
per graduate, the first reading after the migration, the latest one and the
first one at or after the lane's signal time, which is everything the
``pumpswap_momentum`` lane (FEAT-76) decides on.

Every migration and every reading is written to the capture in
pumpfun-trading's row shape (``migration``, ``observation_start``,
``curve_poll`` with ``source: "graduation"``, ``observation_end``), so the
rc.8 read-out scripts and the module's replay read the same file.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from trading_pump.config.settings import GraduationSettings
from trading_pump.market import PoolReading
from trading_pump.sdk.pumpswap import canonical_pool_address
from trading_pump.strategies.observation import (
    GRADUATION_SOURCE,
    NEW_POOL_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
    CurveObservationList,
)

MIGRATION_EVENT = "migration"

Recorder = Callable[[dict[str, Any]], None]


def _no_record(row: dict[str, Any]) -> None:
    return None


@dataclass
class Graduate:
    """What the module knows about one graduated coin."""

    mint: str
    migrated_at: float
    pool: str
    first: PoolReading | None = None
    last: PoolReading | None = None
    signal_reading: PoolReading | None = None
    signal_time: float | None = None
    # The lane decides once per graduate (a pre-registered rule, FEAT-76).
    decided: bool = False
    # ``graduation``, or ``new_pool`` for a new pool that is not a Pump.fun
    # graduation (FEAT-80): recorded, never proposed to a lane.
    source: str = GRADUATION_SOURCE

    def age(self, now: float) -> float:
        return max(0.0, now - self.migrated_at)

    def ratio(self, reading: PoolReading | None = None) -> float | None:
        """``reading`` (default: the latest) over the first reading's price."""
        current = reading or self.last
        if current is None or self.first is None or self.first.price <= 0:
            return None
        return current.price / self.first.price


class GraduateTracker:
    """Graduates being followed, their readings, and the capture rows."""

    def __init__(
        self,
        settings: GraduationSettings,
        *,
        signal_after_seconds: float | None = None,
        record: Recorder | None = None,
    ) -> None:
        self.settings = settings
        self.signal_after_seconds = signal_after_seconds
        self.record: Recorder = record or _no_record
        self.observations = CurveObservationList(
            source=GRADUATION_SOURCE,
            max_mints=int(settings.max_mints),
            ttl_seconds=float(settings.observation_seconds),
            poll_interval_seconds=float(settings.poll_interval_seconds),
            fast_seconds=float(settings.fast_seconds),
            fast_poll_interval_seconds=float(settings.fast_poll_interval_seconds),
        )
        self.graduates: dict[str, Graduate] = {}
        self.stats: dict[str, int] = {}

    def _count(self, key: str, value: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + value

    def __contains__(self, mint: object) -> bool:
        return mint in self.graduates

    def __len__(self) -> int:
        return len(self.graduates)

    def get(self, mint: str) -> Graduate | None:
        return self.graduates.get(mint)

    # -- lifecycle ---------------------------------------------------------
    def add(self, mint: str, *, now: float, held: bool = False) -> Graduate | None:
        """Start following ``mint`` from its migration (``None`` if already
        followed, invalid or the list is full)."""
        if mint in self.graduates:
            self._count("duplicate_migrations")
            return None
        self._count("migrations")
        # No price field: a regime count, as pumpfun-trading recorded it.
        self.record({"timestamp": now, "mint": mint, "event": MIGRATION_EVENT})
        try:
            pool = str(canonical_pool_address(mint))
        except Exception:
            self._count("invalid_mints")
            return None
        graduate = self._follow(
            Graduate(mint=mint, migrated_at=now, pool=pool), now=now
        )
        if graduate is None:
            return None
        if self.signal_after_seconds is not None:
            graduate.signal_time = now + float(self.signal_after_seconds)
        self._start_row(graduate, now, {"held": bool(held)})
        return graduate

    def add_new_pool(
        self,
        mint: str,
        pool: str,
        *,
        now: float,
        details: Mapping[str, Any] | None = None,
    ) -> Graduate | None:
        """Start following a new pool that is not a Pump.fun graduation
        (FEAT-80): the same schedule and rows, ``source: "new_pool"``, and
        never a lane decision. ``None`` if the mint is followed already (a
        graduate's second pool) or the list is full."""
        if mint in self.graduates:
            self._count("new_pool_duplicates")
            return None
        graduate = Graduate(
            mint=mint, migrated_at=now, pool=pool, decided=True, source=NEW_POOL_SOURCE
        )
        if self._follow(graduate, now=now) is None:
            return None
        self._count("new_pools")
        self._start_row(graduate, now, dict(details or {}))
        return graduate

    def _follow(self, graduate: Graduate, *, now: float) -> Graduate | None:
        if self.observations.add(graduate.mint, now=now) is None:
            self._count("list_full")
            return None
        self.graduates[graduate.mint] = graduate
        self._count("followed")
        return graduate

    def _start_row(
        self, graduate: Graduate, now: float, extra: Mapping[str, Any]
    ) -> None:
        self.record(
            {
                "timestamp": now,
                "mint": graduate.mint,
                "event": OBSERVATION_START_EVENT,
                "source": graduate.source,
                "migrated_at": now,
                "pool": graduate.pool,
                **extra,
            }
        )

    def due(self, now: float) -> list[str]:
        """Graduates whose next reading is due."""
        return self.observations.due(now)

    def expire(self, now: float) -> list[str]:
        """End the observations older than ``observation_seconds``."""
        ended = self.observations.expired(now)
        for mint in ended:
            self.end(mint, "ttl", now)
        return ended

    def end(self, mint: str, cause: str, now: float) -> None:
        entry = self.observations.remove(mint, cause)
        graduate = self.graduates.pop(mint, None)
        if entry is None or graduate is None:
            return
        self._count(f"ended_{cause}")
        self.record(
            {
                "timestamp": now,
                "mint": mint,
                "event": OBSERVATION_END_EVENT,
                "source": graduate.source,
                "cause": cause,
                "observed_seconds": round(max(0.0, now - entry.added_at), 1),
                "polls": entry.polls,
                "first_real_sol": entry.first_real_sol,
                "last_real_sol": entry.last_real_sol,
                "peak_real_sol": round(entry.peak_real_sol, 9),
            }
        )

    # -- readings ------------------------------------------------------------
    def update(self, reading: PoolReading) -> Graduate | None:
        """Record one reading of a followed pool (and its capture row)."""
        graduate = self.graduates.get(reading.mint)
        entry = self.observations.get(reading.mint)
        if graduate is None or entry is None:
            return None
        if graduate.last is not None and reading.at <= graduate.last.at:
            # The same reading again (a replay between two recorded reads).
            entry.last_polled_at = reading.at
            return graduate
        self.record(reading.capture_row(source=graduate.source))
        if graduate.first is None and not reading.drained:
            graduate.first = reading
        graduate.last = reading
        if (
            graduate.signal_reading is None
            and graduate.signal_time is not None
            and reading.at >= graduate.signal_time
        ):
            graduate.signal_reading = reading
        self.observations.update(
            reading.mint, real_sol=reading.pool_sol, now=reading.at
        )
        self._count("readings")
        return graduate

    def rejected(self, mint: str, reason: str, now: float) -> None:
        """A read found no usable pool. A missing pool is retried for a while
        after the migration (lagging RPC nodes); anything else ends it."""
        graduate = self.graduates.get(mint)
        entry = self.observations.get(mint)
        if graduate is None or entry is None:
            return
        if reason == "missing" and now - entry.added_at < float(
            self.settings.pool_missing_grace_seconds
        ):
            # Mark it polled so it is retried on its schedule, not every pass.
            entry.last_polled_at = now
            entry.polls += 1
            self._count("pool_missing_retries")
            return
        self.end(mint, reason, now)

    def snapshot(self) -> dict[str, Any]:
        return {
            "following": len(self.graduates),
            "max_mints": int(self.settings.max_mints),
            "stats": dict(self.stats),
        }


__all__ = ["MIGRATION_EVENT", "Graduate", "GraduateTracker"]
