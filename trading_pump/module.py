"""``PumpModule``: Pump.fun graduates on PumpSwap, plugged into trading-core.

Registered as the ``pumpfun`` entry point, so a trading-core settings file
with ``"module": "pumpfun"`` runs it (docs/USER-GUIDE.md)::

    trading-core run --config configs/paper.example.json

Instruments are **mints** of coins that have graduated from the Pump.fun
bonding curve to their canonical PumpSwap pool. Prices are SOL per whole
token (6 decimals), shown in µSOL. The module:

* listens to PumpPortal's free migration feed and follows every graduate's
  pool for 4 hours (FEAT-73), writing each reading to the capture;
* quotes from those pool readings (a fresh read when the last one is older
  than ``execution.quote_max_age_seconds``; never a default price);
* fills paper orders against a fresh pool read with the pool's fee and the
  modelled network fee, priority fee, tip and rent (``execution.py``);
* values open positions at what selling into the pool would return now,
  after the fee (the circuit breaker's exit value, pumpfun BUG-136);
* proposes entries through the ``pumpswap_momentum`` lane (FEAT-76);
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
from trading_pump.recorder import ReplayRecorder
from trading_pump.strategies.enrichment import TokenEnricher
from trading_pump.strategies.pumpswap_momentum import LANE, build_pipeline

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
        lane = self.settings.lane
        self.tracker = GraduateTracker(
            self.settings.graduation,
            signal_after_seconds=(
                float(lane.signal_after_seconds) if lane.enabled else None
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
            self._tasks.append(asyncio.create_task(self.feed.run(), name="pump_feed"))
            self._tasks.append(
                asyncio.create_task(
                    self.poller.run(self.poll_tick, lambda: self._stopping, self.sleep),
                    name="pump_poller",
                )
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
        wrong = []
        keep = 0
        for endpoint, genesis in zip(endpoints, hashes, strict=True):
            if genesis is None:
                logger.warning(
                    "could not confirm the network of RPC endpoint %s", endpoint.label
                )
                keep += 1
            elif genesis != MAINNET_GENESIS_HASH:
                name = CLUSTER_GENESIS_HASHES.get(genesis, "an unknown network")
                wrong.append((endpoint, f"{endpoint.label} serves {name}"))
            else:
                keep += 1
        problems = [text for _, text in wrong]
        if not wrong:
            return problems
        detail = (
            "; ".join(problems) + ", not mainnet-beta: check PUMPFUN_RPC_URL / "
            "PUMPFUN_RPC_URLS"
        )
        if keep:
            for endpoint, _ in wrong:
                pool.remove_endpoint(endpoint.url)
            detail += " (left out of the pool)"
        logger.error("RPC endpoint on the wrong network: %s", detail)
        if self.host is not None:
            self.host.record_event(f"RPC endpoint on the wrong network: {detail}")
            if not keep:
                self.host.set_degraded(CONDITION_NETWORK, True, detail)
        return problems

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
        if not self.settings.lane.enabled:
            return None
        if self._pipeline is None:
            enricher = self.enricher
            if self.settings.lane.screen_entries and enricher is None:
                enricher = self.enricher = TokenEnricher(
                    execution_client=self.client, config=self.settings.screening
                )
            self._pipeline = build_pipeline(
                self.tracker,
                self.settings.lane,
                self.settings.execution,
                clock=self.clock,
                enricher=enricher,
            )
        return self._pipeline

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
        if self.recorder is not None:
            rows.append(("Capture", f"{self.recorder.records_written} rows"))
        return rows

    def strategy_rows(self) -> Sequence[tuple[str, str]]:
        lane = self.settings.lane
        if not lane.enabled:
            return [("Lane", "off (record-only)")]
        return [
            ("Lane", LANE),
            (
                "Signal",
                f">= {lane.min_ratio:g}x first price at "
                f"{lane.signal_after_seconds:g}s (+{lane.signal_window_seconds:g}s)",
            ),
            (
                "Standard pool",
                f"first MC {lane.first_market_cap_min_sol:.0f}-"
                f"{lane.first_market_cap_max_sol:.0f} SOL",
            ),
        ]

    # -- operations -------------------------------------------------------------------
    def is_public_identifier(self, segment: str) -> bool:
        return is_solana_pubkey(segment)

    def provenance(self) -> Mapping[str, Any]:
        return {
            "lane": asdict(self.settings.lane),
            "graduation": asdict(self.settings.graduation),
            "execution": asdict(self.settings.execution),
            "capture_path": self.settings.capture.path,
            "rpc_endpoints": len(self.credentials.rpc_urls),
            "fees": {
                mint: {"bps": fee.bps, "source": fee.source}
                for mint, fee in list(self.fees.items())[:5]
            },
        }


__all__ = ["PUMP_QUOTE", "PumpModule", "QuoteUnavailable"]
