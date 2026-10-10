import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import deque
from enum import Enum
from typing import Any

import websockets
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.strategy import TradingBotConfig, resolve_strategy_config
from pumpfun_trading.sdk.execution import PumpFunExecutionClient


class TradingBotState(str, Enum):
    IDLE = "idle"
    MONITORING = "monitoring"
    BUYING = "buying"
    HOLDING = "holding"
    SELLING = "selling"
    SHUTDOWN = "shutdown"


class TradingBot:
    """Production-ready Pump.fun trading bot with strategy presets and lifecycle safeguards."""

    _VALID_STATE_TRANSITIONS: dict[TradingBotState, set[TradingBotState]] = {
        TradingBotState.IDLE: {TradingBotState.MONITORING, TradingBotState.SHUTDOWN},
        TradingBotState.MONITORING: {TradingBotState.BUYING, TradingBotState.HOLDING, TradingBotState.SHUTDOWN},
        TradingBotState.BUYING: {TradingBotState.HOLDING, TradingBotState.MONITORING, TradingBotState.SHUTDOWN},
        TradingBotState.HOLDING: {TradingBotState.SELLING, TradingBotState.MONITORING, TradingBotState.SHUTDOWN},
        TradingBotState.SELLING: {TradingBotState.MONITORING, TradingBotState.HOLDING, TradingBotState.SHUTDOWN},
        TradingBotState.SHUTDOWN: set(),
    }

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
            health_check_timeout_seconds=int(getattr(base, "health_check_timeout_seconds", 60)),
        )

        if self.config.buy_amount_sol <= 0:
            raise ValueError("buy_amount_sol must be greater than zero.")
        if not 0 < self.config.stop_loss < self.config.take_profit:
            raise ValueError("stop_loss must be less than take_profit and both must be greater than zero.")
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
        self.console = Console(file=sys.stdout, force_terminal=True, force_interactive=True, color_system="auto")

        self._metrics: dict[str, Any] = {
            "buys": 0,
            "sells": 0,
            "failures": 0,
            "retries": 0,
            "connection_loss": 0,
            "stale_data": 0,
            "latency_ms": deque(maxlen=200),
        }

        self.logger = logging.getLogger("pumpfun_trading.bot")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers.clear()

        resolved_log_file = log_file or os.path.join(tempfile.gettempdir(), "pumpfun_trading_bot.log")
        handler = logging.FileHandler(resolved_log_file)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        self.audit_log_path = audit_log_path or os.getenv("PUMPFUN_AUDIT_LOG") or os.path.join(tempfile.gettempdir(), "pumpfun_trading_audit.jsonl")
        self._audit_handle = None
        if self.audit_log_path:
            directory = os.path.dirname(self.audit_log_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._audit_handle = open(self.audit_log_path, "a", encoding="utf-8")

        self.bot_status_path = os.getenv("PUMPFUN_BOT_STATUS_PATH") or os.path.join(os.getcwd(), "bot_status.json")
        self.alert_provider = (os.getenv("PUMPFUN_ALERT_PROVIDER") or "none").strip().lower()
        self.alert_discord_webhook_url = os.getenv("PUMPFUN_ALERT_DISCORD_WEBHOOK_URL")
        self.alert_slack_webhook_url = os.getenv("PUMPFUN_ALERT_SLACK_WEBHOOK_URL")
        self.alert_telegram_bot_token = os.getenv("PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN")
        self.alert_telegram_chat_id = os.getenv("PUMPFUN_ALERT_TELEGRAM_CHAT_ID")
        self.alert_enabled = False
        self._configure_alerting()
        self._recent_events: deque[str] = deque(maxlen=8)

        self.api = PumpFunApiClient(base_url=self.api_base_url)

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
        if provider == "telegram" and (not self.alert_telegram_bot_token or not self.alert_telegram_chat_id):
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
                    data=json.dumps({"chat_id": self.alert_telegram_chat_id, "text": payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
        except Exception as exc:  # pragma: no cover - network path
            self._log(f"Failed to send alert via {provider}: {exc}", level=logging.WARNING)

    def _write_status_snapshot(self) -> None:
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

    def _transition_to(self, next_state: TradingBotState, *, reason: str | None = None) -> None:
        current = self.state
        if next_state not in self._VALID_STATE_TRANSITIONS.get(current, set()):
            if current != next_state:
                self._log(f"Illegal state transition from {current.value} to {next_state.value}: {reason or 'no reason provided'}", level=logging.WARNING)
            return
        self.state = next_state
        event = {"timestamp": time.time(), "state": next_state.value, "previous_state": current.value, "reason": reason}
        self._recent_actions.append(event)
        self._write_audit_record("state_transition", event)
        self._write_status_snapshot()
        if self.alert_enabled and next_state in {TradingBotState.BUYING, TradingBotState.SELLING, TradingBotState.SHUTDOWN}:
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
            raise ValueError(f"Invalid mint address '{cleaned}'. It must be a valid base58 Solana mint address.") from exc
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

        private_key = os.getenv("PUMPFUN_PRIVATE_KEY") or os.getenv("SOLANA_PRIVATE_KEY")
        rpc_url = os.getenv("PUMPFUN_RPC_URL") or os.getenv("HELIUS_RPC_URL")
        if not private_key:
            raise ValueError("Missing PUMPFUN_PRIVATE_KEY (or SOLANA_PRIVATE_KEY) in environment.")
        if not rpc_url:
            raise ValueError("Missing PUMPFUN_RPC_URL (or HELIUS_RPC_URL) in environment.")
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
        expired = [mint for mint, seen_at in self._seen_mints.items() if seen_at < cutoff]
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
        entry: float | None = None,
        exit_value: float | None = None,
        reason: str | None = None,
        trade_id: str | None = None,
        position_id: str | None = None,
    ) -> None:
        trade_id = trade_id or position_id or self._next_trade_id()
        if position_id is None and action == "buy":
            position_id = trade_id
        record = {
            "timestamp": time.time(),
            "trade_id": trade_id,
            "position_id": position_id or trade_id,
            "action": action,
            "mint": mint,
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
        self._recent_actions.append({"timestamp": record["timestamp"], "type": "trade", "payload": record})
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
            self._write_audit_record("metric", {"name": "failures", "category": category, "value": 1})

    def _record_connection_loss(self) -> None:
        self._record_metric("connection_loss")

    def _metrics_snapshot(self) -> dict[str, Any]:
        latency_values = list(self._metrics.get("latency_ms", deque()))
        snapshot = {key: value for key, value in self._metrics.items() if key != "latency_ms"}
        snapshot["latency_ms"] = {
            "samples": len(latency_values),
            "avg_ms": round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0,
            "last_ms": round(latency_values[-1], 2) if latency_values else 0.0,
            "max_ms": round(max(latency_values), 2) if latency_values else 0.0,
        }
        return snapshot

    def _render_dashboard(self) -> Panel:
        strategy = Table.grid(expand=True)
        strategy.add_column(justify="left")
        strategy.add_column(justify="right")
        strategy.add_row("Preset", self.config.strategy_preset)
        strategy.add_row("Buy amount", f"{self.config.buy_amount_sol:.4f} SOL")
        strategy.add_row("Take profit", f"{self.config.take_profit:.2%}")
        strategy.add_row("Stop loss", f"{self.config.stop_loss:.2%}")
        strategy.add_row("Max active", str(self.max_active_positions))
        strategy.add_row("Min market cap", f"{self.min_market_cap_sol:.2f} SOL")
        strategy.add_row("Dry run", "yes" if self.dry_run else "no")
        strategy.add_row("Paper trade", "yes" if self.paper_trade else "no")
        strategy.add_row("", "")
        strategy.add_row("", "")

        risk = Table.grid(expand=True)
        risk.add_column(justify="left")
        risk.add_column(justify="right")
        risk.add_row("Max total exposure", f"{self.config.max_total_exposure_sol:.2f} SOL")
        risk.add_row("Max position size", f"{self.config.max_position_size_sol:.2f} SOL")
        risk.add_row("Max loss / trade", f"{self.config.max_loss_per_trade_sol:.2f} SOL")
        risk.add_row("Daily drawdown", f"{self.config.max_daily_drawdown_pct:.2%}")
        risk.add_row("Reserve balance", f"{self.config.reserve_balance_sol:.2f} SOL")
        risk.add_row("Health timeout", f"{self.config.health_check_timeout_seconds}s")
        risk.add_row("Risk killed", "yes" if self._risk_killed else "no")
        risk.add_row("Equity guard", "enabled" if not self.dry_run else "dry-run")
        risk.add_row("", "")
        risk.add_row("", "")

        bot_status = Table.grid(expand=True)
        bot_status.add_column(justify="left")
        bot_status.add_column(justify="right")
        bot_status.add_row("State", str(self.state.value))
        bot_status.add_row("Health", "ok" if self._health_ok else "degraded")
        bot_status.add_row("Risk killed", "yes" if self._risk_killed else "no")
        bot_status.add_row("Active positions", str(len(self.active_positions)))
        bot_status.add_row("Last event", self._last_event)
        bot_status.add_row("Status", str(self._last_status))
        bot_status.add_row("Last message", f"{time.time() - self._last_message_at:.1f}s ago" if self._last_message_at else "never")
        bot_status.add_row("Stream URL", self.stream_url)
        bot_status.add_row("Audit log", str(self.audit_log_path))
        bot_status.add_row("Last new token", self._last_new_token_name)

        health = Table.grid(expand=True)
        health.add_column(justify="left")
        health.add_column(justify="right")
        health.add_row("Heartbeat", f"{max(0.0, time.monotonic() - self._last_health_check):.1f}s ago")
        health.add_row("Last message", f"{time.time() - self._last_message_at:.1f}s ago" if self._last_message_at else "never")
        health.add_row("Health timeout", f"{self.config.health_check_timeout_seconds}s")
        health.add_row("API/WS health", "ok" if self._health_ok else "degraded")
        health.add_row("Risk killed", "yes" if self._risk_killed else "no")
        health.add_row("Stop requested", "yes" if self._stop_requested else "no")
        health.add_row("Last status", str(self._last_status))
        health.add_row("Last event", self._last_event)

        overview_height = max(
            len(strategy.rows),
            len(risk.rows),
            len(bot_status.rows),
            len(health.rows),
        )

        overview = Table.grid(expand=True)
        overview.add_column(ratio=1)
        overview.add_column(ratio=1)
        overview.add_column(ratio=1)
        overview.add_column(ratio=1)
        overview.add_row(
            Panel(strategy, title="Strategy", border_style="cyan", height=overview_height),
            Panel(risk, title="Risk", border_style="red", height=overview_height),
            Panel(bot_status, title="Bot Status", border_style="blue", height=overview_height),
            Panel(health, title="Health Check", border_style="yellow", height=overview_height),
        )

        positions_table = Table(show_lines=True, expand=True)
        positions_table.add_column("Name", style="cyan")
        positions_table.add_column("Mint", style="green")
        positions_table.add_column("Entry", justify="right")
        positions_table.add_column("Current", justify="right")
        positions_table.add_column("Perf", justify="right")
        positions_table.add_column("Reason", style="yellow")

        if self.active_positions:
            for mint, position in self.active_positions.items():
                name = str(position.get("name") or mint)
                entry = float(position.get("entry_market_cap", 0.0) or 0.0)
                current = float(position.get("current_market_cap", 0.0) or 0.0)
                performance = (current / entry) if entry > 0 else 1.0
                reason = str(position.get("reason") or "watch")
                positions_table.add_row(name[:18], mint[:8] + "...", f"{entry:.2f}", f"{current:.2f}", f"{performance:.2%}", reason)
        else:
            positions_table.add_row("No active positions.", "-", "-", "-", "-", "-")

        runtime = Table.grid(expand=True)
        runtime.add_column(justify="left")
        runtime.add_column(justify="right")
        runtime.add_row("Last message", f"{time.time() - self._last_message_at:.1f}s ago" if self._last_message_at else "never")
        runtime.add_row("Last token", self._last_new_token_name)
        runtime.add_row("Stream URL", self.stream_url)
        runtime.add_row("Observed", str(len(self._recent_events)))

        metrics = self._metrics_snapshot()
        metrics_table = Table.grid(expand=True)
        metrics_table.add_column(justify="left")
        metrics_table.add_column(justify="right")
        for key in ("buys", "sells", "failures", "retries", "connection_loss", "stale_data"):
            metrics_table.add_row(key, str(metrics.get(key, 0)))
        metrics_table.add_row("latency avg", f"{metrics['latency_ms']['avg_ms']} ms")

        events = list(self._recent_events)[-6:]
        event_lines = [f"• {event}" for event in events] or ["No events yet."]

        ledger_lines: list[str] = []
        for record in reversed(self._trade_ledger[-5:]):
            action = record.get("action", "trade")
            reason = record.get("reason") or "unknown"
            mint = record.get("mint", "-")[:8]
            if action == "buy":
                ledger_lines.append(f"{action.upper()} {mint} @ {record.get('entry')} | {reason}")
            else:
                ledger_lines.append(f"{action.upper()} {mint} -> {record.get('exit')} | {reason}")
        if not ledger_lines:
            ledger_lines = ["No trades recorded yet."]

        audit_group = Group(
            Panel("\n".join(event_lines), title="Events", border_style="cyan"),
            Panel("\n".join(ledger_lines), title="Trade Ledger", border_style="green"),
        )

        runtime_group = Group(
            Panel(positions_table, title="Open Positions", border_style="green"),
            Panel(runtime, title="Coin Polling", border_style="yellow"),
        )

        return Panel(
            Group(
                Panel(overview, title="Overview", border_style="blue"),
                Panel(runtime_group, title="Run Time", border_style="yellow"),
                Panel(audit_group, title="Audit Trail", border_style="magenta"),
                Panel(metrics_table, title="Metrics", border_style="magenta"),
            ),
            title="Trading Bot",
            border_style="white",
        )

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

    async def _resolve_token_name(self, mint: str, token_name: str | None = None) -> str | None:
        if token_name and token_name.strip():
            return token_name.strip()
        return None

    async def _unsubscribe_from_token_trades(self, websocket, mint: str) -> None:
        _ = websocket, mint
        return None

    def _check_risk_limits(self, *, mint: str, proposed_entry_sol: float, current_positions: dict[str, dict[str, Any]]) -> bool:
        total_exposure = sum(float(pos.get("entry_market_cap", 0.0) or 0.0) for pos in current_positions.values())
        if total_exposure + proposed_entry_sol > self.config.max_total_exposure_sol:
            self._last_event = f"risk limit: max exposure {self.config.max_total_exposure_sol:.2f} SOL"
            return False
        if proposed_entry_sol > self.config.max_position_size_sol:
            self._last_event = f"risk limit: position cap {self.config.max_position_size_sol:.2f} SOL"
            return False
        if mint in current_positions:
            self._last_event = f"risk limit: mint already active {mint[:8]}..."
            return False

        if current_positions:
            max_per_token_ratio = max(
                float(pos.get("entry_market_cap", 0.0) or 0.0) / self.config.max_total_exposure_sol
                for pos in current_positions.values()
            ) if self.config.max_total_exposure_sol > 0 else 0.0
            if max_per_token_ratio > float(getattr(self.config, "max_token_concentration_pct", 0.35)):
                self._last_event = (
                    "risk limit: per-token concentration cap reached "
                    f"({max_per_token_ratio:.2%} > {float(getattr(self.config, 'max_token_concentration_pct', 0.35)):.2%})"
                )
                return False

        return True

    def _check_daily_drawdown(self) -> bool:
        if not self.active_positions:
            return True

        total_equity = sum(float(pos.get("entry_market_cap", 0.0) or 0.0) for pos in self.active_positions.values())
        if total_equity <= 0:
            return True

        drawdown = 1.0 - (sum(float(pos.get("current_market_cap", 0.0) or 0.0) for pos in self.active_positions.values()) / total_equity)
        if drawdown > self.config.max_daily_drawdown_pct:
            self._last_event = (
                f"risk limit: daily drawdown {drawdown:.2%} exceeds {self.config.max_daily_drawdown_pct:.2%}"
            )
            return False
        return True

    def _check_loss_per_trade(self, *, mint: str, current_market_cap: float | None = None) -> bool:
        position = self.active_positions.get(mint)
        if position is None:
            return True

        if current_market_cap is None:
            current_market_cap = float(position.get("current_market_cap", 0.0) or 0.0)
        entry_market_cap = float(position.get("entry_market_cap", 0.0) or 0.0)
        if entry_market_cap <= 0:
            return True

        loss_ratio = 1.0 - (current_market_cap / entry_market_cap)
        if loss_ratio > self.config.max_loss_per_trade_sol / self.config.buy_amount_sol:
            self._last_event = (
                f"risk limit: trade loss {loss_ratio:.2%} exceeds max {self.config.max_loss_per_trade_sol / self.config.buy_amount_sol:.2%}"
            )
            return False
        return True

    def _health_ok_for_trading(self) -> bool:
        if self._stop_requested or self._risk_killed:
            return False
        if not self._health_ok:
            return False
        if time.monotonic() - self._last_health_check > self.config.health_check_timeout_seconds:
            self._last_status = "health timeout"
            self._health_ok = False
            self._risk_killed = True
            self._last_event = "risk kill: health timeout"
            return False
        return True

    def _mark_health_check(self) -> None:
        self._last_health_check = time.monotonic()
        self._health_ok = True

    async def _check_account_equity_guard(self, *, required_sol: float) -> bool:
        if self.dry_run:
            return True
        try:
            balance_sol = float(await self.execution.get_balance_sol())
        except Exception as exc:  # pragma: no cover - defensive branch
            self._health_ok = False
            self._risk_killed = True
            self._last_event = "risk kill: API balance check failed"
            self._log(f"Could not read wallet balance for equity guard: {exc}", level=logging.WARNING)
            return False

        available_after_reserve = balance_sol - self.config.reserve_balance_sol
        if required_sol > available_after_reserve:
            self._last_event = (
                f"equity guard: required {required_sol:.4f} SOL, available {available_after_reserve:.4f} SOL"
            )
            self._log(
                f"Account equity guard blocked trade: {required_sol:.4f} SOL required, "
                f"{available_after_reserve:.4f} SOL available after reserve {self.config.reserve_balance_sol:.4f} SOL",
                level=logging.WARNING,
            )
            return False
        return True

    async def _update_health_state(self) -> None:
        if self._stop_requested:
            return
        if time.monotonic() - self._last_message_at > self.config.health_check_timeout_seconds:
            if self._health_ok:
                self._health_ok = False
                self._risk_killed = True
                self._last_status = "health timeout"
                self._last_event = "risk kill: websocket stale"
                self._log(
                    "WebSocket health stale: no messages received within the configured health timeout.",
                    level=logging.CRITICAL,
                )
        else:
            self._mark_health_check()

    def get_status_snapshot(self) -> dict[str, Any]:
        return {
            "active_positions": list(self.active_positions.keys()),
            "trade_count": len(self.active_positions),
            "stop_requested": self._stop_requested,
            "dry_run": self.dry_run,
            "paper_trade": self.paper_trade,
            "last_message_at": self._last_message_at,
            "buy_attempts": dict(self._buy_attempts),
            "strategy": self.config.strategy_preset,
            "health_ok": self._health_ok,
            "risk_killed": self._risk_killed,
            "state": self.state.value,
            "recent_actions": list(self._recent_actions),
            "trade_ledger": list(self._trade_ledger[-10:]),
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

    async def _buy_token(self, mint: str, market_cap_sol: float, token_name: str | None = None) -> bool:
        if not self._should_buy(mint, market_cap_sol):
            return False

        self._transition_to(TradingBotState.BUYING, reason=f"buying {mint}")
        if not await self._check_account_equity_guard(required_sol=self.buy_amount_sol):
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_rejected_equity_guard {mint}")
            return False

        if not await self._validate_balance():
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_rejected_balance {mint}")
            return False

        resolved_name = await self._resolve_token_name(mint, token_name)
        position_name = (resolved_name or self.active_positions.get(mint, {}).get("name") or mint).strip() or mint
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
            self._record_trade(mint=mint, action="buy", entry=self.buy_amount_sol, reason="dry_run")
            self._transition_to(TradingBotState.HOLDING, reason=f"dry_run_buy {mint}")
            return True

        try:
            bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
        except Exception as exc:
            self._log(f"Could not compute bonding curve PDA for {mint}: {exc}", level=logging.WARNING)
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_pda_failed {mint}")
            return False

        self._log(f"Buying {mint} with {self.buy_amount_sol} SOL")
        self._last_event = f"buying {mint}"
        try:
            signature = await self.execution.buy(mint, bonding_curve, self.buy_amount_sol)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(f"Buy transaction failed for {mint}: {exc}", level=logging.WARNING)
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_failed {mint}")
            return False

        if not signature:
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_signature_missing {mint}")
            return False

        confirmed = await self.execution.confirm_transaction(signature)
        if not confirmed:
            self._log(f"Buy confirmation failed for {mint}", level=logging.WARNING)
            self._buy_attempts[mint] = self._buy_attempts.get(mint, 0) + 1
            self._transition_to(TradingBotState.MONITORING, reason=f"buy_confirmation_failed {mint}")
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
        self._record_trade(mint=mint, action="buy", entry=self.buy_amount_sol, reason="entry")
        self._transition_to(TradingBotState.HOLDING, reason=f"buy_confirmed {mint}")
        return True

    async def _sell_token(self, mint: str) -> bool:
        if mint not in self.active_positions:
            return False

        self._transition_to(TradingBotState.SELLING, reason=f"selling {mint}")
        if self.dry_run:
            self._log(f"DRY RUN SELL: {mint}")
            self._last_event = f"dry-run sell for {mint}"
            self.active_positions.pop(mint, None)
            self._transition_to(TradingBotState.MONITORING, reason=f"dry_run_sell {mint}")
            return True

        try:
            token_balance = await self.execution.get_token_balance(mint)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(f"Unable to fetch token balance for {mint}: {exc}", level=logging.WARNING)
            self.active_positions.pop(mint, None)
            self._transition_to(TradingBotState.MONITORING, reason=f"sell_balance_failed {mint}")
            return False

        if token_balance <= self.min_sell_balance:
            self._log(f"No actionable balance for {mint}; current balance={token_balance}")
            self.active_positions.pop(mint, None)
            self._transition_to(TradingBotState.MONITORING, reason=f"sell_zero_balance {mint}")
            return True

        try:
            bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
        except Exception as exc:
            self._log(f"Could not compute bonding curve PDA for sell on {mint}: {exc}", level=logging.WARNING)
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_pda_failed {mint}")
            return False

        self._log(f"Selling {token_balance} units of {mint} at threshold")
        self._last_event = f"selling {mint}"
        try:
            signature = await self.execution.sell(mint, bonding_curve, token_balance)
        except Exception as exc:  # pragma: no cover - defensive branch
            self._log(f"Sell transaction failed for {mint}: {exc}", level=logging.WARNING)
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_transaction_failed {mint}")
            return False

        if not signature:
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_missing_signature {mint}")
            return False

        confirmed = await self.execution.confirm_transaction(signature)
        if not confirmed:
            self._log(f"Sell confirmation failed for {mint}", level=logging.WARNING)
            self._transition_to(TradingBotState.HOLDING, reason=f"sell_confirmation_failed {mint}")
            return False

        self.active_positions.pop(mint, None)
        self._transition_to(TradingBotState.MONITORING, reason=f"sell_complete {mint}")
        return True

    async def _handle_new_token_event(self, data: dict[str, Any], websocket) -> None:
        if self._stop_requested:
            return

        mint_value = data.get("mint")
        if not mint_value:
            return
        mint = self.validate_mint_address(str(mint_value))
        market_cap_sol = float(data.get("marketCapSol") or data.get("marketCap") or 30.0)
        token_name = str(data.get("name") or data.get("tokenName") or data.get("displayName") or "").strip() or None

        if self._is_recently_seen(mint):
            return

        if not self._should_buy(mint, market_cap_sol):
            self._log(f"Skipping new token {mint}: not eligible for buy")
            self._last_event = f"skipped {mint}"
            return

        self._log(f"New token detected: {mint} | launch market cap: {market_cap_sol:.2f} SOL")
        self._last_event = f"new token {mint}"
        self._last_new_token = mint
        self._last_new_token_name = token_name
        if await self._buy_token(mint, market_cap_sol, token_name):
            self._record_event(f"bought {self.active_positions[mint].get('name', mint)}")

    async def _handle_trade_update(self, data: dict[str, Any], websocket) -> None:
        if self._stop_requested:
            return

        mint_value = data.get("mint")
        if not mint_value or not isinstance(mint_value, str):
            return

        mint = self.validate_mint_address(mint_value)
        if mint not in self.active_positions:
            return

        current_market_cap = float(data.get("marketCapSol") or data.get("marketCap") or 0.0)
        if current_market_cap <= 0:
            return

        position = self.active_positions[mint]
        position["current_market_cap"] = current_market_cap
        entry_market_cap = float(position.get("entry_market_cap") or current_market_cap)
        performance = current_market_cap / entry_market_cap if entry_market_cap > 0 else 1.0

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

        backoff = self.reconnect_delay_seconds
        with Live(
            self._render_dashboard(),
            console=self.console,
            refresh_per_second=2,
            transient=True,
            screen=False,
        ) as live:

            self._display_live = live
            while not self._stop_requested:
                try:
                    async with websockets.connect(self.stream_url, ping_interval=20, ping_timeout=20) as websocket:
                        self._last_status = "stream connected"
                        live.update(self._render_dashboard())
                        await websocket.send(json.dumps({"method": "subscribeNewToken"}))
                        async for raw_message in websocket:
                            if self._stop_requested:
                                break
                            try:
                                data = json.loads(raw_message)
                            except json.JSONDecodeError:
                                continue
                            await self._handle_message(data, websocket)
                            if time.monotonic() - self._last_message_at > 60:
                                self._log("WebSocket heartbeat timeout: no messages received for 60s.", level=logging.WARNING)
                                self._last_status = "heartbeat timeout"
                            live.update(self._render_dashboard())
                            live.refresh()
                except asyncio.CancelledError:
                    self._log("TradingBot shutdown requested.")
                    self._last_status = "shutdown requested"
                    break
                except websockets.ConnectionClosed as exc:  # pragma: no cover - network branch
                    self._log(f"WebSocket closed: {exc}. Reconnecting in {backoff:.1f}s", level=logging.WARNING)
                    self._last_status = f"reconnecting in {backoff:.1f}s"
                except Exception as exc:  # pragma: no cover - defensive branch
                    self._log(f"Bot loop error: {exc}. Reconnecting in {backoff:.1f}s", level=logging.ERROR)
                    self._last_status = f"reconnect after error in {backoff:.1f}s"
                if self._stop_requested:
                    break
                live.update(self._render_dashboard())
                live.refresh()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

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
