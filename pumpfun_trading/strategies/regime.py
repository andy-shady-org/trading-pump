"""Market-regime telemetry: hour of day, launch rate and graduation rate.

The v0.3.0-rc.1 capture did better in its EU/US daytime half under every
setting, but one day cannot tell the hour apart from the settings. Every buy
and every screened launch now carries a snapshot of the regime it happened
in, so later captures can test that offline. Nothing here gates a trade.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Any

DEFAULT_REGIME_WINDOW_SECONDS = 900.0
# Bounds memory on a burst; ~1 create/s means ~900 entries in a 15 min window.
MAX_REGIME_EVENTS = 20_000


class MarketRegimeTracker:
    """Rolling counts of Pump.fun launches and graduations over a fixed window."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_REGIME_WINDOW_SECONDS,
        *,
        now: float | None = None,
    ) -> None:
        self.window_seconds = max(1.0, float(window_seconds))
        self.started_at = time.time() if now is None else float(now)
        self._launches: deque[float] = deque(maxlen=MAX_REGIME_EVENTS)
        # Keyed by mint: the migration feed, Geyser and curve polls can all
        # report the same graduation.
        self._graduations: OrderedDict[str, float] = OrderedDict()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._launches and self._launches[0] < cutoff:
            self._launches.popleft()
        while self._graduations:
            mint, ts = next(iter(self._graduations.items()))
            if ts >= cutoff and len(self._graduations) <= MAX_REGIME_EVENTS:
                break
            self._graduations.pop(mint)

    def record_launch(self, timestamp: float | None = None) -> None:
        now = time.time() if timestamp is None else float(timestamp)
        self._launches.append(now)
        self._prune(now)

    def record_graduation(self, mint: str, timestamp: float | None = None) -> bool:
        """Count a graduation once per mint; returns False for a repeat."""
        if not mint or mint in self._graduations:
            return False
        now = time.time() if timestamp is None else float(timestamp)
        self._graduations[mint] = now
        self._prune(now)
        return True

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        """The regime right now. ``warm`` is False until one full window has passed."""
        ts = time.time() if now is None else float(now)
        self._prune(ts)
        launches = len(self._launches)
        graduations = len(self._graduations)
        clock = time.gmtime(ts)
        return {
            "hour_utc": clock.tm_hour,
            "weekday_utc": clock.tm_wday,
            "window_seconds": self.window_seconds,
            "launches": launches,
            "graduations": graduations,
            "launches_per_minute": round(launches * 60.0 / self.window_seconds, 3),
            "graduations_per_hour": round(
                graduations * 3600.0 / self.window_seconds, 3
            ),
            "graduation_ratio": (
                round(graduations / launches, 5) if launches > 0 else None
            ),
            "warm": ts - self.started_at >= self.window_seconds,
        }
