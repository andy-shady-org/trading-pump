"""New PumpSwap pools that are not Pump.fun graduations (FEAT-80), record-only.

The trading-scout run found about 60 new PumpSwap pools an hour that never
came through PumpPortal's migration feed (other launchpads' and hand-made
SOL pairs), more than the graduations, and with sharper first-hour moves.
This module finds them on-chain and hands them to the graduate tracker,
which follows and records them like graduates (``source: "new_pool"``);
no lane ever trades them.

* :class:`NewPoolFeed` holds ``programSubscribe`` subscriptions on the
  PumpSwap program, filtered to pool accounts (301 bytes, and 287 for a
  layout many new pools still have). PumpSwap writes the pool account on
  every swap, so the stream carries every pool that trades (about 47-73
  messages and 36 kB a second, measured 2026-10-31), not only new ones.
  The pools seen during ``warmup_seconds`` are the busy existing ones and
  are only remembered; after that a pool seen for the first time is passed
  on.
* :class:`NewPoolWatcher` decides what such a pool is. A canonical pool is
  a graduate's (an old one trading, or a migration PumpPortal reports): it
  is only counted. Any other pool with SOL on one side is looked up (its
  signatures: when it was created, and the coin's decimals), and one created
  at most ``max_age_seconds`` ago is followed. Most of these pools hold SOL
  as their *base* and the coin as the quote, the reverse of a graduation
  pool (GeckoTerminal shows them flipped); both orders are read.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from trading_core.ops.redact import redact_text

from trading_pump.config.settings import NewPoolSettings
from trading_pump.graduates import GraduateTracker
from trading_pump.market import NewPoolInfo
from trading_pump.sdk.execution_types import WSOL_MINT_STR
from trading_pump.sdk.pumpswap import (
    PUMP_AMM_PROGRAM_ID,
    PumpSwapPool,
    canonical_pool_address,
    decode_pool,
)
from trading_pump.streams.websocket import run_websocket_stream, send_ws_message

logger = logging.getLogger("trading_pump.pools")

CONDITION_POOL_FEED = "pumpswap pool feed"
# Pool account sizes: the current program version's, and an older layout
# (no trailing padding) that many new non-graduate pools still have.
POOL_ACCOUNT_SIZES = (301, 287)
POOL_SUBSCRIPTIONS: tuple[dict[str, Any], ...] = tuple(
    {
        "jsonrpc": "2.0",
        "id": index,
        "method": "programSubscribe",
        "params": [
            PUMP_AMM_PROGRAM_ID,
            {
                "encoding": "base64",
                "commitment": "confirmed",
                "filters": [{"dataSize": size}],
            },
        ],
    }
    for index, size in enumerate(POOL_ACCOUNT_SIZES, start=1)
)
POOL_CREATED_EVENT = "pool_created"

PoolHandler = Callable[[str, bytes, int], None]
Recorder = Callable[[dict[str, Any]], None]


def pool_notice(data: Any) -> tuple[str, bytes, int] | None:
    """``(pool address, account bytes, slot)`` of a ``programNotification``,
    else ``None`` (the subscription's confirmation, malformed messages)."""
    if not isinstance(data, dict) or data.get("method") != "programNotification":
        return None
    try:
        result = data["params"]["result"]
        value = result["value"]
        raw = base64.b64decode(value["account"]["data"][0])
        return str(value["pubkey"]), raw, int(result["context"]["slot"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


@dataclass
class NewPoolFeed:
    """A ``WebSocketStreamHost`` on the Solana RPC WebSocket; see the module
    docstring. ``on_pool`` gets each pool seen for the first time after the
    warm-up, with its account bytes and slot."""

    on_pool: PoolHandler
    connect_url: Callable[[], str]
    stream_url: str
    warmup_seconds: float = 1800.0
    reconnect_delay_seconds: float = 1.0
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 60.0
    on_state: Callable[[bool, str], None] | None = None
    clock: Callable[[], float] = time.time
    connected: bool = False
    stats: dict[str, int] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)
    started_at: float | None = None
    _stop: bool = False

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def _state(self, connected: bool, detail: str = "") -> None:
        self.connected = connected
        if self.on_state is not None:
            self.on_state(connected, detail)

    def warming_up(self, now: float) -> bool:
        return self.started_at is None or now - self.started_at < self.warmup_seconds

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
        if self.started_at is None:
            # The warm-up runs once: a reconnect keeps what was seen.
            self.started_at = self.clock()
        for subscription in POOL_SUBSCRIPTIONS:
            await send_ws_message(ws, subscription)
        self._state(True)

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        notice = pool_notice(data)
        if notice is None:
            return
        address, raw, slot = notice
        self._count("messages")
        if address in self.seen:
            return
        self.seen.add(address)
        if self.warming_up(self.clock()):
            self._count("warmup_pools")
            return
        self._count("first_seen")
        self.on_pool(address, raw, slot)

    def on_stream_error(self, message: str) -> None:
        self._count("errors")
        self.stream_log(message, logging.WARNING)
        self._state(False, message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._count("errors")
        self.stream_log(
            f"pool stream failed: {exc}; retry in {backoff:.0f}s", logging.WARNING
        )
        self._state(False, redact_text(str(exc)))

    def on_stream_ended(self) -> None:
        self._count("disconnects")
        self._state(False, "connection closed")

    def on_stream_closed(self) -> None:
        if self.connected:
            self._state(False, "connection closed")

    async def run(self) -> None:
        await run_websocket_stream(self)


def is_canonical(pool: PumpSwapPool) -> bool:
    """The pool a Pump.fun migration creates for its mint."""
    try:
        return str(canonical_pool_address(pool.base_mint, pool.quote_mint)) == (
            pool.address
        )
    except Exception:
        return False


def sol_side(pool: PumpSwapPool) -> tuple[str, bool] | None:
    """``(coin mint, SOL is the base)`` of a pool paired with SOL, else
    ``None`` (two coins, or SOL on both sides)."""
    base_sol = pool.base_mint == WSOL_MINT_STR
    quote_sol = pool.quote_mint == WSOL_MINT_STR
    if base_sol == quote_sol:
        return None
    return (pool.quote_mint, True) if base_sol else (pool.base_mint, False)


@dataclass
class NewPoolWatcher:
    """Classifies first-seen pools and starts following the new ones."""

    settings: NewPoolSettings
    tracker: GraduateTracker
    source: Any
    record: Recorder
    clock: Callable[[], float] = time.time
    stats: dict[str, int] = field(default_factory=dict)
    last_error: str = ""
    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _slots: asyncio.Semaphore | None = None

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def on_pool(self, address: str, raw: bytes, slot: int) -> None:
        """A pool seen for the first time (sync: the feed's callback)."""
        try:
            pool = decode_pool(address, raw)
        except Exception:
            self._count("decode_errors")
            return
        side = sol_side(pool)
        if is_canonical(pool):
            self._count("canonical")
        elif side is None:
            self._count("not_sol_pair")
        else:
            self._count("looked_up")
            task = asyncio.get_running_loop().create_task(
                self.inspect(pool, slot, *side)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def inspect(
        self, pool: PumpSwapPool, slot: int, mint: str, sol_is_base: bool
    ) -> None:
        """Look the pool up and follow it when it is new; never raises."""
        if self._slots is None:
            self._slots = asyncio.Semaphore(int(self.settings.max_lookups))
        async with self._slots:
            try:
                info = await self.source.inspect_new_pool(
                    pool.address, mint, limit=int(self.settings.signature_limit)
                )
            except Exception as exc:
                self._count("lookup_errors")
                self.last_error = redact_text(str(exc))[:200]
                return
        self._decide(pool, slot, mint, sol_is_base, info)

    def _decide(
        self,
        pool: PumpSwapPool,
        slot: int,
        mint: str,
        sol_is_base: bool,
        info: NewPoolInfo,
    ) -> None:
        now = self.clock()
        if info.created_at is None or now - info.created_at > float(
            self.settings.max_age_seconds
        ):
            self._count("old_pools")
            return
        self.source.register_pool(
            mint,
            pool.address,
            pool.base_vault,
            pool.quote_vault,
            sol_is_base=sol_is_base,
        )
        details = {
            "found_by": POOL_CREATED_EVENT,
            "created_at": info.created_at,
            "created_exact": info.exact,
            "signatures": info.signatures,
            "decimals": info.decimals,
            "slot": slot,
            "sol_is_base": sol_is_base,
            "virtual_quote_reserves": pool.virtual_quote_reserves,
            "coin_creator": pool.coin_creator,
        }
        if self.tracker.add_new_pool(mint, pool.address, now=now, details=details):
            self._count("followed")

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def status_text(self, feed: NewPoolFeed) -> str:
        state = "connected" if feed.connected else "disconnected"
        if feed.connected and feed.warming_up(self.clock()):
            state += " (warming up)"
        return (
            f"{state} · {self.stats.get('followed', 0)} new followed · "
            f"{self.stats.get('old_pools', 0)} old · "
            f"{self.stats.get('canonical', 0)} graduates' pools skipped"
        )


__all__ = [
    "CONDITION_POOL_FEED",
    "POOL_ACCOUNT_SIZES",
    "POOL_CREATED_EVENT",
    "POOL_SUBSCRIPTIONS",
    "NewPoolFeed",
    "NewPoolWatcher",
    "is_canonical",
    "pool_notice",
    "sol_side",
]
