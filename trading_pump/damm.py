"""New Meteora DAMM v2 pools, record-only (FEAT-107).

trading-scout's scout-1 run (2026-11-02) ranked new Meteora DAMM v2 pools on
Solana first: on 30-second snapshots the FEAT-76 rule made money on them in
both halves and on every day. This module records them on-chain at the
resolution a lane would need; nothing here trades.

* :class:`DammFeed` holds one ``programSubscribe`` on the DAMM v2 program
  (``cp-amm``), filtered to pool accounts (1,112 bytes). The program writes
  the pool account on every swap, so the stream carries every active pool's
  state (37.5 messages and 69 kB a second, measured 2026-11-02): new pools
  are found within a second of their first write, and a followed pool's
  price path needs no polling.
* :class:`DammWatcher` decides which pools to follow (paired with SOL, its
  ``activation_point`` within ``max_age_seconds`` of now) and writes the
  capture rows: ``damm_pool`` when it starts following, ``damm_decimals``
  once the coin's decimals are read, ``damm_state`` on every change of a
  followed pool (and on each heartbeat read), ``damm_end`` when it stops.

The pool layout is the program's ``Pool`` (MeteoraAg/damm-v2 ``5398b5c``,
``programs/cp-amm/src/state/pool.rs``), checked against mainnet accounts on
2026-11-02. The fees are recorded raw (``pool_fees_hex``, 160 bytes): five
base-fee modes and a dynamic fee, worked out when a read-out needs them.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from solders.pubkey import Pubkey
from trading_core.ops.redact import redact_text

from trading_pump.config.settings import DammSettings
from trading_pump.pools import pool_notice
from trading_pump.sdk.execution_types import WSOL_MINT_STR
from trading_pump.streams.websocket import run_websocket_stream, send_ws_message

logger = logging.getLogger("trading_pump.damm")

DAMM_PROGRAM_ID = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"
CONDITION_DAMM_FEED = "damm v2 feed"
POOL_ACCOUNT_SIZE = 1112
POOL_DISCRIMINATOR = bytes.fromhex("f19a6d0411b16dbc")
SOL_DECIMALS = 9
# Seconds per slot, for pools whose activation point is a slot.
SLOT_SECONDS = 0.4
ACTIVATION_BY_TIMESTAMP = 1
POOL_ENABLED = 0
HEARTBEAT_BATCH = 100
# SPL / Token-2022 mint: mint_authority COption (36), supply u64, decimals u8.
MINT_DECIMALS_OFFSET = 44

# Offsets into ``Pool``, after the 8-byte account discriminator.
_BODY = 8
_FEES = (0, 160)
_MINT_A, _MINT_B, _VAULT_A, _VAULT_B = 160, 192, 224, 256
_LIQUIDITY, _SQRT_MIN, _SQRT_MAX, _SQRT_PRICE = 352, 416, 432, 448
_ACTIVATION_POINT, _ACTIVATION_TYPE, _STATUS = 464, 472, 473
_COLLECT_FEE_MODE, _POOL_TYPE, _FEE_VERSION = 476, 477, 478
_CREATOR, _AMOUNT_A, _AMOUNT_B, _LAYOUT_VERSION = 640, 672, 680, 688

SUBSCRIPTION: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "programSubscribe",
    "params": [
        DAMM_PROGRAM_ID,
        {
            "encoding": "base64",
            "commitment": "confirmed",
            "filters": [{"dataSize": POOL_ACCOUNT_SIZE}],
        },
    ],
}

AccountHandler = Callable[[str, bytes, int], None]
Recorder = Callable[[dict[str, Any]], None]
AccountReader = Callable[[list[str]], Awaitable[list[Any]]]


@dataclass(frozen=True)
class DammPool:
    """The fields of a DAMM v2 pool account this capture records."""

    address: str
    token_a_mint: str
    token_b_mint: str
    token_a_vault: str
    token_b_vault: str
    creator: str
    liquidity: int
    sqrt_price: int
    sqrt_min_price: int
    sqrt_max_price: int
    activation_point: int
    activation_type: int
    status: int
    collect_fee_mode: int
    pool_type: int
    fee_version: int
    token_a_amount: int
    token_b_amount: int
    layout_version: int
    pool_fees: bytes

    @property
    def price(self) -> float:
        """Token B per token A in raw units: the Q64.64 ``sqrt_price`` squared."""
        return float(self.sqrt_price / 2**64) ** 2

    def sol_side(self) -> tuple[str, bool] | None:
        """``(coin mint, SOL is token A)`` of a pool paired with SOL, else
        ``None`` (two coins, or SOL on both sides)."""
        a_sol = self.token_a_mint == WSOL_MINT_STR
        b_sol = self.token_b_mint == WSOL_MINT_STR
        if a_sol == b_sol:
            return None
        return (self.token_b_mint, True) if a_sol else (self.token_a_mint, False)

    def sol_amount(self, sol_is_a: bool) -> int | None:
        """Lamports of SOL in the pool, when the layout tracks the amounts."""
        if self.layout_version < 1:
            return None
        return self.token_a_amount if sol_is_a else self.token_b_amount

    def state(self) -> tuple[int, int, int, int, int]:
        """What a ``damm_state`` row records, for spotting repeats."""
        return (
            self.sqrt_price,
            self.liquidity,
            self.token_a_amount,
            self.token_b_amount,
            self.status,
        )


def _u(raw: bytes, offset: int, size: int) -> int:
    start = _BODY + offset
    return int.from_bytes(raw[start : start + size], "little")


def _key(raw: bytes, offset: int) -> str:
    start = _BODY + offset
    return str(Pubkey.from_bytes(raw[start : start + 32]))


def decode_damm_pool(address: str, raw: bytes) -> DammPool:
    """A pool account's bytes; ``ValueError`` when they are not one."""
    if len(raw) != POOL_ACCOUNT_SIZE or raw[:8] != POOL_DISCRIMINATOR:
        raise ValueError(f"{address} is not a DAMM v2 pool account")
    return DammPool(
        address=address,
        token_a_mint=_key(raw, _MINT_A),
        token_b_mint=_key(raw, _MINT_B),
        token_a_vault=_key(raw, _VAULT_A),
        token_b_vault=_key(raw, _VAULT_B),
        creator=_key(raw, _CREATOR),
        liquidity=_u(raw, _LIQUIDITY, 16),
        sqrt_price=_u(raw, _SQRT_PRICE, 16),
        sqrt_min_price=_u(raw, _SQRT_MIN, 16),
        sqrt_max_price=_u(raw, _SQRT_MAX, 16),
        activation_point=_u(raw, _ACTIVATION_POINT, 8),
        activation_type=raw[_BODY + _ACTIVATION_TYPE],
        status=raw[_BODY + _STATUS],
        collect_fee_mode=raw[_BODY + _COLLECT_FEE_MODE],
        pool_type=raw[_BODY + _POOL_TYPE],
        fee_version=raw[_BODY + _FEE_VERSION],
        token_a_amount=_u(raw, _AMOUNT_A, 8),
        token_b_amount=_u(raw, _AMOUNT_B, 8),
        layout_version=raw[_BODY + _LAYOUT_VERSION],
        pool_fees=bytes(raw[_BODY + _FEES[0] : _BODY + _FEES[1]]),
    )


def sol_per_coin(pool: DammPool, sol_is_a: bool, coin_decimals: int) -> float | None:
    """The coin's price in SOL, or ``None`` at a zero price."""
    price = pool.price
    if price <= 0:
        return None
    if sol_is_a:
        coin_per_sol = price * 10 ** (SOL_DECIMALS - coin_decimals)
        return 1.0 / coin_per_sol
    return price * 10 ** (coin_decimals - SOL_DECIMALS)


def activation_age(pool: DammPool, *, now: float, slot: int) -> float:
    """Seconds since the pool's activation point (negative: not yet)."""
    if pool.activation_type == ACTIVATION_BY_TIMESTAMP:
        return now - float(pool.activation_point)
    return (slot - pool.activation_point) * SLOT_SECONDS


def mint_decimals(value: Any) -> int | None:
    """A mint account read's decimals, or ``None``."""
    try:
        raw = base64.b64decode((value.get("data") or [""])[0])
    except Exception:
        return None
    return raw[MINT_DECIMALS_OFFSET] if len(raw) > MINT_DECIMALS_OFFSET else None


def _state_row(
    pool: DammPool, *, now: float, slot: int | None, via: str, price: float | None
) -> dict[str, Any]:
    return {
        "event": "damm_state",
        "timestamp": now,
        "pool": pool.address,
        "slot": slot,
        "via": via,
        "sqrt_price": str(pool.sqrt_price),
        "liquidity": str(pool.liquidity),
        "a_amount": pool.token_a_amount,
        "b_amount": pool.token_b_amount,
        "status": pool.status,
        "price_sol": price,
    }


@dataclass
class Followed:
    """A pool being followed."""

    pool: DammPool
    coin_mint: str
    sol_is_a: bool
    since: float
    decimals: int | None = None
    rows: int = 0
    last_state: tuple[int, int, int, int, int] | None = None

    def price(self, pool: DammPool) -> float | None:
        if self.decimals is None:
            return None
        return sol_per_coin(pool, self.sol_is_a, self.decimals)


@dataclass
class DammWatcher:
    """Chooses the pools to follow and writes their rows; see the module
    docstring. ``read_accounts`` is ``getMultipleAccounts`` (base64 account
    reads, ``None`` for a missing account); without it there are no decimal
    reads or heartbeats."""

    settings: DammSettings
    record: Recorder
    read_accounts: AccountReader | None = None
    clock: Callable[[], float] = time.time
    followed: dict[str, Followed] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    stats: dict[str, int] = field(default_factory=dict)
    last_error: str = ""
    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    def on_account(self, address: str, raw: bytes, slot: int) -> None:
        """One pool write from the stream (sync: the feed's callback)."""
        followed = self.followed.get(address)
        if followed is not None:
            self._update(followed, raw, slot, via="stream")
        elif address not in self.skipped:
            self._consider(address, raw, slot)

    def _consider(self, address: str, raw: bytes, slot: int) -> None:
        try:
            pool = decode_damm_pool(address, raw)
        except ValueError:
            self._count("decode_errors")
            self.skipped.add(address)
            return
        reason = self._refusal(pool, slot)
        if reason is not None:
            self._count(reason)
            if reason != "list_full":
                self.skipped.add(address)
            return
        self._follow(pool, slot)

    def _refusal(self, pool: DammPool, slot: int) -> str | None:
        if pool.sol_side() is None:
            return "not_sol_pair"
        age = activation_age(pool, now=self.clock(), slot=slot)
        if age > float(self.settings.max_age_seconds):
            return "old_pools"
        if age < -float(self.settings.max_future_seconds):
            return "far_future"
        if len(self.followed) >= int(self.settings.max_followed):
            return "list_full"
        return None

    def _follow(self, pool: DammPool, slot: int) -> None:
        coin, sol_is_a = pool.sol_side() or ("", False)
        now = self.clock()
        followed = Followed(pool, coin, sol_is_a, since=now)
        self.followed[pool.address] = followed
        self._count("followed")
        self.record(
            {
                "event": "damm_pool",
                "timestamp": now,
                "pool": pool.address,
                "slot": slot,
                "coin_mint": coin,
                "sol_is_a": sol_is_a,
                "creator": pool.creator,
                "activation_point": pool.activation_point,
                "activation_type": pool.activation_type,
                "age_seconds": activation_age(pool, now=now, slot=slot),
                "pool_type": pool.pool_type,
                "collect_fee_mode": pool.collect_fee_mode,
                "fee_version": pool.fee_version,
                "sqrt_min_price": str(pool.sqrt_min_price),
                "sqrt_max_price": str(pool.sqrt_max_price),
                "pool_fees_hex": pool.pool_fees.hex(),
            }
        )
        self._write_state(followed, pool, slot=slot, via="stream", now=now)
        if self.read_accounts is not None:
            task = asyncio.get_running_loop().create_task(self._read_decimals(followed))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _read_decimals(self, followed: Followed) -> None:
        """The coin's decimals, read once; never raises."""
        assert self.read_accounts is not None
        try:
            (value,) = await self.read_accounts([followed.coin_mint])
        except Exception as exc:
            self._count("read_errors")
            self.last_error = redact_text(str(exc))[:200]
            return
        decimals = mint_decimals(value) if value else None
        if decimals is None:
            self._count("decimals_unread")
            return
        followed.decimals = decimals
        self.record(
            {
                "event": "damm_decimals",
                "timestamp": self.clock(),
                "pool": followed.pool.address,
                "coin_mint": followed.coin_mint,
                "decimals": decimals,
            }
        )

    def _update(
        self, followed: Followed, raw: bytes, slot: int | None, via: str
    ) -> None:
        try:
            pool = decode_damm_pool(followed.pool.address, raw)
        except ValueError:
            self._count("decode_errors")
            return
        if via == "stream" and pool.state() == followed.last_state:
            self._count("unchanged")
            return
        self._write_state(followed, pool, slot=slot, via=via, now=self.clock())

    def _write_state(
        self,
        followed: Followed,
        pool: DammPool,
        *,
        slot: int | None,
        via: str,
        now: float,
    ) -> None:
        followed.pool = pool
        followed.last_state = pool.state()
        followed.rows += 1
        self._count("state_rows")
        self.record(
            _state_row(pool, now=now, slot=slot, via=via, price=followed.price(pool))
        )

    def end(self, address: str, cause: str) -> None:
        followed = self.followed.pop(address, None)
        if followed is None:
            return
        self.skipped.add(address)
        self._count(f"ended_{cause}")
        now = self.clock()
        self.record(
            {
                "event": "damm_end",
                "timestamp": now,
                "pool": address,
                "cause": cause,
                "followed_seconds": now - followed.since,
                "rows": followed.rows,
            }
        )

    async def heartbeat(self) -> None:
        """End the pools followed long enough, then read the rest once."""
        now = self.clock()
        for address, followed in list(self.followed.items()):
            if now - followed.since >= float(self.settings.follow_seconds):
                self.end(address, "follow_time")
        if self.read_accounts is None or not self.followed:
            return
        addresses = list(self.followed)
        for start in range(0, len(addresses), HEARTBEAT_BATCH):
            await self._heartbeat_batch(addresses[start : start + HEARTBEAT_BATCH])

    async def _heartbeat_batch(self, addresses: Sequence[str]) -> None:
        assert self.read_accounts is not None
        try:
            values = await self.read_accounts(list(addresses))
        except Exception as exc:
            self._count("read_errors")
            self.last_error = redact_text(str(exc))[:200]
            return
        self._count("heartbeats")
        for address, value in zip(addresses, values, strict=True):
            self._heartbeat_one(address, value)

    def _heartbeat_one(self, address: str, value: Any) -> None:
        followed = self.followed.get(address)
        if followed is None:
            return
        if not value:
            self.end(address, "closed")
            return
        try:
            raw = base64.b64decode((value.get("data") or [""])[0])
        except Exception:
            self._count("decode_errors")
            return
        self._update(followed, raw, None, via="heartbeat")

    async def run_heartbeats(
        self, stopping: Callable[[], bool], sleep: Callable[[float], Awaitable[Any]]
    ) -> None:
        """Heartbeats every ``heartbeat_seconds`` until ``stopping()``."""
        while not stopping():
            await sleep(float(self.settings.heartbeat_seconds))
            if not stopping():
                await self.heartbeat()

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def status_text(self, feed: DammFeed) -> str:
        state = "connected" if feed.connected else "disconnected"
        return (
            f"{state} · {len(self.followed)} followed · "
            f"{self.stats.get('followed', 0)} found · "
            f"{feed.stats.get('messages', 0)} writes"
        )


@dataclass
class DammFeed:
    """A ``WebSocketStreamHost`` on a Solana RPC WebSocket: every DAMM v2 pool
    write goes to ``on_account``; ``on_message`` is told of each one (the
    module marks market data fresh with it)."""

    on_account: AccountHandler
    connect_url: Callable[[], str]
    stream_url: str
    reconnect_delay_seconds: float = 1.0
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 60.0
    on_state: Callable[[bool, str], None] | None = None
    on_message: Callable[[], None] | None = None
    connected: bool = False
    stats: dict[str, int] = field(default_factory=dict)
    _stop: bool = False

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
        await send_ws_message(ws, SUBSCRIPTION)
        self._state(True)

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        notice = pool_notice(data)
        if notice is None:
            return
        self._count("messages")
        if self.on_message is not None:
            self.on_message()
        self.on_account(*notice)

    def on_stream_error(self, message: str) -> None:
        self._count("errors")
        self.stream_log(message, logging.WARNING)
        self._state(False, message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._count("errors")
        self.stream_log(
            f"DAMM v2 stream failed: {exc}; retry in {backoff:.0f}s", logging.WARNING
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


__all__ = [
    "CONDITION_DAMM_FEED",
    "DAMM_PROGRAM_ID",
    "POOL_ACCOUNT_SIZE",
    "POOL_DISCRIMINATOR",
    "SUBSCRIPTION",
    "DammFeed",
    "DammPool",
    "DammWatcher",
    "Followed",
    "activation_age",
    "decode_damm_pool",
    "mint_decimals",
    "sol_per_coin",
]
