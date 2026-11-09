"""The Float capture (FEAT-179), record-only: launches, curve trades,
graduations and the graduates' first hours on Raydium CPMM.

Float coins trade more naturally than pump.fun's (fewer creation-slot
buyers, fewer dumps after graduation), and the window may close once
snipers arrive, so the platform is recorded at the finest grain while it
lasts (run ``float-1``). Nothing here trades.

* :class:`FloatFeed` holds one RPC WebSocket (``PUMPFUN_RPC_WS_URL``) with a
  ``logsSubscribe`` mentioning Float's program (launches, fee cycles), one
  for each Float platform config (every LaunchLab trade on a Float curve
  names its platform config, so these carry the curve trades and the
  migrations), and one per followed graduate's CPMM pool.
* :class:`FloatWatcher` reads each transaction's logs once (the same
  transaction can arrive on several subscriptions) with
  ``float_events`` and writes the rows:

  - ``float_launch``: from Float's and LaunchLab's launch events, completed
    by one read of the curve and the mint (platform, curve state, token
    program, authorities and extensions);
  - ``float_trade``: each LaunchLab ``TradeEvent`` (side, amounts, fees,
    reserves after, curve status) with the slot and receive time;
  - ``float_trader``: a trade's signers and block time, looked up at a
    capped rate (the logs carry neither); one the queue cannot take is
    counted and left to the read-out's backfill;
  - ``float_migration``: at ``MigrateToCpswap``, the migration's accounts,
    the curve's final state, the CPMM pool and its vaults, and the largest
    holders (``getTokenLargestAccounts``, with each account's owner);
  - ``float_cpmm_trade``: each CPMM ``SwapEvent`` on a followed graduate's
    pool for ``cpmm_logs_seconds``;
  - ``float_pool_reading``: the graduate's vaults and the fees held in them,
    every ``reading_interval_seconds`` for ``reading_seconds``;
  - ``float_fee_cycle``: Float's fee claims, holder payouts and harvests,
    their instruction names and events as bytes (Float publishes no IDL);
  - ``float_platforms``: the platform list and fees, at each refresh.

Non-SOL quotes (tokenized stocks, other tokens) are kept in their own raw
units with the quote mint.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Protocol

from trading_core.ops.redact import redact_text
from trading_core.ops.stream import run_websocket_stream, send_ws_message
from trading_solana.mint_facts import mint_facts

from trading_pump.config.settings import FloatSettings
from trading_pump.float_events import (
    CPMM_PROGRAM_ID,
    CPMM_SWAP_EVENT,
    FEE_INSTRUCTIONS,
    FLOAT_CONFIG,
    FLOAT_LAUNCH_EVENT,
    FLOAT_PLATFORMS,
    FLOAT_PROGRAM_ID,
    LAUNCHLAB_PROGRAM_ID,
    MIGRATE_INSTRUCTION,
    POOL_CREATE_EVENT,
    TRADE_EVENT,
    CpmmPool,
    LogRecords,
    Migration,
    PlatformFees,
    decode_cpmm_pool,
    decode_cpmm_swap,
    decode_float_launch,
    decode_float_platforms,
    decode_launchlab_pool,
    decode_migration,
    decode_platform_fees,
    decode_pool_create_event,
    decode_trade_event,
    pubkey_at,
    read_logs,
    transaction_signers,
)
from trading_pump.sdk.pumpswap import token_account_amount

logger = logging.getLogger("trading_pump.float_capture")

CONDITION_FLOAT_FEED = "float feed"
LOGS_SUBSCRIBE = "logsSubscribe"
LOGS_UNSUBSCRIBE = "logsUnsubscribe"
LOGS_NOTIFICATION = "logsNotification"
LAUNCH_EVENT = "float_launch"
TRADE_ROW = "float_trade"
TRADER_ROW = "float_trader"
MIGRATION_ROW = "float_migration"
CPMM_TRADE_ROW = "float_cpmm_trade"
READING_ROW = "float_pool_reading"
FEE_CYCLE_ROW = "float_fee_cycle"
PLATFORMS_ROW = "float_platforms"
ACCOUNTS_PER_READ = 99  # getMultipleAccounts takes 100; three a pool
# A trade's transaction the RPC does not serve yet is asked this many times.
TRADER_LOOKUP_TRIES = 3

Recorder = Callable[[dict[str, Any]], None]


class FloatSource(Protocol):
    """The RPC reads the capture makes (``RpcFloatSource`` live)."""

    async def get_accounts(self, addresses: Sequence[str]) -> list[Any]: ...

    async def get_transaction(self, signature: str) -> Mapping[str, Any] | None: ...

    async def largest_accounts(self, mint: str) -> list[tuple[str, int]]: ...


@dataclass
class RpcFloatSource:
    """:class:`FloatSource` on the module's SDK client (its RPC pool)."""

    client: Any
    timeout_seconds: float = 10.0

    async def get_accounts(self, addresses: Sequence[str]) -> list[Any]:
        result: list[Any] = await self.client._get_accounts(
            list(addresses), timeout_seconds=self.timeout_seconds
        )
        return result

    async def get_transaction(self, signature: str) -> Mapping[str, Any] | None:
        # Version 1: the smoke of 2026-11-09 saw 57 of 142 trades refused
        # with -32015 when only version 0 was accepted.
        parsed = await self.client._request_rpc_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "json",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 1,
                    },
                ],
            },
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(parsed, dict) or "error" in parsed:
            raise RuntimeError(f"getTransaction error: {parsed}")
        result = parsed.get("result")
        return result if isinstance(result, dict) else None

    async def largest_accounts(self, mint: str) -> list[tuple[str, int]]:
        result: list[tuple[str, int]] = await self.client.get_token_largest_accounts(
            mint, timeout_seconds=self.timeout_seconds
        )
        return result


def token_owner_and_amount(value: Any) -> tuple[str | None, int | None]:
    """A token account read's owner and amount (``None`` when unreadable)."""
    try:
        raw = base64.b64decode(value["data"][0])
        return pubkey_at(raw, 32), int(token_account_amount(raw))
    except Exception:
        return None, None


# -- the stream ------------------------------------------------------------------
@dataclass
class Mention:
    """One ``logsSubscribe`` mention: what it is for and until when."""

    address: str
    kind: str
    until: float | None = None
    subscription: int | None = None


LogsHandler = Callable[[str, int | None, Any, list[str]], None]


@dataclass(kw_only=True)
class FloatFeed:
    """A ``WebSocketStreamHost`` holding the ``logsSubscribe`` mentions; see
    the module docstring. ``connect_url()`` may carry the provider's key and
    is never logged."""

    connect_url: Callable[[], str]
    stream_url: str
    settings: FloatSettings
    on_logs: LogsHandler
    clock: Callable[[], float] = time.time
    on_state: Callable[[bool, str], None] | None = None
    on_message: Callable[[], None] | None = None
    reconnect_delay_seconds: float = 1.0
    stream_heartbeat_seconds: float | None = 20.0
    stream_idle_timeout_seconds: float | None = 600.0
    mentions: dict[str, Mention] = field(default_factory=dict)
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

    def mention(self, address: str, kind: str, *, until: float | None = None) -> bool:
        """Follow transactions mentioning ``address`` (until ``until``, or
        for the whole run); ``False`` when it is followed already."""
        if address in self.mentions:
            return False
        self.mentions[address] = Mention(address, kind, until)
        self._queued.append(address)
        self._count(f"mentions_{kind}")
        return True

    def forget(self, address: str) -> None:
        entry = self.mentions.pop(address, None)
        if entry is not None and entry.subscription is not None:
            self._by_subscription.pop(entry.subscription, None)
            self._ending.append(entry.subscription)

    def _expire(self, now: float) -> None:
        for address, entry in list(self.mentions.items()):
            if entry.until is not None and now >= entry.until:
                self.forget(address)
                self._count("mentions_ended")

    def _request_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def flush(self, now: float | None = None) -> None:
        """End the mentions past their time and send what is queued, while
        connected; each item leaves its queue only once sent."""
        self._expire(self.clock() if now is None else float(now))
        ws = self.ws
        if ws is None:
            return
        while self._ending:
            await send_ws_message(
                ws, self._request(LOGS_UNSUBSCRIBE, [self._ending[0]])
            )
            self._ending.pop(0)
        while self._queued:
            address = self._queued[0]
            if address in self.mentions:
                request = self._request(
                    LOGS_SUBSCRIBE,
                    [{"mentions": [address]}, {"commitment": self.settings.commitment}],
                )
                self._pending[request["id"]] = address
                await send_ws_message(ws, request)
            self._queued.pop(0)

    def _request(self, method: str, params: list[Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": self._request_id(),
            "method": method,
            "params": params,
        }

    def _reply(self, data: Mapping[str, Any]) -> None:
        request_id = data.get("id")
        address = (
            self._pending.pop(request_id, None) if isinstance(request_id, int) else None
        )
        if address is None:
            return
        entry = self.mentions.get(address)
        result = data.get("result")
        if entry is None or not isinstance(result, int) or isinstance(result, bool):
            self._count("subscribe_refused")
            return
        entry.subscription = result
        self._by_subscription[result] = address
        self._count("subscribed")

    def _notification(self, params: Mapping[str, Any]) -> None:
        result = params.get("result") or {}
        value = result.get("value") or {}
        signature = value.get("signature")
        logs = value.get("logs")
        if not isinstance(signature, str) or not isinstance(logs, list):
            self._count("malformed_notifications")
            return
        self._count("notifications")
        if self.on_message is not None:
            self.on_message()
        slot = (result.get("context") or {}).get("slot")
        self.on_logs(signature, slot, value.get("err"), [str(line) for line in logs])

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
        for entry in self.mentions.values():
            entry.subscription = None
        self._queued = list(self.mentions)
        self.ws = ws
        self._state(True)
        await self.flush()

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        if not isinstance(data, dict):
            return
        if data.get("method") == LOGS_NOTIFICATION:
            self._notification(data.get("params") or {})
        elif "id" in data:
            self._reply(data)

    def on_stream_error(self, message: str) -> None:
        self._count("errors")
        self.stream_log(message, logging.WARNING)
        self._state(False, message)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._count("errors")
        self.stream_log(
            f"float stream failed: {exc}; retry in {backoff:.0f}s", logging.WARNING
        )
        self._state(False, redact_text(str(exc)))

    def on_stream_ended(self) -> None:
        self._count("disconnects")
        self._state(False, "connection closed")

    def on_stream_closed(self) -> None:
        if self.connected:
            self._state(False, "connection closed")


# -- what the logs say ---------------------------------------------------------------
@dataclass
class Graduate:
    """A followed graduate: its CPMM pool, vaults and reading window."""

    mint: str
    cpmm_pool: str
    vault_0: str
    vault_1: str
    readings_until: float
    logs_until: float


@dataclass
class FloatWatcher:
    """Turns logs into rows and runs the lookups; see the module docstring."""

    settings: FloatSettings
    source: FloatSource
    record: Recorder
    feed: FloatFeed | None = None
    clock: Callable[[], float] = time.time
    stats: dict[str, int] = field(default_factory=dict)
    platforms: dict[str, PlatformFees | None] = field(default_factory=dict)
    graduates: dict[str, Graduate] = field(default_factory=dict)
    last_error: str = ""
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict)
    _traders: deque[tuple[str, str, int]] = field(default_factory=deque)
    _tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    _slots: asyncio.Semaphore | None = None

    def _count(self, key: str, value: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + value

    def _error(self, key: str, exc: Exception) -> None:
        self._count(key)
        self.last_error = redact_text(str(exc))[:200]

    def start(self) -> None:
        """Follow Float's program and the known platform configs."""
        if self.feed is None:
            return
        self.feed.mention(FLOAT_PROGRAM_ID, "program")
        for platform in FLOAT_PLATFORMS:
            self.platforms.setdefault(platform, None)
            self.feed.mention(platform, "platform")

    def _first_time(self, signature: str) -> bool:
        if signature in self._seen:
            self._count("duplicates")
            return False
        self._seen[signature] = None
        while len(self._seen) > int(self.settings.seen_signatures):
            self._seen.popitem(last=False)
        return True

    # -- one transaction --------------------------------------------------------
    def on_logs(
        self, signature: str, slot: int | None, err: Any, logs: list[str]
    ) -> None:
        """One transaction's logs, from any subscription (sync: the feed's
        callback; lookups run as tasks)."""
        if not self._first_time(signature):
            return
        if err is not None:
            self._count("failed_transactions")
            return
        records = read_logs(logs)
        if records.truncated:
            self._count("truncated_logs")
        base = {"signature": signature, "slot": slot, "timestamp": self.clock()}
        self._launches(records, base)
        self._trades(records, base)
        self._cpmm_trades(records, base)
        self._fee_cycles(records, base)
        if MIGRATE_INSTRUCTION in records.instructions_of(LAUNCHLAB_PROGRAM_ID):
            self._spawn(lambda: self._migration(signature, base))

    def _launches(self, records: LogRecords, base: dict[str, Any]) -> None:
        launches = records.data_of(FLOAT_PROGRAM_ID, FLOAT_LAUNCH_EVENT)
        creates = records.data_of(LAUNCHLAB_PROGRAM_ID, POOL_CREATE_EVENT)
        for raw in launches:
            launch = decode_float_launch(raw)
            if launch is None:
                self._count("undecoded_launches")
                continue
            created = next(
                (
                    event
                    for event in map(decode_pool_create_event, creates)
                    if event is not None and event.pool == launch.pool
                ),
                None,
            )
            row: dict[str, Any] = {
                **base,
                "event": LAUNCH_EVENT,
                "pool": launch.pool,
                "mint": launch.mint,
                "quote_mint": launch.quote_mint,
                "launcher": launch.launcher,
                "second_key": launch.second_key,
                "symbol": launch.symbol,
            }
            if created is not None:
                row.update(_created_fields(created))
            self._count("launches")
            self._spawn(partial(self._complete_launch, row))

    def _trades(self, records: LogRecords, base: dict[str, Any]) -> None:
        for raw in records.data_of(LAUNCHLAB_PROGRAM_ID, TRADE_EVENT):
            trade = decode_trade_event(raw)
            if trade is None:
                self._count("undecoded_trades")
                continue
            self.record({**base, "event": TRADE_ROW, **trade.row_fields()})
            self._count("trades")
        if records.data_of(LAUNCHLAB_PROGRAM_ID, TRADE_EVENT):
            self._queue_trader(base["signature"], "curve")

    def _cpmm_trades(self, records: LogRecords, base: dict[str, Any]) -> None:
        followed = False
        for raw in records.data_of(CPMM_PROGRAM_ID, CPMM_SWAP_EVENT):
            swap = decode_cpmm_swap(raw)
            if swap is None or swap.pool not in self._cpmm_pools():
                continue
            graduate = self._cpmm_pools()[swap.pool]
            self.record(
                {
                    **base,
                    "event": CPMM_TRADE_ROW,
                    "mint": graduate.mint,
                    **swap.row_fields(),
                }
            )
            self._count("cpmm_trades")
            followed = True
        if followed:
            self._queue_trader(base["signature"], "cpmm")

    def _cpmm_pools(self) -> dict[str, Graduate]:
        return {graduate.cpmm_pool: graduate for graduate in self.graduates.values()}

    def _fee_cycles(self, records: LogRecords, base: dict[str, Any]) -> None:
        names = [
            name
            for name in records.instructions_of(FLOAT_PROGRAM_ID)
            if name in FEE_INSTRUCTIONS
        ]
        if not names:
            return
        events = [
            {"discriminator": raw[:8].hex(), "data": base64.b64encode(raw).decode()}
            for owner, raw in records.data
            if owner == FLOAT_PROGRAM_ID
        ]
        self.record(
            {**base, "event": FEE_CYCLE_ROW, "instructions": names, "events": events}
        )
        self._count("fee_cycles")

    # -- lookups ------------------------------------------------------------------
    def _spawn(self, work: Callable[[], Awaitable[None]]) -> None:
        """Run a lookup as a task, at most ``max_lookups`` at once; the
        lookup's coroutine is made only once it runs, so a cancelled task
        leaves none behind."""
        task = asyncio.ensure_future(self._limited(work))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _limited(self, work: Callable[[], Awaitable[None]]) -> None:
        if self._slots is None:
            self._slots = asyncio.Semaphore(int(self.settings.max_lookups))
        async with self._slots:
            await work()

    def _queue_trader(self, signature: str, venue: str) -> None:
        if not self.settings.trader_lookups_per_second:
            return
        if len(self._traders) >= int(self.settings.max_queued_lookups):
            self._count("trader_lookups_dropped")
            return
        self._traders.append((signature, venue, 0))

    async def _complete_launch(self, row: dict[str, Any]) -> None:
        try:
            pool_value, mint_value = await self.source.get_accounts(
                [row["pool"], row["mint"]]
            )
        except Exception as exc:
            self._error("launch_lookup_errors", exc)
            row["lookup_error"] = self.last_error
            self.record(row)
            return
        row.update(self._launch_accounts(pool_value, mint_value))
        self.record(row)

    def _launch_accounts(self, pool_value: Any, mint_value: Any) -> dict[str, Any]:
        found: dict[str, Any] = {}
        pool = decode_launchlab_pool(pool_value)
        if pool is not None:
            found.update(pool.terms())
            fees = self.platforms.get(pool.platform)
            found["fee_bps_a_side"] = fees.total_fee_bps if fees else None
        facts = mint_facts(mint_value)
        if facts is not None:
            found.update(
                token_program=facts.token_program,
                mint_authority=facts.mint_authority,
                freeze_authority=facts.freeze_authority,
                extensions=list(facts.extensions),
                transfer_fee_bps=facts.transfer_fee_bps,
                mint_risks=facts.risks,
            )
        return found

    async def lookup_traders(self, limit: int) -> int:
        """Look up to ``limit`` queued trades' signers and block times."""
        done = 0
        while self._traders and done < limit:
            signature, venue, tries = self._traders.popleft()
            done += 1
            try:
                tx = await self.source.get_transaction(signature)
            except Exception as exc:
                self._error("trader_lookup_errors", exc)
                continue
            if tx is None and tries + 1 < TRADER_LOOKUP_TRIES:
                # Not served yet by the node read: asked again after the rest.
                self._traders.append((signature, venue, tries + 1))
                self._count("trader_lookups_retried")
                continue
            signers = transaction_signers(tx)
            self.record(
                {
                    "timestamp": self.clock(),
                    "event": TRADER_ROW,
                    "signature": signature,
                    "venue": venue,
                    "fee_payer": signers[0] if signers else None,
                    "signers": signers,
                    "block_time": (tx or {}).get("blockTime"),
                }
            )
            self._count("trader_lookups")
        return done

    async def _migration(self, signature: str, base: dict[str, Any]) -> None:
        try:
            migration = decode_migration(await self.source.get_transaction(signature))
            if migration is None:
                self._count("undecoded_migrations")
                return
            row = await self._migration_row(migration, base)
        except Exception as exc:
            self._error("migration_lookup_errors", exc)
            return
        self.record(row)
        self._count("migrations")

    async def _migration_row(
        self, migration: Migration, base: dict[str, Any]
    ) -> dict[str, Any]:
        pool_value, cpmm_value = await self.source.get_accounts(
            [migration.pool, migration.cpmm_pool]
        )
        curve = decode_launchlab_pool(pool_value)
        cpmm = decode_cpmm_pool(cpmm_value)
        holders = await self._holders(migration, curve, cpmm)
        followed = cpmm is not None and self._follow(migration, cpmm)
        return {
            **base,
            "event": MIGRATION_ROW,
            "pool": migration.pool,
            "mint": migration.base_mint,
            "quote_mint": migration.quote_mint,
            "platform": migration.platform,
            "block_time": migration.block_time,
            "cpmm_pool": migration.cpmm_pool,
            "cpmm_base_vault": migration.cpmm_base_vault,
            "cpmm_quote_vault": migration.cpmm_quote_vault,
            "curve": curve.terms() if curve is not None else None,
            "holders": holders,
            "followed": followed,
        }

    async def _holders(
        self, migration: Migration, curve: Any, cpmm: CpmmPool | None
    ) -> list[dict[str, Any]]:
        pools = {migration.cpmm_base_vault, migration.cpmm_quote_vault}
        if curve is not None:
            pools |= {curve.base_vault, curve.quote_vault}
        largest = (await self.source.largest_accounts(migration.base_mint))[
            : int(self.settings.holders)
        ]
        if not largest:
            return []
        values = await self.source.get_accounts([address for address, _ in largest])
        holders = []
        for (address, amount), value in zip(largest, values, strict=True):
            owner, _ = token_owner_and_amount(value)
            holders.append(
                {
                    "account": address,
                    "owner": owner,
                    "amount": amount,
                    "pool": address in pools,
                }
            )
        return holders

    def _follow(self, migration: Migration, cpmm: CpmmPool) -> bool:
        if len(self.graduates) >= int(self.settings.max_graduates):
            self._count("graduates_list_full")
            return False
        now = self.clock()
        self.graduates[migration.base_mint] = Graduate(
            mint=migration.base_mint,
            cpmm_pool=migration.cpmm_pool,
            vault_0=cpmm.vault_0,
            vault_1=cpmm.vault_1,
            readings_until=now + float(self.settings.reading_seconds),
            logs_until=now + float(self.settings.cpmm_logs_seconds),
        )
        if self.feed is not None:
            self.feed.mention(
                migration.cpmm_pool,
                "cpmm",
                until=now + float(self.settings.cpmm_logs_seconds),
            )
        return True

    # -- the periodic work ----------------------------------------------------------
    async def read_pools(self) -> int:
        """Read every graduate in its reading window: the CPMM pool and both
        vaults, 33 pools a call; ends a graduate past both windows."""
        now = self.clock()
        for mint, graduate in list(self.graduates.items()):
            if now >= max(graduate.readings_until, graduate.logs_until):
                del self.graduates[mint]
                self._count("graduates_ended")
        due = [g for g in self.graduates.values() if now < g.readings_until]
        per_call = ACCOUNTS_PER_READ // 3
        for start in range(0, len(due), per_call):
            chunk = due[start : start + per_call]
            addresses = [a for g in chunk for a in (g.cpmm_pool, g.vault_0, g.vault_1)]
            try:
                values = await self.source.get_accounts(addresses)
            except Exception as exc:
                self._error("reading_errors", exc)
                continue
            for index, graduate in enumerate(chunk):
                self._reading(graduate, values[3 * index : 3 * index + 3], now)
        return len(due)

    def _reading(self, graduate: Graduate, values: Sequence[Any], now: float) -> None:
        cpmm = decode_cpmm_pool(values[0])
        _, amount_0 = token_owner_and_amount(values[1])
        _, amount_1 = token_owner_and_amount(values[2])
        held_0 = cpmm.held_fees_0 if cpmm else None
        held_1 = cpmm.held_fees_1 if cpmm else None
        self.record(
            {
                "timestamp": now,
                "event": READING_ROW,
                "mint": graduate.mint,
                "cpmm_pool": graduate.cpmm_pool,
                "mint_0": cpmm.mint_0 if cpmm else None,
                "mint_1": cpmm.mint_1 if cpmm else None,
                "vault_0_amount": amount_0,
                "vault_1_amount": amount_1,
                "held_fees_0": held_0,
                "held_fees_1": held_1,
                "reserve_0": _less(amount_0, held_0),
                "reserve_1": _less(amount_1, held_1),
            }
        )
        self._count("readings")

    async def refresh_platforms(self) -> None:
        """Read Float's platform list and each platform's fees; follow a new
        one. A failed or unreadable read keeps the list as it was."""
        try:
            (config,) = await self.source.get_accounts([FLOAT_CONFIG])
            listed = decode_float_platforms(config)
            if listed is None:
                self._count("platform_list_unreadable")
                listed = tuple(self.platforms) or FLOAT_PLATFORMS
            values = await self.source.get_accounts(list(listed))
        except Exception as exc:
            self._error("platform_refresh_errors", exc)
            return
        for platform, value in zip(listed, values, strict=True):
            self.platforms[platform] = decode_platform_fees(platform, value)
            if self.feed is not None and self.feed.mention(platform, "platform"):
                self._count("platforms_added")
        self.record(
            {
                "timestamp": self.clock(),
                "event": PLATFORMS_ROW,
                "platforms": {
                    key: (fees.total_fee_bps if fees else None)
                    for key, fees in self.platforms.items()
                },
            }
        )

    async def run(
        self,
        stop: Callable[[], bool],
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        """The periodic work until ``stop()``: subscriptions every
        ``flush_interval_seconds``, the pool readings, the trader lookups at
        their rate and the platform list every ``platform_refresh_seconds``."""
        pause = sleep or asyncio.sleep
        tick = float(self.settings.flush_interval_seconds)
        next_reading = next_platforms = self.clock()
        allowance = 0.0
        while not stop():
            now = self.clock()
            try:
                if now >= next_platforms:
                    next_platforms = now + float(self.settings.platform_refresh_seconds)
                    await self.refresh_platforms()
                if now >= next_reading:
                    next_reading = now + float(self.settings.reading_interval_seconds)
                    await self.read_pools()
                allowance = min(
                    allowance + tick * float(self.settings.trader_lookups_per_second),
                    float(self.settings.trader_lookups_per_second) * 5,
                )
                allowance -= await self.lookup_traders(int(allowance))
                if self.feed is not None:
                    await self.feed.flush()
            except Exception as exc:  # a failed pass must not end the loop
                self._error("loop_errors", exc)
            await pause(tick)

    async def stop(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def status_text(self) -> str:
        feed = self.feed
        state = "connected" if feed is not None and feed.connected else "disconnected"
        return (
            f"{state} · {self.stats.get('launches', 0)} launches · "
            f"{self.stats.get('trades', 0)} trades · "
            f"{self.stats.get('migrations', 0)} migrations · "
            f"{len(self.graduates)} graduates followed"
        )


def _less(amount: int | None, held: int | None) -> int | None:
    if amount is None or held is None:
        return None
    return amount - held


def _created_fields(created: Any) -> dict[str, Any]:
    return {
        "name": created.name,
        "symbol": created.symbol or None,
        "decimals": created.decimals,
        "uri_host": created.uri_host,
        "creator": created.creator,
        "curve_kind": created.curve,
        "curve_supply": created.supply,
        "curve_total_base_sell": created.total_base_sell,
        "curve_total_quote_fund_raising": created.total_quote_fund_raising,
        "migrate_type": created.migrate_type,
        "vesting_locked": created.vesting_locked,
        "vesting_cliff": created.vesting_cliff,
        "vesting_unlock": created.vesting_unlock,
    }


__all__ = [
    "CONDITION_FLOAT_FEED",
    "CPMM_TRADE_ROW",
    "FEE_CYCLE_ROW",
    "LAUNCH_EVENT",
    "MIGRATION_ROW",
    "PLATFORMS_ROW",
    "READING_ROW",
    "TRADER_ROW",
    "TRADE_ROW",
    "FloatFeed",
    "FloatSource",
    "FloatWatcher",
    "Graduate",
    "Mention",
    "RpcFloatSource",
    "token_owner_and_amount",
]
