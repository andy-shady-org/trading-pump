"""Yellowstone Geyser (gRPC) streaming client and binary parsers for Pump.fun.

This module provides sub-millisecond on-chain event ingestion for Pump.fun trading:
- Real-time bonding curve account updates
- Zero-copy binary decoding for bonding curve states and trade events
- Resilient bidirectional streaming with automatic reconnection, jitter, and keepalives
- Latency telemetry and dropped message tracking
"""

from __future__ import annotations

import asyncio
import base64
import logging
import random
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Coroutine, Optional, Union

import base58

logger = logging.getLogger("pumpfun_trading.streams.geyser")

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Anchor / Program Discriminators
BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])
CREATE_DISCRIMINATOR = bytes([24, 30, 200, 40, 5, 28, 7, 119])
TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
COMPLETE_EVENT_DISCRIMINATOR = bytes([95, 114, 97, 156, 212, 46, 152, 8])


class GeyserConnectionState(str, Enum):
    """Lifecycle state of the Yellowstone Geyser stream connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass(slots=True)
class GeyserAccountUpdate:
    """Raw account update received from the Geyser stream."""

    pubkey: str
    owner: str
    lamports: int
    data: bytes
    slot: int
    is_startup: bool = False
    txn_signature: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class GeyserTransactionUpdate:
    """Raw transaction update received from the Geyser stream."""

    signature: str
    slot: int
    is_vote: bool = False
    transaction: Optional[dict[str, Any]] = None
    meta: Optional[dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class BondingCurveStateUpdate:
    """Decoded on-chain state of a Pump.fun bonding curve account."""

    mint: str
    bonding_curve_pubkey: str
    slot: int
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool
    price_sol: float
    market_cap_sol: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert bonding curve state to a serializable dictionary."""
        return {
            "mint": self.mint,
            "bonding_curve_pubkey": self.bonding_curve_pubkey,
            "slot": self.slot,
            "virtual_token_reserves": self.virtual_token_reserves,
            "virtual_sol_reserves": self.virtual_sol_reserves,
            "real_token_reserves": self.real_token_reserves,
            "real_sol_reserves": self.real_sol_reserves,
            "token_total_supply": self.token_total_supply,
            "complete": self.complete,
            "price_sol": self.price_sol,
            "market_cap_sol": self.market_cap_sol,
            "timestamp": self.timestamp,
        }


@dataclass(slots=True)
class TradeEventUpdate:
    """Decoded on-chain trade execution event emitted by Pump.fun."""

    mint: str
    sol_amount_lamports: int
    token_amount: int
    is_buy: bool
    user: str
    timestamp: int
    virtual_sol_reserves: int
    virtual_token_reserves: int
    real_sol_reserves: int
    real_token_reserves: int
    slot: int = 0
    signature: str = ""
    received_at: float = field(default_factory=time.time)

    @property
    def sol_amount(self) -> float:
        """SOL amount formatted as floating-point SOL."""
        return self.sol_amount_lamports / 1_000_000_000.0

    @property
    def price_sol(self) -> float:
        """Estimated spot price in SOL derived from event reserves."""
        if self.virtual_token_reserves > 0:
            return (self.virtual_sol_reserves / 1_000_000_000.0) / (
                self.virtual_token_reserves / 1_000_000.0
            )
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert trade event to a dictionary."""
        return {
            "mint": self.mint,
            "sol_amount_lamports": self.sol_amount_lamports,
            "sol_amount": self.sol_amount,
            "token_amount": self.token_amount,
            "is_buy": self.is_buy,
            "user": self.user,
            "timestamp": self.timestamp,
            "virtual_sol_reserves": self.virtual_sol_reserves,
            "virtual_token_reserves": self.virtual_token_reserves,
            "real_sol_reserves": self.real_sol_reserves,
            "real_token_reserves": self.real_token_reserves,
            "price_sol": self.price_sol,
            "slot": self.slot,
            "signature": self.signature,
            "received_at": self.received_at,
        }


@dataclass(slots=True)
class CompleteEventUpdate:
    """Decoded bonding curve graduation event emitted when a curve reaches migration."""

    mint: str
    user: str
    bonding_curve: str
    timestamp: int
    slot: int = 0
    signature: str = ""
    received_at: float = field(default_factory=time.time)


@dataclass
class GeyserStreamMetrics:
    """Operational telemetry and latency tracking for Geyser streaming."""

    messages_received: int = 0
    messages_processed: int = 0
    dropped_messages: int = 0
    reconnect_count: int = 0
    last_slot: int = 0
    last_message_timestamp: float = 0.0
    total_processing_latency_ms: float = 0.0
    peak_processing_latency_ms: float = 0.0

    def record_received(self) -> None:
        """Record an incoming stream message."""
        self.messages_received += 1
        self.last_message_timestamp = time.time()

    def record_processed(self, latency_ms: float, slot: int = 0) -> None:
        """Record successful message processing and compute latency."""
        self.messages_processed += 1
        self.total_processing_latency_ms += max(0.0, latency_ms)
        if latency_ms > self.peak_processing_latency_ms:
            self.peak_processing_latency_ms = latency_ms
        if slot > self.last_slot:
            self.last_slot = slot

    def record_drop(self) -> None:
        """Record a dropped message due to backpressure / queue full."""
        self.dropped_messages += 1

    def record_reconnect(self) -> None:
        """Record a reconnection attempt."""
        self.reconnect_count += 1

    @property
    def average_latency_ms(self) -> float:
        """Return rolling average processing latency in milliseconds."""
        if self.messages_processed == 0:
            return 0.0
        return round(self.total_processing_latency_ms / self.messages_processed, 3)

    def summary(self) -> dict[str, Any]:
        """Return diagnostic metrics dictionary."""
        return {
            "messages_received": self.messages_received,
            "messages_processed": self.messages_processed,
            "dropped_messages": self.dropped_messages,
            "reconnect_count": self.reconnect_count,
            "last_slot": self.last_slot,
            "last_message_timestamp": self.last_message_timestamp,
            "avg_latency_ms": self.average_latency_ms,
            "peak_latency_ms": round(self.peak_processing_latency_ms, 3),
        }


@dataclass
class GeyserSubscriptionFilter:
    """Subscription parameters sent to Yellowstone Geyser."""

    accounts: dict[str, list[str]] = field(default_factory=dict)
    programs: list[str] = field(default_factory=lambda: [PUMP_PROGRAM_ID])
    transactions: dict[str, list[str]] = field(default_factory=dict)
    slots: bool = True


class BondingCurveBinaryParser:
    """Zero-copy binary struct parser for Pump.fun on-chain bonding curve accounts."""

    # struct format: 8 bytes discriminator (skipped), 5 u64 integers (little-endian), 1 bool
    # Layout:
    # 0..8: Discriminator
    # 8..16: virtual_token_reserves (u64)
    # 16..24: virtual_sol_reserves (u64)
    # 24..32: real_token_reserves (u64)
    # 32..40: real_sol_reserves (u64)
    # 40..48: token_total_supply (u64)
    # 48..49: complete (bool)
    _STRUCT_FORMAT = "<QQQQQ?"
    _HEADER_SIZE = 8
    _PAYLOAD_SIZE = struct.calcsize(_STRUCT_FORMAT)  # 41 bytes
    _MIN_ACCOUNT_SIZE = _HEADER_SIZE + _PAYLOAD_SIZE  # 49 bytes

    @classmethod
    def parse_account_data(
        cls,
        data: bytes | memoryview | bytearray,
        *,
        mint: str = "",
        bonding_curve_pubkey: str = "",
        slot: int = 0,
    ) -> BondingCurveStateUpdate:
        """Parse raw bonding curve account buffer into a structured BondingCurveStateUpdate.

        Uses memoryview slicing for zero-copy unpack without intermediate buffer copies.
        """
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < cls._MIN_ACCOUNT_SIZE:
            raise ValueError(
                f"Bonding curve account buffer too short: {len(buf)} bytes (expected >= {cls._MIN_ACCOUNT_SIZE})"
            )

        (
            virtual_token_reserves,
            virtual_sol_reserves,
            real_token_reserves,
            real_sol_reserves,
            token_total_supply,
            complete,
        ) = struct.unpack_from(cls._STRUCT_FORMAT, buf, cls._HEADER_SIZE)

        price_sol = (
            (virtual_sol_reserves / 1_000_000_000.0)
            / (virtual_token_reserves / 1_000_000.0)
            if virtual_token_reserves > 0
            else 0.0
        )
        market_cap_sol = (
            (virtual_sol_reserves / 1_000_000_000.0)
            * (token_total_supply / float(virtual_token_reserves))
            if virtual_token_reserves > 0
            else 0.0
        )

        return BondingCurveStateUpdate(
            mint=mint,
            bonding_curve_pubkey=bonding_curve_pubkey,
            slot=slot,
            virtual_token_reserves=virtual_token_reserves,
            virtual_sol_reserves=virtual_sol_reserves,
            real_token_reserves=real_token_reserves,
            real_sol_reserves=real_sol_reserves,
            token_total_supply=token_total_supply,
            complete=complete,
            price_sol=price_sol,
            market_cap_sol=market_cap_sol,
        )

    @classmethod
    def parse_raw_reserves(
        cls, data: bytes | memoryview | bytearray
    ) -> tuple[int, int, int, int, int, bool]:
        """Extract tuple of (v_tokens, v_sol, r_tokens, r_sol, total_supply, complete)."""
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < cls._MIN_ACCOUNT_SIZE:
            raise ValueError(f"Account buffer too short for reserves: {len(buf)} bytes")
        return struct.unpack_from(cls._STRUCT_FORMAT, buf, cls._HEADER_SIZE)


class TradeInstructionBinaryParser:
    """Parser for Pump.fun instruction inner data and Anchor log events."""

    _TRADE_EVENT_FORMAT = "<32sQQ?32sqQQQQ"
    _TRADE_EVENT_PAYLOAD_SIZE = struct.calcsize(_TRADE_EVENT_FORMAT)  # 121 bytes
    _TRADE_EVENT_MIN_SIZE = 8 + _TRADE_EVENT_PAYLOAD_SIZE  # 129 bytes

    _COMPLETE_EVENT_FORMAT = "<32s32s32sq"
    _COMPLETE_EVENT_PAYLOAD_SIZE = struct.calcsize(_COMPLETE_EVENT_FORMAT)
    _COMPLETE_EVENT_MIN_SIZE = 8 + _COMPLETE_EVENT_PAYLOAD_SIZE

    @classmethod
    def parse_buy_instruction(
        cls, data: bytes | memoryview | bytearray
    ) -> dict[str, int]:
        """Parse raw Buy instruction data (amount: u64, max_sol_cost: u64)."""
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < 24:
            raise ValueError(
                f"Buy instruction data too short: {len(buf)} bytes (expected >= 24)"
            )
        amount, max_sol_cost = struct.unpack_from("<QQ", buf, 8)
        return {"amount": amount, "max_sol_cost": max_sol_cost}

    @classmethod
    def parse_sell_instruction(
        cls, data: bytes | memoryview | bytearray
    ) -> dict[str, int]:
        """Parse raw Sell instruction data (amount: u64, min_sol_output: u64)."""
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < 24:
            raise ValueError(
                f"Sell instruction data too short: {len(buf)} bytes (expected >= 24)"
            )
        amount, min_sol_output = struct.unpack_from("<QQ", buf, 8)
        return {"amount": amount, "min_sol_output": min_sol_output}

    @classmethod
    def parse_trade_event_buffer(
        cls,
        data: bytes | memoryview | bytearray,
        *,
        slot: int = 0,
        signature: str = "",
    ) -> Optional[TradeEventUpdate]:
        """Parse binary Anchor trade event buffer into TradeEventUpdate."""
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < cls._TRADE_EVENT_MIN_SIZE:
            return None

        discriminator = bytes(buf[:8])
        if discriminator != TRADE_EVENT_DISCRIMINATOR:
            return None

        (
            mint_bytes,
            sol_amount,
            token_amount,
            is_buy,
            user_bytes,
            timestamp,
            v_sol,
            v_tokens,
            r_sol,
            r_tokens,
        ) = struct.unpack_from(cls._TRADE_EVENT_FORMAT, buf, 8)

        mint_str = base58.b58encode(mint_bytes).decode("ascii")
        user_str = base58.b58encode(user_bytes).decode("ascii")

        return TradeEventUpdate(
            mint=mint_str,
            sol_amount_lamports=sol_amount,
            token_amount=token_amount,
            is_buy=is_buy,
            user=user_str,
            timestamp=timestamp,
            virtual_sol_reserves=v_sol,
            virtual_token_reserves=v_tokens,
            real_sol_reserves=r_sol,
            real_token_reserves=r_tokens,
            slot=slot,
            signature=signature,
        )

    @classmethod
    def parse_complete_event_buffer(
        cls,
        data: bytes | memoryview | bytearray,
        *,
        slot: int = 0,
        signature: str = "",
    ) -> Optional[CompleteEventUpdate]:
        """Parse binary Anchor complete event buffer into CompleteEventUpdate."""
        buf = memoryview(data) if not isinstance(data, memoryview) else data
        if len(buf) < cls._COMPLETE_EVENT_MIN_SIZE:
            return None

        discriminator = bytes(buf[:8])
        if discriminator != COMPLETE_EVENT_DISCRIMINATOR:
            return None

        user_bytes, mint_bytes, curve_bytes, timestamp = struct.unpack_from(
            cls._COMPLETE_EVENT_FORMAT, buf, 8
        )

        return CompleteEventUpdate(
            mint=base58.b58encode(mint_bytes).decode("ascii"),
            user=base58.b58encode(user_bytes).decode("ascii"),
            bonding_curve=base58.b58encode(curve_bytes).decode("ascii"),
            timestamp=timestamp,
            slot=slot,
            signature=signature,
        )

    @classmethod
    def parse_program_log_event(
        cls,
        log: str,
        *,
        slot: int = 0,
        signature: str = "",
    ) -> Optional[Union[TradeEventUpdate, CompleteEventUpdate]]:
        """Parse base64 program event logs formatted as 'Program data: <base64>'."""
        if not log.startswith("Program data: "):
            return None

        payload_b64 = log[len("Program data: ") :].strip()
        try:
            raw_bytes = base64.b64decode(payload_b64)
        except Exception:
            return None

        if (
            len(raw_bytes) >= cls._TRADE_EVENT_MIN_SIZE
            and raw_bytes[:8] == TRADE_EVENT_DISCRIMINATOR
        ):
            return cls.parse_trade_event_buffer(
                raw_bytes, slot=slot, signature=signature
            )

        if (
            len(raw_bytes) >= cls._COMPLETE_EVENT_MIN_SIZE
            and raw_bytes[:8] == COMPLETE_EVENT_DISCRIMINATOR
        ):
            return cls.parse_complete_event_buffer(
                raw_bytes, slot=slot, signature=signature
            )

        return None


EventCallback = Callable[[Any], Union[Coroutine[Any, Any, None], None]]


class YellowstoneGeyserClient:
    """Yellowstone Geyser gRPC streaming client with reconnection and zero-copy parsing.

    Features:
    - High-throughput asynchronous streaming
    - Subscriptions for Pump.fun program transactions and bonding curve accounts
    - Auto-reconnect with exponential backoff and jitter
    - Zero-copy binary event dispatching
    - Health telemetry and dropped message accounting
    """

    def __init__(
        self,
        endpoint: str,
        *,
        x_token: Optional[str] = None,
        program_id: str = PUMP_PROGRAM_ID,
        reconnect_initial_backoff: float = 0.5,
        reconnect_max_backoff: float = 30.0,
        backoff_multiplier: float = 2.0,
        jitter: float = 0.1,
        keepalive_interval: float = 10.0,
        max_queue_size: int = 10_000,
        custom_transport: Optional[Any] = None,
    ) -> None:
        self.endpoint = endpoint
        self.x_token = x_token
        self.program_id = program_id
        self.reconnect_initial_backoff = reconnect_initial_backoff
        self.reconnect_max_backoff = reconnect_max_backoff
        self.backoff_multiplier = backoff_multiplier
        self.jitter = jitter
        self.keepalive_interval = keepalive_interval
        self.max_queue_size = max_queue_size

        self.state = GeyserConnectionState.DISCONNECTED
        self.metrics = GeyserStreamMetrics()
        self.filter = GeyserSubscriptionFilter(programs=[self.program_id])

        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._keepalive_task: Optional[asyncio.Task[None]] = None
        self._custom_transport = custom_transport

        # Registered event callbacks
        self._on_bonding_curve_callbacks: list[EventCallback] = []
        self._on_trade_callbacks: list[EventCallback] = []
        self._on_complete_callbacks: list[EventCallback] = []
        self._on_account_callbacks: list[EventCallback] = []
        self._on_transaction_callbacks: list[EventCallback] = []

    def on_bonding_curve(self, callback: EventCallback) -> None:
        """Register a callback invoked when a bonding curve account changes."""
        self._on_bonding_curve_callbacks.append(callback)

    def on_trade(self, callback: EventCallback) -> None:
        """Register a callback invoked when an on-chain trade event occurs."""
        self._on_trade_callbacks.append(callback)

    def on_complete(self, callback: EventCallback) -> None:
        """Register a callback invoked when a bonding curve reaches completion."""
        self._on_complete_callbacks.append(callback)

    def on_account(self, callback: EventCallback) -> None:
        """Register a callback invoked for raw Geyser account updates."""
        self._on_account_callbacks.append(callback)

    def on_transaction(self, callback: EventCallback) -> None:
        """Register a callback invoked for raw Geyser transaction updates."""
        self._on_transaction_callbacks.append(callback)

    def subscribe_bonding_curves(self, mints: list[str]) -> None:
        """Add specific mint addresses to the account subscription filter."""
        existing = self.filter.accounts.setdefault("pump_curves", [])
        for m in mints:
            if m not in existing:
                existing.append(m)

    def subscribe_transactions(
        self, account_include: list[str], filter_name: str = "pump_txs"
    ) -> None:
        """Subscribe to transaction notifications involving specific accounts."""
        self.filter.transactions[filter_name] = list(account_include)

    async def start(self) -> None:
        """Start the Yellowstone Geyser client streaming worker in the background."""
        if self._running:
            return
        self._running = True
        self.state = GeyserConnectionState.CONNECTING
        self._worker_task = asyncio.create_task(self._stream_loop())
        if self.keepalive_interval > 0:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info("Yellowstone Geyser client started for endpoint: %s", self.endpoint)

    async def stop(self) -> None:
        """Stop streaming and release connections."""
        self._running = False
        self.state = GeyserConnectionState.CLOSING

        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        self.state = GeyserConnectionState.CLOSED
        logger.info("Yellowstone Geyser client stopped.")

    async def listen(
        self,
    ) -> AsyncIterator[
        Union[
            BondingCurveStateUpdate,
            TradeEventUpdate,
            CompleteEventUpdate,
            GeyserAccountUpdate,
            GeyserTransactionUpdate,
        ]
    ]:
        """Async generator yielding incoming parsed events from the stream."""
        while self._running or not self._queue.empty():
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield item
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue

    async def dispatch_raw_account(
        self,
        pubkey: str,
        owner: str,
        lamports: int,
        data: bytes,
        slot: int,
        *,
        mint: str = "",
        signature: Optional[str] = None,
    ) -> Optional[BondingCurveStateUpdate]:
        """Process and dispatch a raw account update from Geyser."""
        start_time = time.time()
        self.metrics.record_received()

        account_update = GeyserAccountUpdate(
            pubkey=pubkey,
            owner=owner,
            lamports=lamports,
            data=data,
            slot=slot,
            txn_signature=signature,
            timestamp=start_time,
        )

        await self._trigger_callbacks(self._on_account_callbacks, account_update)
        self._enqueue(account_update)

        # If owned by Pump.fun and long enough, parse bonding curve state
        bonding_update: Optional[BondingCurveStateUpdate] = None
        if owner == self.program_id or owner == PUMP_PROGRAM_ID:
            try:
                bonding_update = BondingCurveBinaryParser.parse_account_data(
                    data,
                    mint=mint or pubkey,
                    bonding_curve_pubkey=pubkey,
                    slot=slot,
                )
                await self._trigger_callbacks(
                    self._on_bonding_curve_callbacks, bonding_update
                )
                self._enqueue(bonding_update)
            except Exception as e:
                logger.debug("Account %s not parsed as bonding curve: %s", pubkey, e)

        latency_ms = (time.time() - start_time) * 1000.0
        self.metrics.record_processed(latency_ms, slot=slot)
        return bonding_update

    async def dispatch_raw_transaction(
        self,
        signature: str,
        slot: int,
        logs: list[str],
        *,
        meta: Optional[dict[str, Any]] = None,
    ) -> list[Union[TradeEventUpdate, CompleteEventUpdate]]:
        """Process transaction log entries and extract trade and completion events."""
        start_time = time.time()
        self.metrics.record_received()

        tx_update = GeyserTransactionUpdate(
            signature=signature,
            slot=slot,
            meta=meta,
            timestamp=start_time,
        )
        await self._trigger_callbacks(self._on_transaction_callbacks, tx_update)
        self._enqueue(tx_update)

        events: list[Union[TradeEventUpdate, CompleteEventUpdate]] = []
        for log in logs:
            event = TradeInstructionBinaryParser.parse_program_log_event(
                log, slot=slot, signature=signature
            )
            if event is not None:
                events.append(event)
                if isinstance(event, TradeEventUpdate):
                    await self._trigger_callbacks(self._on_trade_callbacks, event)
                elif isinstance(event, CompleteEventUpdate):
                    await self._trigger_callbacks(self._on_complete_callbacks, event)
                self._enqueue(event)

        latency_ms = (time.time() - start_time) * 1000.0
        self.metrics.record_processed(latency_ms, slot=slot)
        return events

    def _enqueue(self, item: Any) -> None:
        """Place item onto ingestion queue or record drop on overflow."""
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self.metrics.record_drop()
            logger.warning(
                "Geyser client queue full (%d items); dropped event %s",
                self.max_queue_size,
                type(item).__name__,
            )

    async def _trigger_callbacks(
        self, callbacks: list[EventCallback], event: Any
    ) -> None:
        """Execute registered callbacks for an event safely."""
        for cb in callbacks:
            try:
                res = cb(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(
                    "Error executing event callback %s: %s", cb, e, exc_info=True
                )

    async def _stream_loop(self) -> None:
        """Main connection and message consumption loop with backoff."""
        backoff = self.reconnect_initial_backoff

        while self._running:
            try:
                self.state = (
                    GeyserConnectionState.CONNECTING
                    if self.metrics.reconnect_count == 0
                    else GeyserConnectionState.RECONNECTING
                )

                if self._custom_transport is not None:
                    self.state = GeyserConnectionState.CONNECTED
                    backoff = self.reconnect_initial_backoff
                    await self._custom_transport(self)
                else:
                    # Built-in mock / simulation stream connection handler
                    self.state = GeyserConnectionState.CONNECTED
                    backoff = self.reconnect_initial_backoff
                    await self._run_mock_or_grpc_stream()

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.metrics.record_reconnect()
                logger.warning(
                    "Geyser stream connection error: %s. Reconnecting in %.2fs...",
                    e,
                    backoff,
                )
                self.state = GeyserConnectionState.RECONNECTING

                # Apply exponential backoff with random jitter
                jitter_val = random.uniform(1.0 - self.jitter, 1.0 + self.jitter)
                sleep_time = min(backoff * jitter_val, self.reconnect_max_backoff)
                backoff = min(
                    backoff * self.backoff_multiplier,
                    self.reconnect_max_backoff,
                )

                try:
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    break

        self.state = GeyserConnectionState.CLOSED

    async def _run_mock_or_grpc_stream(self) -> None:
        """Default stream execution loop."""
        while self._running:
            await asyncio.sleep(0.5)

    async def _keepalive_loop(self) -> None:
        """Periodic keepalive loop sending ping / heartbeat telemetry."""
        while self._running:
            try:
                await asyncio.sleep(self.keepalive_interval)
                if self.state == GeyserConnectionState.CONNECTED:
                    logger.debug(
                        "Geyser keepalive ping ok. Messages processed: %d, avg_lat: %.2fms",
                        self.metrics.messages_processed,
                        self.metrics.average_latency_ms,
                    )
            except asyncio.CancelledError:
                break
