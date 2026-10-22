from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterator, Optional

from dotenv import load_dotenv
from rich.live import Live

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.alerts import AlertDispatcher
from pumpfun_trading.bot.factory import (
    audit_retention_policy,
    build_arbitrage_monitor,
    build_bot_logger,
    build_copy_trade_engine,
    build_event_logger,
    build_execution_from_env,
    build_geyser_client,
    build_graduation_engine,
    build_order_flow_engine,
    build_persistence,
    build_replay_recorder,
    build_retention_managers,
    build_rpc_pool,
    resolve_audit_log_path,
    resolve_bot_config,
    resolve_replay_log_path,
    resolve_rpc_endpoints,
    resolve_status_path,
    retention_check_interval_seconds,
    replay_retention_policy,
    stream_max_consecutive_failures,
    use_jito_from_env,
)
from pumpfun_trading.bot.enrichment import (
    TokenEnricher,
    screening_snapshot,
)
from pumpfun_trading.bot.event_router import EventRouter
from pumpfun_trading.bot.handlers import curve as curve_handlers
from pumpfun_trading.bot.handlers import new_token as new_token_handlers
from pumpfun_trading.bot.handlers import raydium as raydium_handlers
from pumpfun_trading.bot.handlers import trade as trade_handlers
from pumpfun_trading.bot.handlers import watch as watch_handlers
from pumpfun_trading.bot.health import (
    health_ok_for_trading,
    mark_health_check,
    update_health_state,
)
from pumpfun_trading.bot.lifecycle import (
    TradingBotState,
    VALID_STATE_TRANSITIONS,
    settled_state,
)
from pumpfun_trading.bot.operator import OperatorPause
from pumpfun_trading.bot.pnl import PnlTotals, build_pnl_fields
from pumpfun_trading.bot.trade_feed import (
    TradeFeedBreaker,
    stream_connect_url,
    stream_url_has_api_key,
)
from pumpfun_trading.bot.trade_feed import is_confirmation as is_trade_feed_confirmation
from pumpfun_trading.bot.trade_feed import is_refusal as is_trade_feed_refusal
from pumpfun_trading.bot.reconcile import (
    ReconciliationStatusReader,
    describe_reconciliation_status,
    reconcile_status_path,
)
from pumpfun_trading.bot.position_manager import (
    CapitalDisplacementEngine,
    PositionManager,
)
from pumpfun_trading.bot.supervision import (
    DailySummarySchedule,
    DegradationMonitor,
    ReconcileGapWatcher,
    format_daily_summary,
)
from pumpfun_trading.bot.sweep import (
    SweepState,
    effective_sweep_floor,
    plan_sweep,
    validate_sweep_config,
)
from pumpfun_trading.bot.risk import (
    CircuitBreakerAction,
    DailyEquityTracker,
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
    evaluate_portfolio_circuit_breaker,
)
from pumpfun_trading.bot.strategy import (
    ArbitrageOpportunity,
    ExitAction,
    MempoolBackrunEngine,
    RaydiumPoolKeys,
    ScreeningCache,
    TokenScreeningVerdict,
    TradingBotConfig,
    TradingStrategy,
)
from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.execution.executor import ExecutionResult, OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.execution.sell_pipeline import (
    estimate_sell_proceeds,
    plan_sell_size,
    position_entry_sol,
    position_id,
    position_token_amounts,
    sell_replay_snapshot,
    sold_fraction,
    stop_exit_metrics,
)
from pumpfun_trading.infra.rpc_pool import RpcConnectionPool
from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.ops.events import (
    EventCategory,
    EventSeverity,
)
from pumpfun_trading.ops.logging import (
    get_configured_console,
)
from pumpfun_trading.ops.metrics import (
    metrics_snapshot,
    new_runtime_metrics,
    record_latency_ms,
    record_metric,
    restore_metrics,
)
from pumpfun_trading.ops.redact import redact_text
from pumpfun_trading.sdk.costs import (
    BASE_FEE_LAMPORTS_PER_SIGNATURE,
    COST_SOURCE_TRANSACTION_META,
    TransactionCosts,
)
from pumpfun_trading.sdk.curve import LAUNCH_MARKET_CAP_SOL, TOTAL_TOKEN_SUPPLY_RAW
from pumpfun_trading.sdk.execution import PUMP_DEFAULT_FEE_BPS, WSOL_MINT_STR
from pumpfun_trading.strategies.observation import CurveObservationList
from pumpfun_trading.strategies.regime import MarketRegimeTracker
from pumpfun_trading.strategies.shadow import (
    ShadowSignal,
    ShadowVariantBook,
    parse_shadow_variants,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)
from pumpfun_trading.streams.websocket import (
    MIGRATION_SUBSCRIPTION,
    MIGRATION_TX_TYPES,
    NEW_TOKEN_SUBSCRIPTION,
    run_websocket_stream,
    send_ws_message,
    token_trade_message,
)
from pumpfun_trading.ui.dashboard import build_dashboard

# Mints bought before; persisted in the status file and capped so the snapshot
# stays small (~2k new buys a day in the Stage 0 paper run) (BUG-109).
TRADED_MINTS_LIMIT = 10_000


class TradingBot:
    """Production-ready Pump.fun trading bot with modular SOLID architecture and lifecycle safeguards."""

    _VALID_STATE_TRANSITIONS: dict[TradingBotState, set[TradingBotState]] = (
        VALID_STATE_TRANSITIONS
    )
    # Created lazily by the first shadow fill (bot/handlers/trade.py).
    _shadow_fill_tasks: set[asyncio.Task[None]]
    # rc.3 record-only observations, created lazily (bot/handlers/observe.py).
    _reject_sample_list: CurveObservationList
    _discovery_list: CurveObservationList
    _discovery_scanned_at: float

    def __init__(
        self,
        private_key_b58: str,
        rpc_url: str,
        *,
        config: TradingBotConfig | None = None,
        buy_amount_sol: float | None = None,
        take_profit: float | None = None,
        stop_loss: float | None = None,
        max_active_positions: int | None = None,
        api_base_url: str = "https://frontend-api-v3.pump.fun",
        stream_url: str = "http://127.0.0.1:10000",
        geyser_endpoint: str | None = None,
        geyser_x_token: str | None = None,
        geyser_client: YellowstoneGeyserClient | None = None,
        min_market_cap_sol: float | None = None,
        min_balance_sol: float | None = None,
        dry_run: bool = False,
        paper_trade: bool = False,
        verbose: bool = True,
        headless: bool = False,
        log_file: str | None = None,
        strategy_preset: str = "balanced",
        audit_log_path: str | None = None,
        bot_status_path: str | None = None,
        replay_log_path: str | Path | None = None,
    ):
        resolved_config = resolve_bot_config(
            config=config,
            strategy_preset=strategy_preset,
            overrides={
                "buy_amount_sol": buy_amount_sol,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "max_active_positions": max_active_positions,
                "min_market_cap_sol": min_market_cap_sol,
                "min_balance_sol": min_balance_sol,
            },
            stream_url=stream_url,
            api_base_url=api_base_url,
            dry_run=dry_run,
            paper_trade=paper_trade,
            verbose=verbose,
            headless=headless,
            replay_log_path=replay_log_path,
        )
        self._stream_api_key: str | None = resolved_config.stream_api_key
        self._stream_key_in_url = resolved_config.stream_key_in_url
        self.config = resolved_config.config

        self.private_key_b58 = private_key_b58
        self.rpc_url = rpc_url
        self.api_base_url = self.config.api_base_url
        self.stream_url = self.config.stream_url
        self.buy_amount_sol = self.config.buy_amount_sol
        self.take_profit = self.config.take_profit
        self.stop_loss = self.config.stop_loss
        self.max_active_positions = self.config.max_active_positions
        # Positions are tracked one lot per mint, so pyramiding is unsupported (BUG-92).
        if self.config.max_positions_per_mint != 1:
            logging.getLogger(__name__).warning(
                "max_positions_per_mint=%s is not supported; using 1.",
                self.config.max_positions_per_mint,
            )
        self.max_positions_per_mint = 1
        self.min_market_cap_sol = self.config.min_market_cap_sol
        self.max_buy_attempts_per_mint = self.config.max_buy_attempts_per_mint
        self.min_balance_sol = self.config.min_balance_sol
        self.min_sell_balance = self.config.min_sell_balance
        self.recent_token_ttl_seconds = self.config.recent_token_ttl_seconds
        self.reconnect_delay_seconds = self.config.reconnect_delay_seconds
        self.dry_run = self.config.dry_run
        self.paper_trade = self.config.paper_trade
        self.verbose = self.config.verbose
        self.headless = self.config.headless or bool(
            os.getenv("PUMPFUN_HEADLESS", "").lower() in {"1", "true", "yes"}
        )
        self._stop_requested = False
        self._start_time = time.monotonic()
        self._last_message_at = time.monotonic()
        self._last_event = "waiting for new token stream"
        self._last_new_token = "-"
        self._last_new_token_name = "-"
        self._observed_tokens_count = 0
        self._last_status = "initializing"
        self._display_live: Optional[Live] = None
        self._trade_ledger: list[dict[str, Any]] = []
        self._recent_actions: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_events: deque[str] = deque(maxlen=20)
        self._trade_sequence = 0
        # Session gross/net PnL and costs since the status file was created (FEAT-49).
        self._pnl_totals = PnlTotals()
        self._health_ok = True
        self._risk_killed = False
        self._last_health_check = time.monotonic()
        self.state = TradingBotState.IDLE
        # In-flight buys/sells; a paper buy can wait while a sell runs (BUG-111).
        self._inflight_operations: dict[str, int] = {}
        self._counted_breaker_lock_at: float | None = None
        # Server notices from the stream (e.g. PumpPortal refusals) by text (BUG-112).
        self._stream_server_messages: dict[str, int] = {}
        self.trade_feed_breaker = TradeFeedBreaker(
            probe_interval_seconds=float(
                getattr(self.config, "trade_feed_probe_seconds", 300.0) or 300.0
            ),
            stream_has_api_key=stream_url_has_api_key(self._stream_connect_url()),
        )

        # Subsystems & Engines
        self.position_manager = PositionManager(self.config)
        self.active_positions = self.position_manager.get_all_positions()
        self.displacement_engine = CapitalDisplacementEngine(
            self.config, self.position_manager
        )

        self.strategy = TradingStrategy(self.config)
        self.order_flow_engine = build_order_flow_engine(self.config)
        # Confirmed-entry watch list counters (FEAT-51): watched, promoted, ...
        self._watch_stats: dict[str, int] = {}
        # Entry lane per bought mint (momentum / pre_graduation), for sell records.
        self._entry_lane_by_mint: dict[str, str] = {}
        self.graduation_engine = build_graduation_engine(self.config)
        # Hour / launch rate / graduation rate on every buy and screen record.
        self.market_regime = MarketRegimeTracker()
        self.arb_monitor = build_arbitrage_monitor(self.config)
        self.backrun_engine = MempoolBackrunEngine(
            disparity_monitor=self.arb_monitor,
        )
        self.copy_trade_engine = build_copy_trade_engine(self.config)

        self.daily_equity_tracker = DailyEquityTracker()
        self.wallet_balance_sol = self._initial_simulated_balance()
        # Live runs start from the simulated figure above until the first real
        # balance read; the breaker must not baseline the day on it (BUG-130).
        self._live_balance_confirmed = False
        self.screening_cache = ScreeningCache(
            default_ttl=float(self.config.screening_cache_ttl_seconds)
        )
        self._buy_attempts: dict[str, int] = {}
        self._seen_mints: dict[str, float] = {}
        # Every mint ever bought (wall-clock time of the buy), oldest first (BUG-109).
        self._traded_mints: dict[str, float] = {}
        # Stream tokens rejected as not Pump.fun launches, by reason (BUG-108).
        self._non_pump_rejections: dict[str, int] = {}
        self._mayhem_rejections = 0
        self.console = get_configured_console(file=sys.stdout)

        self.geyser_endpoint = geyser_endpoint or os.getenv("PUMPFUN_GEYSER_ENDPOINT")
        self.geyser_x_token = geyser_x_token or os.getenv("PUMPFUN_GEYSER_X_TOKEN")
        self.geyser_client = geyser_client or build_geyser_client(
            endpoint=self.geyser_endpoint,
            x_token=self.geyser_x_token,
            stream_url=self.stream_url,
            reconnect_delay_seconds=self.reconnect_delay_seconds,
        )
        self._active_ws: Optional[Any] = None

        self._stream_consecutive_failures = 0
        self._circuit_breaker_tripped = False
        self._max_stream_consecutive_failures = stream_max_consecutive_failures()

        self._exit_retry_queue: dict[str, dict[str, Any]] = {}
        self.max_exit_retries = int(os.getenv("PUMPFUN_MAX_EXIT_RETRIES", "5"))
        self.base_exit_slippage_bps = int(
            os.getenv("PUMPFUN_BASE_EXIT_SLIPPAGE_BPS", "500")
        )
        self.max_exit_slippage_bps = int(
            os.getenv("PUMPFUN_MAX_EXIT_SLIPPAGE_BPS", "5000")
        )

        # RPC Pooling & Failover (FEAT-08)
        endpoints_list = resolve_rpc_endpoints(self.config, self.rpc_url)
        self.rpc_pool: RpcConnectionPool | None = build_rpc_pool(
            self.config, endpoints_list
        )
        self.logger, effective_log_file = build_bot_logger(
            self.config, log_file=log_file, headless=self.headless, verbose=self.verbose
        )

        self._metrics = new_runtime_metrics()

        # Multi-Channel Alerting & Persistence Extracted Components
        self.alert_provider = (
            os.getenv("PUMPFUN_ALERT_PROVIDER", "none").lower().strip()
        )
        self.alert_discord_webhook_url = os.getenv("PUMPFUN_ALERT_DISCORD_WEBHOOK_URL")
        self.alert_slack_webhook_url = os.getenv("PUMPFUN_ALERT_SLACK_WEBHOOK_URL")
        self.alert_telegram_bot_token = os.getenv("PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN")
        self.alert_telegram_chat_id = os.getenv("PUMPFUN_ALERT_TELEGRAM_CHAT_ID")
        self.alerts = AlertDispatcher(
            provider=self.alert_provider,
            discord_webhook_url=self.alert_discord_webhook_url,
            slack_webhook_url=self.alert_slack_webhook_url,
            telegram_bot_token=self.alert_telegram_bot_token,
            telegram_chat_id=self.alert_telegram_chat_id,
        )
        self.alert_enabled = self.alerts.enabled
        # Webhook deliveries in flight; never awaited on the trading path (BUG-110).
        self._alert_tasks: set[asyncio.Task[bool]] = set()

        # Unattended operation (Sprint 24D): operator pause, daily summary,
        # degradation alerts and the profit sweep. Restored by safe_startup().
        self._operator_pause = OperatorPause()
        self._daily_summary = DailySummarySchedule(
            hour_utc=int(getattr(self.config, "daily_summary_hour_utc", 0)) % 24
        )
        degradation_minutes = getattr(self.config, "degradation_alert_minutes", 5.0)
        self._degradation = DegradationMonitor(
            threshold_seconds=max(0.0, float(degradation_minutes)) * 60.0
        )
        self._reconcile_watcher = ReconcileGapWatcher()
        self._sweep_state = SweepState()

        self.bot_status_path = resolve_status_path(bot_status_path)
        self.audit_log_path = resolve_audit_log_path(audit_log_path)
        self.audit_policy = audit_retention_policy(self.config)
        self.persistence = build_persistence(
            bot_status_path=self.bot_status_path,
            audit_log_path=self.audit_log_path,
            policy=self.audit_policy,
        )

        # Diagnostic Telemetry Event Logger (FEAT-30)
        self.event_logger, effective_event_log_path = build_event_logger(self.config)
        self._audit_handle = self.persistence._audit_handle

        self.replay_log_path = resolve_replay_log_path(replay_log_path, self.config)
        self.replay_policy = replay_retention_policy(self.config)
        self.replay_recorder = build_replay_recorder(
            self.replay_log_path, self.replay_policy
        )

        # Retention managers and background pruning
        self._last_retention_check = time.monotonic()
        self.retention_check_interval_seconds = retention_check_interval_seconds(
            self.config
        )
        self.retention_managers = build_retention_managers(
            (
                effective_log_file,
                self.audit_log_path,
                effective_event_log_path,
                self.replay_log_path,
            ),
            self.audit_policy,
        )

        self.api = PumpFunApiClient(base_url=self.api_base_url)

        self.use_jito = use_jito_from_env()
        self.execution = build_execution_from_env(
            self.private_key_b58,
            rpc_url=self.rpc_url,
            rpc_pool=self.rpc_pool,
            endpoints=endpoints_list,
            config=self.config,
            use_jito=self.use_jito,
        )

        self.arb_builder = AtomicArbitrageBuilder(self.execution)
        self.arb_executor = AtomicArbitrageExecutor(
            execution_client=self.execution,
            builder=self.arb_builder,
            dry_run=self.dry_run,
        )

        # Extracted Order Executor, Liquidator, and Token Enricher
        self.executor = OrderExecutor(
            execution_client=self.execution,
            config=self.config,
            rpc_pool=self.rpc_pool,
            use_jito=self.use_jito,
            dry_run=self.dry_run,
        )
        self.liquidator = OrderLiquidator(
            executor=self.executor,
            position_manager=self.position_manager,
            config=self.config,
        )
        self.enricher = TokenEnricher(
            api_client=self.api,
            execution_client=self.execution,
            config=self.config,
            strategy=self.strategy,
            screening_cache=self.screening_cache,
        )

        # Event Router Wiring
        self.event_router = EventRouter(
            on_curve_update=self._handle_bonding_curve_state_update,
            on_trade_event=self._handle_trade_event_update,
            on_complete_event=self._handle_complete_event_update,
            on_raydium_pool=self._handle_raydium_pool_update,
            on_ws_new_token=self._handle_new_token_event,
            on_ws_trade=self._handle_trade_update,
        )

        self._trade_lock = asyncio.Lock()
        # Per-mint sell serialization (BUG-41) and graduation exit state (BUG-44).
        self._sell_locks: dict[str, asyncio.Lock] = {}
        self._migrating_mints: set[str] = set()
        self._raydium_exit_pools: dict[str, RaydiumPoolKeys] = {}
        self._config = self.config
        sweep_problems = validate_sweep_config(
            self.config, self.execution.get_wallet_pubkey()
        )
        if sweep_problems:
            # Fail fast: a misconfigured sweep must never move funds (FEAT-42).
            raise ValueError("profit sweep misconfigured: " + "; ".join(sweep_problems))
        self.safe_startup()

    @property
    def config(self) -> TradingBotConfig:
        return self._config

    @config.setter
    def config(self, value: TradingBotConfig) -> None:
        self._config = value
        if hasattr(self, "position_manager") and self.position_manager is not None:
            self.position_manager.config = value
        if hasattr(self, "strategy") and self.strategy is not None:
            self.strategy.config = value
        if hasattr(self, "enricher") and self.enricher is not None:
            self.enricher.config = value
        if hasattr(self, "executor") and self.executor is not None:
            self.executor.config = value

    @property
    def uptime_seconds(self) -> float:
        """Return the bot's runtime uptime in seconds using monotonic clock."""
        start = getattr(self, "_start_time", None) or getattr(self, "_started_at", None)
        if start is None:
            return 0.0
        return max(0.0, time.monotonic() - float(start))

    @property
    def uptime(self) -> str:
        """Return formatted uptime string."""
        from pumpfun_trading.ui.dashboard import format_uptime

        return format_uptime(self.uptime_seconds)

    def reconciliation_status(self) -> dict[str, Any] | None:
        """Last ``pumpfun-audit reconcile`` result for this audit trail (FEAT-49)."""
        path = reconcile_status_path(getattr(self, "audit_log_path", None))
        reader = getattr(self, "_reconcile_reader", None)
        if not isinstance(reader, ReconciliationStatusReader) or reader.path != path:
            reader = ReconciliationStatusReader(path)
            self._reconcile_reader = reader
        return reader.read()

    async def close(self) -> None:
        """Closes persistence handles and background resources."""
        self.persistence.close()
        if hasattr(self, "event_logger") and self.event_logger is not None:
            await self.event_logger.flush_and_close()
        if self.replay_recorder is not None:
            await self.replay_recorder.close()
        if hasattr(self, "rpc_pool") and self.rpc_pool is not None:
            await self.rpc_pool.close()
        await self._close_http_clients()

    async def _close_http_clients(self) -> None:
        for client in (getattr(self, "execution", None), getattr(self, "api", None)):
            if client is None or not hasattr(client, "close"):
                continue
            try:
                res = client.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                self._log(f"Error closing client: {exc}", level=logging.DEBUG)

    def _configure_alerting(self) -> None:
        self.alerts.provider = (self.alert_provider or "").lower().strip()
        self.alerts.discord_webhook_url = self.alert_discord_webhook_url
        self.alerts.slack_webhook_url = self.alert_slack_webhook_url
        self.alerts.telegram_bot_token = self.alert_telegram_bot_token
        self.alerts.telegram_chat_id = self.alert_telegram_chat_id
        self.alerts._configure()
        self.alert_enabled = self.alerts.enabled

    def _send_alert(self, message: str) -> None:
        if not self.alert_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.alerts.send_alert(message)
            return
        # A webhook call blocks for up to 10 s; never on the trading loop (BUG-110).
        task = loop.create_task(self.alerts.send_alert_async(message))
        tasks = getattr(self, "_alert_tasks", None)
        if tasks is None:
            tasks = self._alert_tasks = set()
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def _flush_alerts(self, timeout_seconds: float = 5.0) -> None:
        """Waits (bounded) for alerts still being delivered, e.g. on shutdown."""
        pending = list(getattr(self, "_alert_tasks", ()) or ())
        if pending:
            await asyncio.wait(pending, timeout=timeout_seconds)

    @property
    def buying_paused(self) -> bool:
        pause = getattr(self, "_operator_pause", None)
        return bool(pause is not None and pause.paused)

    def pause_buying(self, reason: str = "operator", source: str = "api") -> bool:
        """No new buys; open positions keep being managed (Sprint 24D, FEAT-50)."""
        if not self._operator_pause.pause(reason=reason, source=source):
            return False
        self._on_pause_change(f"buying paused ({reason}, via {source})")
        return True

    def resume_buying(self, source: str = "api") -> bool:
        if not self._operator_pause.resume(source=source):
            return False
        self._on_pause_change(f"buying resumed (via {source})")
        tracker = getattr(self, "daily_equity_tracker", None)
        if isinstance(tracker, DailyEquityTracker) and tracker.cumulative_cap_hit:
            # Resuming after the cumulative loss cap is the operator's reset:
            # the cap is measured again from the equity as it is now (BUG-128).
            equity = float(self.wallet_balance_sol) + float(
                self.position_manager.calculate_total_open_value()
            )
            tracker.reset_circuit_breaker(new_baseline_sol=equity)
            self._risk_killed = False
            self._record_event(
                f"cumulative loss cap reset by the operator (reference: {equity:.4f} SOL)",
                alert=True,
            )
        return True

    def toggle_buying_pause(self, source: str = "SIGUSR1") -> bool:
        """``SIGUSR1`` handler; returns the new paused state."""
        if self.buying_paused:
            self.resume_buying(source=source)
        else:
            self.pause_buying(reason="operator signal", source=source)
        return self.buying_paused

    def _on_pause_change(self, message: str) -> None:
        self._log(message, level=logging.WARNING)
        self._last_status = message
        self._record_event(message, alert=True)
        self._write_audit_record(
            "operator_pause",
            {
                **self._operator_pause.to_dict(),
                "open_positions": len(self.active_positions),
            },
        )

    def _write_status_snapshot(self) -> None:
        if not self.bot_status_path:
            return
        snapshot = self.get_status_snapshot()
        snapshot.update(
            {
                "timestamp": time.time(),
                "last_event": self._last_event,
                "last_status": self._last_status,
                "last_new_token": self._last_new_token,
                "last_new_token_name": self._last_new_token_name,
                "observed_tokens": self._observed_tokens_count,
                "audit_log_path": self.audit_log_path,
                "bot_status_path": self.bot_status_path,
                "metrics": self._metrics_snapshot(),
                "recent_events": list(self._recent_events),
                "alert_provider": self.alert_provider,
                "alert_enabled": self.alert_enabled,
                "reconciliation": self.reconciliation_status(),
                # So `kill -USR1 <pid>` can find the process (Sprint 24D).
                "pid": os.getpid(),
            }
        )
        self.persistence.write_status_snapshot(snapshot)

    def safe_startup(self) -> None:
        """Restores persisted bot state and reconciles active on-chain positions during startup."""
        self.persistence.bot_status_path = self.bot_status_path
        self.persistence.audit_log_path = self.audit_log_path
        snapshot = self.persistence.load_status_snapshot()
        if not snapshot:
            return

        positions = snapshot.get("active_positions")
        if isinstance(positions, dict):
            self.position_manager.restore_from_dict(positions)
            self.active_positions = self.position_manager.get_all_positions()
            for mint, pos in self.active_positions.items():
                if pos.pop("migrating", False):
                    self._migrating_mints.add(mint)
                if pos.get("pool_keys") is None:
                    pos.pop("pool_keys", None)
        elif isinstance(positions, list):
            self.position_manager.clear()
            self.active_positions = self.position_manager.get_all_positions()

        buy_attempts = snapshot.get("buy_attempts", {})
        if isinstance(buy_attempts, dict):
            self._buy_attempts = {
                str(key): int(value)
                for key, value in buy_attempts.items()
                if isinstance(value, (int, float))
            }

        seen_mints = snapshot.get("seen_mints", {})
        if isinstance(seen_mints, dict):
            self._seen_mints = {
                str(key): float(value)
                for key, value in seen_mints.items()
                if isinstance(value, (int, float))
            }

        traded_mints = snapshot.get("traded_mints", {})
        if isinstance(traded_mints, dict):
            self._traded_mints = {
                str(key): float(value)
                for key, value in traded_mints.items()
                if isinstance(value, (int, float))
            }
        # Older snapshots: anything in the ledger was traded (BUG-109).
        for item in snapshot.get("trade_ledger") or []:
            if isinstance(item, dict) and item.get("mint"):
                self._traded_mints.setdefault(str(item["mint"]), 0.0)
        for mint in self.active_positions:
            self._traded_mints.setdefault(mint, 0.0)

        trade_ledger = snapshot.get("trade_ledger", [])
        if isinstance(trade_ledger, list):
            self._trade_ledger = [
                item for item in trade_ledger if isinstance(item, dict)
            ]

        recent_actions = snapshot.get("recent_actions", [])
        if isinstance(recent_actions, list):
            self._recent_actions = deque(maxlen=50)
            for item in recent_actions:
                if isinstance(item, dict):
                    self._recent_actions.append(item)

        recent_events = snapshot.get("recent_events", [])
        if isinstance(recent_events, list):
            self._recent_events = deque(maxlen=20)
            for item in recent_events:
                self._recent_events.append(str(item))

        exit_retry_queue = snapshot.get("exit_retry_queue")
        if isinstance(exit_retry_queue, dict):
            # Monotonic timestamps are meaningless after a restart: retry now (BUG-39).
            now_mono = time.monotonic()
            self._exit_retry_queue = {
                str(k): {
                    **dict(v),
                    "first_attempt": now_mono,
                    "last_attempt": now_mono,
                    "next_retry_at": now_mono,
                }
                for k, v in exit_retry_queue.items()
                if isinstance(v, dict)
            }

        if "circuit_breaker_tripped" in snapshot:
            self._circuit_breaker_tripped = bool(
                snapshot.get("circuit_breaker_tripped")
            )

        if "state" in snapshot:
            try:
                self.state = TradingBotState(snapshot["state"])
            except ValueError:
                self.state = TradingBotState.IDLE
        if self.state == TradingBotState.SHUTDOWN:
            self.state = TradingBotState.IDLE

        self._health_ok = bool(snapshot.get("health_ok", self._health_ok))
        self._risk_killed = bool(snapshot.get("risk_killed", self._risk_killed))
        self._stop_requested = False
        # `_last_message_at` is a monotonic clock; a persisted value is meaningless (BUG-72).
        self._last_event = str(snapshot.get("last_event", self._last_event))
        self._last_status = str(snapshot.get("last_status", self._last_status))
        self._last_new_token = str(snapshot.get("last_new_token", self._last_new_token))
        self._last_new_token_name = str(
            snapshot.get("last_new_token_name", self._last_new_token_name)
        )
        self._observed_tokens_count = int(
            snapshot.get(
                "observed_tokens",
                snapshot.get("metrics", {}).get(
                    "observed_tokens", self._observed_tokens_count
                ),
            )
        )
        self._trade_sequence = max(
            int(snapshot.get("trade_sequence", self._trade_sequence)),
            len(self._trade_ledger),
        )
        pnl_totals = snapshot.get("pnl_totals")
        if isinstance(pnl_totals, dict):
            self._pnl_totals = PnlTotals.from_dict(pnl_totals)
        # A supervisor restart must never resume buying on its own (Sprint 24D).
        self._operator_pause = OperatorPause.from_dict(snapshot.get("operator_pause"))
        self._daily_summary = DailySummarySchedule.from_dict(
            snapshot.get("daily_summary"), hour_utc=self._daily_summary.hour_utc
        )
        self._sweep_state = SweepState.from_dict(snapshot.get("profit_sweep"))

        equity_tracker_data = snapshot.get("daily_equity_tracker")
        if isinstance(equity_tracker_data, dict):
            self.daily_equity_tracker = DailyEquityTracker.from_dict(
                equity_tracker_data
            )
        elif "circuit_breaker_engaged" in snapshot:
            self.daily_equity_tracker.circuit_breaker_engaged = bool(
                snapshot.get("circuit_breaker_engaged", False)
            )
            # Before BUG-114 the lockout field held the lock time.
            self.daily_equity_tracker.locked_at_timestamp = snapshot.get(
                "circuit_breaker_locked_at",
                snapshot.get("circuit_breaker_lockout_until"),
            )
        # A lock restored from disk was already counted when it tripped (BUG-114).
        self._counted_breaker_lock_at = self.daily_equity_tracker.locked_at_timestamp

        metrics = snapshot.get("metrics", {})
        if isinstance(metrics, dict):
            restore_metrics(self._metrics, metrics)

        self._log(
            f"Restored persisted bot state from {self.bot_status_path} with {len(self.active_positions)} active positions.",
            level=logging.INFO,
        )

    def _holder_lookup_stats(self) -> dict[str, int]:
        stats = getattr(getattr(self, "enricher", None), "holder_lookup_stats", None)
        return dict(stats) if isinstance(stats, dict) else {}

    def _transition_to(self, next_state: TradingBotState, reason: str = "") -> None:
        current = self.state
        next_state = settled_state(
            current, next_state, holds_positions=bool(self.active_positions)
        )
        if current == next_state:
            return
        if (
            next_state in (TradingBotState.MONITORING, TradingBotState.HOLDING)
            and current in (TradingBotState.BUYING, TradingBotState.SELLING)
            and self._inflight_count() > 1
        ):
            # Another buy/sell is still running; it settles the state (BUG-111).
            return
        if current == TradingBotState.SHUTDOWN and next_state != TradingBotState.IDLE:
            # In-flight work finishing after shutdown must not revive the bot (BUG-91).
            self._log(
                f"Shutdown in progress; skipped transition to {next_state} ({reason})",
                level=logging.DEBUG,
            )
            return
        if next_state not in self._VALID_STATE_TRANSITIONS.get(current, set()):
            if current == TradingBotState.IDLE and next_state == TradingBotState.BUYING:
                self._transition_to(
                    TradingBotState.MONITORING, reason="auto_advance_idle_to_monitoring"
                )
                current = self.state
            else:
                self._log(
                    f"Ignored invalid state transition from {current} to {next_state} (reason: {reason})",
                    level=logging.WARNING,
                )
                return

        self.state = next_state
        event = {
            "timestamp": time.time(),
            "from_state": current.value,
            "to_state": next_state.value,
            "reason": reason,
        }
        self._recent_actions.append(event)
        self._write_audit_record("state_transition", event)
        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.LIFECYCLE,
                severity=EventSeverity.INFO,
                event_name="state_transition",
                data={
                    "from_state": current.value,
                    "to_state": next_state.value,
                    "reason": reason,
                },
            )
        self._record_event(
            f"state: {current.value} -> {next_state.value}"
            + (f" ({reason})" if reason else ""),
            alert=False,
        )
        self._write_status_snapshot()
        if self.alert_enabled and next_state in {
            TradingBotState.BUYING,
            TradingBotState.SELLING,
            TradingBotState.SHUTDOWN,
        }:
            self._send_alert(
                f"Bot state change: {current.value} -> {next_state.value}"
                + (f" | {reason}" if reason else "")
            )

    def _write_audit_record(self, record_type: str, payload: dict[str, Any]) -> None:
        self.persistence.write_audit_record(record_type, self.state.value, payload)
        self._write_status_snapshot()

    @staticmethod
    def validate_mint_address(mint: str) -> str:
        if not isinstance(mint, str) or not mint.strip():
            raise ValueError("Mint address is required.")
        cleaned = mint.strip()
        try:
            decoded = __import__("base58").b58decode(cleaned)
        except Exception as exc:
            raise ValueError(
                f"Invalid mint address '{cleaned}'. It must be a valid base58 Solana mint address."
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                f"Invalid mint address '{cleaned}'. Solana mint addresses decode to 32 bytes, not {len(decoded)}."
            )
        return cleaned

    @classmethod
    def from_env(cls, *, env_file: str | None = None, **kwargs) -> "TradingBot":
        if env_file is not None:
            load_dotenv(env_file)
        else:
            load_dotenv()

        private_key = os.getenv("PUMPFUN_PRIVATE_KEY") or os.getenv(
            "SOLANA_PRIVATE_KEY"
        )
        rpc_url = (
            os.getenv("PUMPFUN_RPC_URL")
            or os.getenv("HELIUS_RPC_URL")
            or (os.getenv("PUMPFUN_RPC_URLS") or "").split(",")[0].strip()
            or (os.getenv("SOLANA_RPC_URLS") or "").split(",")[0].strip()
        )
        if not private_key:
            raise ValueError(
                "Missing PUMPFUN_PRIVATE_KEY (or SOLANA_PRIVATE_KEY) in environment."
            )
        if not rpc_url:
            raise ValueError(
                "Missing PUMPFUN_RPC_URL (or HELIUS_RPC_URL / PUMPFUN_RPC_URLS) in environment."
            )
        replay_log_path = kwargs.pop("replay_log_path", None) or os.getenv(
            "PUMPFUN_REPLAY_LOG_PATH"
        )
        if not replay_log_path:
            rec_env = os.getenv("PUMPFUN_RECORD_REPLAY")
            if rec_env and rec_env.lower() not in {"false", "0", "no"}:
                replay_log_path = (
                    rec_env
                    if rec_env.lower() not in {"true", "1", "yes"}
                    else "market_replay.jsonl"
                )
        headless = kwargs.pop("headless", None)
        if headless is None:
            head_env = os.getenv("PUMPFUN_HEADLESS", "")
            headless = head_env.lower() in {"1", "true", "yes"}
        return cls(
            private_key,
            rpc_url,
            headless=headless,
            replay_log_path=replay_log_path,
            **kwargs,
        )

    def _log(self, message: str, level: int = logging.INFO) -> None:
        if self.verbose or self.headless:
            self.logger.log(level, message)

    def request_shutdown(self) -> None:
        self._stop_requested = True
        self._last_status = "shutdown requested"
        self._record_event("shutdown requested", alert=False)
        if hasattr(self, "geyser_client") and self.geyser_client is not None:
            self.geyser_client._running = False
        if self.state != TradingBotState.SHUTDOWN:
            self._transition_to(TradingBotState.SHUTDOWN, reason="shutdown_requested")
        self._log("Shutdown requested.")

    def _register_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self.request_shutdown())
            except (ValueError, OSError):
                pass
        self._register_pause_signal()

    def _register_pause_signal(self) -> None:
        """``SIGUSR1`` toggles the operator pause (POSIX only; Sprint 24D)."""
        sigusr1 = getattr(signal, "SIGUSR1", None)
        if sigusr1 is None:
            return
        try:
            # Through the loop, so the handler runs as a normal callback and may
            # schedule alert tasks safely.
            asyncio.get_running_loop().add_signal_handler(
                sigusr1, self.toggle_buying_pause
            )
            return
        except (RuntimeError, NotImplementedError, ValueError, OSError):
            pass
        try:
            signal.signal(sigusr1, lambda *_: self.toggle_buying_pause())
        except (ValueError, OSError):
            pass

    def _prune_strategy_caches(self) -> None:
        """Evict stale per-mint screening, order-flow and graduation state (BUG-77)."""
        from pumpfun_trading.strategies.filters import _GLOBAL_SCREENING_CACHE

        _GLOBAL_SCREENING_CACHE.evict_expired()
        self.order_flow_engine.cleanup_inactive_tokens()
        self.graduation_engine.cleanup_expired_candidates()

    def _prune_seen_mints(self) -> None:
        cutoff = time.monotonic() - self.recent_token_ttl_seconds
        expired = [
            mint for mint, seen_at in self._seen_mints.items() if seen_at < cutoff
        ]
        for mint in expired:
            self._seen_mints.pop(mint, None)

    def _mark_seen(self, mint: str) -> None:
        self._prune_seen_mints()
        self._seen_mints[mint] = time.monotonic()

    def _is_recently_seen(self, mint: str) -> bool:
        self._prune_seen_mints()
        return mint in self._seen_mints

    def _mark_traded(self, mint: str) -> None:
        self._traded_mints.pop(mint, None)
        self._traded_mints[mint] = time.time()
        while len(self._traded_mints) > TRADED_MINTS_LIMIT:
            self._traded_mints.pop(next(iter(self._traded_mints)))

    def _is_closed_reentry(self, mint: str) -> bool:
        """A mint already traded whose position is closed: never buy it again.

        The seen-mints cache expires after ``recent_token_ttl_seconds`` and a
        fill resets the attempt counter, so Stage 0 bought exited mints again
        hours later (BUG-109). Adding to an open position is still allowed.
        """
        if getattr(self.config, "allow_mint_reentry", False):
            return False
        return mint in self._traded_mints and mint not in self.active_positions

    def _next_trade_id(self) -> str:
        self._trade_sequence += 1
        return f"trade-{self._trade_sequence:06d}"

    @staticmethod
    def _execution_costs(exec_res: Any) -> TransactionCosts | None:
        """Transaction costs attached to an execution result, if any (FEAT-49)."""
        costs = getattr(exec_res, "costs", None)
        return costs if isinstance(costs, TransactionCosts) else None

    def _paper_round_trip_fee_factor(self) -> float:
        """``(1 - fee)^2``: share of SOL left after the buy and sell protocol fees."""
        fee_bps = getattr(self.execution, "pump_fee_bps", PUMP_DEFAULT_FEE_BPS)
        if not isinstance(fee_bps, int) or not 0 <= fee_bps < 10_000:
            fee_bps = PUMP_DEFAULT_FEE_BPS
        return (1.0 - fee_bps / 10_000.0) ** 2

    def _paper_exit_factor(self) -> float:
        """Round-trip fee factor times the paper exit haircut (BUG-126)."""
        bps = getattr(self.config, "paper_exit_slippage_bps", 0)
        bps = bps if isinstance(bps, int) and not isinstance(bps, bool) else 0
        keep = (10_000 - max(0, min(5_000, bps))) / 10_000.0
        return self._paper_round_trip_fee_factor() * keep

    def _open_positions_exit_value(self) -> float:
        """Open positions at what selling them would return, for the breaker.

        Spot value times the same fee and exit haircut a sell pays, so equity
        is not overstated and drawdown checks fire on time (BUG-136).
        """
        spot = float(self.position_manager.calculate_total_open_value() or 0.0)
        return spot * self._paper_exit_factor()

    def _book_trade_costs(self, net_pnl_sol: float, costs_sol: float) -> None:
        """Feeds net realized PnL to the daily breaker; paper wallets pay costs too."""
        tracker = getattr(self, "daily_equity_tracker", None)
        if tracker is not None:
            tracker.record_realized_trade(net_pnl_sol, costs_sol)
        if costs_sol and (self.dry_run or self.paper_trade):
            self.wallet_balance_sol = max(
                0.0, float(self.wallet_balance_sol) - float(costs_sol)
            )

    def _record_trade(
        self,
        *,
        mint: str,
        action: str,
        token_name: str | None = None,
        mint_name: str | None = None,
        entry: float | None = None,
        exit_value: float | None = None,
        reason: str | None = None,
        trade_id: str | None = None,
        position_id: str | None = None,
        buy_price: float | None = None,
        sell_price: float | None = None,
        entry_price: float | None = None,
        exit_price: float | None = None,
        unit_price_sol: float | None = None,
        signature: str | None = None,
        costs: TransactionCosts | None = None,
        strategy: str | None = None,
        entry_metrics: dict[str, Any] | None = None,
        exit_metrics: dict[str, Any] | None = None,
    ) -> None:
        trade_id = trade_id or self._next_trade_id()
        position_id = position_id or trade_id
        pos_info = self.active_positions.get(mint, {})
        # Entry lane (FEAT-52): momentum / pre_graduation buys and their sells
        # are grouped apart from the preset in ``pumpfun-audit pnl``.
        lane = strategy or pos_info.get("strategy") or self._entry_lanes().get(mint)
        name = (
            token_name
            or mint_name
            or pos_info.get("name")
            or (self._last_new_token_name if self._last_new_token == mint else None)
        )
        if buy_price is not None:
            effective_buy_price = float(buy_price)
        elif entry_price is not None:
            effective_buy_price = float(entry_price)
        elif entry is not None and float(entry) > 0:
            effective_buy_price = float(entry)
        else:
            effective_buy_price = float(
                pos_info.get("buy_price")
                or pos_info.get("entry_price")
                or pos_info.get("cost_sol")
                or pos_info.get("entry_sol")
                or 0.0
            )

        if sell_price is not None:
            effective_sell_price = float(sell_price)
        elif exit_price is not None:
            effective_sell_price = float(exit_price)
        elif exit_value is not None:
            effective_sell_price = float(exit_value)
        else:
            effective_sell_price = 0.0

        entry_mc = float(pos_info.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(pos_info.get("current_market_cap", 0.0) or entry_mc or 0.0)
        if unit_price_sol is not None:
            eff_unit_price = float(unit_price_sol)
        elif "sell" in action:
            eff_unit_price = (
                curr_mc / 1_000_000_000.0
                if curr_mc > 0
                else (
                    entry_mc / 1_000_000_000.0 if entry_mc > 0 else effective_sell_price
                )
            )
        else:
            eff_unit_price = (
                entry_mc / 1_000_000_000.0 if entry_mc > 0 else effective_buy_price
            )

        record = {
            "id": trade_id,
            "trade_id": trade_id,
            "position_id": position_id,
            "mint": mint,
            "token": mint,
            "mint_name": name,
            "token_name": name,
            "name": name,
            "action": action,
            "side": action,
            "entry": float(entry or 0.0),
            "exit": float(exit_value or 0.0),
            "cost_sol": float(entry or 0.0),
            "proceeds_sol": float(exit_value or 0.0),
            "sol_amount": float(
                (exit_value or 0.0) if "sell" in action else (entry or 0.0)
            ),
            "unit_price_sol": float(eff_unit_price),
            "execution_price": float(eff_unit_price),
            "buy_price": float(effective_buy_price),
            "sell_price": float(effective_sell_price),
            "entry_price": float(effective_buy_price),
            "exit_price": float(effective_sell_price),
            "reason": reason or "",
            "timestamp": time.time(),
            "signature": signature,
            "dry_run": bool(self.dry_run),
            "strategy": lane or getattr(self.config, "strategy_preset", None),
        }
        if entry_metrics:
            record["entry_metrics"] = dict(entry_metrics)
        if exit_metrics:
            record["exit_metrics"] = dict(exit_metrics)
        if "buy" in action:
            record["market_regime"] = self._market_regime().snapshot()
        # Net of network fee, priority fee, Jito tip and token-account rent (FEAT-49).
        record.update(
            build_pnl_fields(
                action=action,
                cost_sol=float(entry or 0.0),
                proceeds_sol=float(exit_value or 0.0),
                costs=costs,
            )
        )
        self._pnl_totals.add(record)
        self._trade_ledger.append(record)
        if len(self._trade_ledger) > 50:
            self._trade_ledger.pop(0)
        self._recent_actions.append(record)
        if action == "buy" or "buy" in action:
            self._record_metric("buys")
            self._record_event(
                f"BUY {mint[:8]} @ {record['entry']:.4f} SOL ({name or mint[:8]})",
                alert=True,
            )
        elif "sell" in action:
            self._record_metric("sells")
            self._record_event(
                f"SELL {mint[:8]} -> {record['exit']:.4f} SOL ({reason or 'exit'})",
                alert=True,
            )
        self._write_audit_record("trade", record)
        self._write_status_snapshot()

    def _record_latency_ms(self, latency_ms: float) -> None:
        record_latency_ms(self._metrics, latency_ms)

    def _record_metric(self, name: str, value: float | int = 1) -> None:
        record_metric(self._metrics, name, value)

    def _metrics_snapshot(self) -> dict[str, Any]:
        return metrics_snapshot(self._metrics)

    def _record_event(self, event_message: str, alert: bool = True) -> None:
        # Events feed the status file, dashboard and alerts: never carry a key (BUG-102).
        event_message = redact_text(event_message)
        formatted = f"[{time.strftime('%H:%M:%S')}] {event_message}"
        self._recent_events.append(formatted)
        self._last_event = event_message
        if alert and getattr(self, "alert_enabled", False):
            self._send_alert(event_message)

    def _record_stale_data(self, reason: str = "") -> None:
        self._record_metric("stale_data")
        if reason:
            self._log(f"Stale data recorded: {reason}", level=logging.WARNING)
            self._record_event(f"stale data: {reason}", alert=False)

    def _record_failure(
        self, reason: str = "", category: str = "", **kwargs: Any
    ) -> None:
        self._record_metric("failures")
        msg = category or reason or "unknown"
        self._log(f"Failure recorded: {msg}", level=logging.WARNING)
        self._record_event(f"failure: {msg}", alert=False)

    def _record_connection_loss(self) -> None:
        self._record_metric("connection_loss")
        self._record_event("stream connection loss", alert=False)

    def _next_position_id(self) -> str:
        return self._next_trade_id()

    def _check_daily_drawdown(self) -> bool:
        return check_daily_drawdown(self)

    def _check_loss_per_trade(self, mint: str) -> bool:
        return check_loss_per_trade(self, mint=mint)

    def _health_ok_for_trading(self) -> bool:
        return health_ok_for_trading(self)

    async def _update_health_state(self) -> None:
        update_health_state(self)

    def _mark_health_check(self) -> None:
        mark_health_check(self)

    def reset_circuit_breaker(
        self,
        new_baseline_sol: float | None = None,
        force: bool = False,
    ) -> None:
        baseline = (
            new_baseline_sol
            if new_baseline_sol is not None
            else self.wallet_balance_sol
        )
        self.daily_equity_tracker.reset_circuit_breaker(
            new_baseline_sol=baseline, force=force
        )
        if new_baseline_sol is not None and (self.paper_trade or self.dry_run):
            self.wallet_balance_sol = max(
                self.wallet_balance_sol, float(new_baseline_sol)
            )
        self._risk_killed = False
        self._record_event(
            f"circuit breaker reset (baseline: {baseline:.2f} SOL)",
            alert=True,
        )
        self._transition_to(TradingBotState.MONITORING, reason="circuit_breaker_reset")

    def _check_risk_limits(
        self,
        mint: str,
        proposed_entry_sol: float,
        current_positions: dict[str, Any],
    ) -> bool:
        return check_risk_limits(
            self,
            mint=mint,
            proposed_entry_sol=proposed_entry_sol,
            current_positions=current_positions,
        )

    async def _check_account_equity_guard(self, required_sol: float) -> bool:
        if self.dry_run:
            return True
        try:
            balance_sol = await self.execution.get_balance_sol()
            self.wallet_balance_sol = balance_sol
            self._live_balance_confirmed = True
            open_val_sol = self._open_positions_exit_value()
            self.daily_equity_tracker.update_valuation(balance_sol, open_val_sol)

            if balance_sol - required_sol < self.config.reserve_balance_sol:
                self._log(
                    f"Account equity guard rejected buy: balance {balance_sol:.3f} SOL insufficient to maintain {self.config.reserve_balance_sol:.3f} SOL reserve.",
                    level=logging.WARNING,
                )
                return False

            if not check_daily_drawdown(self):
                self._log("Daily drawdown threshold exceeded.", level=logging.WARNING)
                self._risk_killed = True
                return False

            return True
        except Exception as exc:
            # A failed balance read is transient: skip this entry only (BUG-46).
            self._log(
                f"Error checking account equity guard: {exc}", level=logging.WARNING
            )
            self._last_event = "entry skipped: balance check failed"
            return False

    async def _validate_balance(self) -> bool:
        if self.dry_run:
            return True
        try:
            balance = await self.execution.get_balance_sol()
            self.wallet_balance_sol = balance
            self._live_balance_confirmed = True
            return balance >= self.min_balance_sol
        except Exception:
            return False

    def _equity_known(self) -> bool:
        """Paper / dry-run equity is simulated; a live run needs one real balance read."""
        return bool(self.dry_run or getattr(self, "_live_balance_confirmed", False))

    async def _check_and_enforce_circuit_breaker(self) -> bool:
        """Evaluates daily drawdown baseline and engages circuit breaker if breached."""
        try:
            if not self.dry_run:
                balance_sol = await self.execution.get_balance_sol()
                self.wallet_balance_sol = balance_sol
                self._live_balance_confirmed = True
            open_val_sol = self._open_positions_exit_value()
            self.daily_equity_tracker.update_valuation(
                self.wallet_balance_sol, open_val_sol
            )
        except Exception as exc:
            self._log(
                f"Valuation check error during circuit breaker check: {exc}",
                level=logging.DEBUG,
            )

        if not self._equity_known():
            # Never baseline the day on the simulated start balance (BUG-130);
            # buys stay blocked by the equity guard until a read succeeds.
            self._last_event = "circuit breaker waiting for the first wallet balance"
            return False

        is_locked, reason = evaluate_portfolio_circuit_breaker(self)

        if is_locked:
            self._last_event = f"circuit breaker: {reason}"
            action = getattr(
                self.daily_equity_tracker,
                "circuit_breaker_action",
                CircuitBreakerAction.EMERGENCY_LIQUIDATE,
            )

            if action == CircuitBreakerAction.EMERGENCY_LIQUIDATE:
                if (
                    self.config.auto_liquidate_on_circuit_breaker
                    and len(self.active_positions) > 0
                ):
                    self._log(
                        f"Engaging emergency liquidation due to circuit breaker breach: {reason}",
                        level=logging.ERROR,
                    )
                    await self._liquidate_all_positions(
                        reason=f"circuit_breaker: {reason}"
                    )

                self._risk_killed = True
                if self.daily_equity_tracker.cumulative_cap_hit:
                    # The cumulative cap stays until the operator resumes buying;
                    # the pause survives restarts and lock expiry (BUG-128).
                    self.pause_buying(reason="cumulative loss cap", source="risk")
                # Count a trip once per lock, not on every check while locked (BUG-114).
                locked_at = self.daily_equity_tracker.locked_at_timestamp
                if locked_at != getattr(self, "_counted_breaker_lock_at", None):
                    self._counted_breaker_lock_at = locked_at
                    self._record_metric("circuit_breaker_trips")
                if self.state in {
                    TradingBotState.BUYING,
                    TradingBotState.HOLDING,
                    TradingBotState.SELLING,
                }:
                    self._transition_to(
                        TradingBotState.MONITORING,
                        reason=f"circuit_breaker: {reason}",
                    )
                return True
            elif action == CircuitBreakerAction.HALT_NEW_BUYS:
                self._log(
                    f"Engaging soft buy halt due to profit-zone retracement: {reason}",
                    level=logging.WARNING,
                )
                self._record_metric("circuit_breaker_soft_halts")
                return True

        return False

    async def _liquidate_all_positions(
        self, reason: str = "emergency_circuit_breaker_liquidation"
    ) -> list[str]:
        """Liquidates all active open positions."""
        mints = list(self.active_positions.keys())
        liquidated: list[str] = []
        for mint in mints:
            try:
                success = await self._sell_token(mint, reason=reason)
                if success:
                    liquidated.append(mint)
            except Exception as exc:
                self._log(f"Failed to liquidate {mint}: {exc}", level=logging.WARNING)
        return liquidated

    async def _emergency_liquidate_all_positions(
        self, reason: str = "emergency_circuit_breaker_liquidation"
    ) -> list[str]:
        return await self._liquidate_all_positions(reason=reason)

    def get_status_snapshot(self) -> dict[str, Any]:
        """Returns a comprehensive structured snapshot of runtime status."""
        open_val = self._open_positions_exit_value()
        # Reading the drawdown initialises the day's baseline, so not before
        # the live balance is known (BUG-130).
        drawdown = (
            self.daily_equity_tracker.calculate_drawdown(
                self.wallet_balance_sol, open_val
            )
            if self._equity_known()
            else 0.0
        )
        return {
            "state": self.state.value,
            "wallet_balance_sol": self.wallet_balance_sol,
            "active_positions_count": len(self.active_positions),
            "active_positions": {
                mint: {
                    "name": position.get("name", mint),
                    "entry_market_cap": float(
                        position.get("entry_market_cap", 0.0) or 0.0
                    ),
                    "current_market_cap": float(
                        position.get("current_market_cap", 0.0) or 0.0
                    ),
                    "peak_market_cap": float(
                        position.get("peak_market_cap", 0.0) or 0.0
                    ),
                    "buy_price": float(
                        position.get("buy_price")
                        or position.get("entry_price")
                        or position.get("cost_sol", 0.0)
                        or 0.0
                    ),
                    "entry_price": float(
                        position.get("buy_price")
                        or position.get("entry_price")
                        or position.get("cost_sol", 0.0)
                        or 0.0
                    ),
                    "token_amount": int(
                        position.get("remaining_token_amount")
                        or position.get("token_amount")
                        or 0
                    ),
                    "initial_token_amount": int(
                        position.get("initial_token_amount") or 0
                    ),
                    "remaining_token_amount": int(
                        position.get("remaining_token_amount") or 0
                    ),
                    "tier_1_executed": bool(position.get("tier_1_executed", False)),
                    "tier_2_executed": bool(position.get("tier_2_executed", False)),
                    "moonbag_active": bool(position.get("moonbag_active", False)),
                    "trailing_stop_active": bool(
                        position.get("trailing_stop_active", False)
                    ),
                    # Cost basis and venue metadata survive restarts (BUG-45).
                    "cost_sol": float(position.get("cost_sol") or 0.0),
                    "entry_sol": float(
                        position.get("entry_sol") or position.get("cost_sol") or 0.0
                    ),
                    "position_id": position.get("position_id"),
                    "buy_signature": position.get("buy_signature"),
                    "entry_reason": position.get("entry_reason"),
                    "entry_time": position.get("entry_time"),
                    "migrating": mint in self._migrating_mints,
                    "pool_keys": self._serialize_pool_keys(
                        self._exit_pool_keys(mint, position)
                    ),
                }
                for mint, position in self.active_positions.items()
            },
            "positions": [dict(pos) for pos in self.active_positions.values()],
            "trade_count": len(self.active_positions),
            "stop_requested": self._stop_requested,
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "health_ok": self._health_ok,
            "risk_killed": self._risk_killed,
            "exit_retry_queue": {
                mint: {
                    "reason": entry.get("reason", ""),
                    "retries": entry.get("retries", 1),
                    "retry_count": entry.get("retry_count", 1),
                    "slippage_bps": entry.get("slippage_bps"),
                }
                for mint, entry in self._exit_retry_queue.items()
            },
            "buy_attempts": dict(self._buy_attempts),
            "seen_mints": dict(self._seen_mints),
            "traded_mints": dict(self._traded_mints),
            "non_pump_rejections": dict(self._non_pump_rejections),
            "mayhem_rejections": int(getattr(self, "_mayhem_rejections", 0)),
            "watch_list": self.watch_list_status(),
            "market_regime": self._market_regime().snapshot(),
            "trade_ledger": list(self._trade_ledger),
            "recent_actions": list(self._recent_actions),
            "recent_events": list(self._recent_events),
            "trade_sequence": self._trade_sequence,
            "pnl_totals": self._pnl_totals.to_dict(),
            # Unattended operation (Sprint 24D): pause, summary, degradation, sweep.
            "buying_paused": self.buying_paused,
            "operator_pause": self._operator_pause.to_dict(),
            "daily_summary": self._daily_summary.to_dict(),
            "degraded_conditions": self._degradation.degraded_for(time.monotonic()),
            "trade_feed_available": self.trade_feed_available(),
            "trade_feed_breaker": self._trade_feed_breaker().to_dict(),
            "stream_server_messages": dict(self._stream_server_messages),
            "profit_sweep": self._sweep_state.to_dict(),
            # How often the holder lookup found data while screening (BUG-107).
            "holder_lookup_stats": self._holder_lookup_stats(),
            "daily_realized_costs_sol": self.daily_equity_tracker.realized_daily_costs_sol,
            "daily_realized_gross_pnl_sol": (
                self.daily_equity_tracker.realized_daily_gross_pnl_sol
            ),
            "daily_equity_tracker": self.daily_equity_tracker.to_dict(),
            "daily_drawdown_pct": drawdown,
            "daily_realized_pnl_sol": self.daily_equity_tracker.realized_daily_pnl_sol,
            "daily_unrealized_pnl_sol": (
                self.position_manager.calculate_unrealized_pnl()
                if hasattr(self, "position_manager")
                and hasattr(self.position_manager, "calculate_unrealized_pnl")
                else 0.0
            ),
            "daily_starting_equity_sol": self.daily_equity_tracker.starting_equity_sol,
            "effective_baseline_sol": self.daily_equity_tracker.effective_baseline_sol,
            "circuit_breaker_action": (
                self.daily_equity_tracker.circuit_breaker_action.value
                if isinstance(
                    self.daily_equity_tracker.circuit_breaker_action,
                    CircuitBreakerAction,
                )
                else str(self.daily_equity_tracker.circuit_breaker_action)
            ),
            "circuit_breaker_engaged": self.daily_equity_tracker.circuit_breaker_engaged,
            "circuit_breaker_locked_at": self.daily_equity_tracker.locked_at_timestamp,
            "circuit_breaker_lockout_until": self.daily_equity_tracker.lockout_until(
                float(getattr(self.config, "emergency_hard_lock_hours", 0.0) or 0.0)
            ),
            "screening_cache_size": len(getattr(self.screening_cache, "_cache", {})),
            "enable_anti_rug_filters": self.config.enable_anti_rug_filters,
            "enable_momentum_signals": self.config.enable_momentum_signals,
            "order_flow_tracked_tokens": self.order_flow_engine.tracked_token_count,
            "enable_raydium_migration_sniping": self.config.enable_raydium_migration_sniping,
            "graduation_tracked_candidates": self.graduation_engine.tracked_candidate_count,
            "copy_trading_tracked_wallets": self.copy_trade_engine.registry.wallet_count,
            "enable_copy_trading": self.config.enable_copy_trading,
            "enable_rpc_pool": self.config.enable_rpc_pool,
            "rpc_pool_telemetry": (
                self.rpc_pool.get_telemetry()
                if hasattr(self, "rpc_pool") and self.rpc_pool is not None
                else {}
            ),
        }

    async def _enrich_and_screen_token(
        self,
        mint: str,
        token_data: dict[str, Any] | None = None,
        *,
        token_name: str | None = None,
        market_cap_sol: float = 0.0,
    ) -> TokenScreeningVerdict:
        t0 = time.perf_counter()
        verdict = await self.enricher.enrich_and_screen(
            mint, token_data=token_data, config=self.config
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if self.replay_recorder is not None:
            # Record what the screener saw, so filters can be tuned on captures.
            self.replay_recorder.record_snapshot(
                screening_snapshot(
                    verdict,
                    name=token_name,
                    market_cap_sol=market_cap_sol,
                    latency_ms=latency_ms,
                    market_regime=self._market_regime().snapshot(),
                )
            )
        if hasattr(self, "event_logger") and self.event_logger is not None:
            gini = (
                verdict.holder_distribution.compute_gini_coefficient()
                if verdict.holder_distribution is not None
                else None
            )
            top5 = (
                verdict.holder_distribution.compute_top5_non_curve_pct()
                if verdict.holder_distribution is not None
                else None
            )
            creator_hold = (
                verdict.holder_distribution.creator_initial_pct
                if verdict.holder_distribution is not None
                else None
            )
            self.event_logger.emit(
                category=EventCategory.SCREENING,
                severity=(
                    EventSeverity.INFO if verdict.passed else EventSeverity.WARNING
                ),
                event_name="token_screened",
                mint=mint,
                latency_ms=latency_ms,
                data={
                    "passed": verdict.passed,
                    "risk_score": verdict.risk_score,
                    "reasons": (
                        list(verdict.reasons)
                        if getattr(verdict, "reasons", None)
                        else []
                    ),
                    "gini_coefficient": gini,
                    "top5_concentration": top5,
                    "creator_holding_pct": creator_hold,
                },
            )
        return verdict

    def _should_buy(
        self,
        mint: str,
        market_cap_sol: float,
        screening_verdict: TokenScreeningVerdict | None = None,
        proposed_entry_sol: float | None = None,
    ) -> bool:
        if self.buying_paused:
            # Operator pause: exits keep running, nothing new is opened (Sprint 24D).
            self._last_event = "buying paused"
            return False
        if not self._health_ok_for_trading():
            return False
        if (
            getattr(self.config, "require_trade_feed", True) is True
            and not self.trade_feed_available()
        ):
            # Never open a position the bot cannot watch (BUG-112).
            self._last_event = "buy blocked: token-trade feed refused"
            return False
        if self._is_recently_seen(mint):
            return False
        if self._is_closed_reentry(mint):
            return False
        open_lots = 1 if mint in self.active_positions else 0
        if open_lots >= self.max_positions_per_mint:
            return False
        if len(self.active_positions) >= self.max_active_positions:
            return False
        if not self.strategy.is_eligible_for_buy(
            market_cap_sol=market_cap_sol,
            mint_seen_recently=False,
            buy_attempts=self._buy_attempts.get(mint, 0),
            screening_verdict=screening_verdict,
        ):
            return False
        entry_sol = (
            proposed_entry_sol
            if proposed_entry_sol is not None
            else self.buy_amount_sol
        )
        if not self._check_risk_limits(
            mint=mint,
            proposed_entry_sol=entry_sol,
            current_positions=self.active_positions,
        ):
            return False
        if self._entry_mode() == "confirmed" and not self._entry_cost_share_ok(
            entry_sol
        ):
            return False
        return self._buy_attempts.get(mint, 0) < self.max_buy_attempts_per_mint

    def _entry_cost_share_ok(self, entry_sol: float) -> bool:
        """Cost guard (FEAT-52): fixed round-trip costs from the same model as
        paper and replay must stay below ``max_entry_cost_share_pct``."""
        limit = float(getattr(self.config, "max_entry_cost_share_pct", 0.0) or 0.0)
        if limit <= 0:
            return True
        model = ReplayCostModel.from_env(
            close_token_account_on_full_exit=bool(
                getattr(self.config, "close_token_account_on_full_exit", True)
            )
        )
        share = model.round_trip_fixed_costs_sol() / max(float(entry_sol), 1e-9)
        if share > limit:
            self._count_watch("cost_guard_refused")
            self._last_event = f"buy blocked: costs {share:.1%} > {limit:.1%}"
            return False
        return True

    async def _resolve_token_name(
        self, mint: str, token_name: str | None = None
    ) -> str | None:
        if token_name:
            return token_name
        cached = self.active_positions.get(mint, {}).get("name")
        if cached:
            return cached
        try:
            coin = await self.api.get_coin(mint)
            if isinstance(coin, dict):
                found = coin.get("name") or coin.get("symbol")
                if found:
                    return str(found)
        except Exception:
            pass
        return None

    def _initial_simulated_balance(self) -> float:
        """Starting SOL of the simulated (paper/dry-run) wallet.

        Defaults to reserve + 10 buys; ``paper_starting_balance_sol`` raises it
        for long data-capture runs that would otherwise hit the drawdown
        breaker within hours. Live runs overwrite it from the chain.
        """
        configured = getattr(self.config, "paper_starting_balance_sol", 0.0)
        if isinstance(configured, (int, float)) and configured > 0:
            return float(configured)
        return float(self.config.reserve_balance_sol + self.config.buy_amount_sol * 10)

    @contextlib.contextmanager
    def _track_operation(self, kind: str) -> Iterator[None]:
        """Counts an in-flight buy or sell; re-settles the state when it ends (BUG-111)."""
        counts = self._inflight_operations_map()
        counts[kind] = counts.get(kind, 0) + 1
        try:
            yield
        finally:
            counts[kind] = max(0, counts.get(kind, 0) - 1)
            self._settle_after_operation()

    def _inflight_count(self) -> int:
        return sum(self._inflight_operations_map().values())

    def _inflight_operations_map(self) -> dict[str, int]:
        counts: dict[str, int] | None = getattr(self, "_inflight_operations", None)
        if counts is None:
            counts = {}
            self._inflight_operations = counts
        return counts

    def _settle_after_operation(self) -> None:
        """Leave BUYING/SELLING only once no buy or sell is in flight (BUG-111)."""
        if self.state not in (TradingBotState.BUYING, TradingBotState.SELLING):
            return
        counts = self._inflight_operations_map()
        if counts.get("sell", 0):
            target = TradingBotState.SELLING
        elif counts.get("buy", 0):
            target = TradingBotState.BUYING
        else:
            target = (
                TradingBotState.HOLDING
                if self.active_positions
                else TradingBotState.MONITORING
            )
        if target != self.state:
            self._transition_to(target, reason="operation_settled")

    async def _buy_token(
        self,
        mint: str,
        market_cap_sol: float,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = None,
        buy_amount_sol: float | None = None,
        strategy: str | None = None,
        entry_metrics: dict[str, Any] | None = None,
    ) -> bool:
        with self._track_operation("buy"):
            return await self._buy_token_impl(
                mint,
                market_cap_sol,
                token_name=token_name,
                screening_verdict=screening_verdict,
                reason=reason,
                buy_amount_sol=buy_amount_sol,
                strategy=strategy,
                entry_metrics=entry_metrics,
            )

    async def _buy_token_impl(
        self,
        mint: str,
        market_cap_sol: float,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = None,
        buy_amount_sol: float | None = None,
        strategy: str | None = None,
        entry_metrics: dict[str, Any] | None = None,
    ) -> bool:
        effective_buy_amount = (
            buy_amount_sol if buy_amount_sol is not None else self.buy_amount_sol
        )
        self._last_buy_error: str | None = None
        if not self._should_buy(
            mint,
            market_cap_sol,
            screening_verdict=screening_verdict,
            proposed_entry_sol=effective_buy_amount,
        ):
            return False

        self._transition_to(TradingBotState.BUYING, reason=f"buying {mint}")
        if not await self._check_account_equity_guard(
            required_sol=effective_buy_amount
        ):
            self._transition_to(
                TradingBotState.MONITORING, reason=f"buy_rejected_equity_guard {mint}"
            )
            return False

        if not await self._validate_balance():
            self._transition_to(
                TradingBotState.MONITORING, reason=f"buy_rejected_balance {mint}"
            )
            return False

        resolved_name = await self._resolve_token_name(mint, token_name)
        position_name = (resolved_name or mint).strip() or mint

        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.STRATEGY,
                severity=EventSeverity.INFO,
                event_name="entry_signal",
                mint=mint,
                mint_name=position_name,
                data={
                    "amount_sol": effective_buy_amount,
                    "market_cap_sol": float(market_cap_sol or 0.0),
                    "reason": reason or "entry",
                },
            )

        if self._stop_requested:
            # Never send a new order once shutdown was requested (BUG-91).
            return False

        drift_guard: dict[str, Any] = {}
        drift_limit = float(
            getattr(self.config, "momentum_max_entry_drift_pct", 0.0) or 0.0
        )
        if strategy == "momentum" and drift_limit > 0 and market_cap_sol > 0:
            # Skip the buy if the price ran away between signal and fill.
            drift_guard = {
                "signal_market_cap_sol": float(market_cap_sol),
                "max_entry_drift_pct": drift_limit,
            }
        t_exec_start = time.perf_counter()
        exec_res = await self.executor.execute_buy(
            mint=mint,
            amount_sol=effective_buy_amount,
            reason=reason or "entry",
            token_name=position_name,
            dry_run=self.dry_run,
            **drift_guard,
        )
        exec_latency_ms = (time.perf_counter() - t_exec_start) * 1000.0
        exec_meta = getattr(exec_res, "metadata", None)
        fill_curve_mc = (
            exec_meta.get("fill_curve_market_cap_sol")
            if isinstance(exec_meta, dict)
            else None
        )
        if isinstance(fill_curve_mc, (int, float)):
            # The curve the paper fill read: replay prices its fill from it.
            self._record_curve_poll(
                mint, float(fill_curve_mc), ts=time.time(), source="entry_fill"
            )

        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.EXECUTION,
                severity=(
                    EventSeverity.INFO if exec_res.success else EventSeverity.ERROR
                ),
                event_name="buy_executed",
                mint=mint,
                mint_name=position_name,
                latency_ms=exec_latency_ms,
                data={
                    "success": exec_res.success,
                    "signature": exec_res.signature,
                    "error": exec_res.error,
                    "amount_sol": effective_buy_amount,
                    "token_amount": exec_res.token_amount,
                },
                error_message=exec_res.error,
            )

        if not exec_res.success:
            self._last_buy_error = exec_res.error
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING,
                reason=f"buy_failed {mint} ({exec_res.error})",
            )
            return False

        exec_metadata = getattr(exec_res, "metadata", None)
        fill_drift = (
            exec_metadata.get("fill_drift_pct")
            if isinstance(exec_metadata, dict)
            else None
        )
        if isinstance(fill_drift, (int, float)) and entry_metrics is not None:
            entry_metrics = {**entry_metrics, "fill_drift_pct": float(fill_drift)}
        curve_entry_mc = (
            exec_metadata.get("entry_market_cap_sol")
            if isinstance(exec_metadata, dict)
            else None
        )
        signal_market_cap_sol = float(market_cap_sol or 0.0)
        if isinstance(curve_entry_mc, (int, float)) and curve_entry_mc > 0:
            # Paper fills are priced from the curve exits read, not the stream
            # create event (BUG-104); live fills from their own transaction
            # (BUG-129), so stops and take-profits measure from the real entry.
            market_cap_sol = float(curve_entry_mc)
        entry_price_source = (
            exec_metadata.get("entry_price_source")
            if isinstance(exec_metadata, dict)
            else None
        )

        trade_id = self._next_trade_id()
        position_id = trade_id
        buy_costs = self._execution_costs(exec_res)
        cost_basis = float(effective_buy_amount)
        if (
            buy_costs is not None
            and buy_costs.source == COST_SOURCE_TRANSACTION_META
            and buy_costs.swap_sol
            and buy_costs.swap_sol > 0
        ):
            # SOL actually paid into the curve, read from the transaction.
            cost_basis = float(buy_costs.swap_sol)
        self.position_manager.record_buy(
            mint=mint,
            token_amount=exec_res.token_amount or (100_000_000 if self.dry_run else 0),
            cost_sol=cost_basis,
            entry_market_cap=float(market_cap_sol or LAUNCH_MARKET_CAP_SOL),
            name=position_name,
            buy_signature=exec_res.signature,
            reason=reason or "entry",
            dry_run=self.dry_run,
            metadata={
                "position_id": position_id,
                "trade_id": trade_id,
                **({"strategy": strategy} if strategy else {}),
                **(
                    {
                        "entry_price_source": str(entry_price_source),
                        "signal_market_cap_sol": signal_market_cap_sol,
                    }
                    if entry_price_source
                    else {}
                ),
            },
        )
        if strategy:
            lanes = self._entry_lanes()
            lanes[mint] = strategy
            while len(lanes) > 1_000:
                lanes.pop(next(iter(lanes)))
        self.active_positions = self.position_manager.get_all_positions()
        if self.dry_run or self.paper_trade:
            self.wallet_balance_sol = max(
                0.0, float(self.wallet_balance_sol) - float(cost_basis)
            )
        buy_costs_sol = buy_costs.total_cost_sol if buy_costs is not None else 0.0
        self._book_trade_costs(-buy_costs_sol, buy_costs_sol)

        self._buy_attempts[mint] = 0
        self._mark_seen(mint)
        self._mark_traded(mint)
        self._last_new_token = mint
        self._last_new_token_name = position_name
        self._record_trade(
            trade_id=trade_id,
            position_id=position_id,
            mint=mint,
            action="buy",
            token_name=position_name,
            mint_name=position_name,
            entry=cost_basis,
            reason=reason or "entry",
            signature=exec_res.signature,
            costs=buy_costs,
            strategy=strategy,
            entry_metrics=entry_metrics,
        )
        if self.replay_recorder is not None:
            price = (
                float(market_cap_sol) / 1_000_000_000.0 if market_cap_sol > 0 else 0.0
            )
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": time.time(),
                    "mint": mint,
                    "name": position_name,
                    "price": price,
                    "market_cap_sol": float(market_cap_sol or LAUNCH_MARKET_CAP_SOL),
                    "is_buy": True,
                    "sol_amount": float(effective_buy_amount),
                    "token_amount": int(exec_res.token_amount or 0),
                    "signal": "buy",
                    "reason": reason or "entry",
                }
            )
        self._transition_to(TradingBotState.HOLDING, reason=f"buy_confirmed {mint}")
        return True

    def _raydium_fill_market_cap(self, exec_res: ExecutionResult) -> float | None:
        """Market cap at a live Raydium buy's average fill price (BUG-131).

        SOL spent (the transaction's swap amount when read, else the order
        size) over the tokens the balance delta shows. ``None`` in paper and
        dry-run modes, or when the token amount is not a measured delta.
        """
        if self.dry_run:
            return None
        metadata = exec_res.metadata if isinstance(exec_res.metadata, dict) else {}
        tokens = int(exec_res.token_amount or 0)
        if tokens <= 0 or metadata.get("fill_source") != "balance_delta":
            return None
        costs = self._execution_costs(exec_res)
        spent = float(exec_res.amount_sol or 0.0)
        if (
            costs is not None
            and costs.source == COST_SOURCE_TRANSACTION_META
            and costs.swap_sol
            and costs.swap_sol > 0
        ):
            spent = float(costs.swap_sol)
        if spent <= 0:
            return None
        return spent / tokens * TOTAL_TOKEN_SUPPLY_RAW

    async def _buy_raydium_token(
        self,
        mint: str,
        pool_keys: RaydiumPoolKeys,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = "raydium_graduation_snipe",
    ) -> bool:
        with self._track_operation("buy"):
            return await self._buy_raydium_token_impl(
                mint,
                pool_keys,
                token_name=token_name,
                screening_verdict=screening_verdict,
                reason=reason,
            )

    async def _buy_raydium_token_impl(
        self,
        mint: str,
        pool_keys: RaydiumPoolKeys,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = "raydium_graduation_snipe",
    ) -> bool:
        buy_amount = self.config.raydium_buy_amount_sol
        if not self._should_buy(
            mint,
            market_cap_sol=69.0,
            screening_verdict=screening_verdict,
            proposed_entry_sol=buy_amount,
        ):
            return False

        self._transition_to(TradingBotState.BUYING, reason=f"buying_raydium {mint}")
        if not await self._check_account_equity_guard(required_sol=buy_amount):
            self._transition_to(
                TradingBotState.MONITORING,
                reason=f"raydium_buy_rejected_equity_guard {mint}",
            )
            return False

        resolved_name = await self._resolve_token_name(mint, token_name)
        position_name = (resolved_name or mint).strip() or mint

        if self._stop_requested:
            # Never send a new order once shutdown was requested (BUG-91).
            return False

        exec_res = await self.executor.execute_raydium_buy(
            mint=mint,
            pool_keys=pool_keys,
            amount_sol=buy_amount,
            slippage_bps=self.config.raydium_slippage_bps,
            reason=reason or "raydium_graduation_snipe",
            dry_run=self.dry_run,
        )

        if not exec_res.success:
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING,
                reason=f"raydium_buy_failed {mint} ({exec_res.error})",
            )
            return False

        trade_id = self._next_trade_id()
        position_id = trade_id
        raydium_entry_mc = self._raydium_fill_market_cap(exec_res)
        self.position_manager.record_buy(
            mint=mint,
            token_amount=exec_res.token_amount or (100_000_000 if self.dry_run else 0),
            cost_sol=buy_amount,
            # From the fill; 0 when it is unknown, so the first price the
            # position sees becomes its entry (BUG-76) instead of a made-up
            # 69 SOL, the "$69k" graduation figure read as SOL (BUG-131).
            entry_market_cap=raydium_entry_mc or 0.0,
            name=position_name,
            buy_signature=exec_res.signature,
            reason=reason or "raydium_graduation_snipe",
            dry_run=self.dry_run,
            metadata={
                "position_id": position_id,
                "trade_id": trade_id,
                "pool_keys": pool_keys.to_dict(),
                "raydium_pool_id": pool_keys.amm_id,
                "amm_id": pool_keys.amm_id,
            },
        )
        self.active_positions = self.position_manager.get_all_positions()
        if self.dry_run or self.paper_trade:
            self.wallet_balance_sol = max(
                0.0, float(self.wallet_balance_sol) - float(buy_amount)
            )
        raydium_costs = self._execution_costs(exec_res)
        raydium_costs_sol = (
            raydium_costs.total_cost_sol if raydium_costs is not None else 0.0
        )
        self._book_trade_costs(-raydium_costs_sol, raydium_costs_sol)

        self._buy_attempts[mint] = 0
        self._mark_seen(mint)
        self._mark_traded(mint)
        self._last_new_token = mint
        self._last_new_token_name = position_name
        self._record_trade(
            trade_id=trade_id,
            position_id=position_id,
            mint=mint,
            action="raydium_buy",
            token_name=position_name,
            mint_name=position_name,
            entry=buy_amount,
            reason=reason or "raydium_graduation_snipe",
            signature=exec_res.signature,
            costs=raydium_costs,
        )
        if self.replay_recorder is not None:
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": time.time(),
                    "mint": mint,
                    "name": position_name,
                    "price": 69.0 / 1_000_000_000.0,
                    "market_cap_sol": 69.0,
                    "is_buy": True,
                    "sol_amount": float(buy_amount),
                    "token_amount": int(exec_res.token_amount or 0),
                    "signal": "buy",
                    "reason": reason or "raydium_graduation_snipe",
                }
            )
        self._transition_to(
            TradingBotState.HOLDING, reason=f"raydium_buy_confirmed {mint}"
        )
        return True

    async def _evaluate_and_trigger_displacement(
        self,
        candidate_mint: str,
        market_cap_sol: float,
        candidate_signal: Any | None = None,
        conviction_percentile: float = 0.95,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
    ) -> bool:
        """Evaluate if an incoming breakout candidate should displace the weakest active holding."""
        if not getattr(self.config, "enable_capital_rotation", True):
            return False
        if self.buying_paused:
            # Rotation sells to buy; while paused it would sell and then not buy.
            return False

        if candidate_mint in self.active_positions:
            return False

        if screening_verdict is not None and not screening_verdict.passed:
            return False

        decision = self.displacement_engine.evaluate_displacement(
            candidate_mint=candidate_mint,
            candidate_signal=candidate_signal,
            conviction_percentile=conviction_percentile,
        )

        if not decision.displace or not decision.displaced_mint:
            return False

        displaced_mint = decision.displaced_mint
        self._log(
            f"Opportunistic capital displacement triggered: displacing {displaced_mint[:8]} for breakout candidate {candidate_mint[:8]} (EV delta: +{decision.ev_delta:.4f})"
        )

        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.STRATEGY,
                severity=EventSeverity.INFO,
                event_name="capital_displacement",
                mint=displaced_mint,
                data={
                    "displaced_mint": displaced_mint,
                    "candidate_mint": candidate_mint,
                    "ev_delta": decision.ev_delta,
                    "candidate_ev": decision.candidate_ev,
                    "weakest_ev": decision.weakest_ev,
                    "friction_sol": decision.estimated_friction_sol,
                    "reason": decision.reason,
                },
            )

        self.displacement_engine.request_displacement_exit(
            displaced_mint, candidate_mint
        )
        sell_success = await self._sell_token(
            mint=displaced_mint,
            reason="capital_displacement",
        )
        self.displacement_engine.clear_displacement(displaced_mint)

        if sell_success or self.dry_run:
            return await self._buy_token(
                mint=candidate_mint,
                market_cap_sol=market_cap_sol,
                token_name=token_name,
                screening_verdict=screening_verdict,
                reason="capital_displacement_entry",
            )
        return False

    def _enqueue_exit_retry(self, mint: str, reason: str = "") -> None:
        if mint not in self._exit_retry_queue:
            retry_count = 1
            slippage = self.base_exit_slippage_bps + 500
            self._exit_retry_queue[mint] = {
                "retries": retry_count,
                "retry_count": retry_count,
                "first_attempt": time.monotonic(),
                "last_attempt": time.monotonic(),
                "next_retry_at": time.monotonic() + 2.0,
                "reason": reason,
                "slippage_bps": slippage,
            }
            self._record_event(f"exit retry #1: {mint[:8]} ({reason})", alert=False)
        else:
            entry = self._exit_retry_queue[mint]
            entry["retries"] = (
                int(entry.get("retries") or entry.get("retry_count") or 0) + 1
            )
            entry["retry_count"] = entry["retries"]
            if entry["retry_count"] >= self.max_exit_retries:
                self._record_failure(
                    f"Max exit retries ({self.max_exit_retries}) exceeded for {mint}",
                    category="max_exit_retries",
                )
                self._exit_retry_queue.pop(mint, None)
                return
            entry["last_attempt"] = time.monotonic()
            entry["reason"] = reason
            entry["slippage_bps"] = min(
                self.max_exit_slippage_bps,
                self.base_exit_slippage_bps + (entry["retry_count"] * 500),
            )
            entry["next_retry_at"] = time.monotonic() + (2.0 ** entry["retry_count"])
            self._record_event(
                f"exit retry #{entry['retry_count']}: {mint[:8]} ({reason})",
                alert=False,
            )

    async def _process_exit_retry_queue(self, websocket: Any = None) -> None:
        now = time.monotonic()
        for mint, entry in list(self._exit_retry_queue.items()):
            if entry.get("next_retry_at", 0) <= now:
                success = await self._sell_token(
                    mint,
                    reason=entry.get("reason", "retry_exit"),
                    slippage_bps=entry.get("slippage_bps"),
                    retry_count=entry.get("retry_count", 1),
                )
                if success:
                    self._exit_retry_queue.pop(mint, None)

    async def reconcile_onchain_positions(self) -> dict[str, Any]:
        return await self._reconcile_positions_on_startup()

    async def _reconcile_positions_on_startup(self) -> dict[str, Any]:
        """Reconciles on-chain token balances for open positions upon startup."""
        if self.dry_run:
            return {
                mint: {"status": "reconciled_dry_run"} for mint in self.active_positions
            }

        reconciled: dict[str, Any] = {}
        for mint in list(self.active_positions.keys()):
            position = self.active_positions.get(mint)
            if not position:
                continue

            try:
                balance = await self.execution.get_token_balance(mint)
            except Exception as exc:
                self._log(
                    f"Startup reconciliation: failed to fetch balance for {mint}: {exc}",
                    level=logging.WARNING,
                )
                continue

            if balance <= self.min_sell_balance:
                self._log(
                    f"Startup reconciliation: closing orphaned position for {mint} (balance={balance})"
                )
                self.position_manager.remove_position(mint)
                self.active_positions.pop(mint, None)
                reconciled[mint] = {"status": "purged", "balance": balance}
            else:
                position["token_amount"] = balance
                position["remaining_token_amount"] = balance
                if not position.get("initial_token_amount"):
                    position["initial_token_amount"] = balance
                try:
                    curve = await self.execution.get_bonding_curve_state(mint)
                    if isinstance(curve, dict) and "market_cap_sol" in curve:
                        mc = float(curve["market_cap_sol"])
                    else:
                        vt = int(curve.get("virtual_token_reserves", 0))
                        vs = int(curve.get("virtual_sol_reserves", 0))
                        mc = (
                            (vs / 1_000_000_000.0)
                            * (1_000_000_000.0 / (vt / 1_000_000.0))
                            if (vt > 0 and vs > 0)
                            else float(position.get("current_market_cap", 0.0) or 0.0)
                        )
                    position["current_market_cap"] = mc
                    entry_mc = float(position.get("entry_market_cap", mc) or mc)
                    peak_mc = float(
                        position.get("peak_market_cap", max(entry_mc, mc))
                        or max(entry_mc, mc)
                    )
                    position["peak_market_cap"] = max(peak_mc, mc)
                except Exception:
                    pass
                reconciled[mint] = {"status": "active", "balance": balance}

        if reconciled:
            self._write_status_snapshot()
        return reconciled

    def _mint_lock(self, mint: str) -> asyncio.Lock:
        lock = self._sell_locks.get(mint)
        if lock is None:
            lock = asyncio.Lock()
            self._sell_locks[mint] = lock
        return lock

    @staticmethod
    def _serialize_pool_keys(pool: Any) -> dict[str, Any] | None:
        if isinstance(pool, RaydiumPoolKeys):
            return pool.to_dict()
        if isinstance(pool, dict):
            return dict(pool)
        return None

    def _exit_pool_keys(self, mint: str, position: dict[str, Any]) -> Any:
        pool = self._raydium_exit_pools.get(mint)
        if pool is not None:
            return pool
        raw = position.get("pool_keys")
        if isinstance(raw, RaydiumPoolKeys):
            return raw
        if isinstance(raw, dict):
            try:
                return RaydiumPoolKeys.from_dict(raw)
            except Exception:
                return None
        return None

    async def _sell_token(
        self,
        mint: str,
        *,
        sell_amount_tokens: int | None = None,
        sell_fraction: float = 1.0,
        reason: str = "exit",
        target_tier: int | str | None = None,
        slippage_bps: int | None = None,
        retry_count: int = 0,
    ) -> bool:
        """Sell under a per-mint lock so concurrent exits cannot overlap (BUG-41)."""
        held = mint in self.active_positions
        async with self._mint_lock(mint):
            with self._track_operation("sell"):
                sold = await self._sell_token_locked(
                    mint,
                    sell_amount_tokens=sell_amount_tokens,
                    sell_fraction=sell_fraction,
                    reason=reason,
                    target_tier=target_tier,
                    slippage_bps=slippage_bps,
                    retry_count=retry_count,
                )
        # Every path that closes a position (exit stack, retry queue, copy-trade
        # mirror, breaker liquidation, rotation) ends here, so this is where the
        # trade subscription stops; PumpPortal bills per message (BUG-120).
        if held and mint not in self.active_positions:
            await self._unsubscribe_from_token_trades(None, mint)
        return sold

    async def _sell_token_locked(
        self,
        mint: str,
        *,
        sell_amount_tokens: int | None = None,
        sell_fraction: float = 1.0,
        reason: str = "exit",
        target_tier: int | str | None = None,
        slippage_bps: int | None = None,
        retry_count: int = 0,
    ) -> bool:
        if mint not in self.active_positions:
            self._exit_retry_queue.pop(mint, None)
            return False

        position = self.active_positions[mint]
        pos_name = position.get("name") or mint
        pool_keys = self._exit_pool_keys(mint, position)
        use_pumpswap = False
        if pool_keys is None and mint in self._migrating_mints:
            # The curve is complete and takes no sells (BUG-44). Pump.fun
            # migrates into PumpSwap, not Raydium, so exit there (BUG-123).
            pool_mc = (
                await self._pumpswap_exit_market_cap(mint)
                if bool(getattr(self.config, "enable_pumpswap_exit", True))
                else None
            )
            if pool_mc is None:
                self._last_event = f"awaiting pool {mint[:8]}"
                return False
            # Paper proceeds scale with market cap: price from the pool.
            position["current_market_cap"] = pool_mc
            position["peak_market_cap"] = max(
                float(position.get("peak_market_cap", 0.0) or 0.0), pool_mc
            )
            use_pumpswap = True

        self._transition_to(
            TradingBotState.SELLING, reason=f"selling {mint} ({reason})"
        )

        initial_tokens, rem_tokens = position_token_amounts(
            position, dry_run=self.dry_run
        )

        if not self.dry_run:
            try:
                token_balance = await self.execution.get_token_balance(mint)
                rem_tokens = token_balance
            except Exception as exc:
                self._log(
                    f"Unable to fetch token balance for {mint}: {exc}",
                    level=logging.WARNING,
                )
                self._enqueue_exit_retry(mint, reason=f"balance_fetch_error: {exc}")
                self._transition_to(
                    TradingBotState.HOLDING, reason=f"sell_balance_failed {mint}"
                )
                return False

            if rem_tokens <= self.min_sell_balance:
                self.position_manager.remove_position(mint)
                self.active_positions = self.position_manager.get_all_positions()
                self._exit_retry_queue.pop(mint, None)
                self._transition_to(
                    TradingBotState.MONITORING, reason=f"sell_zero_balance {mint}"
                )
                return True

        size = plan_sell_size(
            initial_tokens=initial_tokens,
            remaining_tokens=rem_tokens,
            sell_amount_tokens=sell_amount_tokens,
            sell_fraction=sell_fraction,
            min_sell_balance=self.min_sell_balance,
        )
        tokens_to_sell, is_partial = size.tokens_to_sell, size.is_partial

        effective_slippage = slippage_bps or self.base_exit_slippage_bps
        t_sell_start = time.perf_counter()
        if pool_keys is not None:
            exec_res = await self.executor.execute_raydium_sell(
                mint,
                pool_keys,
                tokens_to_sell,
                slippage_bps=effective_slippage,
                reason=reason,
                dry_run=self.dry_run,
            )
        elif use_pumpswap:
            exec_res = await self.executor.execute_pumpswap_sell(
                mint,
                tokens_to_sell,
                slippage_bps=effective_slippage,
                reason=reason,
                dry_run=self.dry_run,
                close_token_account=not is_partial,
            )
        else:
            exec_res = await self.executor.execute_sell(
                mint=mint,
                token_amount=tokens_to_sell,
                slippage_bps=effective_slippage,
                reason=reason,
                dry_run=self.dry_run,
                # A full exit closes the token account to recover rent (BUG-96).
                close_token_account=not is_partial,
            )
        sell_latency_ms = (time.perf_counter() - t_sell_start) * 1000.0

        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.EXECUTION,
                severity=(
                    EventSeverity.INFO if exec_res.success else EventSeverity.ERROR
                ),
                event_name="sell_executed",
                mint=mint,
                mint_name=pos_name,
                latency_ms=sell_latency_ms,
                data={
                    "success": exec_res.success,
                    "signature": exec_res.signature,
                    "error": exec_res.error,
                    "tokens_sold": tokens_to_sell,
                    "is_partial": is_partial,
                    "reason": reason,
                },
                error_message=exec_res.error,
            )

        if not exec_res.success:
            self._enqueue_exit_retry(mint, reason=f"sell_exec_failed: {exec_res.error}")
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_failed {mint}")
            return False

        pos_entry = position_entry_sol(
            position, float(getattr(self.config, "buy_amount_sol", 0.0) or 0.0)
        )
        entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(position.get("current_market_cap", 0.0) or entry_mc or 0.0)
        frac = sold_fraction(tokens_to_sell, initial_tokens, rem_tokens)
        sell_p = estimate_sell_proceeds(
            exec_res,
            dry_run=self.dry_run,
            cost_sol=pos_entry,
            fraction=frac,
            entry_market_cap=entry_mc,
            current_market_cap=curr_mc,
            # Pump.fun charges its fee on the buy and on the sell; live swap
            # amounts include it, so paper proceeds must too (FEAT-49), plus
            # the exit haircut replay charges (BUG-126).
            paper_fee_factor=(self._paper_exit_factor() if self.dry_run else 1.0),
        )
        # rc.3: where the stop was first crossed vs. what this exit sold at.
        exit_metrics = (
            stop_exit_metrics(
                position,
                stop_loss=float(self.config.stop_loss),
                sold_at=time.time(),
                proceeds_sol=sell_p,
                cost_sol=pos_entry * frac,
            )
            if not is_partial and getattr(self.config, "record_stop_crossings", False)
            else None
        )

        self.position_manager.record_sell(
            mint=mint,
            sold_tokens=tokens_to_sell,
            proceeds_sol=sell_p,
            target_tier=target_tier,
            is_partial=is_partial,
        )
        self.active_positions = self.position_manager.get_all_positions()
        if self.dry_run or self.paper_trade:
            self.wallet_balance_sol = max(
                0.0, float(self.wallet_balance_sol) + float(sell_p)
            )
        sell_costs = self._execution_costs(exec_res)
        sell_costs_sol = sell_costs.total_cost_sol if sell_costs is not None else 0.0

        if not is_partial:
            self._exit_retry_queue.pop(mint, None)
        effective_entry = pos_entry * frac if pos_entry > 0 else pos_entry
        trade_pnl = sell_p - effective_entry
        net_trade_pnl = trade_pnl - sell_costs_sol
        if getattr(self, "daily_equity_tracker", None) is not None:
            self._book_trade_costs(net_trade_pnl, sell_costs_sol)
            if hasattr(self, "event_logger") and self.event_logger is not None:
                self.event_logger.emit(
                    category=EventCategory.RISK,
                    severity=EventSeverity.INFO,
                    event_name="realized_pnl_banked",
                    mint=mint,
                    mint_name=pos_name,
                    data={
                        "trade_pnl": trade_pnl,
                        "net_trade_pnl": net_trade_pnl,
                        "costs_sol": sell_costs_sol,
                        "is_partial": is_partial,
                        "realized_daily_pnl_sol": self.daily_equity_tracker.realized_daily_pnl_sol,
                        "effective_baseline_sol": self.daily_equity_tracker.effective_baseline_sol,
                    },
                )
        self._record_trade(
            position_id=position_id(position),
            mint=mint,
            action="partial_sell" if is_partial else "sell",
            token_name=pos_name,
            mint_name=pos_name,
            entry=effective_entry,
            exit_value=sell_p,
            buy_price=pos_entry,
            sell_price=sell_p,
            reason=reason,
            signature=exec_res.signature,
            costs=sell_costs,
            exit_metrics=exit_metrics,
        )
        if self.replay_recorder is not None:
            self.replay_recorder.record_snapshot(
                sell_replay_snapshot(
                    mint=mint,
                    name=pos_name,
                    position=position,
                    proceeds_sol=sell_p,
                    tokens_sold=tokens_to_sell,
                    reason=reason,
                    default_reason="partial_exit" if is_partial else "exit",
                    exit_metrics=exit_metrics,
                )
            )
        if is_partial:
            self._transition_to(
                TradingBotState.HOLDING, reason=f"partial_sell_complete {mint}"
            )
        else:
            self._transition_to(
                TradingBotState.MONITORING, reason=f"sell_complete {mint}"
            )
        return True

    async def _evaluate_and_execute_exit(
        self, mint: str, current_market_cap: float, websocket: Any = None
    ) -> bool:
        if mint not in self.active_positions:
            return False

        entry_mc, curr_mc, peak_mc = self.position_manager.update_price(
            mint, current_market_cap
        )
        performance = curr_mc / entry_mc if entry_mc > 0 else 1.0
        peak_ratio = peak_mc / entry_mc if entry_mc > 0 else 1.0

        cand = self.graduation_engine.get_candidate(mint)
        curve_prog = cand.progress_pct if cand else None

        exit_decision = self.position_manager.evaluate_exit(
            mint, current_market_cap=current_market_cap, curve_progress_pct=curve_prog
        )
        if not exit_decision:
            return False

        self._log(
            f"Monitoring {mint[:8]}... | current MC {current_market_cap:.2f} SOL | performance {performance:.2%} (peak {peak_ratio:.2f}x)"
        )
        self._last_event = f"tracking {mint[:8]}... ({performance:.2%})"

        if exit_decision.action == ExitAction.PARTIAL_EXIT:
            self._log(
                f"Partial exit triggered for {mint} ({exit_decision.exit_type}): {exit_decision.reason}"
            )
            self._last_event = f"partial exit {mint[:8]} ({exit_decision.exit_type})"
            sold = await self._sell_token(
                mint,
                sell_amount_tokens=exit_decision.sell_tokens,
                sell_fraction=exit_decision.sell_fraction,
                reason=exit_decision.reason,
                target_tier=exit_decision.target_tier,
            )
            return sold

        if exit_decision.action == ExitAction.FULL_EXIT:
            self._log(
                f"Exit triggered for {mint} ({exit_decision.exit_type}): {exit_decision.reason}"
            )
            self._last_event = f"{exit_decision.exit_type} {mint[:8]}"
            sold = await self._sell_token(
                mint,
                reason=exit_decision.reason,
                target_tier=exit_decision.target_tier,
            )
            return sold

        return False

    async def _maybe_buy_pre_graduation(
        self, mint: str, market_cap_sol: float, *, now: float, min_samples: int = 0
    ) -> bool:
        return await curve_handlers.maybe_buy_pre_graduation(
            self, mint, market_cap_sol, now=now, min_samples=min_samples
        )

    async def _handle_bonding_curve_state_update(
        self, update: BondingCurveStateUpdate
    ) -> None:
        await curve_handlers.handle_bonding_curve_state_update(self, update)

    async def _handle_trade_event_update(self, update: TradeEventUpdate) -> None:
        await trade_handlers.handle_trade_event_update(self, update)

    async def _handle_complete_event_update(self, update: CompleteEventUpdate) -> None:
        await curve_handlers.handle_complete_event_update(self, update)

    async def _handle_raydium_pool_update(self, pool_keys: RaydiumPoolKeys) -> None:
        await raydium_handlers.handle_raydium_pool_update(self, pool_keys)

    async def _arbitrage_costs(
        self, opp: ArbitrageOpportunity, signature: str | None
    ) -> TransactionCosts:
        return await raydium_handlers.arbitrage_costs(self, opp, signature)

    async def _evaluate_and_execute_arbitrage(
        self,
        mint: str,
        virtual_sol: int,
        virtual_token: int,
        trade_sol: float = 0.0,
        is_buy: bool = True,
    ) -> None:
        await raydium_handlers.evaluate_and_execute_arbitrage(
            self, mint, virtual_sol, virtual_token, trade_sol, is_buy
        )

    async def _handle_new_token_event(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        await new_token_handlers.handle_new_token_event(self, data, websocket)

    async def _handle_trade_update(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        await trade_handlers.handle_trade_update(self, data, websocket)

    def _handle_server_message(self, text: str) -> None:
        """Logs, counts and (for subscription refusals) alerts a stream notice.

        PumpPortal answers a refused ``subscribeTokenTrade`` with a mint-less
        ``message``; dropping it left held positions without trade data (BUG-112).
        """
        text = redact_text(str(text)).strip()[:300]
        counts = self._stream_server_messages
        first = text not in counts
        counts[text] = counts.get(text, 0) + 1
        if len(counts) > 50:
            counts.pop(next(iter(counts)))
        breaker = self._trade_feed_breaker()
        if is_trade_feed_refusal(text):
            self._last_status = "degraded: token-trade subscription refused"
            if breaker.record_refusal(text):
                # Usually the API key's wallet ran dry; buys stop until a probe works.
                notice = breaker.trip_message()
                self._log(notice, level=logging.ERROR)
                self._record_event(notice, alert=True)
            else:
                self._log(f"Stream server message: {text}", level=logging.DEBUG)
            return
        self._log(
            f"Stream server message: {text}",
            level=logging.INFO if first else logging.DEBUG,
        )
        if is_trade_feed_confirmation(text):
            self._close_trade_feed_breaker(breaker.record_confirmation())

    def _trade_feed_breaker(self) -> TradeFeedBreaker:
        breaker: TradeFeedBreaker | None = getattr(self, "trade_feed_breaker", None)
        if breaker is None:
            breaker = TradeFeedBreaker()
            self.trade_feed_breaker = breaker
        return breaker

    def _close_trade_feed_breaker(self, closed: bool) -> None:
        if not closed:
            return
        notice = self._trade_feed_breaker().recovery_message()
        self._log(notice, level=logging.WARNING)
        self._record_event(notice, alert=True)
        if self._last_status == "degraded: token-trade subscription refused":
            self._last_status = "monitoring active tokens"

    def trade_feed_available(self) -> bool:
        """False while the trade-feed circuit breaker is open (BUG-112)."""
        return not self._trade_feed_breaker().is_open

    async def _finish_trade_feed_probe(self, websocket: Any = None) -> None:
        """Unsubscribes a probe mint once the server has answered it."""
        breaker = self._trade_feed_breaker()
        mint = breaker.probe_mint
        if mint is None or mint in self.active_positions:
            breaker.take_probe_mint()
            return
        breaker.take_probe_mint()
        await self._unsubscribe_from_token_trades(websocket, mint)

    async def _maybe_probe_trade_feed(self) -> None:
        """While the breaker is open, re-try a subscription every probe interval."""
        breaker = self._trade_feed_breaker()
        if not breaker.probe_due() or self._active_ws is None:
            return
        held = list(self.active_positions)
        mint = held[0] if held else str(self._last_new_token or "")
        if not held and len(mint) < 32:
            # No mint to probe with yet ("-" until the first create event).
            return
        breaker.start_probe(None if held else mint)
        self._log(
            f"Trade-feed breaker open: probing subscribeTokenTrade with {mint[:8]}",
            level=logging.INFO,
        )
        await self._subscribe_to_token_trades(self._active_ws, mint)

    async def _handle_message(self, data: Any, websocket: Any = None) -> None:
        if (
            isinstance(data, dict)
            and isinstance(data.get("message"), str)
            and not data.get("mint")
            and not data.get("txType")
        ):
            self._handle_server_message(data["message"])
            text = data["message"].lower()
            if self._trade_feed_breaker().probe_mint and (
                is_trade_feed_refusal(text) or is_trade_feed_confirmation(text)
            ):
                await self._finish_trade_feed_probe(websocket)
            return
        if (
            isinstance(data, dict)
            and data.get("mint")
            and str(data.get("txType") or "").lower() in MIGRATION_TX_TYPES
        ):
            await self._handle_ws_migration(str(data["mint"]))
            return
        if (
            isinstance(data, dict)
            and data.get("mint")
            and str(data.get("txType") or "").lower() in {"buy", "sell"}
        ):
            # Trade data for a subscribed mint proves the feed delivers.
            self._close_trade_feed_breaker(
                self._trade_feed_breaker().record_trade_data()
            )
        if isinstance(data, dict):
            # Check for Raydium pool keys message
            if "amm_id" in data and "coin_mint" in data:
                try:
                    pool_keys = RaydiumPoolKeys.from_dict(data)
                    await self._handle_raydium_pool_update(pool_keys)
                    return
                except Exception:
                    pass
            elif data.get("event") in {"raydium_pool_created", "raydium_pool"} and (
                "poolKeys" in data or "pool_keys" in data
            ):
                try:
                    pkeys = data.get("poolKeys") or data.get("pool_keys")
                    if isinstance(pkeys, dict):
                        pool_keys = RaydiumPoolKeys.from_dict(pkeys)
                        await self._handle_raydium_pool_update(pool_keys)
                        return
                except Exception:
                    pass
        await self.event_router.route_ws_message(data, websocket)

    # -- Confirmed entries: watch list and batch curve poller (FEAT-51) --------

    def _entry_mode(self) -> str:
        return str(getattr(self.config, "entry_mode", "launch") or "launch").lower()

    def _count_watch(self, key: str, amount: int = 1) -> None:
        stats = getattr(self, "_watch_stats", None)
        if stats is None:
            stats = self._watch_stats = {}
        stats[key] = stats.get(key, 0) + amount

    def _may_watch(self, mint: str) -> bool:
        """Cheap gates before screening a launch for the watch list."""
        if self.buying_paused or self._is_closed_reentry(mint):
            return False
        return not self.order_flow_engine.is_watched(mint)

    def _watch_token(
        self,
        mint: str,
        data: dict[str, Any],
        market_cap_sol: float,
        verdict: TokenScreeningVerdict,
    ) -> None:
        new_token_handlers.watch_token(self, mint, data, market_cap_sol, verdict)

    def _entry_lanes(self) -> dict[str, str]:
        lanes: dict[str, str] | None = getattr(self, "_entry_lane_by_mint", None)
        if lanes is None:
            lanes = self._entry_lane_by_mint = {}
        return lanes

    def _own_wallet(self) -> str:
        try:
            return str(self.execution.get_wallet_pubkey())
        except Exception:
            return ""

    def _note_follow_on_buy(
        self, mint: str, is_buy: bool, sol_amount: float, user: str, ts: float
    ) -> None:
        trade_handlers.note_follow_on_buy(self, mint, is_buy, sol_amount, user, ts)

    async def _maybe_buy_confirmed_momentum(
        self,
        mint: str,
        market_cap_sol: float,
        token_name: str | None,
        *,
        now: float,
    ) -> bool:
        return await trade_handlers.maybe_buy_confirmed_momentum(
            self, mint, market_cap_sol, token_name, now=now
        )

    # -- Shadow variants: momentum rules logged on paper, never traded (FEAT-58) --

    def _shadow_book(self) -> ShadowVariantBook | None:
        book: ShadowVariantBook | None = getattr(self, "_shadow_variant_book", None)
        if book is None:
            variants = parse_shadow_variants(
                getattr(self.config, "shadow_variants", ()) or ()
            )
            book = self._shadow_variant_book = ShadowVariantBook(self.config, variants)
        return book if book.enabled else None

    def _evaluate_shadow_variants(
        self, mint: str, market_cap_sol: float, *, now: float
    ) -> None:
        trade_handlers.evaluate_shadow_variants(self, mint, market_cap_sol, now=now)

    def _schedule_shadow_fill(self, shadow: ShadowSignal) -> None:
        trade_handlers.schedule_shadow_fill(self, shadow)

    async def _record_shadow_fill(self, shadow: ShadowSignal) -> None:
        await trade_handlers.record_shadow_fill(self, shadow)

    async def _cancel_shadow_fills(self) -> None:
        tasks = list(getattr(self, "_shadow_fill_tasks", None) or ())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def watch_list_status(self) -> dict[str, Any]:
        return watch_handlers.watch_list_status(self)

    async def _run_watch_poll_loop(self) -> None:
        await watch_handlers.run_watch_poll_loop(self)

    def _watch_poll_due(self, mint: str, now: float) -> bool:
        return watch_handlers.watch_poll_due(self, mint, now)

    def _record_curve_poll(
        self,
        mint: str,
        market_cap_sol: float,
        *,
        ts: float,
        source: str,
        real_sol: float | None = None,
        virtual_sol: float | None = None,
    ) -> None:
        watch_handlers.record_curve_poll(
            self,
            mint,
            market_cap_sol,
            ts=ts,
            source=source,
            real_sol=real_sol,
            virtual_sol=virtual_sol,
        )

    async def _poll_watch_list(self) -> None:
        await watch_handlers.poll_watch_list(self)

    async def _promote_watched_mints(self) -> None:
        await watch_handlers.promote_watched_mints(self)

    async def _subscribe_to_token_trades(
        self, websocket: Any = None, mint: str = ""
    ) -> None:
        ws = websocket or self._active_ws
        if ws is None or not mint:
            return
        try:
            await send_ws_message(
                ws,
                token_trade_message("subscribeTokenTrade", mint),
                prefer_raw_send=True,
            )
        except Exception as exc:
            # The socket is usually going away; the reconnect resubscribes.
            self._trade_feed_breaker().record_send_failure()
            self._log(
                f"subscribeTokenTrade for {mint[:8]} could not be sent: {exc}",
                level=logging.WARNING,
            )

    async def _unsubscribe_from_token_trades(
        self, websocket: Any = None, mint: str = ""
    ) -> None:
        ws = websocket or self._active_ws
        if ws is None or not mint:
            return
        try:
            await send_ws_message(
                ws,
                token_trade_message("unsubscribeTokenTrade", mint),
                prefer_raw_send=True,
            )
        except Exception:
            pass

    def _stream_connect_url(self) -> str:
        """Stream URL with the PumpPortal key added; never log or display it."""
        return stream_connect_url(
            self.stream_url, getattr(self, "_stream_api_key", None)
        )

    async def _run_websocket_stream(self) -> None:
        """Connects to the WebSocket endpoint and ingests real-time events."""
        if self.trade_feed_breaker.stream_has_api_key is False:
            self._log(
                "PumpPortal stream has no API key: subscribeTokenTrade will be "
                "refused. Export PUMPFUN_STREAM_API_KEY (BUG-117, BUG-118).",
                level=logging.WARNING,
            )
        if getattr(self, "_stream_key_in_url", False):
            self._log(
                "PUMPFUN_STREAM_URL carries ?api-key=; move the key to "
                "PUMPFUN_STREAM_API_KEY and keep the URL key-free (BUG-118).",
                level=logging.WARNING,
            )
        await run_websocket_stream(self)

    # -- WebSocketStreamHost hooks (streams/websocket.py) --------------------

    def stream_stop_requested(self) -> bool:
        return bool(self._stop_requested)

    def stream_connect_url(self) -> str:
        return self._stream_connect_url()

    def stream_log(self, message: str, level: int = logging.INFO) -> None:
        self._log(message, level=level)

    async def on_stream_connected(self, ws: Any) -> None:
        self._active_ws = ws
        self._log(f"Connected to WebSocket stream at {self.stream_url}")
        self._record_event(f"stream connected: {self.stream_url}", alert=False)
        self._last_message_at = time.monotonic()
        self._circuit_breaker_tripped = False
        self._stream_consecutive_failures = 0
        # The breaker stays open across reconnects: only a
        # confirmed subscription or trade data closes it.
        self._last_status = "monitoring active tokens"
        self._health_ok = True
        await send_ws_message(ws, NEW_TOKEN_SUBSCRIPTION)
        # Free feed: graduation rate for the regime record, and the exit signal
        # for a held coin that migrates to PumpSwap (BUG-123).
        await send_ws_message(ws, MIGRATION_SUBSCRIPTION)
        # Resubscribe to held and promoted watched mints.
        for mint in list(self.active_positions.keys()):
            await self._subscribe_to_token_trades(ws, mint)
        for mint in self.order_flow_engine.watched_mints():
            entry = self.order_flow_engine.get_watch(mint)
            if entry is not None and entry.subscribed:
                await self._subscribe_to_token_trades(ws, mint)
        if self.trade_feed_breaker.is_open:
            # Probe on the first health pass after reconnecting.
            self.trade_feed_breaker.next_probe_at = 0.0

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        self._last_message_at = time.monotonic()
        self._circuit_breaker_tripped = False
        self._stream_consecutive_failures = 0
        await self._handle_message(data, ws)

    def on_stream_error(self, message: str) -> None:
        self._stream_consecutive_failures += 1
        self._log(message, level=logging.WARNING)

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self._stream_consecutive_failures += 1
        self._log(
            f"WebSocket stream error: {exc}. Reconnecting in {backoff:.1f}s (attempt {self._stream_consecutive_failures})...",
            level=logging.WARNING,
        )
        # One disconnect reaches exactly one of this hook and on_stream_ended
        # (an ERROR frame goes through on_stream_error, then ends): BUG-122.
        if not self._stop_requested:
            self._record_connection_loss()
        self._trip_stream_breaker_if_failing()

    def on_stream_ended(self) -> None:
        if not self._stop_requested:
            self._record_connection_loss()
        self._trip_stream_breaker_if_failing()

    def on_stream_closed(self) -> None:
        self._active_ws = None

    def _trip_stream_breaker_if_failing(self) -> None:
        if self._stream_consecutive_failures >= self._max_stream_consecutive_failures:
            self._circuit_breaker_tripped = True
            self._health_ok = False
            self._last_status = "degraded: stream circuit breaker active"

    async def _refresh_active_positions_market_caps(self) -> None:
        await curve_handlers.refresh_active_positions_market_caps(self)

    async def _pumpswap_exit_market_cap(self, mint: str) -> float | None:
        return await raydium_handlers.pumpswap_exit_market_cap(self, mint)

    async def _exit_graduated_position(self, mint: str) -> bool:
        return await raydium_handlers.exit_graduated_position(self, mint)

    async def _handle_ws_migration(self, mint: str) -> None:
        await raydium_handlers.handle_ws_migration(self, mint)

    async def _graduation_backfill_pass(self) -> int:
        return await raydium_handlers.graduation_backfill_pass(self)

    async def _run_graduation_backfill_loop(self) -> None:
        await raydium_handlers.run_graduation_backfill_loop(self)

    def _market_regime(self) -> MarketRegimeTracker:
        tracker = getattr(self, "market_regime", None)
        if tracker is None:
            tracker = self.market_regime = MarketRegimeTracker()
        return tracker

    def _position_refresh_interval(self) -> float:
        try:
            return max(0.0, float(getattr(self.config, "position_refresh_seconds", 0)))
        except (TypeError, ValueError):
            return 0.0

    async def _run_position_refresh_loop(self) -> None:
        """Re-prices held positions from their curves every few seconds (BUG-112).

        Trade messages are the fast path; this loop bounds how stale an exit
        decision can get when they are missing or refused.
        """
        interval = self._position_refresh_interval()
        if interval <= 0:
            return
        while not self._stop_requested:
            try:
                await asyncio.sleep(interval)
                await self._refresh_active_positions_market_caps()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log(f"Position refresh exception: {exc}", level=logging.DEBUG)

    async def _run_health_loop(self) -> None:
        """Periodic background task evaluating health, equity, and reconciliations."""
        while not self._stop_requested:
            try:
                await asyncio.sleep(5)
                await self._update_health_state()
                if self._position_refresh_interval() <= 0:
                    await self._refresh_active_positions_market_caps()
                await self._process_exit_retry_queue()
                await self._maybe_probe_trade_feed()
                await self._check_and_enforce_circuit_breaker()
                self._prune_seen_mints()
                self._prune_strategy_caches()
                await self._run_supervision()
                await self._maybe_run_profit_sweep()
                self._write_status_snapshot()
                await self._run_retention_prune()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log(f"Health loop exception: {exc}", level=logging.DEBUG)

    def _degradation_conditions(self) -> dict[str, tuple[bool, str]]:
        """Conditions watched by the degradation alert: name -> (degraded, detail)."""
        silent_for = time.monotonic() - self._last_message_at
        stream_down = bool(self._circuit_breaker_tripped) or (
            silent_for > float(self.config.health_check_timeout_seconds)
        )
        conditions = {
            "stream": (
                stream_down,
                f"{self._last_status}; no message for {int(silent_for)}s",
            ),
            "trade_feed": (
                not self.trade_feed_available(),
                "token-trade subscription refused: "
                + self._trade_feed_breaker().likely_cause(),
            ),
        }
        if self.rpc_pool is not None:
            telemetry = self.rpc_pool.get_telemetry()
            total = int(telemetry.get("total_endpoints") or 0)
            healthy = int(telemetry.get("healthy_endpoints") or 0)
            conditions["rpc"] = (
                total > 0 and healthy == 0,
                f"{healthy}/{total} RPC endpoints healthy",
            )
        return conditions

    def _daily_summary_text(self, now: float) -> str:
        tracker = self.daily_equity_tracker
        open_val = self._open_positions_exit_value()
        breaker = "LOCKED" if tracker.circuit_breaker_engaged else "clear"
        if tracker.circuit_breaker_engaged and tracker.lock_reason:
            breaker = f"LOCKED ({tracker.lock_reason[:80]})"
        return format_daily_summary(
            mode=(
                "paper" if self.paper_trade else ("dry run" if self.dry_run else "live")
            ),
            now=now,
            period_start=self._daily_summary.period_start,
            period=self._daily_summary.period_totals(self._pnl_totals),
            session=self._pnl_totals,
            wallet_balance_sol=float(self.wallet_balance_sol),
            open_positions=len(self.active_positions),
            breaker=breaker,
            drawdown_pct=tracker.calculate_drawdown(self.wallet_balance_sol, open_val),
            reconciliation=describe_reconciliation_status(self.reconciliation_status()),
            buying=self._operator_pause.describe(),
            health="ok" if self._health_ok else "degraded",
            swept_sol=self._sweep_state.total_swept_sol,
        )

    async def _run_supervision(self) -> None:
        """Daily summary, degradation and reconciliation-gap alerts (Sprint 24D)."""
        now_wall = time.time()
        now_mono = time.monotonic()
        for name, (degraded, detail) in self._degradation_conditions().items():
            message = self._degradation.update(
                name, degraded, now=now_mono, detail=detail
            )
            if message:
                self._log(message, level=logging.WARNING)
                self._record_event(message, alert=True)

        gap = self._reconcile_watcher.check(self.reconciliation_status())
        if gap:
            self._log(gap, level=logging.WARNING)
            self._record_event(gap, alert=True)

        if not getattr(self.config, "daily_summary_alert", True):
            return
        self._daily_summary.prime(self._pnl_totals, now_wall)
        if not self._daily_summary.due(now_wall):
            return
        summary = self._daily_summary_text(now_wall)
        self._daily_summary.mark_sent(self._pnl_totals, now_wall)
        self._log(summary)
        self._record_event("daily summary sent", alert=False)
        self._send_alert(summary)
        self._write_audit_record("daily_summary", {"text": summary})

    async def _maybe_run_profit_sweep(self) -> None:
        """Runs the profit sweep when enabled and due (FEAT-42)."""
        if not getattr(self.config, "profit_sweep_enabled", False):
            return
        now = time.time()
        last = self._sweep_state.last_check_at
        interval = float(self.config.profit_sweep_interval_seconds)
        if last is not None and now - last < interval:
            return
        self._sweep_state.last_check_at = now
        await self.run_profit_sweep()

    async def run_profit_sweep(self) -> float:
        """Moves SOL above the hot-wallet floor to the cold wallet; returns SOL swept.

        Runs under the trade lock, so no buy can spend the balance meanwhile. Paper
        and dry-run modes simulate the transfer against the paper wallet.
        """
        destination = str(self.config.profit_sweep_destination).strip()
        async with self._trade_lock:
            simulated = bool(self.dry_run or self.paper_trade)
            try:
                balance = (
                    float(self.wallet_balance_sol)
                    if simulated
                    else float(await self.execution.get_balance_sol())
                )
                if not simulated:
                    self._live_balance_confirmed = True
            except Exception as exc:
                self._sweep_state.last_error = f"balance unavailable: {exc}"
                self._log(f"Profit sweep skipped: {exc}", level=logging.WARNING)
                return 0.0
            plan = plan_sweep(
                balance_sol=balance,
                floor_sol=effective_sweep_floor(self.config),
                min_sweep_sol=float(self.config.profit_sweep_min_sol),
            )
            if plan.lamports <= 0:
                self._log(
                    f"Profit sweep: nothing to move ({plan.skip_reason}; balance "
                    f"{balance:.4f}, floor {plan.floor_sol:.4f} SOL)",
                    level=logging.DEBUG,
                )
                return 0.0
            fee_sol = BASE_FEE_LAMPORTS_PER_SIGNATURE / 1_000_000_000
            cost_source = "modelled"
            if simulated:
                signature = f"dry_run_sweep_{self._sweep_state.sweeps + 1:06d}"
                self.wallet_balance_sol = max(
                    0.0, float(self.wallet_balance_sol) - plan.amount_sol - fee_sol
                )
            else:
                try:
                    signature = await self.execution.transfer_sol(
                        destination, plan.lamports
                    )
                    confirmed = await self.execution.confirm_transaction(signature)
                except Exception as exc:
                    confirmed, signature = False, ""
                    error = str(exc)
                else:
                    error = "" if confirmed else f"not confirmed: {signature}"
                if not confirmed:
                    self._sweep_state.last_error = error
                    message = f"ALERT profit sweep failed: {error}"
                    self._log(message, level=logging.ERROR)
                    self._record_event(message, alert=True)
                    return 0.0
                try:
                    # Only the fee is read; no token account is involved.
                    costs = await asyncio.wait_for(
                        self.execution.get_transaction_costs(
                            signature, WSOL_MINT_STR, is_buy=False
                        ),
                        timeout=8.0,
                    )
                except Exception:
                    costs = None
                if isinstance(costs, TransactionCosts):
                    fee_sol = costs.fee_sol + costs.priority_fee_sol
                    cost_source = costs.source
                self.wallet_balance_sol = max(0.0, balance - plan.amount_sol - fee_sol)

            # A withdrawal is not a drawdown; the fee is a real cost.
            self.daily_equity_tracker.record_withdrawal(plan.amount_sol)
            self.daily_equity_tracker.record_realized_trade(-fee_sol, fee_sol)
            self._sweep_state.record_success(plan.amount_sol, signature, time.time())
            self._write_audit_record(
                "sweep",
                {
                    "signature": signature,
                    "destination": destination,
                    "amount_sol": plan.amount_sol,
                    "fee_sol": fee_sol,
                    "cost_source": cost_source,
                    "cash_flow_sol": -(plan.amount_sol + fee_sol),
                    "balance_before_sol": balance,
                    "floor_sol": plan.floor_sol,
                    "dry_run": simulated,
                },
            )
            message = (
                f"profit sweep: {plan.amount_sol:.4f} SOL to {destination[:4]}…"
                f"{destination[-4:]} ({'simulated' if simulated else signature})"
            )
            self._log(message)
            self._record_event(message, alert=True)
            return plan.amount_sol

    async def _run_retention_prune(self) -> None:
        """Periodic background evaluation of disk retention quotas and archive pruning."""
        now_mono = time.monotonic()
        if (
            now_mono - self._last_retention_check
            < self.retention_check_interval_seconds
        ):
            return
        self._last_retention_check = now_mono
        for mgr in getattr(self, "retention_managers", []):
            try:
                pruned = await mgr.prune_expired_async()
                if pruned:
                    self._log(
                        f"Retention policy pruned {len(pruned)} expired log/audit archives in {mgr.target_directory}",
                        level=logging.DEBUG,
                    )
                await asyncio.to_thread(mgr.compress_uncompressed_archives)
            except Exception as exc:
                self._log(f"Retention manager exception: {exc}", level=logging.DEBUG)

    async def _render_loop(self) -> None:
        """Background loop rendering the Rich terminal dashboard."""
        if not self.verbose or self.headless:
            return

        with Live(
            build_dashboard(self),
            console=self.console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            self._display_live = live
            while not self._stop_requested:
                try:
                    live.update(build_dashboard(self))
                    await asyncio.sleep(0.25)
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

    async def start(self) -> None:
        """Starts background workers and event stream listeners."""
        self._register_signal_handlers()
        if hasattr(self, "event_logger") and self.event_logger is not None:
            await self.event_logger.start()
        if self.rpc_pool:
            await self.rpc_pool.start_health_loop()
        if self.replay_recorder is not None:
            await self.replay_recorder.start()

        self._health_ok = True
        self._risk_killed = False
        self._last_message_at = time.monotonic()
        self._last_health_check = time.monotonic()

        # Alerted, so a supervisor restart is visible to an unattended operator.
        self._record_event(
            f"bot started ({self.config.strategy_preset} preset, "
            f"{'paper' if self.paper_trade else 'live'}, pid {os.getpid()}"
            f"{', buying PAUSED' if self.buying_paused else ''})",
            alert=True,
        )
        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.LIFECYCLE,
                severity=EventSeverity.INFO,
                event_name="bot_started",
                data={
                    "preset": self.config.strategy_preset,
                    "paper_trade": self.paper_trade,
                    "dry_run": self.dry_run,
                    "buy_amount_sol": self.buy_amount_sol,
                },
            )
        self._transition_to(TradingBotState.MONITORING, reason="bot_started")
        await self._reconcile_positions_on_startup()

        health_task = asyncio.create_task(self._run_health_loop())
        refresh_task = asyncio.create_task(self._run_position_refresh_loop())
        watch_task = asyncio.create_task(self._run_watch_poll_loop())
        backfill_task = asyncio.create_task(self._run_graduation_backfill_loop())
        render_task = None
        if self.verbose and not self.headless:
            render_task = asyncio.create_task(self._render_loop())

        is_custom_listen = (
            hasattr(self.geyser_client, "listen")
            and getattr(
                getattr(self.geyser_client, "listen"),
                "__func__",
                getattr(self.geyser_client, "listen", None),
            )
            != YellowstoneGeyserClient.listen
        )

        # The built-in Geyser client has no gRPC transport; never "connect" it and
        # idle while looking healthy. Fall back to the WebSocket stream (BUG-55).
        use_geyser = bool(
            self.geyser_client and (self.geyser_endpoint or is_custom_listen)
        )
        if (
            use_geyser
            and not is_custom_listen
            and not getattr(self.geyser_client, "has_transport", True)
        ):
            use_geyser = False
            message = (
                f"geyser endpoint {self.geyser_endpoint} has no gRPC transport; "
                "using the WebSocket stream instead"
            )
            self._log(message, level=logging.ERROR)
            self._record_event(message)

        try:
            if use_geyser:
                # Events are consumed via listen() only; registering callbacks too
                # would route every event twice (BUG-40).
                # An injected listen() source needs no transport to be started.
                if hasattr(self.geyser_client, "start") and getattr(
                    self.geyser_client, "has_transport", True
                ):
                    await self.geyser_client.start()
                self._record_event(
                    f"geyser stream started: {self.geyser_endpoint}", alert=False
                )
                async for event in self.geyser_client.listen():
                    if self._stop_requested:
                        break
                    self._last_message_at = time.monotonic()
                    self._circuit_breaker_tripped = False
                    self._stream_consecutive_failures = 0
                    if isinstance(event, dict):
                        await self._handle_message(event)
                    elif isinstance(event, BondingCurveStateUpdate):
                        await self.event_router.route_geyser_curve_update(event)
                    elif isinstance(event, TradeEventUpdate):
                        await self.event_router.route_geyser_trade_update(event)
                    elif isinstance(event, CompleteEventUpdate):
                        await self.event_router.route_geyser_complete_update(event)
                    if self._stop_requested:
                        break
            elif (
                self.stream_url
                and self.stream_url.startswith(
                    ("ws://", "wss://", "http://", "https://")
                )
                and self.stream_url != "http://127.0.0.1:10000"
            ):
                await self._run_websocket_stream()
            else:
                self._log(
                    "No Geyser or WebSocket stream configured; idling.",
                    level=logging.WARNING,
                )
                while not self._stop_requested:
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._stream_consecutive_failures += 1
            if (
                self._stream_consecutive_failures
                >= self._max_stream_consecutive_failures
            ):
                self._circuit_breaker_tripped = True
                self._health_ok = False
                self._last_status = "degraded: stream circuit breaker active"
            self._log(f"Stream error in start loop: {exc}", level=logging.WARNING)
        finally:
            health_task.cancel()
            refresh_task.cancel()
            watch_task.cancel()
            backfill_task.cancel()
            if render_task:
                render_task.cancel()
            # Shadow reads still waiting are dropped before the recorder closes.
            await self._cancel_shadow_fills()
            if self.geyser_client and hasattr(self.geyser_client, "stop"):
                await self.geyser_client.stop()
            if self.rpc_pool:
                if hasattr(self.rpc_pool, "stop"):
                    self.rpc_pool.stop()
                elif hasattr(self.rpc_pool, "close"):
                    await self.rpc_pool.close()
            if hasattr(self, "event_logger") and self.event_logger is not None:
                await self.event_logger.flush_and_close()
            if self.replay_recorder is not None:
                await self.replay_recorder.close()
            self.persistence.close()
            # Release HTTP sessions held by the execution and API clients (BUG-74).
            await self._close_http_clients()
            if self.state != TradingBotState.SHUTDOWN:
                self._transition_to(TradingBotState.SHUTDOWN, reason="bot_terminated")
            stop_reason = (
                "shutdown requested" if self._stop_requested else "stream loop ended"
            )
            self._record_event(f"bot stopped ({stop_reason})", alert=True)
            # Deliver the last alerts before asyncio.run() cancels pending tasks.
            await self._flush_alerts()

    def run(self) -> None:
        """Synchronous runner entrypoint."""
        try:
            asyncio.run(self.start())
        except (KeyboardInterrupt, SystemExit):
            self.request_shutdown()


def main() -> None:
    """CLI binary entrypoint."""
    bot = TradingBot.from_env()
    bot.run()


if __name__ == "__main__":
    main()
