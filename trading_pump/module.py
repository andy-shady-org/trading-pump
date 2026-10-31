"""``PumpModule``: Pump.fun graduates on PumpSwap, plugged into trading-core.

Registered as the ``pumpfun`` entry point, so a trading-core settings file
with ``"module": "pumpfun"`` runs it (docs/USER-GUIDE.md)::

    trading-core run --config configs/paper.example.json

Instruments are **mints** of coins that have graduated from the Pump.fun
bonding curve to their canonical PumpSwap pool. Prices are SOL per whole
token (6 decimals), shown in µSOL. The module:

* listens to PumpPortal's free migration feed and follows every graduate's
  pool for 4 hours (FEAT-73), writing each reading to the capture;
* optionally finds new PumpSwap pools that are not graduations on-chain and
  records them the same way, never trading them (``new_pools``, FEAT-80);
* quotes from those pool readings (a fresh read when the last one is older
  than ``execution.quote_max_age_seconds``; never a default price);
* fills paper orders against a fresh pool read with the pool's fee and the
  modelled network fee, priority fee, tip and rent (``execution.py``);
* values open positions at what selling into the pool would return now,
  after the fee (the circuit breaker's exit value, pumpfun BUG-136);
* proposes entries through the ``pumpswap_momentum`` lane (FEAT-76) and,
  when enabled, the ``pumpswap_instant`` lane (FEAT-78), and sells each
  lane's positions on that lane's own exits (FEAT-79);
* refuses live orders until the live gate (``execution.LiveExecutor``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Any

from solders.keypair import Keypair
from trading_core.module.base import (
    Fill,
    MarketQuote,
    OrderRequest,
    TradingModule,
)
from trading_core.money import QuoteAsset
from trading_core.ops.retention import RetentionPolicy
from trading_core.positions import Position
from trading_core.strategy.exits import ExitDecision, evaluate_exit
from trading_core.strategy.pipeline import StrategyPipeline

from trading_pump import __version__
from trading_pump.config.env import Credentials, load_credentials, unread_env_warnings
from trading_pump.config.settings import PumpSettings
from trading_pump.execution import LiveExecutor, PaperExecutor
from trading_pump.feed import (
    CONDITION_FEED,
    CONDITION_NETWORK,
    CONDITION_RPC,
    MigrationFeed,
    PoolPoller,
)
from trading_pump.graduates import GraduateTracker
from trading_pump.identifiers import is_solana_pubkey
from trading_pump.infra.rpc_pool import CLUSTER_GENESIS_HASHES, MAINNET_GENESIS_HASH
from trading_pump.market import (
    LAMPORTS_PER_SOL,
    TOKEN_UNITS,
    PoolReading,
    PoolSource,
    RpcPoolSource,
    SwapFee,
    sell_lamports_out,
)
from trading_pump.pools import CONDITION_POOL_FEED, NewPoolFeed, NewPoolWatcher
from trading_pump.recorder import ReplayRecorder
from trading_pump.strategies.enrichment import TokenEnricher
from trading_pump.strategies.pumpswap_momentum import (
    LANE,
    LANE_INSTANT,
    Lanes,
    build_pipeline,
)

logger = logging.getLogger("trading_pump.module")

PUMP_QUOTE = QuoteAsset(
    symbol="SOL",
    decimals=4,
    atomic_decimals=9,
    small_unit=("µSOL", 1e6),
    small_threshold=0.001,
)
# Poll loop tick: the shortest schedule decides, never faster than this.
MIN_POLL_TICK_SECONDS = 0.5


class QuoteUnavailable(RuntimeError):
    """No pool reading could be had for an instrument."""


def _wrong_network(
    endpoints: list[Any], hashes: list[str | None]
) -> tuple[list[tuple[Any, str]], int]:
    """Endpoints on another network than mainnet-beta, with why, and how many
    endpoints to keep (on mainnet, or not confirmed)."""
    wrong: list[tuple[Any, str]] = []
    keep = 0
    for endpoint, genesis in zip(endpoints, hashes, strict=True):
        if genesis is None:
            logger.warning(
                "could not confirm the network of RPC endpoint %s", endpoint.label
            )
        if genesis is None or genesis == MAINNET_GENESIS_HASH:
            keep += 1
            continue
        name = CLUSTER_GENESIS_HASHES.get(genesis, "an unknown network")
        wrong.append((endpoint, f"{endpoint.label} serves {name}"))
    return wrong, keep


class PumpModule(TradingModule):
    name = "pumpfun"
    version = __version__
    quote = PUMP_QUOTE

    def __init__(
        self,
        *,
        source: PoolSource | None = None,
        client: Any | None = None,
        credentials: Credentials | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
        enricher: TokenEnricher | None = None,
        live_feeds: bool = True,
        **settings: Any,
    ) -> None:
        super().__init__()
        self.settings = PumpSettings.from_mapping(settings)
        self.credentials = credentials or load_credentials()
        self.clock = clock
        self.sleep = sleep
        self.live_feeds = live_feeds
        execution = self.settings.execution
        if source is None:
            if client is None:
                client = self._build_client()
            source = RpcPoolSource(
                client,
                timeout_seconds=float(execution.rpc_timeout_seconds),
                fee_bps_floor=int(execution.fee_bps_floor),
            )
        self.client: Any | None = client
        self.source: PoolSource = source
        capture = self.settings.capture
        self.recorder: ReplayRecorder | None = (
            ReplayRecorder(
                output_path=capture.path,
                flush_interval_seconds=float(capture.flush_interval_seconds),
                policy=RetentionPolicy(
                    max_bytes=int(capture.max_bytes),
                    max_files=int(capture.max_files),
                    max_age_days=int(capture.max_age_days),
                    compress_archives=bool(capture.compress),
                ),
            )
            if capture.path
            else None
        )
        self.lanes = Lanes(self.settings.lane, self.settings.instant)
        enabled = self.settings.enabled_lanes()
        self.tracker = GraduateTracker(
            self.settings.graduation,
            signal_after_seconds=(
                float(enabled[0][1].signal_after_seconds) if enabled else None
            ),
            record=self._record,
        )
        self.readings: dict[str, PoolReading] = {}
        self.fees: dict[str, SwapFee] = {}
        self.paper_executor = PaperExecutor(
            self.source, execution, clock=clock, sleep=sleep
        )
        self.live_executor = LiveExecutor()
        self.enricher = enricher
        self.poller = PoolPoller(
            self.source,
            self.tracker,
            held=lambda: list(self.paper_executor.holdings.raw),
            on_reading=self._store,
            on_success=self._rpc_ok,
            on_failure=self._rpc_failed,
            clock=clock,
        )
        stream = self.settings.stream
        self.feed = MigrationFeed(
            on_migration=self.on_migration,
            connect_url=self.credentials.stream_connect_url,
            stream_url=self.credentials.stream_display_url,
            reconnect_delay_seconds=float(stream.reconnect_delay_seconds),
            stream_heartbeat_seconds=float(stream.heartbeat_seconds) or None,
            stream_idle_timeout_seconds=float(stream.idle_timeout_seconds) or None,
            on_state=self._feed_state,
            clock=clock,
        )
        new_pools = self.settings.new_pools
        self.pool_watcher = NewPoolWatcher(
            new_pools, self.tracker, self.source, self._record, clock=clock
        )
        self.pool_feed = NewPoolFeed(
            on_pool=self.pool_watcher.on_pool,
            connect_url=self.credentials.rpc_ws_connect_url,
            stream_url=self.credentials.rpc_ws_display_url,
            warmup_seconds=float(new_pools.warmup_seconds),
            reconnect_delay_seconds=float(stream.reconnect_delay_seconds),
            stream_heartbeat_seconds=float(stream.heartbeat_seconds) or None,
            stream_idle_timeout_seconds=float(new_pools.idle_timeout_seconds),
            on_state=self._pool_feed_state,
            clock=clock,
        )
        self._pipeline: StrategyPipeline | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopping = False
        self._started = False

    # -- wiring --------------------------------------------------------------
    def _build_client(self) -> Any:
        from trading_pump.sdk.execution import PumpFunExecutionClient

        execution = self.settings.execution
        # Paper reads need no wallet: without a key a throwaway one signs
        # nothing. Live balance reads refuse without the real key.
        key = self.credentials.private_key or str(Keypair())
        return PumpFunExecutionClient(
            key,
            rpc_urls=list(self.credentials.rpc_urls),
            priority_fee_lamports=int(execution.priority_fee_lamports),
            compute_unit_limit=int(execution.compute_unit_limit),
            jito_tip_lamports=int(execution.jito_tip_lamports),
            use_jito=bool(execution.use_jito),
            default_slippage_bps=int(execution.slippage_bps),
        )

    def _record(self, row: dict[str, Any]) -> None:
        if self.recorder is not None:
            self.recorder.record_snapshot(row)

    def _store(self, reading: PoolReading) -> None:
        self.readings[reading.mint] = reading

    def _rpc_ok(self) -> None:
        if self.host is not None:
            self.host.notify_market_data()
            self.host.set_degraded(CONDITION_RPC, False)

    def _rpc_failed(self, detail: str) -> None:
        if self.host is not None:
            self.host.set_degraded(CONDITION_RPC, True, detail)

    def _feed_state(self, connected: bool, detail: str) -> None:
        if self.host is not None:
            self.host.set_degraded(CONDITION_FEED, not connected, detail)

    def _pool_feed_state(self, connected: bool, detail: str) -> None:
        if self.host is not None:
            self.host.set_degraded(CONDITION_POOL_FEED, not connected, detail)

    def on_migration(self, mint: str) -> None:
        """A coin left its curve for PumpSwap: start following its pool."""
        held = mint in self.paper_executor.holdings.raw
        if self.tracker.add(mint, now=self.clock(), held=held) is not None:
            logger.debug("following graduate %s", mint)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopping = False
        if self.recorder is not None:
            await self.recorder.start()
        if self.host is not None:
            for warning in unread_env_warnings():
                self.host.record_event(warning)
            if self.credentials.stream_key_in_url:
                self.host.record_event(
                    "PUMPFUN_STREAM_URL carries api-key: move it to "
                    "PUMPFUN_STREAM_API_KEY (BUG-118)"
                )
        if self.live_feeds:
            await self.check_rpc_network()
            self._start_feeds()

    def _start_feeds(self) -> None:
        """The migration feed, the pool poller and, when on, the new-pool
        feed (FEAT-80), each in its own task."""
        self._tasks.append(asyncio.create_task(self.feed.run(), name="pump_feed"))
        self._tasks.append(
            asyncio.create_task(
                self.poller.run(self.poll_tick, lambda: self._stopping, self.sleep),
                name="pump_poller",
            )
        )
        if self.settings.new_pools.enabled:
            self._tasks.append(
                asyncio.create_task(self.pool_feed.run(), name="pump_pool_feed")
            )

    async def check_rpc_network(self) -> list[str]:
        """Drop RPC endpoints that serve another network than mainnet-beta.

        An endpoint on devnet answers every mainnet pool read with "no
        account", which looks exactly like pools not created yet (BUG-160).
        Each endpoint is asked for its genesis hash at start: one on another
        network is removed while a mainnet (or unconfirmed) endpoint is left;
        when none is, the endpoints stay and ``rpc network`` is reported
        degraded. Returns the problems found.
        """
        pool = getattr(self.client, "rpc_pool", None)
        if pool is None:
            return []
        endpoints = list(pool.endpoints)
        hashes = await asyncio.gather(
            *(pool.endpoint_genesis_hash(endpoint) for endpoint in endpoints)
        )
        wrong, keep = _wrong_network(endpoints, hashes)
        if wrong:
            self._report_wrong_network(pool, wrong, keep=keep)
        return [text for _, text in wrong]

    def _report_wrong_network(
        self, pool: Any, wrong: list[tuple[Any, str]], *, keep: int
    ) -> None:
        detail = (
            "; ".join(text for _, text in wrong)
            + ", not mainnet-beta: check PUMPFUN_RPC_URL / PUMPFUN_RPC_URLS"
        )
        if keep:
            for endpoint, _ in wrong:
                pool.remove_endpoint(endpoint.url)
            detail += " (left out of the pool)"
        logger.error("RPC endpoint on the wrong network: %s", detail)
        if self.host is None:
            return
        self.host.record_event(f"RPC endpoint on the wrong network: {detail}")
        if not keep:
            self.host.set_degraded(CONDITION_NETWORK, True, detail)

    @property
    def poll_tick(self) -> float:
        graduation = self.settings.graduation
        return max(
            MIN_POLL_TICK_SECONDS,
            min(
                float(graduation.poll_interval_seconds),
                float(graduation.fast_poll_interval_seconds),
            ),
        )

    async def stop(self) -> None:
        self._stopping = True
        self.feed.stop()
        self.pool_feed.stop()
        await self.pool_watcher.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        if self.recorder is not None:
            await self.recorder.close()
        close = getattr(self.client, "close", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close()
        self._started = False

    # -- market data -----------------------------------------------------------
    async def reading(self, mint: str) -> PoolReading:
        """The latest reading, or a fresh one when it is too old."""
        now = self.clock()
        reading = self.readings.get(mint)
        max_age = float(self.settings.execution.quote_max_age_seconds)
        if reading is None or reading.age(now) > max_age:
            readings, rejected = await self.source.read_pools([mint], now=now)
            fresh = readings.get(mint)
            if fresh is None:
                raise QuoteUnavailable(
                    f"no PumpSwap pool for {mint} ({rejected.get(mint, 'missing')})"
                )
            self._store(fresh)
            reading = fresh
        return reading

    async def fee(self, reading: PoolReading) -> SwapFee:
        fee = await self.source.swap_fee(reading)
        self.fees[reading.mint] = fee
        return fee

    async def get_quote(self, instrument_id: str) -> MarketQuote:
        reading = await self.reading(instrument_id)
        if reading.drained:
            # A rug: no price to vouch for; exit value is 0 (exit_value below).
            return MarketQuote(instrument_id, timestamp=reading.at, stale=True)
        fee = await self.fee(reading)
        price = reading.price
        cut = fee.bps / 10_000.0
        return MarketQuote(
            instrument_id,
            bid=price * (1.0 - cut),
            ask=price * (1.0 + cut),
            last=price,
            timestamp=reading.at,
        )

    async def get_balance(self) -> float:
        if not self.credentials.has_private_key or self.client is None:
            raise RuntimeError("PUMPFUN_PRIVATE_KEY is not set: no wallet to read")
        return float(await self.client.get_wallet_balance_sol())

    async def execute(self, order: OrderRequest, *, paper: bool) -> Fill:
        if paper:
            return await self.paper_executor.execute(order)
        return await self.live_executor.execute(order)

    # -- strategy ----------------------------------------------------------------
    def pipeline(self) -> StrategyPipeline | None:
        named = self.lanes.named()
        if not named:
            return None
        if self._pipeline is None:
            enricher = self.enricher
            if any(lane.screen_entries for _, lane in named) and enricher is None:
                enricher = self.enricher = TokenEnricher(
                    execution_client=self.client, config=self.settings.screening
                )
            self._pipeline = build_pipeline(
                self.tracker,
                self.lanes,
                self.settings.execution,
                clock=self.clock,
                enricher=enricher,
            )
        return self._pipeline

    def should_exit(
        self, position: Position, quote: MarketQuote | None, now: float
    ) -> ExitDecision | None:
        """The position's lane exits (FEAT-79), when the lane has any: a
        wider take-profit than the engine's, per lane. A lane without exit
        rules, or a position of no known lane, leaves the decision to the
        engine's generic ``exits``."""
        if position.strategy not in (LANE, LANE_INSTANT):
            return None
        rules = self.lanes.settings(position.strategy).exits
        if not rules.any_enabled:
            return None
        price = None if position.price_stale else position.mark_price
        return evaluate_exit(position, rules, price=price, now=now)

    # -- valuation -----------------------------------------------------------------
    def exit_value(self, position: Position, quote: MarketQuote | None = None) -> float:
        """SOL a sale of the whole position into the pool would return now."""
        reading = self.readings.get(position.instrument_id)
        if reading is None:
            return super().exit_value(position, quote)
        fee = self.fees.get(position.instrument_id)
        bps = fee.bps if fee is not None else int(self.settings.execution.fee_bps_floor)
        tokens = int(round(float(position.size) * TOKEN_UNITS))
        return sell_lamports_out(reading, tokens, bps) / LAMPORTS_PER_SOL

    # -- presentation -----------------------------------------------------------------
    def format_price(self, price: float | None) -> str:
        if price is None or price <= 0:
            return "-"
        return f"{price * 1e6:.4f} µSOL"

    def instrument_label(self, instrument_id: str, name: str | None = None) -> str:
        """The mint address, shortened (``7rAX7yVr…pump``): the dashboard's
        Name column already shows the token's name."""
        text = str(instrument_id or "-")
        return text if len(text) <= 14 else f"{text[:8]}…{text[-4:]}"

    def status_rows(self) -> Sequence[tuple[str, str]]:
        feed = self.feed
        stats = self.tracker.stats
        poller = self.poller.stats
        rows = [
            (
                "PumpPortal",
                f"{'connected' if feed.connected else 'disconnected'} · "
                f"{feed.stats.get('migrations', 0)} migrations",
            ),
            (
                "Graduates",
                f"{len(self.tracker)} followed · {stats.get('readings', 0)} readings",
            ),
            (
                "Pool reads",
                f"{poller.get('polls', 0)} ok · {poller.get('poll_errors', 0)} failed"
                + (f" · {self.poller.last_error}" if self.poller.last_error else ""),
            ),
        ]
        pool = getattr(self.client, "rpc_pool", None)
        if pool is not None:
            telemetry = pool.get_telemetry()
            rows.append(
                (
                    "RPC endpoints",
                    f"{telemetry['healthy_endpoints']}/{telemetry['total_endpoints']} "
                    "healthy",
                )
            )
        if self.settings.new_pools.enabled:
            rows.append(("New pools", self.pool_watcher.status_text(self.pool_feed)))
        if self.recorder is not None:
            rows.append(("Capture", f"{self.recorder.records_written} rows"))
        return rows

    def files(self) -> Sequence[tuple[str, str]]:
        """The capture, for the Engine panel's file list (trading-core 0.2.2)."""
        path = self.settings.capture.path
        return (("Capture", str(path)),) if self.recorder is not None and path else ()

    def strategy_rows(self) -> Sequence[tuple[str, str]]:
        named = self.lanes.named()
        if not named:
            return [("Lane", "off (record-only)")]
        rows: list[tuple[str, str]] = []
        for name, lane in named:
            prefix = "" if name == LANE else "Instant "
            rows.append((f"{prefix}Lane", name))
            rows.append((f"{prefix}Signal", _signal_text(lane)))
            rows.append(
                (
                    "Standard pool" if name == LANE else "Instant pool",
                    f"first MC {lane.first_market_cap_min_sol:.0f}-"
                    f"{lane.first_market_cap_max_sol:.0f} SOL",
                )
            )
            if lane.exits.any_enabled:
                rows.append((f"{prefix}Exits", _exits_text(lane)))
        return rows

    # -- operations -------------------------------------------------------------------
    def is_public_identifier(self, segment: str) -> bool:
        return is_solana_pubkey(segment)

    def provenance(self) -> Mapping[str, Any]:
        return {
            "lane": asdict(self.settings.lane),
            "instant": asdict(self.settings.instant),
            "graduation": asdict(self.settings.graduation),
            "new_pools": asdict(self.settings.new_pools),
            "execution": asdict(self.settings.execution),
            "capture_path": self.settings.capture.path,
            "rpc_endpoints": len(self.credentials.rpc_urls),
            "fees": {
                mint: {"bps": fee.bps, "source": fee.source}
                for mint, fee in list(self.fees.items())[:5]
            },
        }


def _signal_text(lane: Any) -> str:
    band = f">= {lane.min_ratio:g}x" + (
        f" and < {lane.max_ratio:g}x" if lane.max_ratio else ""
    )
    return (
        f"{band} first price at {lane.signal_after_seconds:g}s "
        f"(+{lane.signal_window_seconds:g}s)"
    )


def _exits_text(lane: Any) -> str:
    rules = lane.exits
    parts = []
    if rules.take_profit_pct:
        parts.append(f"TP +{rules.take_profit_pct:.0%}")
    if rules.stop_loss_pct:
        parts.append(f"SL -{rules.stop_loss_pct:.0%}")
    if rules.trailing_drop_pct:
        parts.append(f"trail {rules.trailing_drop_pct:.0%}")
    if rules.max_hold_seconds:
        parts.append(f"max {rules.max_hold_seconds / 60:g} min")
    return " · ".join(parts)


__all__ = ["PUMP_QUOTE", "PumpModule", "QuoteUnavailable"]
