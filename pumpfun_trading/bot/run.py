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

import websockets
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
    check_daily_drawdown,
    check_loss_per_trade,
    check_risk_limits,
)
from pumpfun_trading.bot.strategy import TradingBotConfig, resolve_strategy_config
from pumpfun_trading.execution.builder import build_execution_client
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
        stream_url: str = "wss://pumpportal.fun/api/data",
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
            max_daily_drawdown_pct=float(getattr(base, "max_daily_drawdown_pct", 0.2)),
            reserve_balance_sol=float(getattr(base, "reserve_balance_sol", 0.1)),
            health_check_timeout_seconds=int(
                getattr(base, "health_check_timeout_seconds", 60)
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
        self.active_positions: dict[str, dict[str, Any]] = {}
        self._buy_attempts: dict[str, int] = {}
        self._seen_mints: dict[str, float] = {}
        self.console = get_configured_console(file=sys.stdout)

        self._ws_consecutive_failures = 0
        self._circuit_breaker_tripped = False
        self._max_ws_consecutive_failures = int(
            os.getenv("PUMPFUN_WS_MAX_RETRIES", "5")
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
        self.execution = build_execution_client(
            private_key_b58=self.private_key_b58,
            rpc_url=self.rpc_url,
            priority_fee_lamports=int(
                os.getenv("PUMPFUN_PRIORITY_FEE_LAMPORTS", "5000")
            ),
            compute_unit_limit=int(os.getenv("PUMPFUN_COMPUTE_UNIT_LIMIT", "200000")),
            jito_tip_lamports=int(os.getenv("PUMPFUN_JITO_TIP_LAMPORTS", "0")),
            jito_block_engine_url=os.getenv("PUMPFUN_JITO_BLOCK_ENGINE_URL"),
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
                    if key not in {"entry_market_cap", "current_market_cap"}
                }
                normalized["entry_market_cap"] = float(
                    position.get("entry_market_cap", 0.0) or 0.0
                )
                normalized["current_market_cap"] = float(
                    position.get("current_market_cap", 0.0) or 0.0
                )
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
        elif action == "sell":
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

    async def _unsubscribe_from_token_trades(self, websocket, mint: str) -> None:
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
                    if key not in {"entry_market_cap", "current_market_cap"}
                }
                | {
                    "entry_market_cap": float(
                        position.get("entry_market_cap", 0.0) or 0.0
                    ),
                    "current_market_cap": float(
                        position.get("current_market_cap", 0.0) or 0.0
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
            "ws_consecutive_failures": self._ws_consecutive_failures,
        }

    def _should_buy(self, mint: str, market_cap_sol: float) -> bool:
        if not self._health_ok_for_trading():
            return False
        if self._is_recently_seen(mint):
            return False
        if mint in self.active_positions:
            return False
        if len(self.active_positions) >= self.max_active_positions:
            return False
        if market_cap_sol < self.min_market_cap_sol:
            return False
        if not self._check_risk_limits(
            mint=mint,
            proposed_entry_sol=self.buy_amount_sol,
            current_positions=self.active_positions,
        ):
            return False
        return self._buy_attempts.get(mint, 0) < self.max_buy_attempts_per_mint

    async def _buy_token(
        self, mint: str, market_cap_sol: float, token_name: str | None = None
    ) -> bool:
        if not self._should_buy(mint, market_cap_sol):
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
                "dry_run": True,
            }
            self._mark_seen(mint)
            self._last_event = f"dry-run buy for {mint}"
            self._record_trade(
                mint=mint,
                action="buy",
                token_name=position_name,
                mint_name=position_name,
                entry=self.buy_amount_sol,
                reason="dry_run",
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
            "buy_signature": signature,
            "first_seen": time.monotonic(),
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
            reason="entry",
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
                if success and websocket is not None:
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
                try:
                    curve_state = await self.execution.get_bonding_curve_state(mint)
                    mc = float(curve_state.get("market_cap_sol", 0.0) or 0.0)
                    if mc > 0:
                        position["current_market_cap"] = mc
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
        slippage_bps: int | None = None,
        retry_count: int = 0,
    ) -> bool:
        if mint not in self.active_positions:
            self._exit_retry_queue.pop(mint, None)
            return False

        self._transition_to(TradingBotState.SELLING, reason=f"selling {mint}")
        if self.dry_run:
            self._log(f"DRY RUN SELL: {mint}")
            self._last_event = f"dry-run sell for {mint}"
            self.active_positions.pop(mint, None)
            self._exit_retry_queue.pop(mint, None)
            self._record_metric("sells")
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
                    token_balance,
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
            f"Selling {token_balance} units of {mint} (min_sol_lamports={min_sol_output_lamports}, slippage_bps={effective_slippage_bps})"
        )
        self._last_event = f"selling {mint}"
        try:
            signature = await self.execution.sell(
                mint,
                bonding_curve,
                token_balance,
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

        pos_name = self.active_positions.get(mint, {}).get("name")
        self.active_positions.pop(mint, None)
        self._exit_retry_queue.pop(mint, None)
        self._record_metric("sells")
        self._record_trade(
            mint=mint,
            action="sell",
            token_name=pos_name,
            mint_name=pos_name,
            entry=(
                min_sol_output_lamports / 1_000_000_000.0
                if min_sol_output_lamports
                else 0.0
            ),
            reason="exit_confirmed",
        )
        self._transition_to(TradingBotState.MONITORING, reason=f"sell_complete {mint}")
        return True

    async def _handle_new_token_event(self, data: dict[str, Any], websocket) -> None:
        if self._stop_requested:
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

            if not self._should_buy(mint, market_cap_sol):
                self._log(f"Skipping new token {mint}: not eligible for buy")
                self._last_event = f"skipped {mint}"
                return

            self._log(
                f"New token detected: {mint} | launch market cap: {market_cap_sol:.2f} SOL"
            )
            self._last_event = f"new token {mint}"
            self._last_new_token = mint
            self._last_new_token_name = token_name
            bought = await self._buy_token(mint, market_cap_sol, token_name)

        if bought:
            self._record_event(
                f"bought {self.active_positions.get(mint, {}).get('name', mint)}"
            )

    async def _handle_trade_update(self, data: dict[str, Any], websocket) -> None:
        if self._stop_requested:
            return

        mint_value = data.get("mint")
        if not mint_value or not isinstance(mint_value, str):
            return

        mint = self.validate_mint_address(mint_value)
        if mint not in self.active_positions:
            return

        current_market_cap = float(
            data.get("marketCapSol") or data.get("marketCap") or 0.0
        )
        if current_market_cap <= 0:
            return

        position = self.active_positions[mint]
        if not self.dry_run:
            try:
                curve_state = await self.execution.get_bonding_curve_state(mint)
                on_chain_mc = float(curve_state.get("market_cap_sol", 0.0))
                if on_chain_mc > 0:
                    current_market_cap = on_chain_mc
            except Exception:
                pass
        position["current_market_cap"] = current_market_cap
        entry_market_cap = float(position.get("entry_market_cap") or current_market_cap)
        performance = (
            current_market_cap / entry_market_cap if entry_market_cap > 0 else 1.0
        )

        self._log(
            f"Monitoring {mint[:8]}... | current MC {current_market_cap:.2f} SOL | performance {performance:.2%}"
        )
        self._last_event = f"tracking {mint[:8]}... ({performance:.2%})"

        if performance >= self.take_profit:
            self._log(f"Take profit hit for {mint}: {performance:.2%}")
            self._last_event = f"take profit {mint}"
            if await self._sell_token(mint):
                await self._unsubscribe_from_token_trades(websocket, mint)
        elif performance <= self.stop_loss:
            self._log(f"Stop loss hit for {mint}: {performance:.2%}")
            self._last_event = f"stop loss {mint}"
            if await self._sell_token(mint):
                await self._unsubscribe_from_token_trades(websocket, mint)

    async def _handle_message(self, data: Any, websocket) -> None:
        if not isinstance(data, dict):
            return

        self._last_message_at = time.monotonic()
        self._last_status = "processing websocket event"
        if data.get("txType") == "create" or data.get("event") == "new_token":
            await self._handle_new_token_event(data, websocket)
            return

        if "marketCapSol" in data or "marketCap" in data:
            await self._handle_trade_update(data, websocket)

    async def start(self) -> None:
        """Run the live monitor loop, reconnecting automatically on network failure."""
        self._register_signal_handlers()
        self._log("TradingBot started. Monitoring for new Pump.fun launches...")
        self._last_status = "connecting to websocket"
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
                    async with websockets.connect(
                        self.stream_url, ping_interval=20, ping_timeout=20
                    ) as websocket:
                        self._last_status = "stream connected"
                        self._ws_consecutive_failures = 0
                        if self._circuit_breaker_tripped:
                            self._circuit_breaker_tripped = False
                            self._health_ok = True
                            self._log(
                                "WebSocket stream restored. Circuit breaker reset.",
                                level=logging.INFO,
                            )
                        backoff = self.reconnect_delay_seconds
                        live.update(self._render_dashboard(), refresh=True)
                        await websocket.send(
                            json.dumps({"method": "subscribeNewToken"})
                        )
                        async for raw_message in websocket:
                            if self._stop_requested:
                                break
                            try:
                                data = json.loads(raw_message)
                            except json.JSONDecodeError:
                                continue
                            await self._handle_message(data, websocket)
                            await self._process_exit_retry_queue(websocket)
                            if time.monotonic() - self._last_message_at > 60:
                                self._log(
                                    "WebSocket heartbeat timeout: no messages received for 60s.",
                                    level=logging.WARNING,
                                )
                                self._last_status = "heartbeat timeout"
                            live.update(self._render_dashboard(), refresh=True)
                except asyncio.CancelledError:
                    self._log("TradingBot shutdown requested.")
                    self._last_status = "shutdown requested"
                    break
                except (
                    websockets.ConnectionClosed
                ) as exc:  # pragma: no cover - network branch
                    self._ws_consecutive_failures += 1
                    self._record_connection_loss()
                    self._log(
                        f"WebSocket closed: {exc}. Reconnecting (attempt {self._ws_consecutive_failures}).",
                        level=logging.WARNING,
                    )
                except Exception as exc:  # pragma: no cover - defensive branch
                    self._ws_consecutive_failures += 1
                    self._record_connection_loss()
                    self._log(
                        f"Bot loop error: {exc}. Reconnecting (attempt {self._ws_consecutive_failures}).",
                        level=logging.ERROR,
                    )

                if self._stop_requested:
                    break

                # Circuit breaker transition (BUG-06)
                if self._ws_consecutive_failures >= self._max_ws_consecutive_failures:
                    self._circuit_breaker_tripped = True
                    self._health_ok = False
                    self._last_status = "degraded: ws circuit breaker active"
                    self._log(
                        f"WebSocket circuit breaker tripped after {self._ws_consecutive_failures} failures. Bot transitioned to degraded state.",
                        level=logging.ERROR,
                    )
                    self._send_alert(
                        f"⚠️ Circuit Breaker Active: WebSocket connection lost {self._ws_consecutive_failures} times. Trading halted."
                    )

                # Exponential backoff with jitter (BUG-06)
                jitter = random.uniform(0.85, 1.25)
                sleep_delay = min(backoff * jitter, 60.0)
                self._last_status = f"reconnecting in {sleep_delay:.1f}s (attempt {self._ws_consecutive_failures})"
                live.update(self._render_dashboard(), refresh=True)
                await asyncio.sleep(sleep_delay)
                backoff = min(backoff * 2.0, 60.0)
                await self._process_exit_retry_queue()

        self._log("TradingBot shutdown complete.")
        self._transition_to(TradingBotState.SHUTDOWN, reason="loop_exited")

    async def close(self) -> None:
        self.request_shutdown()
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
