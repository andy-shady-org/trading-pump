from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from typing import Any, Optional

import aiohttp
from dotenv import load_dotenv
from rich.live import Live

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.alerts import AlertDispatcher
from pumpfun_trading.bot.enrichment import TokenEnricher
from pumpfun_trading.bot.event_router import EventRouter
from pumpfun_trading.bot.health import (
    health_ok_for_trading,
    mark_health_check,
    update_health_state,
)
from pumpfun_trading.bot.lifecycle import (
    TradingBotState,
    VALID_STATE_TRANSITIONS,
)
from pumpfun_trading.bot.persistence import StatusPersistenceManager
from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.bot.risk import (
    DailyEquityTracker,
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
    evaluate_portfolio_circuit_breaker,
)
from pumpfun_trading.bot.strategy import (
    CopyTradeEngine,
    ExitAction,
    GraduationEngine,
    OrderFlowEngine,
    RaydiumPoolKeys,
    ScreeningCache,
    TokenScreeningVerdict,
    TradingBotConfig,
    TradingStrategy,
    resolve_strategy_config,
)
from pumpfun_trading.execution.builder import build_execution_client
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.infra.rpc_pool import RpcConnectionPool, RpcPoolConfig
from pumpfun_trading.ops.logging import (
    get_configured_console,
    setup_structured_logging,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)
from pumpfun_trading.ui.dashboard import build_dashboard


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
        log_file: str | None = None,
        strategy_preset: str = "balanced",
        audit_log_path: str | None = None,
        bot_status_path: str | None = None,
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
        env_stream_url = os.getenv("PUMPFUN_STREAM_URL") or os.getenv("PUMPFUN_WS_URL")
        effective_stream_url = stream_url
        if effective_stream_url == "http://127.0.0.1:10000" and env_stream_url:
            effective_stream_url = env_stream_url
        elif base.stream_url and base.stream_url != "http://127.0.0.1:10000":
            effective_stream_url = base.stream_url
        elif env_stream_url:
            effective_stream_url = env_stream_url

        self.config = TradingBotConfig(
            buy_amount_sol=float(base.buy_amount_sol),
            take_profit=float(base.take_profit),
            stop_loss=float(base.stop_loss),
            max_active_positions=int(base.max_active_positions),
            max_positions_per_mint=int(base.max_positions_per_mint),
            min_market_cap_sol=float(base.min_market_cap_sol),
            max_buy_attempts_per_mint=int(base.max_buy_attempts_per_mint),
            min_balance_sol=float(base.min_balance_sol),
            min_sell_balance=int(base.min_sell_balance),
            recent_token_ttl_seconds=int(base.recent_token_ttl_seconds),
            reconnect_delay_seconds=float(base.reconnect_delay_seconds),
            dry_run=bool(base.dry_run or dry_run or paper_trade),
            paper_trade=bool(base.paper_trade or paper_trade),
            verbose=bool(base.verbose and verbose),
            stream_url=str(effective_stream_url),
            api_base_url=str(api_base_url if api_base_url else base.api_base_url),
            strategy_preset=str(base.strategy_preset),
            max_total_exposure_sol=float(getattr(base, "max_total_exposure_sol", 0.25)),
            max_position_size_sol=float(getattr(base, "max_position_size_sol", 0.05)),
            max_loss_per_trade_sol=float(getattr(base, "max_loss_per_trade_sol", 0.02)),
            max_daily_drawdown_pct=float(getattr(base, "max_daily_drawdown_pct", 0.15)),
            reserve_balance_sol=float(getattr(base, "reserve_balance_sol", 0.1)),
            health_check_timeout_seconds=int(
                getattr(base, "health_check_timeout_seconds", 60)
            ),
            emergency_hard_lock_hours=float(
                getattr(base, "emergency_hard_lock_hours", 24.0)
            ),
            auto_liquidate_on_circuit_breaker=bool(
                getattr(base, "auto_liquidate_on_circuit_breaker", True)
            ),
            enable_trailing_stop=bool(getattr(base, "enable_trailing_stop", True)),
            trailing_stop_activation_pct=float(
                getattr(base, "trailing_stop_activation_pct", 0.50)
            ),
            trailing_stop_drop_pct=float(getattr(base, "trailing_stop_drop_pct", 0.15)),
            enable_tiered_take_profit=bool(
                getattr(base, "enable_tiered_take_profit", True)
            ),
            tier_1_take_profit=float(getattr(base, "tier_1_take_profit", 2.0)),
            tier_1_sell_fraction=float(getattr(base, "tier_1_sell_fraction", 0.50)),
            tier_2_take_profit=float(getattr(base, "tier_2_take_profit", 3.5)),
            tier_2_sell_fraction=float(getattr(base, "tier_2_sell_fraction", 0.25)),
            moonbag_trailing_floor=float(getattr(base, "moonbag_trailing_floor", 2.5)),
            enable_anti_rug_filters=bool(
                getattr(base, "enable_anti_rug_filters", True)
            ),
            max_dev_24h_launches=int(getattr(base, "max_dev_24h_launches", 5)),
            max_creator_initial_holding_pct=float(
                getattr(base, "max_creator_initial_holding_pct", 0.10)
            ),
            max_top5_holder_concentration_pct=float(
                getattr(base, "max_top5_holder_concentration_pct", 0.15)
            ),
            max_gini_coefficient=float(getattr(base, "max_gini_coefficient", 0.85)),
            require_social_links=bool(getattr(base, "require_social_links", False)),
            min_social_links_count=int(getattr(base, "min_social_links_count", 1)),
            max_acceptable_risk_score=float(
                getattr(base, "max_acceptable_risk_score", 45.0)
            ),
            screening_cache_ttl_seconds=int(
                getattr(base, "screening_cache_ttl_seconds", 60)
            ),
            enable_momentum_signals=bool(
                getattr(base, "enable_momentum_signals", True)
            ),
            momentum_window_seconds=int(getattr(base, "momentum_window_seconds", 30)),
            momentum_min_buy_ratio=float(getattr(base, "momentum_min_buy_ratio", 3.0)),
            momentum_min_z_score=float(getattr(base, "momentum_min_z_score", 2.5)),
            momentum_min_unique_buyers=int(
                getattr(base, "momentum_min_unique_buyers", 3)
            ),
            momentum_min_net_inflow_sol=float(
                getattr(base, "momentum_min_net_inflow_sol", 0.5)
            ),
            momentum_baseline_window_seconds=int(
                getattr(base, "momentum_baseline_window_seconds", 300)
            ),
            momentum_max_token_age_seconds=int(
                getattr(base, "momentum_max_token_age_seconds", 1800)
            ),
            enable_raydium_migration_sniping=bool(
                getattr(base, "enable_raydium_migration_sniping", True)
            ),
            raydium_pre_migration_sol_threshold=float(
                getattr(base, "raydium_pre_migration_sol_threshold", 80.0)
            ),
            raydium_buy_amount_sol=float(getattr(base, "raydium_buy_amount_sol", 0.02)),
            raydium_slippage_bps=int(getattr(base, "raydium_slippage_bps", 500)),
            raydium_priority_fee_lamports=int(
                getattr(base, "raydium_priority_fee_lamports", 100_000)
            ),
            raydium_max_entry_latency_seconds=float(
                getattr(base, "raydium_max_entry_latency_seconds", 30.0)
            ),
            enable_copy_trading=bool(getattr(base, "enable_copy_trading", False)),
            copy_trading_wallets=tuple(getattr(base, "copy_trading_wallets", ())),
            copy_trading_min_wallet_win_rate=float(
                getattr(base, "copy_trading_min_wallet_win_rate", 0.55)
            ),
            copy_trading_max_wallet_risk_score=float(
                getattr(base, "copy_trading_max_wallet_risk_score", 45.0)
            ),
            copy_trading_sizing_mode=str(
                getattr(base, "copy_trading_sizing_mode", "proportional")
            ),
            copy_trading_scale_factor=float(
                getattr(base, "copy_trading_scale_factor", 1.0)
            ),
            copy_trading_mirror_sells=bool(
                getattr(base, "copy_trading_mirror_sells", True)
            ),
            copy_trading_require_anti_rug_screen=bool(
                getattr(base, "copy_trading_require_anti_rug_screen", True)
            ),
            enable_rpc_pool=bool(getattr(base, "enable_rpc_pool", True)),
            rpc_endpoints=tuple(getattr(base, "rpc_endpoints", ())),
            rpc_pool_health_check_interval_seconds=float(
                getattr(base, "rpc_pool_health_check_interval_seconds", 30.0)
            ),
            rpc_pool_circuit_breaker_threshold=int(
                getattr(base, "rpc_pool_circuit_breaker_threshold", 3)
            ),
            rpc_pool_circuit_breaker_cooldown_seconds=float(
                getattr(base, "rpc_pool_circuit_breaker_cooldown_seconds", 60.0)
            ),
            rpc_pool_broadcast_concurrency=int(
                getattr(base, "rpc_pool_broadcast_concurrency", 3)
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
        self.max_positions_per_mint = self.config.max_positions_per_mint
        self.min_market_cap_sol = self.config.min_market_cap_sol
        self.max_buy_attempts_per_mint = self.config.max_buy_attempts_per_mint
        self.min_balance_sol = self.config.min_balance_sol
        self.min_sell_balance = self.config.min_sell_balance
        self.recent_token_ttl_seconds = self.config.recent_token_ttl_seconds
        self.reconnect_delay_seconds = self.config.reconnect_delay_seconds
        self.dry_run = self.config.dry_run
        self.paper_trade = self.config.paper_trade
        self.verbose = self.config.verbose
        self._stop_requested = False
        self._last_message_at = 0.0
        self._last_event = "waiting for new token stream"
        self._last_new_token = "-"
        self._last_new_token_name = "-"
        self._last_status = "initializing"
        self._display_live: Optional[Live] = None
        self._trade_ledger: list[dict[str, Any]] = []
        self._recent_actions: deque[dict[str, Any]] = deque(maxlen=50)
        self._recent_events: deque[str] = deque(maxlen=8)
        self._trade_sequence = 0
        self._health_ok = True
        self._risk_killed = False
        self._last_health_check = time.monotonic()
        self.state = TradingBotState.IDLE

        # Subsystems & Engines
        self.position_manager = PositionManager(self.config)
        self.active_positions = self.position_manager.get_all_positions()

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
        self.wallet_balance_sol = float(
            self.config.reserve_balance_sol + self.config.buy_amount_sol * 10
        )
        self.screening_cache = ScreeningCache(
            default_ttl=float(self.config.screening_cache_ttl_seconds)
        )
        self._buy_attempts: dict[str, int] = {}
        self._seen_mints: dict[str, float] = {}
        self.console = get_configured_console(file=sys.stdout)

        self.geyser_endpoint = (
            geyser_endpoint or os.getenv("PUMPFUN_GEYSER_ENDPOINT")
        )
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

        self.logger = setup_structured_logging(
            logger_name="pumpfun_trading.bot",
            log_file=log_file,
            console=self.verbose,
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

        self.bot_status_path = bot_status_path or os.getenv("PUMPFUN_STATUS_PATH")
        self.audit_log_path = audit_log_path or os.getenv("PUMPFUN_AUDIT_LOG_PATH")
        self.persistence = StatusPersistenceManager(
            bot_status_path=self.bot_status_path,
            audit_log_path=self.audit_log_path,
        )
        self._audit_handle = self.persistence._audit_handle

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
        self._config = self.config
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

    async def close(self) -> None:
        """Closes persistence handles and background resources."""
        self.persistence.close()
        if hasattr(self, "rpc_pool") and self.rpc_pool is not None:
            await self.rpc_pool.close()
        if hasattr(self, "execution") and hasattr(self.execution, "close"):
            await self.execution.close()
        if hasattr(self, "api") and hasattr(self.api, "close"):
            await self.api.close()

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
        self.alerts.send_alert(message)

    def _write_status_snapshot(self) -> None:
        if not self.bot_status_path:
            return
        snapshot = self.get_status_snapshot()
        snapshot.update(
            {
                "timestamp": time.time(),
                "last_event": self._last_event,
                "last_status": self._last_status,
                "last_message_at": self._last_message_at,
                "last_new_token": self._last_new_token,
                "last_new_token_name": self._last_new_token_name,
                "audit_log_path": self.audit_log_path,
                "bot_status_path": self.bot_status_path,
                "metrics": self._metrics_snapshot(),
                "recent_events": list(self._recent_events),
                "alert_provider": self.alert_provider,
                "alert_enabled": self.alert_enabled,
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
            self._recent_events = deque(maxlen=8)
            for item in recent_events:
                self._recent_events.append(str(item))

        exit_retry_queue = snapshot.get("exit_retry_queue")
        if isinstance(exit_retry_queue, dict):
            self._exit_retry_queue = {
                str(k): dict(v)
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
        self._last_message_at = float(
            snapshot.get("last_message_at", self._last_message_at)
        )
        self._last_event = str(snapshot.get("last_event", self._last_event))
        self._last_status = str(snapshot.get("last_status", self._last_status))
        self._last_new_token = str(snapshot.get("last_new_token", self._last_new_token))
        self._last_new_token_name = str(
            snapshot.get("last_new_token_name", self._last_new_token_name)
        )
        self._trade_sequence = max(
            int(snapshot.get("trade_sequence", self._trade_sequence)),
            len(self._trade_ledger),
        )

        equity_tracker_data = snapshot.get("daily_equity_tracker")
        if isinstance(equity_tracker_data, dict):
            self.daily_equity_tracker = DailyEquityTracker.from_dict(
                equity_tracker_data
            )
        elif "circuit_breaker_engaged" in snapshot:
            self.daily_equity_tracker.circuit_breaker_engaged = bool(
                snapshot.get("circuit_breaker_engaged", False)
            )
            self.daily_equity_tracker.locked_at_timestamp = snapshot.get(
                "circuit_breaker_lockout_until"
            )

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

    def _transition_to(self, next_state: TradingBotState, reason: str = "") -> None:
        current = self.state
        if current == next_state:
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
        return cls(private_key, rpc_url, **kwargs)

    def _log(self, message: str, level: int = logging.INFO) -> None:
        if self.verbose:
            self.logger.log(level, message)

    def request_shutdown(self) -> None:
        self._stop_requested = True
        self._last_status = "shutdown requested"
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

    def _next_trade_id(self) -> str:
        self._trade_sequence += 1
        return f"trade-{self._trade_sequence:06d}"

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
    ) -> None:
        trade_id = trade_id or position_id or self._next_trade_id()
        position_id = position_id or trade_id
        name = (
            token_name
            or mint_name
            or self.active_positions.get(mint, {}).get("name")
            or (self._last_new_token_name if self._last_new_token == mint else None)
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
            "reason": reason or "",
            "timestamp": time.time(),
        }
        self._trade_ledger.append(record)
        if len(self._trade_ledger) > 50:
            self._trade_ledger.pop(0)
        self._recent_actions.append(record)
        if action == "buy":
            self._record_metric("buys")
        elif "sell" in action:
            self._record_metric("sells")
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

    def _record_event(self, event_message: str) -> None:
        formatted = f"[{time.strftime('%H:%M:%S')}] {event_message}"
        self._recent_events.append(formatted)
        self._last_event = event_message
        if getattr(self, "alert_enabled", False):
            self._send_alert(event_message)

    def _record_stale_data(self, reason: str = "") -> None:
        self._record_metric("stale_data")
        if reason:
            self._log(f"Stale data recorded: {reason}", level=logging.WARNING)

    def _record_failure(
        self, reason: str = "", category: str = "", **kwargs: Any
    ) -> None:
        self._record_metric("failures")
        msg = category or reason or "unknown"
        self._log(f"Failure recorded: {msg}", level=logging.WARNING)

    def _record_connection_loss(self) -> None:
        self._record_metric("connection_loss")

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
        self._risk_killed = False
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
            self._log(
                f"Error checking account equity guard: {exc}", level=logging.WARNING
            )
            self._risk_killed = True
            self._last_event = "risk kill: API balance check failed"
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
            if (
                self.config.auto_liquidate_on_circuit_breaker
                and len(self.active_positions) > 0
            ):
                self._log(
                    f"Engaging emergency liquidation due to circuit breaker breach: {reason}",
                    level=logging.ERROR,
                )
                await self._liquidate_all_positions(reason=f"circuit_breaker: {reason}")

            self._risk_killed = True
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
            "buy_attempts": dict(self._buy_attempts),
            "seen_mints": dict(self._seen_mints),
            "trade_ledger": list(self._trade_ledger),
            "recent_actions": list(self._recent_actions),
            "recent_events": list(self._recent_events),
            "trade_sequence": self._trade_sequence,
            "daily_equity_tracker": self.daily_equity_tracker.to_dict(),
            "daily_drawdown_pct": drawdown,
            "daily_realized_pnl_sol": self.daily_equity_tracker.realized_daily_pnl_sol,
            "daily_unrealized_pnl_sol": 0.0,
            "daily_starting_equity_sol": self.daily_equity_tracker.starting_equity_sol,
            "circuit_breaker_engaged": self.daily_equity_tracker.circuit_breaker_engaged,
            "circuit_breaker_lockout_until": self.daily_equity_tracker.locked_at_timestamp,
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
        self, mint: str, token_data: dict[str, Any] | None = None
    ) -> TokenScreeningVerdict:
        return await self.enricher.enrich_and_screen(
            mint, token_data=token_data, config=self.config
        )

    def _should_buy(
        self,
        mint: str,
        market_cap_sol: float,
        screening_verdict: TokenScreeningVerdict | None = None,
        proposed_entry_sol: float | None = None,
    ) -> bool:
        if not self._health_ok_for_trading():
            return False
        if self._is_recently_seen(mint):
            return False
        if mint in self.active_positions:
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

    async def _buy_token(
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

        exec_res = await self.executor.execute_buy(
            mint=mint,
            amount_sol=effective_buy_amount,
            reason=reason or "entry",
            token_name=position_name,
            dry_run=self.dry_run,
        )

        if not exec_res.success:
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING,
                reason=f"buy_failed {mint} ({exec_res.error})",
            )
            return False

        self.position_manager.record_buy(
            mint=mint,
            token_amount=exec_res.token_amount or (100_000_000 if self.dry_run else 0),
            cost_sol=effective_buy_amount,
            entry_market_cap=float(market_cap_sol or 30.0),
            name=position_name,
            buy_signature=exec_res.signature,
            reason=reason or "entry",
            dry_run=self.dry_run,
        )
        self.active_positions = self.position_manager.get_all_positions()

        self._buy_attempts[mint] = 0
        self._mark_seen(mint)
        self._last_new_token = mint
        self._last_new_token_name = position_name
        self._record_metric("buys")
        self._record_trade(
            mint=mint,
            action="buy",
            token_name=position_name,
            mint_name=position_name,
            entry=effective_buy_amount,
            reason=reason or "entry",
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
                "pool_keys": pool_keys.to_dict(),
                "raydium_pool_id": pool_keys.amm_id,
                "amm_id": pool_keys.amm_id,
            },
        )
        self.active_positions = self.position_manager.get_all_positions()

        self._buy_attempts[mint] = 0
        self._mark_seen(mint)
        self._last_new_token = mint
        self._last_new_token_name = position_name
        self._record_metric("buys")
        self._record_trade(
            mint=mint,
            action="raydium_buy",
            token_name=position_name,
            mint_name=position_name,
            entry=buy_amount,
            reason=reason or "raydium_graduation_snipe",
        )
        self._transition_to(
            TradingBotState.HOLDING, reason=f"raydium_buy_confirmed {mint}"
        )
        return True

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
        else:
            entry = self._exit_retry_queue[mint]
            entry["retries"] = (
                int(entry.get("retries") or entry.get("retry_count") or 0) + 1
            )
            entry["retry_count"] = entry["retries"]
            entry["last_attempt"] = time.monotonic()
            entry["reason"] = reason
            entry["slippage_bps"] = min(
                self.max_exit_slippage_bps,
                self.base_exit_slippage_bps + (entry["retry_count"] * 500),
            )
            entry["next_retry_at"] = time.monotonic() + (2.0 ** entry["retry_count"])

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

    async def _sell_token(
        self,
        mint: str,
        *,
        sell_amount_tokens: int | None = None,
        sell_fraction: float = 1.0,
        reason: str = "exit",
        target_tier: int | None = None,
        slippage_bps: int | None = None,
        retry_count: int = 0,
    ) -> bool:
        if mint not in self.active_positions:
            self._exit_retry_queue.pop(mint, None)
            return False

        position = self.active_positions[mint]
        pos_name = position.get("name") or mint

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
        exec_res = await self.executor.execute_sell(
            mint=mint,
            token_amount=tokens_to_sell,
            slippage_bps=effective_slippage,
            reason=reason,
            dry_run=self.dry_run,
        )

        if not exec_res.success:
            self._enqueue_exit_retry(mint, reason=f"sell_exec_failed: {exec_res.error}")
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_failed {mint}")
            return False

        is_fully_closed, remaining = self.position_manager.record_sell(
            mint=mint,
            sold_tokens=tokens_to_sell,
            target_tier=target_tier,
            is_partial=is_partial,
        )
        self.active_positions = self.position_manager.get_all_positions()
        self._record_metric("sells")

        if is_partial:
            self._record_trade(
                mint=mint,
                action="partial_sell",
                token_name=pos_name,
                mint_name=pos_name,
                entry=0.0,
                reason=reason,
            )
            self._transition_to(
                TradingBotState.HOLDING, reason=f"partial_sell_complete {mint}"
            )
            return True

        self._exit_retry_queue.pop(mint, None)
        self._record_trade(
            mint=mint,
            action="sell",
            token_name=pos_name,
            mint_name=pos_name,
            entry=0.0,
            reason=reason,
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

        exit_decision = self.position_manager.evaluate_exit(
            mint, current_market_cap=current_market_cap
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

            async with self._trade_lock:
                if self._is_recently_seen(mint):
                    return

                screening_verdict = await self._enrich_and_screen_token(mint)
                if not screening_verdict.passed:
                    self._log(
                        f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                    )
                    self._last_event = f"screen_rejected {mint[:8]}"
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
        ts = float(update.timestamp if update.timestamp > 0 else update.received_at)
        self.order_flow_engine.record_trade(
            mint=mint,
            is_buy=update.is_buy,
            sol_amount=update.sol_amount,
            user=update.user,
            timestamp=ts,
        )

        if update.virtual_token_reserves > 0:
            current_market_cap = (update.virtual_sol_reserves / 1_000_000_000.0) * (
                1_000_000_000.0 / (update.virtual_token_reserves / 1_000_000.0)
            )
        else:
            current_market_cap = 0.0

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
            self._log(
                f"Position held for graduating token {mint}; executing priority exit before Raydium AMM migration."
            )
            await self._sell_token(mint, reason="bonding_curve_graduated")

    async def _handle_raydium_pool_update(self, pool_keys: RaydiumPoolKeys) -> None:
        """Handle Raydium AMM pool creation and dispatch graduation breakout buys."""
        if self._stop_requested:
            return

        mint = pool_keys.coin_mint
        self._log(f"Raydium AMM pool initialized for {mint}: amm_id={pool_keys.amm_id}")
        self._last_event = f"raydium pool {mint[:8]}"
        self.graduation_engine.record_raydium_pool(mint=mint, pool_keys=pool_keys)

        if not self.config.enable_raydium_migration_sniping:
            return

        if mint in self.active_positions:
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

    async def _handle_new_token_event(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        if self._stop_requested:
            return

        self._last_message_at = time.monotonic()
        mint = data.get("mint")
        if not mint:
            return

        current_market_cap = float(
            data.get("market_cap", 0.0)
            or data.get("marketCapSol", 0.0)
            or data.get("market_cap_sol", 0.0)
            or 0.0
        )
        token_name = data.get("name") or mint

        if mint in self.active_positions:
            return

        if not self._should_buy(mint, current_market_cap):
            return

        screening_verdict = await self._enrich_and_screen_token(mint, token_data=data)
        if not screening_verdict.passed:
            self._log(
                f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
            )
            self._last_event = f"screen_rejected {mint[:8]}"
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
            or 0.0
        )
        if mint in self.active_positions:
            if not self.dry_run:
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

    async def _handle_message(self, data: Any, websocket: Any = None) -> None:
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
        except Exception:
            pass

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
                        self._circuit_breaker_tripped = False
                        self._stream_consecutive_failures = 0
                        self._last_status = "monitoring active tokens"
                        self._health_ok = True

                        # Subscribe to token creation events
                        if hasattr(ws, "send_json"):
                            await ws.send_json({"method": "subscribeNewToken"})
                        elif hasattr(ws, "send_str"):
                            await ws.send_str(json.dumps({"method": "subscribeNewToken"}))
                        elif hasattr(ws, "send"):
                            await ws.send(json.dumps({"method": "subscribeNewToken"}))

                        # Resubscribe to active holding tokens if any
                        for mint in list(self.active_positions.keys()):
                            await self._subscribe_to_token_trades(ws, mint)

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

    async def _run_health_loop(self) -> None:
        """Periodic background task evaluating health, equity, and reconciliations."""
        while not self._stop_requested:
            try:
                await asyncio.sleep(5)
                await self._update_health_state()
                await self._check_and_enforce_circuit_breaker()
                self._prune_seen_mints()
                self._write_status_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log(f"Health loop exception: {exc}", level=logging.DEBUG)

    async def _render_loop(self) -> None:
        """Background loop rendering the Rich terminal dashboard."""
        if not self.verbose:
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
        if self.rpc_pool:
            await self.rpc_pool.start_health_loop()

        self._transition_to(TradingBotState.MONITORING, reason="bot_started")
        await self._reconcile_positions_on_startup()

        health_task = asyncio.create_task(self._run_health_loop())
        render_task = None
        if self.verbose:
            render_task = asyncio.create_task(self._render_loop())

        try:
            if self.geyser_client and (
                self.geyser_endpoint
                or (
                    hasattr(self.geyser_client, "listen")
                    and getattr(self.geyser_client, "listen")
                    != YellowstoneGeyserClient.listen
                )
            ):
                if hasattr(self.geyser_client, "on_bonding_curve"):
                    self.geyser_client.on_bonding_curve(
                        self.event_router.route_geyser_curve_update
                    )
                if hasattr(self.geyser_client, "on_trade"):
                    self.geyser_client.on_trade(
                        self.event_router.route_geyser_trade_update
                    )
                if hasattr(self.geyser_client, "on_complete"):
                    self.geyser_client.on_complete(
                        self.event_router.route_geyser_complete_update
                    )
                if hasattr(self.geyser_client, "start"):
                    await self.geyser_client.start()
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
                and self.stream_url.startswith(("ws://", "wss://", "http://", "https://"))
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
            if render_task:
                render_task.cancel()
            if self.geyser_client and hasattr(self.geyser_client, "stop"):
                await self.geyser_client.stop()
            if self.rpc_pool:
                if hasattr(self.rpc_pool, "stop"):
                    self.rpc_pool.stop()
                elif hasattr(self.rpc_pool, "close"):
                    await self.rpc_pool.close()
            self.persistence.close()
            if self.state != TradingBotState.SHUTDOWN:
                self._transition_to(TradingBotState.SHUTDOWN, reason="bot_terminated")

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
