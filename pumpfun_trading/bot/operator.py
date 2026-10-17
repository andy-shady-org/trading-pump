"""Operator pause: stop new buys without a restart (Sprint 24D, FEAT-50).

``SIGUSR1`` toggles the pause (``kill -USR1 <pid>``). While paused the bot keeps
managing every open position (exits, retries, circuit breaker) but opens nothing
new: no buys, no capital rotation. The state survives restarts through
``bot_status.json``, so a supervisor restart never resumes buying on its own.

This is the terminal-only slice of the Sprint 29 ``PAUSED`` lifecycle state; the
lifecycle state machine itself is unchanged.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class OperatorPause:
    paused: bool = False
    reason: str = ""
    source: str = ""
    since: float | None = None

    def pause(self, *, reason: str = "operator", source: str = "api") -> bool:
        """Pause new buys. Returns ``False`` if already paused."""
        if self.paused:
            return False
        self.paused = True
        self.reason = reason
        self.source = source
        self.since = time.time()
        return True

    def resume(self, *, source: str = "api") -> bool:
        """Resume new buys. Returns ``False`` if not paused."""
        if not self.paused:
            return False
        self.paused = False
        self.reason = ""
        self.source = source
        self.since = None
        return True

    def toggle(self, *, source: str = "signal") -> bool:
        """Flip the pause; returns the new ``paused`` value."""
        if self.paused:
            self.resume(source=source)
        else:
            self.pause(reason="operator signal", source=source)
        return self.paused

    def paused_for_seconds(self, now: float | None = None) -> float:
        if not self.paused or self.since is None:
            return 0.0
        return max(0.0, (time.time() if now is None else now) - self.since)

    def describe(self, now: float | None = None) -> str:
        """Dashboard text: ``active`` or ``PAUSED (reason, 5m)``."""
        if not self.paused:
            return "active"
        minutes = int(self.paused_for_seconds(now) // 60)
        return f"PAUSED ({self.reason or 'operator'}, {minutes}m)"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "OperatorPause":
        if not isinstance(data, dict):
            return cls()
        since = data.get("since")
        return cls(
            paused=bool(data.get("paused", False)),
            reason=str(data.get("reason") or ""),
            source=str(data.get("source") or ""),
            since=float(since) if isinstance(since, (int, float)) else None,
        )


__all__ = ["OperatorPause"]
