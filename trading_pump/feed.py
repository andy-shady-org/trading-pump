"""The module's live inputs: PumpPortal migrations and the pool poller.

:class:`MigrationFeed` holds one PumpPortal WebSocket with the free
``subscribeMigration`` subscription (not metered: no API key or funded
wallet needed) and hands every migrated mint to the tracker. The
pumpbot-era per-token trade subscriptions are not used, so the PumpPortal
key-funds breaker (BUG-112/116/156) has nothing to guard here.

:class:`PoolPoller` reads the due graduates' pools in batches (and every
held mint, so positions are marked on fresh reads) and feeds the readings
to the tracker and the module's quote book. A successful read is market
data for the engine's health monitor; a failed one marks the RPC degraded.
Record-only reads never compete with trading reads: a held mint is always
in the batch, and the batch is one ``getMultipleAccounts`` call per 33
pools.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from trading_core.ops.redact import redact_text

from trading_pump.graduates import GraduateTracker
from trading_pump.market import PoolReading, PoolSource
from trading_pump.streams.websocket import (
    MIGRATION_SUBSCRIPTION,
    MIGRATION_TX_TYPES,
    run_websocket_stream,
    send_ws_message,
)

logger = logging.getLogger("trading_pump.feed")

CONDITION_FEED = "pumpportal feed"
CONDITION_RPC = "solana rpc"
# Every RPC endpoint serves a network other than mainnet-beta (BUG-160).
CONDITION_NETWORK = "rpc network"


def migration_mint(data: Any) -> str | None:
    """The mint of a PumpPortal migration message, else ``None``."""
    if not isinstance(data, dict):
        return None
    mint = data.get("mint")
    if not mint or str(data.get("txType") or "").lower() not in MIGRATION_TX_TYPES:
        return None
    return str(mint)


@dataclass
class MigrationFeed:
    """A ``WebSocketStreamHost`` that only listens for migrations."""

    on_migration: Callable[[str], None]
    connect_url: Callable[[], str]
    stream_url: str
    reconnect_delay_seconds: float = 1.0
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 1800.0
    on_state: Callable[[bool, str], None] | None = None
    connected: bool = False
    stats: dict[str, int] = field(default_factory=dict)
    last_message_at: float | None = None
    _stop: bool = False
    clock: Callable[[], float] = time.time

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def _state(self, connected: bool, detail: str = "") -> None:
        self.connected = connected
        if self.on_state is not None:
            self.on_state(connected, detail)

    def stop(self) -> None:
        self._stop = True

    # -- WebSocketStreamHost --------------------------------------------------
    def stream_stop_requested(self) -> bool:
        return self._stop

    def stream_connect_url(self) -> str:
        return self.connect_url()

    def stream_log(self, message: str, level: int = logging.INFO) -> None:
        logger.log(level, "%s", redact_text(message))

    async def on_stream_connected(self, ws: Any) -> None:
        self._count("connects")
        await send_ws_message(ws, MIGRATION_SUBSCRIPTION)
        self._state(True)

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        self._count("messages")
        self.last_message_at = self.clock()
        mint = migration_mint(data)
        if mint is not None:
            self._count("migrations")
            self.on_migration(mint)

    def on_stream_error(self, message: str) -> None:
        self._count("errors")
        self.stream_log(message, logging.WARNING)
        self._state(False, message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._count("errors")
        self.stream_log(
            f"stream failed: {exc}; retry in {backoff:.0f}s", logging.WARNING
        )
        self._state(False, str(exc))

    def on_stream_ended(self) -> None:
        self._count("disconnects")
        self._state(False, "connection closed")

    def on_stream_closed(self) -> None:
        if self.connected:
            self._state(False, "connection closed")

    async def run(self) -> None:
        await run_websocket_stream(self)


ReadingSink = Callable[[PoolReading], None]


@dataclass
class PoolPoller:
    """Reads due graduates and held mints; see the module docstring."""

    source: PoolSource
    tracker: GraduateTracker
    held: Callable[[], Iterable[str]]
    on_reading: ReadingSink
    on_success: Callable[[], None]
    on_failure: Callable[[str], None]
    clock: Callable[[], float] = time.time
    stats: dict[str, int] = field(default_factory=dict)
    last_error: str = ""

    def _count(self, key: str, value: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + value

    def due(self, now: float) -> list[str]:
        mints = list(dict.fromkeys([*self.held(), *self.tracker.due(now)]))
        return mints

    async def poll_once(self, now: float | None = None) -> int:
        """Expire, then read every due pool once; returns readings taken."""
        moment = self.clock() if now is None else float(now)
        self.tracker.expire(moment)
        mints = self.due(moment)
        if not mints:
            return 0
        try:
            readings, rejected = await self.source.read_pools(mints, now=moment)
        except Exception as exc:
            self._count("poll_errors")
            self.last_error = redact_text(str(exc))[:200]
            self.on_failure(self.last_error)
            return 0
        self._count("polls")
        self.on_success()
        for reading in readings.values():
            self.on_reading(reading)
            self.tracker.update(reading)
        for mint, reason in rejected.items():
            self._count(f"rejected_{reason}")
            self.tracker.rejected(mint, reason, moment)
        self._count("readings", len(readings))
        return len(readings)

    async def run(
        self,
        interval: float,
        stop: Callable[[], bool],
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        """Poll every ``interval`` seconds until ``stop()``."""
        pause = sleep or asyncio.sleep
        while not stop():
            try:
                await self.poll_once()
            except Exception as exc:  # a bug must not end the poller
                self._count("loop_errors")
                logger.warning("pool poll failed: %s", redact_text(str(exc)))
            await pause(interval)


__all__ = [
    "CONDITION_FEED",
    "CONDITION_NETWORK",
    "CONDITION_RPC",
    "MigrationFeed",
    "PoolPoller",
    "migration_mint",
]
