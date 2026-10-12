import asyncio
import json
import logging
import os
import random
import signal
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import deque
from typing import Any

from dotenv import load_dotenv
from rich.live import Live
from rich.panel import Panel

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.health import (
    health_ok_for_trading,
    mark_health_check,
    update_health_state,
)
from pumpfun_trading.bot.lifecycle import (
    TradingBotState,
    VALID_STATE_TRANSITIONS,
)
from pumpfun_trading.bot.risk import (
    DailyEquityTracker,
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
    evaluate_portfolio_circuit_breaker,
)
from pumpfun_trading.bot.strategy import (
    DevWalletProfile,
    ExitAction,
    HolderDistribution,
    OrderFlowEngine,
    PositionExitState,
    ScreeningCache,
    TokenMetadata,
    TokenScreeningVerdict,
    TradingBotConfig,
    TradingStrategy,
    evaluate_exit_strategy,
    resolve_strategy_config,
)
from pumpfun_trading.execution.builder import build_execution_client
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
    YellowstoneGeyserClient,
)
from pumpfun_trading.ui.dashboard import build_dashboard
from pumpfun_trading.config.env import (
    sanitize_env_for_logging,
)
from pumpfun_trading.ops.logging import (
    get_configured_console,
    setup_structured_logging,
)


class TradingBot:
    """Production-ready Pump.fun trading bot with strategy presets and lifecycle safeguards."""

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
            stream_url=str(stream_url if stream_url else base.stream_url),
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
            screening_cache_ttl_seconds=float(
                getattr(base, "screening_cache_ttl_seconds", 60.0)
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
        self._display_live = None
        self._trade_ledger: list[dict[str, Any]] = []
        self._recent_actions: deque[dict[str, Any]] = deque(maxlen=50)
        self._trade_sequence = 0
        self._health_ok = True
        self._risk_killed = False
        self._last_health_check = time.monotonic()
        self.state = TradingBotState.IDLE
        self.strategy = TradingStrategy(self.config)
        self.order_flow_engine = OrderFlowEngine(
            max_retention_seconds=600,
            recent_token_ttl_seconds=self.recent_token_ttl_seconds,
        )
        self.daily_equity_tracker = DailyEquityTracker()
        self.wallet_balance_sol = float(
            self.config.reserve_balance_sol + self.config.buy_amount_sol * 10
        )
        self.screening_cache = ScreeningCache(
            default_ttl=float(self.config.screening_cache_ttl_seconds)
        )
        self.active_positions: dict[str, dict[str, Any]] = {}
        self._buy_attempts: dict[str, int] = {}
        self._seen_mints: dict[str, float] = {}
        self.console = get_configured_console(file=sys.stdout)

        self.geyser_endpoint = (
            geyser_endpoint or os.getenv("PUMPFUN_GEYSER_ENDPOINT") or self.stream_url
        )
        self.geyser_x_token = geyser_x_token or os.getenv("PUMPFUN_GEYSER_X_TOKEN")
        self.geyser_client = geyser_client or YellowstoneGeyserClient(
            endpoint=self.geyser_endpoint,
            x_token=self.geyser_x_token,
            reconnect_initial_backoff=self.reconnect_delay_seconds,
        )

        self._stream_consecutive_failures = 0
        self._circuit_breaker_tripped = False
        self._max_stream_consecutive_failures = int(
            os.getenv("PUMPFUN_STREAM_MAX_RETRIES")
            or os.getenv("PUMPFUN_WS_MAX_RETRIES", "5")
        )

        self._exit_retry_queue: dict[str, dict[str, Any]] = {}
        self.max_exit_retries = int(os.getenv("PUMPFUN_MAX_EXIT_RETRIES", "5"))
        self.base_exit_slippage_bps = int(
            os.getenv("PUMPFUN_BASE_EXIT_SLIPPAGE_BPS", "500")
        )
        self.max_exit_slippage_bps = int(
            os.getenv("PUMPFUN_MAX_EXIT_SLIPPAGE_BPS", "5000")
        )

        self._metrics: dict[str, Any] = {
            "buys": 0,
            "sells": 0,
            "failures": 0,
            "retries": 0,
            "connection_loss": 0,
            "stale_data": 0,
            "latency_ms": deque(maxlen=200),
        }

        resolved_log_file = log_file or os.path.join(
            tempfile.gettempdir(), "pumpfun_trading_bot.log"
        )

        self.logger = setup_structured_logging(
            logger_name="pumpfun_trading.bot",
            log_file=resolved_log_file,
            console=self.verbose,
        )
        self.logger.setLevel(logging.INFO)
        self.logger.info(
            "bot_startup_configuration",
            extra={
                "event": "bot_startup_configuration",
                "runtime_env": sanitize_env_for_logging(),
                "dry_run": self.dry_run,
                "paper_trade": self.paper_trade,
            },
        )

        self.audit_log_path = audit_log_path or os.getenv("PUMPFUN_AUDIT_LOG")
        self._audit_handle = None
        if self.audit_log_path:
            directory = os.path.dirname(self.audit_log_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._audit_handle = open(self.audit_log_path, "a", encoding="utf-8")

        self.bot_status_path = bot_status_path or os.getenv("PUMPFUN_BOT_STATUS_PATH")

        self.alert_provider = (
            (os.getenv("PUMPFUN_ALERT_PROVIDER") or "none").strip().lower()
        )
        self.alert_discord_webhook_url = os.getenv("PUMPFUN_ALERT_DISCORD_WEBHOOK_URL")
        self.alert_slack_webhook_url = os.getenv("PUMPFUN_ALERT_SLACK_WEBHOOK_URL")
        self.alert_telegram_bot_token = os.getenv("PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN")
        self.alert_telegram_chat_id = os.getenv("PUMPFUN_ALERT_TELEGRAM_CHAT_ID")
        self.alert_enabled = False
        self._configure_alerting()
        self._recent_events: deque[str] = deque(maxlen=8)

        self.api = PumpFunApiClient(base_url=self.api_base_url)
        use_jito_env = os.getenv("PUMPFUN_USE_JITO", "").lower() in {
            "true",
            "1",
            "yes",
        }
        jito_tip_lamports = int(os.getenv("PUMPFUN_JITO_TIP_LAMPORTS", "0"))
        jito_block_engine = os.getenv("PUMPFUN_JITO_BLOCK_ENGINE_URL")
        use_jito = use_jito_env or jito_tip_lamports > 0 or bool(jito_block_engine)

        self.execution = build_execution_client(
            private_key_b58=self.private_key_b58,
            rpc_url=self.rpc_url,
            priority_fee_lamports=int(
                os.getenv("PUMPFUN_PRIORITY_FEE_LAMPORTS", "5000")
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
        self._trade_lock = asyncio.Lock()
        self.safe_startup()

    def _configure_alerting(self) -> None:
        provider = self.alert_provider
        if not provider or provider == "none":
            self.alert_enabled = False
            return

        provider = provider.lower().strip()
        if provider not in {"discord", "slack", "telegram"}:
            self.alert_enabled = False
            self._log(
                f"Unsupported alert provider '{provider}'. Supported providers: discord, slack, telegram, none.",
                level=logging.WARNING,
            )
            return

        if provider == "discord" and not self.alert_discord_webhook_url:
            self.alert_enabled = False
            self._log(
                "PUMPFUN_ALERT_PROVIDER is set to 'discord' but PUMPFUN_ALERT_DISCORD_WEBHOOK_URL is missing.",
                level=logging.WARNING,
            )
            return
        if provider == "slack" and not self.alert_slack_webhook_url:
            self.alert_enabled = False
            self._log(
                "PUMPFUN_ALERT_PROVIDER is set to 'slack' but PUMPFUN_ALERT_SLACK_WEBHOOK_URL is missing.",
                level=logging.WARNING,
            )
            return
        if provider == "telegram" and (
            not self.alert_telegram_bot_token or not self.alert_telegram_chat_id
        ):
            self.alert_enabled = False
            self._log(
                "PUMPFUN_ALERT_PROVIDER is set to 'telegram' but PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN and/or PUMPFUN_ALERT_TELEGRAM_CHAT_ID are missing.",
                level=logging.WARNING,
            )
            return

        self.alert_enabled = True

    def _send_alert(self, message: str) -> None:
        if not self.alert_enabled:
            return

        payload = message.strip()
        if not payload:
            return

        provider = self.alert_provider
        try:
            if provider == "discord":
                request = urllib.request.Request(
                    self.alert_discord_webhook_url,
                    data=json.dumps({"content": payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
            elif provider == "slack":
                request = urllib.request.Request(
                    self.alert_slack_webhook_url,
                    data=json.dumps({"text": payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
            elif provider == "telegram":
                request = urllib.request.Request(
                    f"https://api.telegram.org/bot{self.alert_telegram_bot_token}/sendMessage",
                    data=json.dumps(
                        {"chat_id": self.alert_telegram_chat_id, "text": payload}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
        except Exception as exc:  # pragma: no cover - network path
            self._log(
                f"Failed to send alert via {provider}: {exc}", level=logging.WARNING
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
        directory = os.path.dirname(self.bot_status_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.bot_status_path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, sort_keys=True, indent=2)
            handle.write("\n")

    def safe_startup(self) -> None:
        """Restore a persisted bot snapshot when the process restarts."""
        if not self.bot_status_path or not os.path.exists(self.bot_status_path):
            return

        try:
            with open(self.bot_status_path, "r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        except (OSError, TypeError, ValueError):
            self._log(
                f"Persisted status file at {self.bot_status_path} could not be read; starting fresh.",
                level=logging.WARNING,
            )
            return

        if not isinstance(snapshot, dict):
            self._log(
                f"Persisted status file at {self.bot_status_path} has an invalid format; starting fresh.",
                level=logging.WARNING,
            )
            return

        positions = snapshot.get("active_positions")
        if isinstance(positions, dict):
            restored_positions: dict[str, dict[str, Any]] = {}
            for mint, position in positions.items():
                if not isinstance(position, dict):
                    continue
                normalized = {
                    key: value
                    for key, value in dict(position).items()
                    if key
                    not in {"entry_market_cap", "current_market_cap", "peak_market_cap"}
                }
                entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
                curr_mc = float(position.get("current_market_cap", 0.0) or 0.0)
                peak_mc = float(
                    position.get("peak_market_cap", max(entry_mc, curr_mc))
                    or max(entry_mc, curr_mc)
                )
                normalized["entry_market_cap"] = entry_mc
                normalized["current_market_cap"] = curr_mc
                normalized["peak_market_cap"] = peak_mc
                restored_positions[str(mint)] = normalized
            self.active_positions = restored_positions
        elif isinstance(positions, list):
            self.active_positions = {}

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

        if "state" in snapshot:
            try:
                self.state = TradingBotState(snapshot["state"])
            except ValueError:
                self.state = TradingBotState.IDLE

        self._health_ok = bool(snapshot.get("health_ok", self._health_ok))
        self._risk_killed = bool(snapshot.get("risk_killed", self._risk_killed))
        self._stop_requested = bool(snapshot.get("stop_requested", False))
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

        metrics = snapshot.get("metrics", {})
        if isinstance(metrics, dict):
            self._metrics = {
                "buys": int(metrics.get("buys", self._metrics.get("buys", 0))),
                "sells": int(metrics.get("sells", self._metrics.get("sells", 0))),
                "failures": int(
                    metrics.get("failures", self._metrics.get("failures", 0))
                ),
                "retries": int(metrics.get("retries", self._metrics.get("retries", 0))),
                "connection_loss": int(
                    metrics.get(
                        "connection_loss",
                        self._metrics.get("connection_loss", 0),
                    )
                ),
                "stale_data": int(
                    metrics.get("stale_data", self._metrics.get("stale_data", 0))
                ),
                "latency_ms": deque(maxlen=200),
            }

        if "daily_equity" in snapshot and isinstance(snapshot["daily_equity"], dict):
            self.daily_equity_tracker = DailyEquityTracker.from_dict(
                snapshot["daily_equity"]
            )
        elif "circuit_breaker_engaged" in snapshot and snapshot.get(
            "circuit_breaker_engaged"
        ):
            self.daily_equity_tracker.circuit_breaker_engaged = True
            self.daily_equity_tracker.lock_reason = str(
                snapshot.get("lock_reason", "restored active circuit breaker lock")
            )

        self._log(
            f"Restored persisted bot state from {self.bot_status_path} with {len(self.active_positions)} active positions.",
            level=logging.INFO,
        )
        self._write_status_snapshot()

    def _transition_to(
        self, next_state: TradingBotState, *, reason: str | None = None
    ) -> None:
        current = self.state
        if next_state not in self._VALID_STATE_TRANSITIONS.get(current, set()):
            if current != next_state:
                self._log(
                    f"Illegal state transition from {current.value} to {next_state.value}: {reason or 'no reason provided'}",
                    level=logging.WARNING,
                )
            return
        self.state = next_state
        event = {
            "timestamp": time.time(),
            "state": next_state.value,
            "previous_state": current.value,
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
        if self._audit_handle is None:
            return
        entry = {
            "timestamp": time.time(),
            "type": record_type,
            "state": self.state.value,
            "payload": payload,
        }
        self._audit_handle.write(json.dumps(entry, sort_keys=True) + "\n")
        self._audit_handle.flush()
        self._write_status_snapshot()

    @staticmethod
    def validate_mint_address(mint: str) -> str:
        if not isinstance(mint, str) or not mint.strip():
            raise ValueError("Mint address is required.")
        cleaned = mint.strip()
        try:
            decoded = __import__("base58").b58decode(cleaned)
        except Exception as exc:  # pragma: no cover - defensive branch
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
        rpc_url = os.getenv("PUMPFUN_RPC_URL") or os.getenv("HELIUS_RPC_URL")
        if not private_key:
            raise ValueError(
                "Missing PUMPFUN_PRIVATE_KEY (or SOLANA_PRIVATE_KEY) in environment."
            )
        if not rpc_url:
            raise ValueError(
                "Missing PUMPFUN_RPC_URL (or HELIUS_RPC_URL) in environment."
            )
        return cls(private_key, rpc_url, **kwargs)

    def _log(self, message: str, level: int = logging.INFO) -> None:
        if self.verbose:
            self.logger.log(level, message)

    def request_shutdown(self) -> None:
        self._stop_requested = True
        self._last_status = "shutdown requested"
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
        if position_id is None and action == "buy":
            position_id = trade_id
        resolved_name = (
            token_name
            or mint_name
            or self.active_positions.get(mint, {}).get("name")
            or (self._last_new_token_name if self._last_new_token == mint else None)
        )
        record = {
            "timestamp": time.time(),
            "trade_id": trade_id,
            "position_id": position_id or trade_id,
            "action": action,
            "mint": mint,
            "token_name": resolved_name,
            "mint_name": resolved_name,
            "entry": entry,
            "exit": exit_value,
            "reason": reason,
        }
        if action == "buy":
            self._record_metric("buys")
        elif action in ("sell", "partial_sell"):
            self._record_metric("sells")
        self._trade_ledger.append(record)
        if len(self._trade_ledger) > 50:
            self._trade_ledger.pop(0)
        self._recent_actions.append(
            {"timestamp": record["timestamp"], "type": "trade", "payload": record}
        )
        self._write_audit_record("trade", record)

    def _record_event(self, message: str) -> None:
        self._recent_events.append(message)
        self._last_event = message
        self._write_audit_record("event", {"message": message})
        if self.alert_enabled:
            self._send_alert(f"Bot event: {message}")

    def _record_metric(self, name: str, value: float | int = 1) -> None:
        if name == "latency_ms":
            latency_ms = float(value)
            metrics_queue = self._metrics.setdefault("latency_ms", deque(maxlen=200))
            if not isinstance(metrics_queue, deque):
                metrics_queue = deque(maxlen=200)
                self._metrics["latency_ms"] = metrics_queue
            metrics_queue.append(latency_ms)
            self._write_status_snapshot()
            return
        self._metrics[name] = int(self._metrics.get(name, 0)) + int(value)
        self._write_status_snapshot()

    def _record_latency_ms(self, started_at: float) -> None:
        elapsed_ms = max(0.0, (time.perf_counter() - started_at) * 1000.0)
        self._record_metric("latency_ms", elapsed_ms)

    def _record_stale_data(self, reason: str) -> None:
        self._record_metric("stale_data")
        self._last_event = f"stale data: {reason}"
        self._write_status_snapshot()

    def _record_retry(self) -> None:
        self._record_metric("retries")

    def _record_failure(self, *, category: str | None = None) -> None:
        self._record_metric("failures")
        if category:
            self._write_audit_record(
                "metric", {"name": "failures", "category": category, "value": 1}
            )

    @property
    def _ws_consecutive_failures(self) -> int:
        return self._stream_consecutive_failures

    @_ws_consecutive_failures.setter
    def _ws_consecutive_failures(self, value: int) -> None:
        self._stream_consecutive_failures = value

    @property
    def _max_ws_consecutive_failures(self) -> int:
        return self._max_stream_consecutive_failures

    @_max_ws_consecutive_failures.setter
    def _max_ws_consecutive_failures(self, value: int) -> None:
        self._max_stream_consecutive_failures = value

    def _record_connection_loss(self) -> None:
        self._record_metric("connection_loss")

    def _metrics_snapshot(self) -> dict[str, Any]:
        latency_values = list(self._metrics.get("latency_ms", deque()))
        snapshot = {
            key: value for key, value in self._metrics.items() if key != "latency_ms"
        }
        snapshot["latency_ms"] = {
            "samples": len(latency_values),
            "avg_ms": (
                round(sum(latency_values) / len(latency_values), 2)
                if latency_values
                else 0.0
            ),
            "last_ms": round(latency_values[-1], 2) if latency_values else 0.0,
            "max_ms": round(max(latency_values), 2) if latency_values else 0.0,
        }
        if hasattr(self, "geyser_client") and self.geyser_client is not None:
            snapshot["geyser_stream"] = self.geyser_client.metrics.summary()
        return snapshot

    def _render_dashboard(self) -> Panel:
        return build_dashboard(self)

    def _next_position_id(self) -> str:
        return self._next_trade_id()

    async def _validate_balance(self) -> bool:
        if self.dry_run:
            return True
        try:
            balance_sol = float(await self.execution.get_balance_sol())
            self.wallet_balance_sol = balance_sol
            open_val_sol = sum(
                float(
                    pos.get("current_market_cap", pos.get("entry_market_cap", 0.0))
                    or 0.0
                )
                for pos in self.active_positions.values()
            )
            self.daily_equity_tracker.update_valuation(balance_sol, open_val_sol)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._last_event = "balance check failed"
            self._log(f"Could not read wallet balance: {exc}", level=logging.WARNING)
            return False
        if balance_sol - self.config.reserve_balance_sol < self.min_balance_sol:
            self._last_event = (
                f"equity guard: available {balance_sol - self.config.reserve_balance_sol:.4f} SOL, "
                f"minimum {self.min_balance_sol:.4f} SOL"
            )
            return False
        return True

    async def _check_account_equity_guard(self, *, required_sol: float) -> bool:
        if self.dry_run:
            return True
        try:
            balance_sol = float(await self.execution.get_balance_sol())
        except Exception as exc:  # pragma: no cover - defensive branch
            self._health_ok = False
            self._risk_killed = True
            self._last_event = "risk kill: API balance check failed"
            self._log(
                f"Could not read wallet balance for equity guard: {exc}",
                level=logging.WARNING,
            )
            return False

        available_after_reserve = balance_sol - self.config.reserve_balance_sol
        if required_sol > available_after_reserve:
            self._last_event = f"equity guard: required {required_sol:.4f} SOL, available {available_after_reserve:.4f} SOL"
            self._log(
                f"Account equity guard blocked trade: {required_sol:.4f} SOL required, "
                f"{available_after_reserve:.4f} SOL available after reserve {self.config.reserve_balance_sol:.4f} SOL",
                level=logging.WARNING,
            )
            return False
        return True

    async def _resolve_token_name(
        self, mint: str, token_name: str | None = None
    ) -> str | None:
        if token_name and token_name.strip():
            return token_name.strip()
        return None

    async def _unsubscribe_from_token_trades(
        self, websocket: Any = None, mint: str = ""
    ) -> None:
        _ = websocket, mint
        return None

    def _check_risk_limits(
        self,
        *,
        mint: str,
        proposed_entry_sol: float,
        current_positions: dict[str, dict[str, Any]],
    ) -> bool:
        return check_risk_limits(
            self,
            mint=mint,
            proposed_entry_sol=proposed_entry_sol,
            current_positions=current_positions,
        )

    async def _liquidate_all_positions(
        self, reason: str = "emergency_hard_lock"
    ) -> list[str]:
        """Liquidates all active open positions aggressively via priority exit orders."""
        mints_to_liquidate = list(self.active_positions.keys())
        liquidated: list[str] = []
        for mint in mints_to_liquidate:
            self._log(
                f"Emergency liquidation triggered for {mint} (reason: {reason})",
                level=logging.WARNING,
            )
            sold = await self._sell_token(mint, reason=reason)
            if sold:
                liquidated.append(mint)
        return liquidated

    async def _check_and_enforce_circuit_breaker(self) -> bool:
        """
        Evaluates portfolio daily drawdown and engages emergency hard lock if breached.
        Returns True if circuit breaker is engaged / locked, False otherwise.
        """
        is_locked, reason = evaluate_portfolio_circuit_breaker(self)
        if is_locked:
            self._last_event = f"circuit breaker: {reason}"
            if self.config.auto_liquidate_on_circuit_breaker and self.active_positions:
                self._log(
                    f"Engaging emergency liquidation due to circuit breaker breach: {reason}",
                    level=logging.ERROR,
                )
                await self._liquidate_all_positions(reason="circuit_breaker_hard_lock")
            if self.alert_enabled:
                self._send_alert(
                    f"🚨 PORTFOLIO CIRCUIT BREAKER ENGAGED: {reason}. Trading halted for {self.config.emergency_hard_lock_hours:.1f} hours."
                )
            self._write_audit_record(
                "circuit_breaker_triggered",
                {
                    "reason": reason,
                    "tracker": self.daily_equity_tracker.to_dict(),
                },
            )
            self._write_status_snapshot()
            return True
        return False

    def reset_circuit_breaker(self, force: bool = True) -> None:
        """Manually unlocks the portfolio circuit breaker and resumes normal operations."""
        self.daily_equity_tracker.reset_circuit_breaker(force=force)
        self._record_event("circuit breaker manually reset by operator")
        self._write_audit_record(
            "circuit_breaker_reset",
            {"force": force, "tracker": self.daily_equity_tracker.to_dict()},
        )
        if self.alert_enabled:
            self._send_alert(
                "🟢 Circuit Breaker Reset: Normal trading operations restored by operator."
            )
        self._write_status_snapshot()

    def _check_daily_drawdown(self) -> bool:
        return check_daily_drawdown(self)

    def _check_loss_per_trade(
        self, *, mint: str, current_market_cap: float | None = None
    ) -> bool:
        return check_loss_per_trade(
            self, mint=mint, current_market_cap=current_market_cap
        )

    def _health_ok_for_trading(self) -> bool:
        return health_ok_for_trading(self)

    def _mark_health_check(self) -> None:
        mark_health_check(self)

    async def _update_health_state(self) -> None:
        update_health_state(self)

    def get_status_snapshot(self) -> dict[str, Any]:
        return {
            "active_positions": {
                mint: {
                    key: value
                    for key, value in position.items()
                    if key
                    not in {"entry_market_cap", "current_market_cap", "peak_market_cap"}
                }
                | {
                    "entry_market_cap": float(
                        position.get("entry_market_cap", 0.0) or 0.0
                    ),
                    "current_market_cap": float(
                        position.get("current_market_cap", 0.0) or 0.0
                    ),
                    "peak_market_cap": float(
                        position.get(
                            "peak_market_cap", position.get("entry_market_cap", 0.0)
                        )
                        or 0.0
                    ),
                }
                for mint, position in self.active_positions.items()
            },
            "trade_count": len(self.active_positions),
            "stop_requested": self._stop_requested,
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "last_message_at": self._last_message_at,
            "buy_attempts": dict(self._buy_attempts),
            "seen_mints": dict(self._seen_mints),
            "trade_sequence": self._trade_sequence,
            "strategy": self.config.strategy_preset,
            "health_ok": self._health_ok,
            "risk_killed": self._risk_killed,
            "state": self.state.value,
            "recent_actions": list(self._recent_actions),
            "trade_ledger": list(self._trade_ledger[-10:]),
            "exit_retry_queue": dict(self._exit_retry_queue),
            "circuit_breaker_tripped": self._circuit_breaker_tripped,
            "circuit_breaker_engaged": self.daily_equity_tracker.circuit_breaker_engaged,
            "daily_equity": self.daily_equity_tracker.to_dict(),
            "daily_drawdown_pct": self.daily_equity_tracker.calculate_drawdown(
                self.wallet_balance_sol,
                sum(
                    float(pos.get("current_market_cap", 0.0) or 0.0)
                    for pos in self.active_positions.values()
                ),
            ),
            "stream_consecutive_failures": self._stream_consecutive_failures,
            "ws_consecutive_failures": self._ws_consecutive_failures,
            "screening_cache_size": self.screening_cache.size(),
            "enable_anti_rug_filters": self.config.enable_anti_rug_filters,
            "order_flow_tracked_tokens": self.order_flow_engine.tracked_token_count,
            "enable_momentum_signals": self.config.enable_momentum_signals,
        }

    async def _enrich_and_screen_token(
        self, mint: str, token_data: dict[str, Any] | None = None
    ) -> TokenScreeningVerdict:
        if not self.config.enable_anti_rug_filters:
            return TokenScreeningVerdict(
                mint=mint,
                passed=True,
                risk_score=0.0,
                reasons=["Anti-rug filters disabled in strategy configuration."],
            )

        cached_verdict = self.screening_cache.get(mint)
        if cached_verdict is not None:
            return cached_verdict

        coin_data: dict[str, Any] = dict(token_data or {})
        if not coin_data and hasattr(self, "api") and self.api:
            try:
                fetched = await self.api.get_coin(mint)
                if isinstance(fetched, dict):
                    coin_data = fetched
            except Exception as exc:
                self._log(
                    f"Metadata query for {mint} failed during screening: {exc}",
                    level=logging.DEBUG,
                )

        metadata = TokenMetadata.from_dict(coin_data) if coin_data else None

        dev_profile = None
        creator = (
            coin_data.get("creator")
            or coin_data.get("user")
            or coin_data.get("creatorAddress")
            or coin_data.get("dev_wallet")
        )
        if creator and isinstance(creator, str):
            try:
                creator_coins = await self.api.get_creator_coins(creator, limit=20)
                if isinstance(creator_coins, list):
                    now_ms = time.time() * 1000
                    day_ago_ms = now_ms - (86400 * 1000)
                    count_24h = sum(
                        1
                        for c in creator_coins
                        if isinstance(c, dict)
                        and (
                            c.get("created_timestamp", 0) > day_ago_ms
                            or c.get("createdAt", 0) > day_ago_ms
                        )
                    )
                    dev_profile = DevWalletProfile(
                        creator_address=creator,
                        tokens_launched_24h=count_24h or len(creator_coins),
                        total_tokens_launched=len(creator_coins),
                    )
                elif isinstance(creator_coins, dict):
                    coins_list = (
                        creator_coins.get("coins") or creator_coins.get("items") or []
                    )
                    dev_profile = DevWalletProfile(
                        creator_address=creator,
                        tokens_launched_24h=len(coins_list),
                        total_tokens_launched=len(coins_list),
                    )
            except Exception as exc:
                self._log(
                    f"Creator profile query for {creator} failed: {exc}",
                    level=logging.DEBUG,
                )
                dev_profile = DevWalletProfile(creator_address=str(creator))

        bonding_curve_pda = None
        if hasattr(self, "execution") and self.execution:
            try:
                pda, _ = self.execution.get_bonding_curve_pda(mint)
                bonding_curve_pda = str(pda)
            except Exception:
                pass

        holder_distribution = None
        holders_data = coin_data.get("holders") or coin_data.get("topHolders")
        creator_holding_val = (
            coin_data.get("creatorHoldingPct")
            or coin_data.get("creator_holding_pct")
            or coin_data.get("creatorPct")
            or coin_data.get("dev_holding_pct")
        )
        creator_pct = (
            float(creator_holding_val) if creator_holding_val is not None else None
        )

        if isinstance(holders_data, list):
            top_holders_list = []
            for h in holders_data:
                if isinstance(h, dict):
                    w = str(h.get("address") or h.get("wallet") or "")
                    amt = int(h.get("amount") or h.get("balance") or 0)
                    if w:
                        top_holders_list.append((w, amt))
            total_supply = int(
                coin_data.get("totalSupply")
                or coin_data.get("total_supply")
                or 1_000_000_000_000_000
            )
            holder_distribution = HolderDistribution(
                total_supply=total_supply,
                creator_initial_pct=creator_pct,
                bonding_curve_address=bonding_curve_pda,
                top_holders=top_holders_list,
            )
        elif creator_pct is not None:
            holder_distribution = HolderDistribution(
                creator_initial_pct=creator_pct,
                bonding_curve_address=bonding_curve_pda,
            )

        verdict = self.strategy.screen_token(
            mint,
            metadata=metadata,
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            bonding_curve_pda=bonding_curve_pda,
            cache=self.screening_cache,
            use_cache=True,
        )

        if verdict.passed:
            self._log(
                f"Anti-rug screening PASSED for {mint} | risk score: {verdict.risk_score:.1f}/100"
            )
        else:
            self._log(
                f"Anti-rug screening REJECTED {mint} | risk score: {verdict.risk_score:.1f}/100 | reasons: {verdict.reasons}",
                level=logging.WARNING,
            )
            self._record_event(
                f"screen_rejected {mint[:8]} (score: {verdict.risk_score:.1f})"
            )

        return verdict

    def _should_buy(
        self,
        mint: str,
        market_cap_sol: float,
        screening_verdict: TokenScreeningVerdict | None = None,
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
        if not self._check_risk_limits(
            mint=mint,
            proposed_entry_sol=self.buy_amount_sol,
            current_positions=self.active_positions,
        ):
            return False
        return self._buy_attempts.get(mint, 0) < self.max_buy_attempts_per_mint

    async def _buy_token(
        self,
        mint: str,
        market_cap_sol: float,
        token_name: str | None = None,
        screening_verdict: TokenScreeningVerdict | None = None,
        reason: str | None = None,
    ) -> bool:
        if not self._should_buy(
            mint, market_cap_sol, screening_verdict=screening_verdict
        ):
            return False

        self._transition_to(TradingBotState.BUYING, reason=f"buying {mint}")
        if not await self._check_account_equity_guard(required_sol=self.buy_amount_sol):
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
        position_name = (
            resolved_name or self.active_positions.get(mint, {}).get("name") or mint
        ).strip() or mint
        if self.dry_run:
            self._log(f"DRY RUN BUY: {mint} @ {self.buy_amount_sol} SOL")
            self.active_positions[mint] = {
                "name": position_name,
                "entry_market_cap": float(market_cap_sol or 30.0),
                "current_market_cap": float(market_cap_sol or 30.0),
                "peak_market_cap": float(market_cap_sol or 30.0),
                "initial_token_amount": 100_000_000,
                "remaining_token_amount": 100_000_000,
                "token_amount": 100_000_000,
                "dry_run": True,
                "entry_reason": reason or "dry_run",
            }
            self._mark_seen(mint)
            self._last_event = f"dry-run buy for {mint}"
            self._record_trade(
                mint=mint,
                action="buy",
                token_name=position_name,
                mint_name=position_name,
                entry=self.buy_amount_sol,
                reason=reason or "dry_run",
            )
            self._transition_to(TradingBotState.HOLDING, reason=f"dry_run_buy {mint}")
            return True

        try:
            bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
        except Exception as exc:
            self._log(
                f"Could not compute bonding curve PDA for {mint}: {exc}",
                level=logging.WARNING,
            )
            self._transition_to(
                TradingBotState.MONITORING, reason=f"buy_pda_failed {mint}"
            )
            return False

        self._log(f"Buying {mint} with {self.buy_amount_sol} SOL")
        self._last_event = f"buying {mint}"
        try:
            signature = await self.execution.buy(
                mint, bonding_curve, self.buy_amount_sol
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(
                f"Buy transaction failed for {mint}: {exc}", level=logging.WARNING
            )
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_failed {mint}")
            return False

        if not signature:
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING, reason=f"buy_signature_missing {mint}"
            )
            return False

        confirmed = await self.execution.confirm_transaction(signature)
        if not confirmed:
            self._log(f"Buy confirmation failed for {mint}", level=logging.WARNING)
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(
                TradingBotState.MONITORING, reason=f"buy_confirmation_failed {mint}"
            )
            return False

        self.active_positions[mint] = {
            "name": position_name,
            "entry_market_cap": float(market_cap_sol or 30.0),
            "current_market_cap": float(market_cap_sol or 30.0),
            "peak_market_cap": float(market_cap_sol or 30.0),
            "initial_token_amount": 0,
            "remaining_token_amount": 0,
            "token_amount": 0,
            "buy_signature": signature,
            "first_seen": time.monotonic(),
            "entry_reason": reason or "entry",
        }
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
            entry=self.buy_amount_sol,
            reason=reason or "entry",
        )
        self._transition_to(TradingBotState.HOLDING, reason=f"buy_confirmed {mint}")
        return True

    def _enqueue_exit_retry(self, mint: str, *, reason: str = "") -> None:
        """Enqueue a failed exit order for retry with escalating slippage (BUG-08)."""
        if mint not in self.active_positions:
            return
        entry = self._exit_retry_queue.get(mint, {})
        retries = int(entry.get("retry_count", 0)) + 1
        escalated_slippage = min(
            self.base_exit_slippage_bps + (retries * 500), self.max_exit_slippage_bps
        )
        backoff_delay = min(2.0**retries, 30.0)
        self._exit_retry_queue[mint] = {
            "mint": mint,
            "retry_count": retries,
            "next_retry_at": time.monotonic() + backoff_delay,
            "slippage_bps": escalated_slippage,
            "reason": reason,
        }
        self._record_retry()
        self._record_failure(category="exit_order")
        self._log(
            f"Enqueued exit retry #{retries} for {mint} in {backoff_delay:.1f}s with slippage {escalated_slippage} bps (reason: {reason})",
            level=logging.WARNING,
        )
        if retries >= self.max_exit_retries:
            self._log(
                f"Max exit retries reached ({retries}) for {mint}; escalating to emergency liquidation mode",
                level=logging.ERROR,
            )
            self._send_alert(
                f"⚠️ Urgent: Exit failed {retries} times for {mint}. Max slippage liquidation scheduled."
            )

    async def _process_exit_retry_queue(self, websocket: Any = None) -> None:
        """Process pending exit retries whose backoff has expired (BUG-08)."""
        if not self._exit_retry_queue:
            return
        now = time.monotonic()
        for mint, item in list(self._exit_retry_queue.items()):
            if now >= item.get("next_retry_at", 0):
                self._log(
                    f"Executing scheduled exit retry for {mint} (attempt {item.get('retry_count')})"
                )
                success = await self._sell_token(
                    mint,
                    slippage_bps=item.get("slippage_bps"),
                    retry_count=item.get("retry_count", 0),
                )
                if success:
                    await self._unsubscribe_from_token_trades(websocket, mint)

    async def reconcile_onchain_positions(self) -> dict[str, Any]:
        """Reconcile active positions against on-chain wallet token accounts (BUG-07)."""
        if self.dry_run or self.paper_trade:
            return {}

        self._log("Reconciling active positions against on-chain wallet balances...")
        reconciled: dict[str, Any] = {}
        for mint, position in list(self.active_positions.items()):
            try:
                balance = await self.execution.get_token_balance(mint)
            except Exception as exc:
                self._log(
                    f"Startup reconciliation: failed to read token balance for {mint}: {exc}",
                    level=logging.WARNING,
                )
                continue

            if balance <= self.min_sell_balance:
                self._log(
                    f"Startup reconciliation: position {mint} has non-actionable on-chain balance ({balance}). Purging stale position.",
                    level=logging.INFO,
                )
                pos_name = self.active_positions.get(mint, {}).get("name")
                self.active_positions.pop(mint, None)
                self._exit_retry_queue.pop(mint, None)
                self._record_trade(
                    mint=mint,
                    action="reconciled_closed",
                    token_name=pos_name,
                    mint_name=pos_name,
                    entry=0.0,
                    reason="startup_zero_balance_reconciliation",
                )
                self._recent_events.append(f"reconciled {mint[:8]} (closed)")
                reconciled[mint] = {"status": "purged", "balance": balance}
            else:
                position["token_amount"] = balance
                position["remaining_token_amount"] = balance
                if int(position.get("initial_token_amount", 0) or 0) <= 0:
                    position["initial_token_amount"] = balance
                try:
                    curve_state = await self.execution.get_bonding_curve_state(mint)
                    mc = float(curve_state.get("market_cap_sol", 0.0) or 0.0)
                    if mc > 0:
                        position["current_market_cap"] = mc
                        entry_mc = float(position.get("entry_market_cap", 0.0) or mc)
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
        if self.dry_run:
            initial_tokens = int(
                position.get("initial_token_amount")
                or position.get("token_amount")
                or 100_000_000
            )
            rem_tokens = int(
                position.get("remaining_token_amount")
                or position.get("token_amount")
                or initial_tokens
            )
            position["initial_token_amount"] = initial_tokens

            if sell_amount_tokens is not None and sell_amount_tokens > 0:
                tokens_to_sell = min(sell_amount_tokens, rem_tokens)
            elif sell_fraction < 1.0:
                tokens_to_sell = int(initial_tokens * sell_fraction)
                tokens_to_sell = max(1, min(tokens_to_sell, rem_tokens))
            else:
                tokens_to_sell = rem_tokens

            remaining_after = rem_tokens - tokens_to_sell
            is_partial = (tokens_to_sell < rem_tokens) and (
                remaining_after > self.min_sell_balance
            )

            if is_partial:
                position["remaining_token_amount"] = remaining_after
                position["token_amount"] = remaining_after
                if target_tier == 1:
                    position["tier_1_executed"] = True
                elif target_tier == 2:
                    position["tier_2_executed"] = True
                    position["moonbag_active"] = True

                entry_sol = float(
                    position.get("entry_market_cap", self.config.buy_amount_sol)
                    or self.config.buy_amount_sol
                )
                current_mc = float(
                    position.get("current_market_cap", entry_sol) or entry_sol
                )
                pnl = (current_mc - entry_sol) * sell_fraction
                self.daily_equity_tracker.record_realized_trade(pnl)

                self._log(
                    f"DRY RUN PARTIAL SELL: {tokens_to_sell} units of {mint} (remaining: {remaining_after}, reason: {reason})"
                )
                self._last_event = f"dry-run partial sell for {mint}"
                self._record_trade(
                    mint=mint,
                    action="partial_sell",
                    token_name=pos_name,
                    mint_name=pos_name,
                    entry=0.0,
                    reason=reason,
                )
                self._transition_to(
                    TradingBotState.HOLDING, reason=f"dry_run_partial_sell {mint}"
                )
                return True

            entry_sol = float(
                position.get("entry_market_cap", self.config.buy_amount_sol)
                or self.config.buy_amount_sol
            )
            current_mc = float(
                position.get("current_market_cap", entry_sol) or entry_sol
            )
            pnl = current_mc - entry_sol
            self.daily_equity_tracker.record_realized_trade(pnl)

            self._log(f"DRY RUN SELL: {mint} (reason: {reason})")
            self._last_event = f"dry-run sell for {mint}"
            self.active_positions.pop(mint, None)
            self._exit_retry_queue.pop(mint, None)
            self._record_trade(
                mint=mint,
                action="sell",
                token_name=pos_name,
                mint_name=pos_name,
                entry=0.0,
                reason=reason,
            )
            self._transition_to(
                TradingBotState.MONITORING, reason=f"dry_run_sell {mint}"
            )
            return True

        try:
            token_balance = await self.execution.get_token_balance(mint)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(
                f"Unable to fetch token balance for {mint}: {exc}",
                level=logging.WARNING,
            )
            self._enqueue_exit_retry(mint, reason=f"balance_fetch_error: {exc}")
            self._transition_to(
                TradingBotState.HOLDING, reason=f"sell_balance_failed {mint}"
            )
            return False

        if token_balance <= self.min_sell_balance:
            self._log(
                f"No actionable balance for {mint}; current balance={token_balance}"
            )
            self.active_positions.pop(mint, None)
            self._exit_retry_queue.pop(mint, None)
            self._transition_to(
                TradingBotState.MONITORING, reason=f"sell_zero_balance {mint}"
            )
            return True

        initial_tokens = int(position.get("initial_token_amount") or token_balance)
        if initial_tokens <= 0:
            initial_tokens = token_balance
        position["initial_token_amount"] = initial_tokens

        if sell_amount_tokens is not None and sell_amount_tokens > 0:
            tokens_to_sell = min(sell_amount_tokens, token_balance)
        elif sell_fraction < 1.0:
            tokens_to_sell = int(initial_tokens * sell_fraction)
            tokens_to_sell = max(1, min(tokens_to_sell, token_balance))
        else:
            tokens_to_sell = token_balance

        rem = token_balance - tokens_to_sell
        is_partial = (rem > self.min_sell_balance) and (tokens_to_sell < token_balance)
        if not is_partial:
            tokens_to_sell = token_balance

        try:
            bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
        except Exception as exc:
            self._log(
                f"Could not compute bonding curve PDA for sell on {mint}: {exc}",
                level=logging.WARNING,
            )
            self._enqueue_exit_retry(mint, reason=f"pda_error: {exc}")
            self._transition_to(
                TradingBotState.HOLDING, reason=f"sell_pda_failed {mint}"
            )
            return False

        # Compute minimum expected SOL output in Lamports (BUG-01 & BUG-03)
        effective_slippage_bps = (
            slippage_bps
            if slippage_bps is not None
            else self.execution.default_slippage_bps
        )
        min_sol_output_lamports = 0
        try:
            curve_state = await self.execution.get_bonding_curve_state(mint)
            v_token = int(curve_state.get("virtual_token_reserves", 0))
            v_sol = int(curve_state.get("virtual_sol_reserves", 0))
            if v_token > 0 and v_sol > 0:
                min_sol_output_lamports = self.execution.calculate_sell_sol_output(
                    tokens_to_sell,
                    v_token,
                    v_sol,
                    slippage_bps=effective_slippage_bps,
                )
        except Exception as exc:
            self._log(
                f"Could not compute on-chain curve sell output for {mint}: {exc}; using default slippage",
                level=logging.DEBUG,
            )

        self._log(
            f"Selling {tokens_to_sell} units of {mint} (min_sol_lamports={min_sol_output_lamports}, slippage_bps={effective_slippage_bps}, partial={is_partial}, reason={reason})"
        )
        self._last_event = f"selling {mint}"
        try:
            if getattr(self, "use_jito", False) and hasattr(
                self.execution, "send_jito_bundle_with_fallback"
            ):
                signature = await self.execution.send_jito_bundle_with_fallback(
                    mint=mint,
                    bonding_curve=bonding_curve,
                    amount_sol_or_tokens=tokens_to_sell,
                    is_buy=False,
                    min_sol_output=min_sol_output_lamports,
                )
            else:
                signature = await self.execution.sell(
                    mint,
                    bonding_curve,
                    tokens_to_sell,
                    min_sol_output=min_sol_output_lamports,
                )
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(
                f"Sell transaction failed for {mint}: {exc}", level=logging.WARNING
            )
            self._enqueue_exit_retry(mint, reason=f"tx_send_error: {exc}")
            self._transition_to(
                TradingBotState.HOLDING, reason=f"sell_transaction_failed {mint}"
            )
            return False

        if not signature:
            self._enqueue_exit_retry(mint, reason="missing_signature")
            self._transition_to(
                TradingBotState.HOLDING, reason=f"sell_missing_signature {mint}"
            )
            return False

        confirmed = await self.execution.confirm_transaction(signature)
        if not confirmed:
            self._log(f"Sell confirmation failed for {mint}", level=logging.WARNING)
            self._enqueue_exit_retry(mint, reason="confirmation_failed")
            self._transition_to(
                TradingBotState.HOLDING, reason=f"sell_confirmation_failed {mint}"
            )
            return False

        sold_sol = (
            min_sol_output_lamports / 1_000_000_000.0
            if min_sol_output_lamports
            else 0.0
        )

        if is_partial:
            position["remaining_token_amount"] = rem
            position["token_amount"] = rem
            if target_tier == 1:
                position["tier_1_executed"] = True
            elif target_tier == 2:
                position["tier_2_executed"] = True
                position["moonbag_active"] = True

            cost_basis = float(self.config.buy_amount_sol * sell_fraction)
            self.daily_equity_tracker.record_realized_trade(sold_sol - cost_basis)

            self._record_trade(
                mint=mint,
                action="partial_sell",
                token_name=pos_name,
                mint_name=pos_name,
                entry=sold_sol,
                reason=reason,
            )
            self._transition_to(
                TradingBotState.HOLDING, reason=f"partial_sell_complete {mint}"
            )
            return True

        self.active_positions.pop(mint, None)
        self._exit_retry_queue.pop(mint, None)
        self.daily_equity_tracker.record_realized_trade(
            sold_sol - float(self.config.buy_amount_sol)
        )
        self._record_trade(
            mint=mint,
            action="sell",
            token_name=pos_name,
            mint_name=pos_name,
            entry=sold_sol,
            reason=reason,
        )
        self._transition_to(TradingBotState.MONITORING, reason=f"sell_complete {mint}")
        return True

    async def _evaluate_and_execute_exit(
        self, mint: str, current_market_cap: float, websocket: Any = None
    ) -> bool:
        if mint not in self.active_positions:
            return False

        position = self.active_positions[mint]
        position["current_market_cap"] = current_market_cap
        entry_market_cap = float(position.get("entry_market_cap") or current_market_cap)
        if entry_market_cap <= 0:
            entry_market_cap = current_market_cap
            position["entry_market_cap"] = entry_market_cap

        peak_mc = float(
            position.get("peak_market_cap", max(entry_market_cap, current_market_cap))
            or max(entry_market_cap, current_market_cap)
        )
        if current_market_cap > peak_mc:
            peak_mc = current_market_cap
        position["peak_market_cap"] = peak_mc

        performance = (
            current_market_cap / entry_market_cap if entry_market_cap > 0 else 1.0
        )

        exit_state = PositionExitState.from_dict(position)
        exit_decision = evaluate_exit_strategy(
            self.config, exit_state, current_market_cap=current_market_cap
        )

        peak_ratio = peak_mc / entry_market_cap if entry_market_cap > 0 else 1.0
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

        if mint in self.active_positions:
            await self._evaluate_and_execute_exit(mint, current_market_cap)
            await self._check_and_enforce_circuit_breaker()
            return

        # New token launch candidate
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
            await self._evaluate_and_execute_exit(mint, current_market_cap)
            await self._check_and_enforce_circuit_breaker()
            return

        # Token is not in active positions - evaluate order flow momentum breakout
        if not self.config.enable_momentum_signals:
            return

        if (
            self.daily_equity_tracker.circuit_breaker_engaged
            or await self._check_and_enforce_circuit_breaker()
        ):
            return

        if self._is_recently_seen(mint):
            return

        if self._buy_attempts.get(mint, 0) >= self.max_buy_attempts_per_mint:
            return

        if len(self.active_positions) >= self.max_active_positions:
            return

        signal = self.strategy.evaluate_momentum(
            self.order_flow_engine,
            mint,
            current_time=ts,
        )

        if signal.triggered:
            self._log(
                f"Momentum breakout detected for {mint}: Z-score={signal.z_score:.2f}, buy_ratio={signal.buy_sell_ratio:.2f}, unique_buyers={signal.unique_buyers}, net_inflow={signal.net_sol_inflow:.2f} SOL",
                level=logging.INFO,
            )
            async with self._trade_lock:
                if (
                    self._is_recently_seen(mint)
                    or len(self.active_positions) >= self.max_active_positions
                    or mint in self.active_positions
                ):
                    return

                screening_verdict = await self._enrich_and_screen_token(mint)
                if not screening_verdict.passed:
                    self._log(
                        f"Skipping momentum token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                    )
                    self._last_event = f"screen_rejected {mint[:8]}"
                    return

                if not self.strategy.validate_risk(
                    current_positions=self.active_positions,
                    proposed_entry_sol=self.buy_amount_sol,
                    wallet_balance_sol=self.wallet_balance_sol,
                ):
                    self._log(f"Skipping momentum token {mint}: risk limits exceeded")
                    return

                token_name = mint[:8]
                self._last_event = f"momentum {mint[:8]}"
                self._last_new_token = mint
                self._last_new_token_name = token_name
                bought = await self._buy_token(
                    mint,
                    current_market_cap or 30.0,
                    token_name,
                    screening_verdict=screening_verdict,
                    reason="momentum_spike",
                )
                if bought:
                    self._record_event(f"bought momentum {mint[:8]}")

    async def _handle_complete_event_update(self, update: CompleteEventUpdate) -> None:
        if self._stop_requested:
            return
        mint = update.mint
        if mint in self.active_positions:
            self._log(
                f"Bonding curve completed / graduated for {mint}. Triggering exit."
            )
            self._last_event = f"graduated {mint}"
            await self._sell_token(mint, reason="bonding_curve_graduated")

    async def _handle_new_token_event(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        if self._stop_requested:
            return

        if (
            self.daily_equity_tracker.circuit_breaker_engaged
            or await self._check_and_enforce_circuit_breaker()
        ):
            self._last_event = "circuit_breaker_active"
            return

        mint_value = data.get("mint")
        if not mint_value:
            return
        mint = self.validate_mint_address(str(mint_value))
        market_cap_sol = float(
            data.get("marketCapSol") or data.get("marketCap") or 30.0
        )
        token_name = (
            str(
                data.get("name")
                or data.get("tokenName")
                or data.get("displayName")
                or ""
            ).strip()
            or None
        )

        async with self._trade_lock:
            if self._is_recently_seen(mint):
                return

            screening_verdict = await self._enrich_and_screen_token(
                mint, token_data=data
            )
            if not screening_verdict.passed:
                self._log(
                    f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                )
                self._last_event = f"screen_rejected {mint[:8]}"
                return

            if not self._should_buy(
                mint, market_cap_sol, screening_verdict=screening_verdict
            ):
                self._log(f"Skipping new token {mint}: not eligible for buy")
                self._last_event = f"skipped {mint}"
                return

            self._log(
                f"New token detected: {mint} | launch market cap: {market_cap_sol:.2f} SOL"
            )
            self._last_event = f"new token {mint}"
            self._last_new_token = mint
            self._last_new_token_name = token_name
            bought = await self._buy_token(
                mint,
                market_cap_sol,
                token_name,
                screening_verdict=screening_verdict,
            )

        if bought:
            self._record_event(
                f"bought {self.active_positions.get(mint, {}).get('name', mint)}"
            )

    async def _handle_trade_update(
        self, data: dict[str, Any], websocket: Any = None
    ) -> None:
        if self._stop_requested:
            return

        mint_value = data.get("mint")
        if not mint_value or not isinstance(mint_value, str):
            return

        mint = self.validate_mint_address(mint_value)

        # Record trade into order flow engine if trade payload is present
        if "txType" in data or "solAmount" in data or "sol_amount" in data:
            is_buy = data.get("txType") == "buy" or bool(data.get("is_buy", True))
            sol_amount = float(data.get("solAmount") or data.get("sol_amount") or 0.0)
            user = str(data.get("user") or data.get("traderPublicKey") or "")
            ts = float(data.get("timestamp") or time.time())
            self.order_flow_engine.record_trade(
                mint=mint,
                is_buy=is_buy,
                sol_amount=sol_amount,
                user=user,
                timestamp=ts,
            )

        if mint not in self.active_positions:
            return

        current_market_cap = float(
            data.get("marketCapSol") or data.get("marketCap") or 0.0
        )
        if current_market_cap <= 0:
            return

        if not self.dry_run:
            try:
                curve_state = await self.execution.get_bonding_curve_state(mint)
                on_chain_mc = float(curve_state.get("market_cap_sol", 0.0))
                if on_chain_mc > 0:
                    current_market_cap = on_chain_mc
            except Exception:
                pass

        await self._evaluate_and_execute_exit(
            mint, current_market_cap, websocket=websocket
        )

    async def _handle_message(self, data: Any, websocket: Any = None) -> None:
        if not isinstance(data, dict):
            return

        self._last_message_at = time.monotonic()
        self._last_status = "processing stream event"
        if data.get("txType") == "create" or data.get("event") == "new_token":
            await self._handle_new_token_event(data, websocket)
            return

        if "marketCapSol" in data or "marketCap" in data:
            await self._handle_trade_update(data, websocket)

    async def start(self) -> None:
        """Run the live monitor loop using Yellowstone Geyser on-chain streaming."""
        self._register_signal_handlers()
        self._log(
            "TradingBot started. Monitoring Yellowstone Geyser on-chain stream..."
        )
        self._last_status = "connecting to geyser stream"
        self._transition_to(TradingBotState.MONITORING, reason="start_monitoring")

        # Perform on-chain position reconciliation at startup (BUG-07)
        try:
            await self.reconcile_onchain_positions()
        except Exception as exc:
            self._log(
                f"On-chain reconciliation error during startup: {exc}",
                level=logging.WARNING,
            )

        backoff = self.reconnect_delay_seconds
        use_screen = bool(self.console.is_terminal)

        # Start Yellowstone Geyser streaming client worker
        await self.geyser_client.start()

        with Live(
            self._render_dashboard(),
            console=self.console,
            refresh_per_second=2,
            transient=True,
            screen=use_screen,
            vertical_overflow="visible",
        ) as live:

            self._display_live = live
            while not self._stop_requested:
                try:
                    self._last_status = "stream connected"
                    live.update(self._render_dashboard(), refresh=True)

                    async for event in self.geyser_client.listen():
                        if self._stop_requested:
                            break

                        self._stream_consecutive_failures = 0
                        if self._circuit_breaker_tripped:
                            self._circuit_breaker_tripped = False
                            self._health_ok = True
                            self._log(
                                "Geyser stream restored. Circuit breaker reset.",
                                level=logging.INFO,
                            )
                        backoff = self.reconnect_delay_seconds

                        if isinstance(event, BondingCurveStateUpdate):
                            await self._handle_bonding_curve_state_update(event)
                        elif isinstance(event, TradeEventUpdate):
                            await self._handle_trade_event_update(event)
                        elif isinstance(event, CompleteEventUpdate):
                            await self._handle_complete_event_update(event)
                        elif isinstance(event, dict):
                            await self._handle_message(event)

                        await self._process_exit_retry_queue()

                        if (
                            time.monotonic() - self._last_message_at
                            > self.config.health_check_timeout_seconds
                        ):
                            self._last_status = "heartbeat timeout"

                        update_health_state(self)
                        live.update(self._render_dashboard(), refresh=True)

                except asyncio.CancelledError:
                    self._log("TradingBot shutdown requested.")
                    self._last_status = "shutdown requested"
                    break
                except Exception as exc:  # pragma: no cover - defensive branch
                    self._stream_consecutive_failures += 1
                    self._record_connection_loss()
                    self._log(
                        f"Stream error: {exc}. Reconnecting (attempt {self._stream_consecutive_failures}).",
                        level=logging.WARNING,
                    )

                if self._stop_requested:
                    break

                # Circuit breaker transition (BUG-06)
                if (
                    self._stream_consecutive_failures
                    >= self._max_stream_consecutive_failures
                ):
                    self._circuit_breaker_tripped = True
                    self._health_ok = False
                    self._last_status = "degraded: stream circuit breaker active"
                    self._log(
                        f"Geyser stream circuit breaker tripped after {self._stream_consecutive_failures} failures. Bot transitioned to degraded state.",
                        level=logging.ERROR,
                    )
                    self._send_alert(
                        f"⚠️ Circuit Breaker Active: Stream connection lost {self._stream_consecutive_failures} times. Trading halted."
                    )

                # Exponential backoff with jitter (BUG-06)
                jitter = random.uniform(0.85, 1.25)
                sleep_delay = min(backoff * jitter, 60.0)
                self._last_status = f"reconnecting in {sleep_delay:.1f}s (attempt {self._stream_consecutive_failures})"
                live.update(self._render_dashboard(), refresh=True)
                await asyncio.sleep(sleep_delay)
                backoff = min(backoff * 2.0, 60.0)
                await self._process_exit_retry_queue()

        await self.geyser_client.stop()
        self._log("TradingBot shutdown complete.")
        self._transition_to(TradingBotState.SHUTDOWN, reason="loop_exited")

    async def close(self) -> None:
        self.request_shutdown()
        if hasattr(self, "geyser_client") and self.geyser_client is not None:
            try:
                await self.geyser_client.stop()
            except Exception:
                pass
        if hasattr(self, "execution") and self.execution is not None:
            try:
                await self.execution.close()
            except Exception:
                pass
        if self._audit_handle is not None:
            self._audit_handle.close()
            self._audit_handle = None
        await self.api.close()


async def main() -> None:
    bot = TradingBot.from_env()
    try:
        await bot.start()
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
