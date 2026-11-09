"""A push feed for the graduates' pools, beside the poller (FEAT-174), record-only.

The poller reads each followed pool every 2 s for its first 300 s, so a
move is about a second old when seen and a peak between two reads is
missed; every pump arm is positive with a 1.5 s fill and negative with 3 s.
This feed asks the RPC to push each change instead, and writes it beside
the poller's readings in the same capture, so the read-out can say how much
sooner a move is seen and how many the 2 s reads miss.

* :class:`VaultPushFeed` holds one RPC WebSocket (``PUMPFUN_RPC_WS_URL``)
  with one ``accountSubscribe`` per vault of each followed pool, at
  ``processed`` commitment by default, from the pool's first reading until
  ``seconds`` after its migration (the poller's fast window). It is not a
  stream over the whole PumpSwap program, which FEAT-77 measured at 47
  messages a second.
* Each push is a ``vault_push`` row: the mint, the vault and its side of
  the pool, the token amount, the slot and the time it was received.
* Subscriptions are sent and ended by :meth:`VaultPushFeed.flush`, which
  the module calls every ``flush_interval_seconds``; a reconnect subscribes
  every live vault again. At most ``max_vaults`` vaults are followed at
  once: a graduate beyond that is counted, not followed.

Nothing here decides a trade: the lanes read the poller's rows only.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from trading_core.ops.redact import redact_text
from trading_core.ops.stream import run_websocket_stream, send_ws_message

from trading_pump.config.settings import PushSettings
from trading_pump.sdk.pumpswap import (
    PumpSwapPoolUnavailableError,
    token_account_amount,
)

logger = logging.getLogger("trading_pump.push")

CONDITION_PUSH_FEED = "push feed"
VAULT_PUSH_EVENT = "vault_push"
ACCOUNT_SUBSCRIBE = "accountSubscribe"
ACCOUNT_UNSUBSCRIBE = "accountUnsubscribe"
ACCOUNT_NOTIFICATION = "accountNotification"
SIDES = ("base", "quote")

Recorder = Callable[[dict[str, Any]], None]


@dataclass
class VaultWatch:
    """One vault being pushed: whose, which side, until when."""

    mint: str
    side: str
    vault: str
    until: float
    source: str
    subscription: int | None = None


def account_amount(value: dict[str, Any]) -> int | None:
    """The token amount of an ``accountNotification``'s account, else
    ``None`` (a closed or malformed account)."""
    try:
        raw = base64.b64decode(value["data"][0])
        return int(token_account_amount(raw))
    except (KeyError, IndexError, TypeError, ValueError, PumpSwapPoolUnavailableError):
        return None


@dataclass(kw_only=True)
class VaultPushFeed:
    """A ``WebSocketStreamHost`` holding the vault subscriptions; see the
    module docstring. ``connect_url()`` may carry the provider's key and is
    never logged; ``stream_url`` is what is shown."""

    connect_url: Callable[[], str]
    stream_url: str
    settings: PushSettings
    record: Recorder
    clock: Callable[[], float] = time.time
    on_state: Callable[[bool, str], None] | None = None
    reconnect_delay_seconds: float = 1.0
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 1800.0
    watches: dict[str, VaultWatch] = field(default_factory=dict)
    mints: set[str] = field(default_factory=set)
    connected: bool = False
    stats: dict[str, int] = field(default_factory=dict)
    ws: Any = None
    _queued: list[str] = field(default_factory=list)
    _ending: list[int] = field(default_factory=list)
    _pending: dict[int, str] = field(default_factory=dict)
    _by_subscription: dict[int, str] = field(default_factory=dict)
    _next_id: int = 0
    _stop: bool = False

    def _count(self, key: str, value: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + value

    def _state(self, connected: bool, detail: str = "") -> None:
        self.connected = connected
        if not connected:
            self.ws = None
        if self.on_state is not None:
            self.on_state(connected, detail)

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        await run_websocket_stream(self)

    # -- what to follow ------------------------------------------------------
    def watch(
        self,
        mint: str,
        vaults: tuple[str, str],
        *,
        migrated_at: float,
        source: str,
    ) -> bool:
        """Follow ``mint``'s two vaults until ``seconds`` after its migration;
        ``False`` when it is followed already, its window is over or the list
        is full."""
        if mint in self.mints:
            return False
        until = float(migrated_at) + float(self.settings.seconds)
        if self.clock() >= until:
            self._count("too_late")
            return False
        if len(self.watches) + len(SIDES) > int(self.settings.max_vaults):
            self._count("list_full")
            return False
        self.mints.add(mint)
        for side, vault in zip(SIDES, vaults, strict=True):
            self.watches[vault] = VaultWatch(mint, side, vault, until, source)
            self._queued.append(vault)
        self._count("followed")
        return True

    def _expire(self, now: float) -> None:
        for vault, entry in list(self.watches.items()):
            if now < entry.until:
                continue
            del self.watches[vault]
            self.mints.discard(entry.mint)
            if entry.subscription is not None:
                self._by_subscription.pop(entry.subscription, None)
                self._ending.append(entry.subscription)
            self._count("ended")

    def _request_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def flush(self, now: float | None = None) -> None:
        """End the vaults past their window and send what is queued (only
        while connected: a reconnect sends every live vault again)."""
        self._expire(self.clock() if now is None else float(now))
        ws = self.ws
        if ws is None:
            return
        # Each item leaves its queue only once sent: a send that fails (a
        # closing socket) is tried again on the next flush or connect.
        while self._ending:
            await send_ws_message(
                ws,
                {
                    "jsonrpc": "2.0",
                    "id": self._request_id(),
                    "method": ACCOUNT_UNSUBSCRIBE,
                    "params": [self._ending[0]],
                },
            )
            self._ending.pop(0)
        while self._queued:
            vault = self._queued[0]
            if vault in self.watches:
                await self._subscribe(ws, vault)
            self._queued.pop(0)

    async def _subscribe(self, ws: Any, vault: str) -> None:
        request_id = self._request_id()
        self._pending[request_id] = vault
        await send_ws_message(
            ws,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": ACCOUNT_SUBSCRIBE,
                "params": [
                    vault,
                    {"encoding": "base64", "commitment": self.settings.commitment},
                ],
            },
        )
        self._count("subscribe_requests")

    async def maintain(
        self,
        stop: Callable[[], bool],
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        """Flush every ``flush_interval_seconds`` until ``stop()``."""
        pause = sleep or asyncio.sleep
        while not stop():
            try:
                await self.flush()
            except Exception as exc:  # a closing socket must not end the loop
                self._count("flush_errors")
                logger.debug("push flush failed: %s", redact_text(str(exc)))
            await pause(float(self.settings.flush_interval_seconds))

    # -- messages --------------------------------------------------------------
    def _reply(self, data: dict[str, Any]) -> None:
        request_id = data.get("id")
        vault = (
            self._pending.pop(request_id, None) if isinstance(request_id, int) else None
        )
        if vault is None:
            return
        entry = self.watches.get(vault)
        result = data.get("result")
        if entry is None or not isinstance(result, int) or isinstance(result, bool):
            self._count("subscribe_refused")
            return
        entry.subscription = result
        self._by_subscription[result] = vault
        self._count("subscribed")

    def _push(self, params: dict[str, Any]) -> None:
        subscription = params.get("subscription")
        vault = (
            self._by_subscription.get(subscription)
            if isinstance(subscription, int)
            else None
        )
        entry = self.watches.get(vault) if vault is not None else None
        if entry is None:
            self._count("unknown_pushes")
            return
        result = params.get("result") or {}
        amount = account_amount(result.get("value") or {})
        self._count("pushes")
        self.record(
            {
                "timestamp": self.clock(),
                "event": VAULT_PUSH_EVENT,
                "mint": entry.mint,
                "source": entry.source,
                "side": entry.side,
                "vault": entry.vault,
                "amount": amount,
                "slot": (result.get("context") or {}).get("slot"),
            }
        )

    # -- WebSocketStreamHost ------------------------------------------------------
    def stream_stop_requested(self) -> bool:
        return self._stop

    def stream_connect_url(self) -> str:
        return self.connect_url()

    def stream_log(self, message: str, level: int = logging.INFO) -> None:
        logger.log(level, "%s", redact_text(message))

    async def on_stream_connected(self, ws: Any) -> None:
        self._count("connects")
        self._pending.clear()
        self._by_subscription.clear()
        self._ending.clear()
        for entry in self.watches.values():
            entry.subscription = None
        self._queued = list(self.watches)
        self.ws = ws
        self._state(True)
        await self.flush()

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        if not isinstance(data, dict):
            return
        if data.get("method") == ACCOUNT_NOTIFICATION:
            self._push(data.get("params") or {})
        elif "id" in data:
            self._reply(data)

    def on_stream_error(self, message: str) -> None:
        self._count("errors")
        self.stream_log(message, logging.WARNING)
        self._state(False, message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._count("errors")
        self.stream_log(
            f"push stream failed: {exc}; retry in {backoff:.0f}s", logging.WARNING
        )
        self._state(False, redact_text(str(exc)))

    def on_stream_ended(self) -> None:
        self._count("disconnects")
        self._state(False, "connection closed")

    def on_stream_closed(self) -> None:
        if self.connected:
            self._state(False, "connection closed")

    def status_text(self) -> str:
        state = "connected" if self.connected else "disconnected"
        return (
            f"{state} · {len(self.mints)} pools · "
            f"{self.stats.get('pushes', 0)} pushes"
        )


__all__ = [
    "ACCOUNT_NOTIFICATION",
    "ACCOUNT_SUBSCRIBE",
    "ACCOUNT_UNSUBSCRIBE",
    "CONDITION_PUSH_FEED",
    "SIDES",
    "VAULT_PUSH_EVENT",
    "VaultPushFeed",
    "VaultWatch",
    "account_amount",
]
