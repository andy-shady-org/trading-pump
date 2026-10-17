from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterator, Optional

import aiohttp
from dotenv import load_dotenv
from rich.live import Live

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.alerts import AlertDispatcher
from pumpfun_trading.bot.enrichment import (
    TokenEnricher,
    mayhem_mode_reason,
    non_pump_launch_reason,
    screening_snapshot,
)
from pumpfun_trading.bot.event_router import EventRouter
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
from pumpfun_trading.bot.persistence import StatusPersistenceManager
from pumpfun_trading.bot.pnl import PnlTotals, build_pnl_fields
from pumpfun_trading.bot.trade_feed import TradeFeedBreaker
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
from pumpfun_trading.bot.recorder import ReplayRecorder
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
    CopyTradeEngine,
    CrossVenueDisparityMonitor,
    ExitAction,
    GraduationEngine,
    MempoolBackrunEngine,
    OrderFlowEngine,
    RaydiumPoolKeys,
    ScreeningCache,
    TokenScreeningVerdict,
    TradingBotConfig,
    TradingStrategy,
    resolve_strategy_config,
)
from pumpfun_trading.config.env import (
    get_env_bool,
    get_env_int,
    resolve_bot_log_path,
)
from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.execution.builder import build_execution_client
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.infra.rpc_pool import RpcConnectionPool, RpcPoolConfig
from pumpfun_trading.ops.events import (
    DiagnosticEventLogger,
    EventCategory,
    EventSeverity,
)
from pumpfun_trading.ops.logging import (
    get_configured_console,
    setup_structured_logging,
)
from pumpfun_trading.ops.redact import redact_text
from pumpfun_trading.ops.retention import LogRetentionManager, RetentionPolicy
from pumpfun_trading.sdk.costs import (
    BASE_FEE_LAMPORTS_PER_SIGNATURE,
    COST_SOURCE_TRANSACTION_META,
    LAMPORTS_PER_SOL,
    TransactionCosts,
    model_transaction_costs,
)
from pumpfun_trading.sdk.execution import PUMP_DEFAULT_FEE_BPS, WSOL_MINT_STR
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)
from pumpfun_trading.ui.dashboard import build_dashboard

# Upper bound on the post-landing ``getTransaction`` cost lookup of an arbitrage
# bundle (BUG-99); on timeout the modelled costs are booked instead.
ARBITRAGE_COST_LOOKUP_TIMEOUT_SECONDS = 8.0
# Raw base-unit virtual token reserves are ~1.07e15; UI units are ~1.07e9 (BUG-75).
RAW_TOKEN_UNITS_THRESHOLD = 1_000_000_000_000
# Mints bought before; persisted in the status file and capped so the snapshot
# stays small (~2k new buys a day in the Stage 0 paper run) (BUG-109).
TRADED_MINTS_LIMIT = 10_000


class TradingBot:
    """Production-ready Pump.fun trading bot with modular SOLID architecture and lifecycle safeguards."""

    _VALID_STATE_TRANSITIONS: dict[TradingBotState, set[TradingBotState]] = (
        VALID_STATE_TRANSITIONS
    )

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
        resolved = resolve_strategy_config(
            strategy_preset,
            overrides={
                key: value
                for key, value in {
                    "buy_amount_sol": buy_amount_sol,
                    "take_profit": take_profit,
                    "stop_loss": stop_loss,
                    "max_active_positions": max_active_positions,
                    "min_market_cap_sol": min_market_cap_sol,
                    "min_balance_sol": min_balance_sol,
                }.items()
                if value is not None
            },
        )
        base = config or resolved
        if not isinstance(base, TradingBotConfig):
            base = TradingBotConfig.from_dict(base if isinstance(base, dict) else {})
        # Precedence (BUG-100): an explicit ``stream_url=`` argument wins, then a
        # config URL, then PUMPFUN_STREAM_URL / PUMPFUN_WS_URL, then the default.
        # ``pumpbot`` never passes the argument, so its order is unchanged.
        default_stream_url = "http://127.0.0.1:10000"
        env_stream_url = os.getenv("PUMPFUN_STREAM_URL") or os.getenv("PUMPFUN_WS_URL")
        effective_stream_url = stream_url
        if stream_url and stream_url != default_stream_url:
            effective_stream_url = stream_url
        elif base.stream_url and base.stream_url != default_stream_url:
            effective_stream_url = base.stream_url
        elif env_stream_url:
            effective_stream_url = env_stream_url

        self.config = replace(
            base,
            dry_run=bool(base.dry_run or dry_run or paper_trade),
            paper_trade=bool(base.paper_trade or paper_trade),
            verbose=bool(base.verbose and verbose),
            headless=bool(getattr(base, "headless", False) or headless),
            stream_url=str(effective_stream_url),
            api_base_url=str(api_base_url if api_base_url else base.api_base_url),
            replay_log_path=(
                str(replay_log_path)
                if replay_log_path is not None
                else (
                    str(base.replay_log_path)
                    if getattr(base, "replay_log_path", None)
                    else None
                )
            ),
        )

        if self.config.buy_amount_sol <= 0:
            raise ValueError("buy_amount_sol must be greater than zero.")
        if not 0 < self.config.stop_loss < self.config.take_profit:
            raise ValueError(
                "stop_loss must be less than take_profit and both must be greater than zero."
            )
        if self.config.max_active_positions < 1:
            raise ValueError("max_active_positions must be at least 1.")

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
            )
        )

        # Subsystems & Engines
        self.position_manager = PositionManager(self.config)
        self.active_positions = self.position_manager.get_all_positions()
        self.displacement_engine = CapitalDisplacementEngine(
            self.config, self.position_manager
        )

        self.strategy = TradingStrategy(self.config)
        self.order_flow_engine = OrderFlowEngine(
            max_retention_seconds=600,
            recent_token_ttl_seconds=self.recent_token_ttl_seconds,
        )
        self.graduation_engine = GraduationEngine(
            target_graduation_sol=85.0,
            candidate_ttl_seconds=1800,
            pre_migration_threshold_sol=self.config.raydium_pre_migration_sol_threshold,
        )
        self.arb_monitor = CrossVenueDisparityMonitor(
            min_arbitrage_spread_pct=self.config.min_arbitrage_spread_pct,
            min_arbitrage_profit_sol=self.config.min_arbitrage_profit_sol,
            max_arbitrage_input_sol=self.config.max_arbitrage_input_sol,
            min_arbitrage_input_sol=self.config.min_arbitrage_input_sol,
            jito_tip_profit_share_pct=self.config.arbitrage_jito_tip_profit_share_pct,
        )
        self.backrun_engine = MempoolBackrunEngine(
            disparity_monitor=self.arb_monitor,
        )
        self.copy_trade_engine = CopyTradeEngine(
            base_buy_amount_sol=self.config.buy_amount_sol,
            max_position_size_sol=self.config.max_position_size_sol,
            sizing_mode=self.config.copy_trading_sizing_mode,
            scale_factor=self.config.copy_trading_scale_factor,
            min_wallet_win_rate=self.config.copy_trading_min_wallet_win_rate,
            max_wallet_risk_score=self.config.copy_trading_max_wallet_risk_score,
            mirror_sells=self.config.copy_trading_mirror_sells,
            enabled=self.config.enable_copy_trading,
        )
        if self.config.copy_trading_wallets:
            self.copy_trade_engine.registry.register_wallets(
                list(self.config.copy_trading_wallets)
            )

        self.daily_equity_tracker = DailyEquityTracker()
        self.wallet_balance_sol = self._initial_simulated_balance()
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
        self.geyser_client = geyser_client or YellowstoneGeyserClient(
            endpoint=self.geyser_endpoint or self.stream_url,
            x_token=self.geyser_x_token,
            reconnect_initial_backoff=self.reconnect_delay_seconds,
        )
        self._active_ws: Optional[Any] = None

        self._stream_consecutive_failures = 0
        self._circuit_breaker_tripped = False
        stream_retries_env = os.getenv("PUMPFUN_STREAM_MAX_RETRIES") or os.getenv(
            "PUMPFUN_WS_MAX_RETRIES", "5"
        )
        self._max_stream_consecutive_failures = int(stream_retries_env or "5")

        self._exit_retry_queue: dict[str, dict[str, Any]] = {}
        self.max_exit_retries = int(os.getenv("PUMPFUN_MAX_EXIT_RETRIES", "5"))
        self.base_exit_slippage_bps = int(
            os.getenv("PUMPFUN_BASE_EXIT_SLIPPAGE_BPS", "500")
        )
        self.max_exit_slippage_bps = int(
            os.getenv("PUMPFUN_MAX_EXIT_SLIPPAGE_BPS", "5000")
        )

        # RPC Pooling & Failover (FEAT-08)
        self.rpc_pool: RpcConnectionPool | None = None
        endpoints_list = list(self.config.rpc_endpoints)
        if not endpoints_list:
            env_urls = os.getenv("PUMPFUN_RPC_URLS") or os.getenv("SOLANA_RPC_URLS")
            if env_urls:
                endpoints_list = [u.strip() for u in env_urls.split(",") if u.strip()]
        if not endpoints_list and self.rpc_url:
            endpoints_list = [self.rpc_url]

        if self.config.enable_rpc_pool and len(endpoints_list) > 0:
            pool_cfg = RpcPoolConfig(
                endpoints=tuple(endpoints_list),
                health_check_interval_seconds=self.config.rpc_pool_health_check_interval_seconds,
                circuit_breaker_threshold=self.config.rpc_pool_circuit_breaker_threshold,
                circuit_breaker_cooldown_seconds=self.config.rpc_pool_circuit_breaker_cooldown_seconds,
                broadcast_concurrency=self.config.rpc_pool_broadcast_concurrency,
            )
            self.rpc_pool = RpcConnectionPool(
                endpoints=tuple(endpoints_list), config=pool_cfg
            )

        # In interactive terminal mode (verbose=True and not headless), Rich's Live dashboard
        # manages the alternate screen buffer. Direct StreamHandler writes to stderr/stdout
        # bypass Rich and trigger cursor repositioning / viewport jumping (BUG-29).
        # We suppress raw console StreamHandler writes during interactive Live UI rendering,
        # enabling console logging only in headless mode or when verbose logging is disabled.
        enable_console_logging = bool(self.headless or not self.verbose)
        log_max_bytes = get_env_int("PUMPFUN_LOG_MAX_BYTES", self.config.log_max_bytes)
        log_backup_count = get_env_int(
            "PUMPFUN_LOG_BACKUP_COUNT", self.config.log_backup_count
        )
        log_rotation_type = os.getenv(
            "PUMPFUN_LOG_ROTATION_TYPE", self.config.log_rotation_type
        )
        log_compress = get_env_bool("PUMPFUN_LOG_COMPRESS", self.config.log_compress)
        effective_log_file = resolve_bot_log_path(log_file, self.config.log_file)

        self.logger = setup_structured_logging(
            logger_name="pumpfun_trading.bot",
            log_file=effective_log_file,
            console=enable_console_logging,
            max_bytes=log_max_bytes,
            backup_count=log_backup_count,
            rotation_type=log_rotation_type,
            compress=log_compress,
        )

        self._metrics = {
            "buys": 0,
            "sells": 0,
            "failures": 0,
            "retries": 0,
            "connection_loss": 0,
            "stale_data": 0,
            "risk_kills": 0,
            "circuit_breaker_trips": 0,
            "latency_ms": {
                "samples": 0,
                "avg_ms": 0.0,
                "last_ms": 0.0,
                "max_ms": 0.0,
                "total_ms": 0.0,
            },
        }

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

        # Primary env names with documented aliases (BUG-87).
        self.bot_status_path = (
            bot_status_path
            or os.getenv("PUMPFUN_STATUS_PATH")
            or os.getenv("PUMPFUN_BOT_STATUS_PATH")
        )
        self.audit_log_path = (
            audit_log_path
            or os.getenv("PUMPFUN_AUDIT_LOG_PATH")
            or os.getenv("PUMPFUN_AUDIT_LOG")
        )
        audit_max_bytes = get_env_int(
            "PUMPFUN_AUDIT_MAX_BYTES", self.config.audit_max_bytes
        )
        audit_backup_count = get_env_int(
            "PUMPFUN_AUDIT_BACKUP_COUNT", self.config.audit_backup_count
        )
        audit_retention_days = get_env_int(
            "PUMPFUN_AUDIT_RETENTION_DAYS", self.config.audit_retention_days
        )
        audit_compress = get_env_bool(
            "PUMPFUN_AUDIT_COMPRESS", self.config.audit_compress
        )
        self.audit_policy = RetentionPolicy(
            max_bytes=audit_max_bytes,
            max_files=audit_backup_count,
            max_age_days=audit_retention_days,
            compress_archives=audit_compress,
        )
        self.persistence = StatusPersistenceManager(
            bot_status_path=self.bot_status_path,
            audit_log_path=self.audit_log_path,
            policy=self.audit_policy,
        )

        # Diagnostic Telemetry Event Logger (FEAT-30)
        event_log_path_env = os.getenv("PUMPFUN_EVENT_LOG_PATH")
        effective_event_log_path = (
            event_log_path_env
            if event_log_path_env
            else getattr(self.config, "event_log_path", "events.jsonl")
            or "events.jsonl"
        )
        subsystems_env = os.getenv("PUMPFUN_EVENT_SUBSYSTEMS")
        effective_subsystems = (
            tuple(p.strip() for p in subsystems_env.split(",") if p.strip())
            if subsystems_env
            else getattr(self.config, "event_log_subsystems", None)
        )
        enable_events_env = os.getenv("PUMPFUN_ENABLE_DIAGNOSTIC_EVENTS")
        effective_enable_events = (
            enable_events_env.lower() in {"1", "true", "yes"}
            if enable_events_env is not None
            else getattr(self.config, "enable_diagnostic_events", True)
        )
        self.event_logger = DiagnosticEventLogger(
            output_path=effective_event_log_path,
            enabled_categories=effective_subsystems,
            enabled=effective_enable_events,
        )
        self._audit_handle = self.persistence._audit_handle

        resolved_replay_path = (
            replay_log_path
            or getattr(self.config, "replay_log_path", None)
            or os.getenv("PUMPFUN_REPLAY_LOG_PATH")
        )
        if not resolved_replay_path:
            rec_env = os.getenv("PUMPFUN_RECORD_REPLAY")
            if rec_env and rec_env.lower() not in {"false", "0", "no"}:
                resolved_replay_path = (
                    rec_env
                    if rec_env.lower() not in {"true", "1", "yes"}
                    else "market_replay.jsonl"
                )
        self.replay_log_path = (
            Path(resolved_replay_path) if resolved_replay_path else None
        )
        replay_max_bytes = get_env_int(
            "PUMPFUN_REPLAY_MAX_BYTES", self.config.replay_max_bytes
        )
        replay_backup_count = get_env_int(
            "PUMPFUN_REPLAY_BACKUP_COUNT", self.config.replay_backup_count
        )
        replay_retention_days = get_env_int(
            "PUMPFUN_REPLAY_RETENTION_DAYS", self.config.replay_retention_days
        )
        replay_compress = get_env_bool(
            "PUMPFUN_REPLAY_COMPRESS", self.config.replay_compress
        )
        self.replay_policy = RetentionPolicy(
            max_bytes=replay_max_bytes,
            max_files=replay_backup_count,
            max_age_days=replay_retention_days,
            compress_archives=replay_compress,
        )
        self.replay_recorder = (
            ReplayRecorder(output_path=self.replay_log_path, policy=self.replay_policy)
            if self.replay_log_path
            else None
        )

        # Retention managers and background pruning
        self._last_retention_check = time.monotonic()
        self.retention_check_interval_seconds = float(
            os.getenv(
                "PUMPFUN_RETENTION_CHECK_INTERVAL_SECONDS",
                str(getattr(self.config, "retention_check_interval_seconds", 3600.0)),
            )
        )
        managed_dirs: set[Path] = set()
        for p in (
            effective_log_file,
            self.audit_log_path,
            effective_event_log_path,
            self.replay_log_path,
        ):
            if p:
                p_path = Path(p)
                parent = p_path.parent if str(p_path.parent) != "" else Path(".")
                managed_dirs.add(parent)
        self.retention_managers = [
            LogRetentionManager(
                target_directory=d,
                policy=self.audit_policy,
                file_patterns=("*.log*", "*.jsonl*"),
            )
            for d in managed_dirs
        ]

        self.api = PumpFunApiClient(base_url=self.api_base_url)

        jito_block_engine = os.getenv(
            "PUMPFUN_JITO_BLOCK_ENGINE_URL",
            "https://mainnet.block-engine.jito.wtf",
        )
        use_jito = os.getenv("PUMPFUN_USE_JITO", "true").lower() not in {
            "false",
            "0",
            "no",
        }
        self.use_jito = use_jito
        jito_tip_lamports = int(os.getenv("PUMPFUN_JITO_TIP_LAMPORTS", "100000"))

        self.execution = build_execution_client(
            self.private_key_b58,
            rpc_url=self.rpc_url,
            rpc_pool=self.rpc_pool,
            rpc_urls=endpoints_list if endpoints_list else None,
            default_slippage_bps=int(
                os.getenv(
                    "PUMPFUN_SLIPPAGE_BPS",
                    str(getattr(self.config, "raydium_slippage_bps", 250)),
                )
            ),
            compute_unit_limit=int(os.getenv("PUMPFUN_COMPUTE_UNIT_LIMIT", "200000")),
            jito_tip_lamports=jito_tip_lamports,
            jito_block_engine_url=jito_block_engine,
            use_jito=use_jito,
            jito_fallback_to_rpc=os.getenv(
                "PUMPFUN_JITO_FALLBACK_TO_RPC", "true"
            ).lower()
            not in {"false", "0", "no"},
            jito_confirmation_timeout=float(
                os.getenv("PUMPFUN_JITO_CONFIRMATION_TIMEOUT", "12.0")
            ),
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
            for k in [
                "buys",
                "sells",
                "failures",
                "retries",
                "connection_loss",
                "stale_data",
                "risk_kills",
                "circuit_breaker_trips",
            ]:
                if k in metrics and isinstance(metrics[k], (int, float)):
                    self._metrics[k] = int(metrics[k])
            if "latency_ms" in metrics and isinstance(metrics["latency_ms"], dict):
                self._metrics["latency_ms"] = dict(metrics["latency_ms"])

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
    ) -> None:
        trade_id = trade_id or self._next_trade_id()
        position_id = position_id or trade_id
        pos_info = self.active_positions.get(mint, {})
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
            "strategy": getattr(self.config, "strategy_preset", None),
        }
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
        lat = self._metrics.get("latency_ms")
        if not isinstance(lat, dict):
            lat = {
                "samples": 0,
                "avg_ms": 0.0,
                "last_ms": 0.0,
                "max_ms": 0.0,
                "total_ms": 0.0,
            }
            self._metrics["latency_ms"] = lat
        lat["samples"] = int(lat.get("samples", 0)) + 1
        lat["total_ms"] = float(lat.get("total_ms", 0.0)) + float(latency_ms)
        lat["last_ms"] = float(latency_ms)
        lat["max_ms"] = max(float(lat.get("max_ms", 0.0)), float(latency_ms))
        lat["avg_ms"] = float(lat["total_ms"]) / int(lat["samples"])

    def _record_metric(self, name: str, value: float | int = 1) -> None:
        if name in {"latency_ms", "last_latency_ms"}:
            self._record_latency_ms(float(value))
            return

        current_val = self._metrics.get(name)
        if isinstance(current_val, (int, float)):
            self._metrics[name] = int(current_val + value)
        else:
            self._metrics[name] = int(value)

    def _metrics_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self._metrics)
        if "latency_ms" in self._metrics and isinstance(
            self._metrics["latency_ms"], dict
        ):
            snapshot["latency_ms"] = dict(self._metrics["latency_ms"])
        return snapshot

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
            open_val_sol = self.position_manager.calculate_total_open_value()
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
            return balance >= self.min_balance_sol
        except Exception:
            return False

    async def _check_and_enforce_circuit_breaker(self) -> bool:
        """Evaluates daily drawdown baseline and engages circuit breaker if breached."""
        try:
            if not self.dry_run:
                balance_sol = await self.execution.get_balance_sol()
                self.wallet_balance_sol = balance_sol
            open_val_sol = self.position_manager.calculate_total_open_value()
            self.daily_equity_tracker.update_valuation(
                self.wallet_balance_sol, open_val_sol
            )
        except Exception as exc:
            self._log(
                f"Valuation check error during circuit breaker check: {exc}",
                level=logging.DEBUG,
            )

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
        open_val = self.position_manager.calculate_total_open_value()
        drawdown = self.daily_equity_tracker.calculate_drawdown(
            self.wallet_balance_sol, open_val
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
        return self._buy_attempts.get(mint, 0) < self.max_buy_attempts_per_mint

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
    ) -> bool:
        with self._track_operation("buy"):
            return await self._buy_token_impl(
                mint,
                market_cap_sol,
                token_name=token_name,
                screening_verdict=screening_verdict,
                reason=reason,
                buy_amount_sol=buy_amount_sol,
            )

    async def _buy_token_impl(
        self,
        mint: str,
        market_cap_sol: float,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = None,
        buy_amount_sol: float | None = None,
    ) -> bool:
        effective_buy_amount = (
            buy_amount_sol if buy_amount_sol is not None else self.buy_amount_sol
        )
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

        t_exec_start = time.perf_counter()
        exec_res = await self.executor.execute_buy(
            mint=mint,
            amount_sol=effective_buy_amount,
            reason=reason or "entry",
            token_name=position_name,
            dry_run=self.dry_run,
        )
        exec_latency_ms = (time.perf_counter() - t_exec_start) * 1000.0

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
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING,
                reason=f"buy_failed {mint} ({exec_res.error})",
            )
            return False

        exec_metadata = getattr(exec_res, "metadata", None)
        curve_entry_mc = (
            exec_metadata.get("entry_market_cap_sol")
            if isinstance(exec_metadata, dict)
            else None
        )
        if isinstance(curve_entry_mc, (int, float)) and curve_entry_mc > 0:
            # Paper fills are priced from the curve exits read, not the stream
            # create event (BUG-104).
            market_cap_sol = float(curve_entry_mc)

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
            entry_market_cap=float(market_cap_sol or 30.0),
            name=position_name,
            buy_signature=exec_res.signature,
            reason=reason or "entry",
            dry_run=self.dry_run,
            metadata={"position_id": position_id, "trade_id": trade_id},
        )
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
                    "market_cap_sol": float(market_cap_sol or 30.0),
                    "is_buy": True,
                    "sol_amount": float(effective_buy_amount),
                    "token_amount": int(exec_res.token_amount or 0),
                    "signal": "buy",
                    "reason": reason or "entry",
                }
            )
        self._transition_to(TradingBotState.HOLDING, reason=f"buy_confirmed {mint}")
        return True

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
        self.position_manager.record_buy(
            mint=mint,
            token_amount=exec_res.token_amount or (100_000_000 if self.dry_run else 0),
            cost_sol=buy_amount,
            entry_market_cap=69.0,
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
                    if websocket:
                        await self._unsubscribe_from_token_trades(websocket, mint)

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
        async with self._mint_lock(mint):
            with self._track_operation("sell"):
                return await self._sell_token_locked(
                    mint,
                    sell_amount_tokens=sell_amount_tokens,
                    sell_fraction=sell_fraction,
                    reason=reason,
                    target_tier=target_tier,
                    slippage_bps=slippage_bps,
                    retry_count=retry_count,
                )

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
        if pool_keys is None and mint in self._migrating_mints:
            # The curve is complete; hold until the AMM pool is known (BUG-44).
            self._last_event = f"awaiting pool {mint[:8]}"
            return False

        self._transition_to(
            TradingBotState.SELLING, reason=f"selling {mint} ({reason})"
        )

        initial_tokens = int(
            position.get("initial_token_amount")
            or position.get("token_amount")
            or (100_000_000 if self.dry_run else 0)
        )
        rem_tokens = int(
            position.get("remaining_token_amount")
            or position.get("token_amount")
            or initial_tokens
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

        if sell_amount_tokens is not None and sell_amount_tokens > 0:
            tokens_to_sell = min(sell_amount_tokens, rem_tokens)
        elif sell_fraction < 1.0:
            tokens_to_sell = int((initial_tokens or rem_tokens) * sell_fraction)
            tokens_to_sell = max(1, min(tokens_to_sell, rem_tokens))
        else:
            tokens_to_sell = rem_tokens

        rem_after = rem_tokens - tokens_to_sell
        is_partial = (tokens_to_sell < rem_tokens) and (
            rem_after > self.min_sell_balance
        )
        if not is_partial:
            tokens_to_sell = rem_tokens

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

        # `buy_price` is a per-token unit price, never the position cost (BUG-45).
        pos_entry = float(
            position.get("cost_sol")
            or position.get("entry_sol")
            or getattr(self.config, "buy_amount_sol", 0.0)
            or 0.0
        )
        entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(position.get("current_market_cap", 0.0) or entry_mc or 0.0)
        cost_sol = float(
            position.get("cost_sol")
            or position.get("entry_sol")
            or getattr(self.config, "buy_amount_sol", 0.0)
            or pos_entry
            or 0.0
        )
        frac = float(tokens_to_sell) / float(
            initial_tokens or rem_tokens or tokens_to_sell
        )
        frac = max(0.0, min(1.0, frac))

        if self.dry_run:
            # Pump.fun charges its fee on the buy and on the sell; live swap
            # amounts include it, so paper proceeds must too (FEAT-49).
            fee_factor = self._paper_round_trip_fee_factor()
            if entry_mc > 0 and curr_mc > 0 and cost_sol > 0:
                sell_p = (cost_sol * frac) * (curr_mc / entry_mc) * fee_factor
            elif cost_sol > 0:
                sell_p = cost_sol * frac * fee_factor
            else:
                sell_p = float(getattr(exec_res, "amount_sol", 0.0) or 0.0)
        else:
            sell_p = float(
                getattr(exec_res, "amount_sol", 0.0)
                or getattr(exec_res, "sol_amount", 0.0)
                or (
                    float(getattr(exec_res, "min_sol_lamports", 0)) / 1e9
                    if getattr(exec_res, "min_sol_lamports", 0) > 0
                    else 0.0
                )
                or 0.0
            )
            if sell_p <= 0.0:
                if entry_mc > 0 and curr_mc > 0 and cost_sol > 0:
                    sell_p = (cost_sol * frac) * (curr_mc / entry_mc)
                elif cost_sol > 0:
                    sell_p = cost_sol * frac

        is_fully_closed, remaining = self.position_manager.record_sell(
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

        pos_id = (
            position.get("position_id")
            or position.get("id")
            or position.get("trade_id")
        )

        if is_partial:
            frac = float(tokens_to_sell) / float(
                initial_tokens or rem_tokens or tokens_to_sell
            )
            frac = max(0.0, min(1.0, frac))
            partial_entry = pos_entry * frac if pos_entry > 0 else pos_entry
            trade_pnl = sell_p - partial_entry
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
                            "is_partial": True,
                            "realized_daily_pnl_sol": self.daily_equity_tracker.realized_daily_pnl_sol,
                            "effective_baseline_sol": self.daily_equity_tracker.effective_baseline_sol,
                        },
                    )
            self._record_trade(
                position_id=pos_id,
                mint=mint,
                action="partial_sell",
                token_name=pos_name,
                mint_name=pos_name,
                entry=partial_entry,
                exit_value=sell_p,
                buy_price=pos_entry,
                sell_price=sell_p,
                reason=reason,
                signature=exec_res.signature,
                costs=sell_costs,
            )
            if self.replay_recorder is not None:
                curr_mc = float(
                    position.get("current_market_cap", 0.0)
                    or position.get("entry_market_cap", 0.0)
                    or 0.0
                )
                price = curr_mc / 1_000_000_000.0 if curr_mc > 0 else 0.0
                self.replay_recorder.record_snapshot(
                    {
                        "timestamp": time.time(),
                        "mint": mint,
                        "name": pos_name,
                        "price": price,
                        "market_cap_sol": curr_mc,
                        "is_buy": False,
                        "sol_amount": float(sell_p),
                        "token_amount": int(tokens_to_sell),
                        "signal": "sell",
                        "reason": reason or "partial_exit",
                    }
                )
            self._transition_to(
                TradingBotState.HOLDING, reason=f"partial_sell_complete {mint}"
            )
            return True

        self._exit_retry_queue.pop(mint, None)
        frac = float(tokens_to_sell) / float(
            initial_tokens or rem_tokens or tokens_to_sell
        )
        frac = max(0.0, min(1.0, frac))
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
                        "is_partial": False,
                        "realized_daily_pnl_sol": self.daily_equity_tracker.realized_daily_pnl_sol,
                        "effective_baseline_sol": self.daily_equity_tracker.effective_baseline_sol,
                    },
                )
        self._record_trade(
            position_id=pos_id,
            mint=mint,
            action="sell",
            token_name=pos_name,
            mint_name=pos_name,
            entry=effective_entry,
            exit_value=sell_p,
            buy_price=pos_entry,
            sell_price=sell_p,
            reason=reason,
            signature=exec_res.signature,
            costs=sell_costs,
        )
        if self.replay_recorder is not None:
            curr_mc = float(
                position.get("current_market_cap", 0.0)
                or position.get("entry_market_cap", 0.0)
                or 0.0
            )
            price = curr_mc / 1_000_000_000.0 if curr_mc > 0 else 0.0
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": time.time(),
                    "mint": mint,
                    "name": pos_name,
                    "price": price,
                    "market_cap_sol": curr_mc,
                    "is_buy": False,
                    "sol_amount": float(sell_p),
                    "token_amount": int(tokens_to_sell),
                    "signal": "sell",
                    "reason": reason or "exit",
                }
            )
        self._transition_to(TradingBotState.MONITORING, reason=f"sell_complete {mint}")
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
            if sold and websocket:
                await self._unsubscribe_from_token_trades(websocket, mint)
            return sold

        return False

    async def _handle_bonding_curve_state_update(
        self, update: BondingCurveStateUpdate
    ) -> None:
        if self._stop_requested:
            return

        self._last_message_at = time.monotonic()
        self._last_status = "processing geyser stream"
        latency_ms = max(0.0, (time.time() - update.timestamp) * 1000.0)
        self._record_metric("latency_ms", latency_ms)

        mint = update.mint
        self._observed_tokens_count += 1
        self._last_new_token = mint
        self._last_new_token_name = f"{mint[:8]}..."
        current_market_cap = update.market_cap_sol

        real_sol = update.real_sol_reserves / 1_000_000_000.0
        virt_sol = update.virtual_sol_reserves / 1_000_000_000.0
        self.graduation_engine.update_bonding_curve(
            mint=mint,
            bonding_curve=update.bonding_curve_pubkey,
            real_sol_reserves=real_sol,
            virtual_sol_reserves=virt_sol,
            market_cap_sol=current_market_cap,
            complete=update.complete,
            timestamp=update.timestamp,
        )

        if self.config.enable_cross_venue_arbitrage:
            await self._evaluate_and_execute_arbitrage(
                mint=mint,
                virtual_sol=update.virtual_sol_reserves,
                virtual_token=update.virtual_token_reserves,
            )

        if self.replay_recorder is not None:
            price = (
                current_market_cap / 1_000_000_000.0 if current_market_cap > 0 else 0.0
            )
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": update.timestamp,
                    "mint": mint,
                    "name": self.active_positions.get(mint, {}).get("name")
                    or f"{mint[:8]}...",
                    "price": price,
                    "market_cap_sol": current_market_cap,
                    "volume": real_sol,
                }
            )

        if mint in self.active_positions:
            await self._evaluate_and_execute_exit(mint, current_market_cap)
            await self._check_and_enforce_circuit_breaker()
            return

        if not update.complete and current_market_cap > 0:
            if (
                self.daily_equity_tracker.circuit_breaker_engaged
                or await self._check_and_enforce_circuit_breaker()
            ):
                self._last_event = "circuit_breaker_active"
                return

            # Pre-graduation acceleration harvesting evaluation (FEAT-25)
            if (
                self.config.enable_pre_graduation_harvesting
                and mint not in self.active_positions
                and not self._is_recently_seen(mint)
            ):
                min_p = (
                    self.config.pre_graduation_entry_progress_pct * 100.0
                    if self.config.pre_graduation_entry_progress_pct <= 1.0
                    else self.config.pre_graduation_entry_progress_pct
                )
                max_p = (
                    self.config.pre_graduation_max_entry_progress_pct * 100.0
                    if self.config.pre_graduation_max_entry_progress_pct <= 1.0
                    else self.config.pre_graduation_max_entry_progress_pct
                )
                grad_sig = (
                    self.graduation_engine.evaluate_pre_graduation_harvesting_entry(
                        mint=mint,
                        min_progress_pct=min_p,
                        max_progress_pct=max_p,
                        min_acceleration=self.config.pre_graduation_min_acceleration,
                        current_time=update.timestamp,
                    )
                )
                if grad_sig.triggered:
                    async with self._trade_lock:
                        if mint in self.active_positions or self._is_recently_seen(
                            mint
                        ):
                            return
                        screening_verdict = await self._enrich_and_screen_token(mint)
                        if not screening_verdict.passed:
                            return
                        if not self._should_buy(
                            mint,
                            current_market_cap,
                            screening_verdict=screening_verdict,
                        ):
                            if getattr(self.config, "enable_capital_rotation", True):
                                await self._evaluate_and_trigger_displacement(
                                    candidate_mint=mint,
                                    market_cap_sol=current_market_cap,
                                    conviction_percentile=0.98,
                                    screening_verdict=screening_verdict,
                                )
                            return
                        self._log(
                            f"Pre-graduation harvesting entry triggered for {mint}: {grad_sig.reason}"
                        )
                        self._last_event = f"pre-grad entry {mint[:8]}"
                        bought = await self._buy_token(
                            mint,
                            current_market_cap,
                            None,
                            screening_verdict=screening_verdict,
                            reason="pre_graduation_harvesting_entry",
                        )
                        if bought:
                            self._record_event(f"bought pre-graduation {mint[:8]}")
                            return

            async with self._trade_lock:
                if self._is_recently_seen(mint):
                    return

                screening_verdict = await self._enrich_and_screen_token(mint)
                if not screening_verdict.passed:
                    self._log(
                        f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                    )
                    reasons_str = (
                        "; ".join(screening_verdict.reasons)
                        if screening_verdict.reasons
                        else "anti-rug"
                    )
                    self._record_event(
                        f"screen_rejected {mint[:8]}: {reasons_str}",
                        alert=False,
                    )
                    return

                if not self._should_buy(
                    mint, current_market_cap, screening_verdict=screening_verdict
                ):
                    self._log(f"Skipping new token {mint}: not eligible for buy")
                    self._last_event = f"skipped {mint}"
                    return

                self._log(
                    f"New token detected via Geyser: {mint} | launch market cap: {current_market_cap:.2f} SOL"
                )
                self._last_event = f"new token {mint}"
                self._last_new_token = mint
                self._last_new_token_name = mint[:8]
                bought = await self._buy_token(
                    mint,
                    current_market_cap,
                    None,
                    screening_verdict=screening_verdict,
                )

            if bought:
                self._record_event(
                    f"bought {self.active_positions.get(mint, {}).get('name', mint)}"
                )

    async def _handle_trade_event_update(self, update: TradeEventUpdate) -> None:
        if self._stop_requested:
            return

        self._last_message_at = time.monotonic()
        latency_ms = max(0.0, (time.time() - update.received_at) * 1000.0)
        self._record_metric("latency_ms", latency_ms)

        mint = update.mint
        self._observed_tokens_count += 1
        ts = float(update.timestamp if update.timestamp > 0 else update.received_at)
        self.order_flow_engine.record_trade(
            mint=mint,
            is_buy=update.is_buy,
            sol_amount=update.sol_amount,
            user=update.user,
            timestamp=ts,
        )

        if self.config.enable_cross_venue_arbitrage and update.virtual_sol_reserves > 0:
            await self._evaluate_and_execute_arbitrage(
                mint=mint,
                virtual_sol=update.virtual_sol_reserves,
                virtual_token=update.virtual_token_reserves,
                trade_sol=update.sol_amount,
                is_buy=update.is_buy,
            )

        if update.virtual_token_reserves > 0:
            current_market_cap = (update.virtual_sol_reserves / 1_000_000_000.0) * (
                1_000_000_000.0 / (update.virtual_token_reserves / 1_000_000.0)
            )
        else:
            current_market_cap = 0.0

        if self.replay_recorder is not None:
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": ts,
                    "mint": mint,
                    "name": self.active_positions.get(mint, {}).get("name")
                    or f"{mint[:8]}...",
                    "price": (
                        current_market_cap / 1_000_000_000.0
                        if current_market_cap > 0
                        else 0.0
                    ),
                    "market_cap_sol": current_market_cap,
                    "is_buy": update.is_buy,
                    "sol_amount": update.sol_amount,
                    "token_amount": float(update.token_amount),
                    "user": update.user,
                    "signal": "buy" if update.is_buy else "sell",
                }
            )

        if mint in self.active_positions:
            if current_market_cap <= 0:
                return

            if (
                not update.is_buy
                and self.config.enable_copy_trading
                and self.config.copy_trading_mirror_sells
                and self.copy_trade_engine.is_tracked_wallet(update.user)
            ):
                wallet_obj = self.copy_trade_engine.registry.get_wallet(update.user)
                wallet_label = (
                    wallet_obj.label
                    if wallet_obj and wallet_obj.label
                    else update.user[:8]
                )
                self._log(
                    f"Smart money sell detected on held token {mint} by {wallet_label}... executing mirrored exit."
                )
                self._last_event = f"copy-trade exit {mint[:8]}"
                await self._sell_token(
                    mint, reason=f"copy_trade_mirror_exit_{wallet_label}"
                )
                return

            await self._evaluate_and_execute_exit(mint, current_market_cap)
            await self._check_and_enforce_circuit_breaker()
            return

        if current_market_cap <= 0:
            return

        # Smart Money Copy-Trading Entry Evaluation
        if (
            update.is_buy
            and self.config.enable_copy_trading
            and self.copy_trade_engine.is_tracked_wallet(update.user)
            and mint not in self.active_positions
            and not self._is_recently_seen(mint)
        ):
            signal = self.copy_trade_engine.record_and_evaluate(
                user=update.user,
                mint=mint,
                sol_amount=update.sol_amount,
                is_buy=True,
                timestamp=ts,
            )
            if signal.triggered and signal.is_buy and signal.computed_copy_size_sol > 0:
                async with self._trade_lock:
                    if mint in self.active_positions or self._is_recently_seen(mint):
                        return

                    wallet_obj = self.copy_trade_engine.registry.get_wallet(update.user)
                    wallet_label = (
                        wallet_obj.label
                        if wallet_obj and wallet_obj.label
                        else update.user[:8]
                    )
                    reason_label = f"copy_trade_{wallet_label}"

                    screening_verdict = None
                    if self.config.copy_trading_require_anti_rug_screen:
                        screening_verdict = await self._enrich_and_screen_token(mint)
                        if not screening_verdict.passed:
                            self._log(
                                f"Copy-trade buy rejected for {mint} by {wallet_label}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                            )
                            return

                    if not self._should_buy(
                        mint,
                        current_market_cap,
                        screening_verdict=screening_verdict,
                        proposed_entry_sol=signal.computed_copy_size_sol,
                    ):
                        return

                    self._log(
                        f"Executing copy-trade buy for {mint} mirroring wallet {wallet_label} ({signal.reason}) with {signal.computed_copy_size_sol:.3f} SOL"
                    )
                    self._last_event = f"copy-trade buy {mint[:8]}"
                    bought = await self._buy_token(
                        mint,
                        current_market_cap,
                        None,
                        screening_verdict=screening_verdict,
                        reason=reason_label,
                        buy_amount_sol=signal.computed_copy_size_sol,
                    )
                    if bought:
                        self._record_event(f"bought copy-trade {mint[:8]}")
                        return

        # Momentum Spikes Evaluation
        if (
            self.config.enable_momentum_signals
            and mint not in self.active_positions
            and not self._is_recently_seen(mint)
        ):
            mom_signal = self.order_flow_engine.evaluate_momentum_signal(
                mint,
                window_seconds=self.config.momentum_window_seconds,
                min_buy_ratio=self.config.momentum_min_buy_ratio,
                min_z_score=self.config.momentum_min_z_score,
                min_unique_buyers=self.config.momentum_min_unique_buyers,
                min_net_inflow_sol=self.config.momentum_min_net_inflow_sol,
                baseline_window_seconds=self.config.momentum_baseline_window_seconds,
                max_token_age_seconds=self.config.momentum_max_token_age_seconds,
            )

            if mom_signal.triggered:
                async with self._trade_lock:
                    if mint in self.active_positions or self._is_recently_seen(mint):
                        return

                    screening_verdict = await self._enrich_and_screen_token(mint)
                    if not screening_verdict.passed:
                        self._log(
                            f"Momentum buy skipped for {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                        )
                        self._last_event = f"screen_rejected {mint[:8]}"
                        return

                    if not self._should_buy(
                        mint, current_market_cap, screening_verdict=screening_verdict
                    ):
                        if getattr(self.config, "enable_capital_rotation", True):
                            displaced = await self._evaluate_and_trigger_displacement(
                                candidate_mint=mint,
                                market_cap_sol=current_market_cap,
                                candidate_signal=mom_signal,
                                conviction_percentile=0.95,
                                screening_verdict=screening_verdict,
                            )
                            if displaced:
                                self._record_event(f"displaced for momentum {mint[:8]}")
                        return

                    self._log(
                        f"Momentum breakout detected for {mint}: {mom_signal.reason} (Z={mom_signal.z_score:.2f}, BuyRatio={mom_signal.buy_sell_ratio:.1f}x, Inflow={mom_signal.net_sol_inflow:.2f} SOL)"
                    )
                    self._last_event = f"momentum breakout {mint[:8]}"
                    bought = await self._buy_token(
                        mint,
                        current_market_cap,
                        None,
                        screening_verdict=screening_verdict,
                        reason="momentum_spike",
                    )
                    if bought:
                        self._record_event(f"bought momentum {mint[:8]}")

    async def _handle_complete_event_update(self, update: CompleteEventUpdate) -> None:
        if self._stop_requested:
            return

        mint = update.mint
        curve_key = getattr(update, "bonding_curve", None) or getattr(
            update, "bonding_curve_pubkey", ""
        )
        self._log(
            f"Bonding curve completed / graduated for {mint}! Bonding curve: {curve_key}"
        )
        self._last_event = f"graduated {mint[:8]}"
        self.graduation_engine.record_graduation(
            mint=mint,
            bonding_curve=str(curve_key),
            timestamp=update.timestamp,
        )

        if mint in self.active_positions:
            # A completed curve rejects trades: exit on the AMM instead (BUG-44).
            self._migrating_mints.add(mint)
            self._exit_retry_queue.pop(mint, None)
            candidate = self.graduation_engine.get_candidate(mint)
            pool = getattr(candidate, "pool_keys", None) if candidate else None
            if isinstance(pool, RaydiumPoolKeys):
                self._raydium_exit_pools[mint] = pool
                await self._sell_token(mint, reason="bonding_curve_graduated")
            else:
                self._log(
                    f"Position held for graduating token {mint}; waiting for the AMM pool to exit."
                )

    async def _handle_raydium_pool_update(self, pool_keys: RaydiumPoolKeys) -> None:
        """Handle Raydium AMM pool creation and dispatch graduation breakout buys."""
        if self._stop_requested:
            return

        mint = pool_keys.coin_mint
        self._log(f"Raydium AMM pool initialized for {mint}: amm_id={pool_keys.amm_id}")
        self._last_event = f"raydium pool {mint[:8]}"
        self.graduation_engine.record_raydium_pool(mint=mint, pool_keys=pool_keys)

        if mint in self.active_positions:
            # Attach the pool to the held position and exit through the AMM (BUG-44).
            self._raydium_exit_pools[mint] = pool_keys
            if mint in self._migrating_mints:
                await self._sell_token(mint, reason="bonding_curve_graduated")
            return

        if not self.config.enable_raydium_migration_sniping:
            return

        signal = self.graduation_engine.evaluate_graduation_signal(
            mint=mint,
        )

        if signal.triggered and signal.stage == "raydium_pool_ready":
            async with self._trade_lock:
                if mint in self.active_positions or self._is_recently_seen(mint):
                    return

                screening_verdict = await self._enrich_and_screen_token(mint)
                if not screening_verdict.passed:
                    self._log(
                        f"Raydium migration snipe skipped for {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                    )
                    self._last_event = f"screen_rejected {mint[:8]}"
                    return

                buy_amount = self.config.raydium_buy_amount_sol
                if not self._should_buy(
                    mint,
                    market_cap_sol=69.0,
                    screening_verdict=screening_verdict,
                    proposed_entry_sol=buy_amount,
                ):
                    return

                self._log(
                    f"Executing Raydium graduation snipe for {mint} with {buy_amount:.3f} SOL"
                )
                self._last_event = f"sniping raydium {mint[:8]}"
                bought = await self._buy_raydium_token(
                    mint,
                    pool_keys=pool_keys,
                    screening_verdict=screening_verdict,
                    reason="raydium_graduation_snipe",
                )
                if bought:
                    self._record_event(f"bought raydium {mint[:8]}")

        # Check for immediate cross-venue arbitrage on newly listed Raydium pool
        if self.config.enable_cross_venue_arbitrage:
            cand = self.graduation_engine.get_candidate(mint)
            if cand:
                virt_sol = int(round((cand.real_sol_reserves + 30.0) * 1_000_000_000))
                virt_tok = int(200_000_000_000_000)
                await self._evaluate_and_execute_arbitrage(
                    mint=mint,
                    virtual_sol=virt_sol,
                    virtual_token=virt_tok,
                )

    async def _arbitrage_costs(
        self, opp: ArbitrageOpportunity, signature: str | None
    ) -> TransactionCosts:
        """Fee, priority fee and tip of a landed arbitrage bundle (BUG-99)."""
        getter = getattr(self.execution, "get_transaction_costs", None)
        if signature and not (self.dry_run or self.paper_trade) and callable(getter):
            try:
                costs = await asyncio.wait_for(
                    getter(signature, opp.mint, is_buy=True),
                    timeout=ARBITRAGE_COST_LOOKUP_TIMEOUT_SECONDS,
                )
                if isinstance(costs, TransactionCosts):
                    return costs
            except Exception as exc:
                self._log(
                    f"[ARBITRAGE] could not read costs of {signature}: {exc}; "
                    "booking modelled costs",
                    level=logging.WARNING,
                )
        gas_lamports = int(round(float(opp.estimated_fees_sol) * LAMPORTS_PER_SOL))
        return model_transaction_costs(
            priority_fee_lamports=max(
                0, gas_lamports - BASE_FEE_LAMPORTS_PER_SIGNATURE
            ),
            tip_lamports=int(
                round(float(opp.estimated_jito_tip_sol) * LAMPORTS_PER_SOL)
            ),
            signature=signature,
        )

    async def _evaluate_and_execute_arbitrage(
        self,
        mint: str,
        virtual_sol: int,
        virtual_token: int,
        trade_sol: float = 0.0,
        is_buy: bool = True,
    ) -> None:
        """Evaluate cross-venue disparity and execute atomic Jito arbitrage bundle."""
        if not self.config.enable_cross_venue_arbitrage or self._stop_requested:
            return

        candidate = self.graduation_engine.get_candidate(mint)
        if not candidate or not candidate.pool_keys:
            return

        pool_keys = candidate.pool_keys
        # Derive Raydium pool reserves from candidate real reserves
        ray_sol = int(round((candidate.real_sol_reserves or 80.0) * 1_000_000_000))
        ray_tokens = int(200_000_000_000_000)

        opp: Optional[ArbitrageOpportunity] = None
        if self.config.enable_mempool_backrunning and trade_sol >= 1.0:
            opp = self.backrun_engine.evaluate_whale_transaction(
                mint=mint,
                is_buy=is_buy,
                trade_sol=trade_sol,
                pump_virtual_sol=virtual_sol,
                pump_virtual_token=virtual_token,
                raydium_sol_reserve=ray_sol,
                raydium_token_reserve=ray_tokens,
                raydium_keys=pool_keys,
            )

        if opp is None:
            opp = self.arb_monitor.evaluate_spread(
                mint=mint,
                pump_virtual_sol=virtual_sol,
                pump_virtual_token=virtual_token,
                raydium_sol_reserve=ray_sol,
                raydium_token_reserve=ray_tokens,
                raydium_keys=pool_keys,
            )

        if opp is not None and opp.is_profitable:
            self._log(
                f"[ARBITRAGE] Found {opp.direction} spread {opp.spread_pct * 100:.2f}% on {mint[:8]}! "
                f"Optimal size: {opp.optimal_input_sol:.4f} SOL -> Est Profit: {opp.net_profit_sol:.4f} SOL"
            )
            if hasattr(self, "event_logger") and self.event_logger:
                self.event_logger.emit(
                    category=EventCategory.ARBITRAGE,
                    event_name="arbitrage_opportunity_detected",
                    mint=mint,
                    data=opp.to_dict(),
                )

            if not opp.reserves_verified:
                # Reserves above are placeholders (curve SOL + a constant token
                # lot), so the spread is not real: never execute or bank it, in
                # live or dry-run (BUG-59).
                self._log(
                    f"[ARBITRAGE] {mint[:8]} not executed: reserves are estimates, "
                    "not on-chain reads",
                    level=logging.WARNING,
                )
                return
            res = await self.arb_executor.execute_arbitrage(opp)
            if res.get("success"):
                # Book net of the bundle's network fee, priority fee and Jito tip
                # (BUG-99): read from the landed transaction, modelled otherwise.
                signature = res.get("signature")
                arb_costs = await self._arbitrage_costs(
                    opp, signature if isinstance(signature, str) else None
                )
                gross_profit = float(opp.expected_output_sol) - float(
                    opp.optimal_input_sol
                )
                self._record_trade(
                    mint=mint,
                    action="ARBITRAGE",
                    entry=opp.optimal_input_sol,
                    exit_value=opp.expected_output_sol,
                    entry_price=opp.pump_spot_price,
                    exit_price=opp.raydium_spot_price,
                    reason="cross_venue_arbitrage",
                    signature=signature if isinstance(signature, str) else None,
                    costs=arb_costs,
                )
                if self.dry_run or self.paper_trade:
                    self.wallet_balance_sol += gross_profit
                self._book_trade_costs(
                    gross_profit - arb_costs.total_cost_sol, arb_costs.total_cost_sol
                )
                if hasattr(self, "event_logger") and self.event_logger:
                    self.event_logger.emit(
                        category=EventCategory.ARBITRAGE,
                        event_name="arbitrage_bundle_landed",
                        mint=mint,
                        data=res,
                    )
            else:
                if hasattr(self, "event_logger") and self.event_logger:
                    self.event_logger.emit(
                        category=EventCategory.ARBITRAGE,
                        event_name="arbitrage_bundle_reverted",
                        mint=mint,
                        data=res,
                    )

    async def _handle_new_token_event(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        if self._stop_requested:
            return

        self._last_message_at = time.monotonic()
        mint = data.get("mint")
        if not mint:
            return

        self._observed_tokens_count += 1
        current_market_cap = float(
            data.get("market_cap", 0.0)
            or data.get("marketCapSol", 0.0)
            or data.get("market_cap_sol", 0.0)
            or data.get("marketCap", 0.0)
            or 0.0
        )
        if current_market_cap <= 0.0:
            v_sol = float(
                data.get("vSolInBondingCurve", 0.0)
                or data.get("v_sol_in_bonding_curve", 0.0)
                or data.get("virtual_sol_reserves", 0.0)
                or 0.0
            )
            v_tokens = float(
                data.get("vTokensInBondingCurve", 0.0)
                or data.get("v_tokens_in_bonding_curve", 0.0)
                or data.get("virtual_token_reserves", 0.0)
                or 0.0
            )
            if v_sol > 0 and v_tokens > 0:
                sol_val = v_sol / 1_000_000_000.0 if v_sol > 1_000_000 else v_sol
                token_val = (
                    v_tokens / 1_000_000.0
                    if v_tokens > RAW_TOKEN_UNITS_THRESHOLD
                    else v_tokens
                )
                if token_val > 0:
                    current_market_cap = sol_val * (1_000_000_000.0 / token_val)
        token_name = data.get("name") or mint
        self._last_new_token = mint
        self._last_new_token_name = (
            f"{token_name} ({mint[:6]}...)" if len(mint) > 6 else token_name
        )

        if hasattr(self, "event_logger") and self.event_logger is not None:
            self.event_logger.emit(
                category=EventCategory.STREAM,
                severity=EventSeverity.DEBUG,
                event_name="new_token_event",
                mint=mint,
                mint_name=token_name,
                data={"market_cap_sol": current_market_cap},
            )

        if self.replay_recorder is not None:
            price = (
                current_market_cap / 1_000_000_000.0 if current_market_cap > 0 else 0.0
            )
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": time.time(),
                    "mint": mint,
                    "name": token_name,
                    "price": price,
                    "market_cap_sol": current_market_cap,
                    "is_buy": True,
                    "signal": "buy",
                }
            )

        not_pump = non_pump_launch_reason(
            mint,
            data,
            require_suffix=bool(getattr(self.config, "require_pump_mint_suffix", True)),
        )
        if not_pump is not None:
            # Never screen or buy another launchpad's token (BUG-108).
            key = not_pump.split(",")[0]
            self._non_pump_rejections[key] = self._non_pump_rejections.get(key, 0) + 1
            self._mark_seen(mint)
            self._last_event = f"not_pump_fun {mint[:8]}"
            if hasattr(self, "event_logger") and self.event_logger is not None:
                self.event_logger.emit(
                    category=EventCategory.SCREENING,
                    severity=EventSeverity.DEBUG,
                    event_name="token_rejected_not_pump_fun",
                    mint=mint,
                    mint_name=token_name,
                    data={"reason": not_pump, "pool": data.get("pool")},
                )
            return

        mayhem = (
            mayhem_mode_reason(data)
            if bool(getattr(self.config, "skip_mayhem_mode", True))
            else None
        )
        if mayhem is not None:
            # Mayhem curves drift off the standard reserves; never screen them.
            self._mayhem_rejections = getattr(self, "_mayhem_rejections", 0) + 1
            self._mark_seen(mint)
            self._last_event = f"mayhem_mode {mint[:8]}"
            if hasattr(self, "event_logger") and self.event_logger is not None:
                self.event_logger.emit(
                    category=EventCategory.SCREENING,
                    severity=EventSeverity.DEBUG,
                    event_name="token_rejected_mayhem_mode",
                    mint=mint,
                    mint_name=token_name,
                    data={"reason": mayhem},
                )
            return

        async with self._trade_lock:
            if mint in self.active_positions or self._is_recently_seen(mint):
                return

            if not self._should_buy(mint, current_market_cap):
                return

            screening_verdict = await self._enrich_and_screen_token(
                mint,
                token_data=data,
                token_name=token_name,
                market_cap_sol=current_market_cap,
            )
            if not screening_verdict.passed:
                self._log(
                    f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                )
                reasons_str = (
                    "; ".join(screening_verdict.reasons)
                    if screening_verdict.reasons
                    else "anti-rug"
                )
                self._last_event = f"screen_rejected {mint[:8]}"
                self._record_event(
                    f"screen_rejected {mint[:8]}: {reasons_str}",
                    alert=False,
                )
                return

            bought = await self._buy_token(
                mint,
                current_market_cap,
                token_name=token_name,
                screening_verdict=screening_verdict,
            )
            if bought and websocket:
                await self._subscribe_to_token_trades(websocket, mint)

    async def _handle_trade_update(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        if self._stop_requested:
            return

        self._last_message_at = time.monotonic()
        mint = data.get("mint")
        if not mint:
            return

        self._observed_tokens_count += 1
        token_name = data.get("name")
        if token_name:
            self._last_new_token = mint
            self._last_new_token_name = (
                f"{token_name} ({mint[:6]}...)" if len(mint) > 6 else token_name
            )

        is_buy = bool(
            data.get("is_buy")
            or data.get("type") == "buy"
            or data.get("txType") == "buy"
            or data.get("side") == "buy"
        )
        sol_amount = float(
            data.get("sol_amount", 0.0)
            or data.get("solAmount", 0.0)
            or (float(data.get("sol_amount_lamports", 0)) / 1_000_000_000.0)
            or (float(data.get("solAmountLamports", 0)) / 1_000_000_000.0)
        )
        user = str(
            data.get("user") or data.get("traderPublicKey") or data.get("owner") or ""
        )
        ts = float(data.get("timestamp") or data.get("time") or time.time())
        self.order_flow_engine.record_trade(
            mint=mint,
            is_buy=is_buy,
            sol_amount=sol_amount,
            user=user,
            timestamp=ts,
        )

        current_market_cap = float(
            data.get("market_cap", 0.0)
            or data.get("marketCapSol", 0.0)
            or data.get("market_cap_sol", 0.0)
            or data.get("marketCap", 0.0)
            or 0.0
        )
        if current_market_cap <= 0.0:
            v_sol = float(
                data.get("vSolInBondingCurve", 0.0)
                or data.get("v_sol_in_bonding_curve", 0.0)
                or data.get("virtual_sol_reserves", 0.0)
                or 0.0
            )
            v_tokens = float(
                data.get("vTokensInBondingCurve", 0.0)
                or data.get("v_tokens_in_bonding_curve", 0.0)
                or data.get("virtual_token_reserves", 0.0)
                or 0.0
            )
            if v_sol > 0 and v_tokens > 0:
                sol_val = v_sol / 1_000_000_000.0 if v_sol > 1_000_000 else v_sol
                token_val = (
                    v_tokens / 1_000_000.0
                    if v_tokens > RAW_TOKEN_UNITS_THRESHOLD
                    else v_tokens
                )
                if token_val > 0:
                    current_market_cap = sol_val * (1_000_000_000.0 / token_val)

        if self.replay_recorder is not None:
            self.replay_recorder.record_snapshot(
                {
                    "timestamp": ts,
                    "mint": mint,
                    "name": (
                        token_name
                        or self.active_positions.get(mint, {}).get("name")
                        or f"{mint[:8]}..."
                    ),
                    "price": (
                        current_market_cap / 1_000_000_000.0
                        if current_market_cap > 0
                        else 0.0
                    ),
                    "market_cap_sol": current_market_cap,
                    "is_buy": is_buy,
                    "sol_amount": sol_amount,
                    "token_amount": float(
                        data.get("token_amount", 0.0)
                        or data.get("tokenAmount", 0.0)
                        or 0.0
                    ),
                    "user": user,
                    "signal": "buy" if is_buy else "sell",
                }
            )

        if mint in self.active_positions:
            if not self.dry_run or current_market_cap <= 0.0:
                try:
                    curve = await self.execution.get_bonding_curve_state(mint)
                    if isinstance(curve, dict) and "market_cap_sol" in curve:
                        current_market_cap = float(curve["market_cap_sol"])
                    elif (
                        isinstance(curve, dict)
                        and "virtual_token_reserves" in curve
                        and "virtual_sol_reserves" in curve
                    ):
                        vt = int(curve.get("virtual_token_reserves", 0))
                        vs = int(curve.get("virtual_sol_reserves", 0))
                        if vt > 0 and vs > 0:
                            current_market_cap = (vs / 1_000_000_000.0) * (
                                1_000_000_000.0 / (vt / 1_000_000.0)
                            )
                except Exception:
                    pass

            if (
                not is_buy
                and self.config.enable_copy_trading
                and self.config.copy_trading_mirror_sells
                and self.copy_trade_engine.is_tracked_wallet(user)
            ):
                wallet_obj = self.copy_trade_engine.registry.get_wallet(user)
                wallet_label = (
                    wallet_obj.label if wallet_obj and wallet_obj.label else user[:8]
                )
                self._log(
                    f"Smart money sell detected on held token {mint} by {wallet_label}... executing mirrored exit."
                )
                self._last_event = f"copy-trade exit {mint[:8]}"
                await self._sell_token(
                    mint, reason=f"copy_trade_mirror_exit_{wallet_label}"
                )
                if websocket:
                    await self._unsubscribe_from_token_trades(websocket, mint)
                return

            await self._evaluate_and_execute_exit(
                mint, current_market_cap, websocket=websocket
            )
            return

        # Smart Money Copy-Trading Entry Evaluation via WS
        if (
            is_buy
            and self.config.enable_copy_trading
            and self.copy_trade_engine.is_tracked_wallet(user)
            and mint not in self.active_positions
            and not self._is_recently_seen(mint)
        ):
            signal = self.copy_trade_engine.record_and_evaluate(
                user=user,
                mint=mint,
                sol_amount=sol_amount,
                is_buy=True,
                timestamp=ts,
            )
            if signal.triggered and signal.is_buy and signal.computed_copy_size_sol > 0:
                async with self._trade_lock:
                    if mint in self.active_positions or self._is_recently_seen(mint):
                        return

                    wallet_obj = self.copy_trade_engine.registry.get_wallet(user)
                    wallet_label = (
                        wallet_obj.label
                        if wallet_obj and wallet_obj.label
                        else user[:8]
                    )
                    reason_label = f"copy_trade_{wallet_label}"

                    screening_verdict = None
                    if self.config.copy_trading_require_anti_rug_screen:
                        screening_verdict = await self._enrich_and_screen_token(
                            mint, token_data=data
                        )
                        if not screening_verdict.passed:
                            self._log(
                                f"Copy-trade buy rejected for {mint} by {wallet_label}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                            )
                            return

                    if not self._should_buy(
                        mint,
                        current_market_cap,
                        screening_verdict=screening_verdict,
                        proposed_entry_sol=signal.computed_copy_size_sol,
                    ):
                        return

                    self._log(
                        f"Executing copy-trade buy for {mint} mirroring wallet {wallet_label} ({signal.reason}) with {signal.computed_copy_size_sol:.3f} SOL"
                    )
                    self._last_event = f"copy-trade buy {mint[:8]}"
                    bought = await self._buy_token(
                        mint,
                        current_market_cap,
                        data.get("name") or mint,
                        screening_verdict=screening_verdict,
                        reason=reason_label,
                        buy_amount_sol=signal.computed_copy_size_sol,
                    )
                    if bought and websocket:
                        await self._subscribe_to_token_trades(websocket, mint)
                    return

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

    async def _subscribe_to_token_trades(
        self, websocket: Any = None, mint: str = ""
    ) -> None:
        ws = websocket or self._active_ws
        if ws is None or not mint:
            return
        try:
            msg = {"method": "subscribeTokenTrade", "keys": [mint]}
            if hasattr(ws, "send") and not isinstance(
                ws, aiohttp.ClientWebSocketResponse
            ):
                await ws.send(json.dumps(msg))
            elif hasattr(ws, "send_json"):
                await ws.send_json(msg)
            elif hasattr(ws, "send_str"):
                await ws.send_str(json.dumps(msg))
            elif hasattr(ws, "send"):
                await ws.send(json.dumps(msg))
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
            msg = {"method": "unsubscribeTokenTrade", "keys": [mint]}
            if hasattr(ws, "send") and not isinstance(
                ws, aiohttp.ClientWebSocketResponse
            ):
                await ws.send(json.dumps(msg))
            elif hasattr(ws, "send_json"):
                await ws.send_json(msg)
            elif hasattr(ws, "send_str"):
                await ws.send_str(json.dumps(msg))
            elif hasattr(ws, "send"):
                await ws.send(json.dumps(msg))
        except Exception:
            pass

    async def _run_websocket_stream(self) -> None:
        """Connects to the WebSocket endpoint and ingests real-time events."""
        backoff = self.reconnect_delay_seconds
        while not self._stop_requested:
            try:
                self._log(f"Connecting to WebSocket stream at {self.stream_url}...")
                timeout = aiohttp.ClientTimeout(total=None, sock_read=60.0)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(self.stream_url) as ws:
                        self._active_ws = ws
                        self._log(f"Connected to WebSocket stream at {self.stream_url}")
                        self._record_event(
                            f"stream connected: {self.stream_url}", alert=False
                        )
                        self._last_message_at = time.monotonic()
                        self._circuit_breaker_tripped = False
                        self._stream_consecutive_failures = 0
                        # The breaker stays open across reconnects: only a
                        # confirmed subscription or trade data closes it.
                        self._last_status = "monitoring active tokens"
                        self._health_ok = True

                        # Subscribe to token creation events
                        if hasattr(ws, "send_json"):
                            await ws.send_json({"method": "subscribeNewToken"})
                        elif hasattr(ws, "send_str"):
                            await ws.send_str(
                                json.dumps({"method": "subscribeNewToken"})
                            )
                        elif hasattr(ws, "send"):
                            await ws.send(json.dumps({"method": "subscribeNewToken"}))

                        # Resubscribe to active holding tokens if any
                        for mint in list(self.active_positions.keys()):
                            await self._subscribe_to_token_trades(ws, mint)
                        if self.trade_feed_breaker.is_open:
                            # Probe on the first health pass after reconnecting.
                            self.trade_feed_breaker.next_probe_at = 0.0

                        backoff = self.reconnect_delay_seconds

                        async for msg in ws:
                            if self._stop_requested:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                except json.JSONDecodeError:
                                    continue
                                self._last_message_at = time.monotonic()
                                self._circuit_breaker_tripped = False
                                self._stream_consecutive_failures = 0
                                await self._handle_message(data, ws)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                self._stream_consecutive_failures += 1
                                self._log(
                                    f"WebSocket connection error: {ws.exception()}",
                                    level=logging.WARNING,
                                )
                                break
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.CLOSING,
                            ):
                                self._log(
                                    "WebSocket connection closed by remote server.",
                                    level=logging.INFO,
                                )
                                break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._stream_consecutive_failures += 1
                self._log(
                    f"WebSocket stream error: {exc}. Reconnecting in {backoff:.1f}s (attempt {self._stream_consecutive_failures})...",
                    level=logging.WARNING,
                )
                if (
                    self._stream_consecutive_failures
                    >= self._max_stream_consecutive_failures
                ):
                    self._circuit_breaker_tripped = True
                    self._health_ok = False
                    self._last_status = "degraded: stream circuit breaker active"
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2.0, 30.0)
            else:
                if not self._stop_requested:
                    if (
                        self._stream_consecutive_failures
                        >= self._max_stream_consecutive_failures
                    ):
                        self._circuit_breaker_tripped = True
                        self._health_ok = False
                        self._last_status = "degraded: stream circuit breaker active"
                    try:
                        await asyncio.sleep(backoff)
                    except asyncio.CancelledError:
                        break
                    backoff = min(backoff * 2.0, 30.0)
            finally:
                self._active_ws = None

    async def _refresh_active_positions_market_caps(self) -> None:
        """Periodically refresh active position market caps from on-chain bonding curve states."""
        if not self.active_positions:
            return
        for mint in list(self.active_positions.keys()):
            try:
                curve = await self.execution.get_bonding_curve_state(mint)
                mc = 0.0
                if isinstance(curve, dict):
                    mc = float(curve.get("market_cap_sol", 0.0) or 0.0)
                    if mc <= 0.0:
                        vt = int(curve.get("virtual_token_reserves", 0))
                        vs = int(curve.get("virtual_sol_reserves", 0))
                        if vt > 0 and vs > 0:
                            mc = (vs / 1_000_000_000.0) * (
                                1_000_000_000.0 / (vt / 1_000_000.0)
                            )
                if mc > 0.0:
                    await self._evaluate_and_execute_exit(mint, mc)
                else:
                    pos = self.active_positions.get(mint, {})
                    curr_mc = float(
                        pos.get("current_market_cap", 0.0)
                        or pos.get("entry_market_cap", 0.0)
                        or 0.0
                    )
                    if curr_mc > 0.0:
                        await self._evaluate_and_execute_exit(mint, curr_mc)
            except Exception:
                try:
                    pos = self.active_positions.get(mint, {})
                    curr_mc = float(
                        pos.get("current_market_cap", 0.0)
                        or pos.get("entry_market_cap", 0.0)
                        or 0.0
                    )
                    if curr_mc > 0.0:
                        await self._evaluate_and_execute_exit(mint, curr_mc)
                except Exception:
                    pass

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
        open_val = self.position_manager.calculate_total_open_value()
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
            if render_task:
                render_task.cancel()
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
