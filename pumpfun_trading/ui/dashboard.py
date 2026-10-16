from __future__ import annotations

import time
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table

from pumpfun_trading.bot.pnl import PnlTotals
from pumpfun_trading.bot.reconcile import describe_reconciliation_status


def format_sol_amount(value: float) -> str:
    """Signed SOL amount; values under 0.001 SOL are shown in µSOL (BUG-19)."""
    if value != 0.0 and abs(value) < 0.001:
        return f"{value * 1_000_000:+.4f} µSOL"
    return f"{value:+.4f} SOL"


def format_compact_tokens(amount: int | float | None) -> str:
    """Format token amount with compact metric suffixes (K, M, B)."""
    val = float(amount or 0)
    if val <= 0:
        return "0"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"{val / 1_000:.2f}K"
    return f"{val:.0f}"


def format_uptime(seconds: float | int | None) -> str:
    """Format duration in seconds into a concise human-readable string (e.g. '04h 12m 30s', '12m 30s', '45s')."""
    if seconds is None:
        return "0s"
    val = max(0.0, float(seconds))
    total_seconds = int(val)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours:02d}h {minutes:02d}m {secs:02d}s"
    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes:02d}m {secs:02d}s"
    return f"{secs}s"


def _reconciliation_text(bot: Any) -> str:
    """Last wallet reconciliation, coloured: green OK, red GAP, yellow stale/none."""
    reader = getattr(bot, "reconciliation_status", None)
    status = None
    if callable(reader):
        try:
            status = reader()
        except Exception:
            status = None
    text = describe_reconciliation_status(status if isinstance(status, dict) else None)
    if text.startswith("OK"):
        return f"[green]{text}[/green]"
    if text.startswith("GAP"):
        return f"[red]{text}[/red]"
    return f"[yellow]{text}[/yellow]"


def build_dashboard(bot: Any) -> Panel:
    """Build the bot dashboard panel from the live bot state."""
    strategy = Table.grid(expand=True)
    strategy.add_column(justify="left")
    strategy.add_column(justify="right")
    strategy.add_row("Preset", bot.config.strategy_preset)
    strategy.add_row("Buy amount", f"{bot.config.buy_amount_sol:.4f} SOL")
    strategy.add_row("Take profit", f"{bot.config.take_profit:.2%}")
    strategy.add_row("Stop loss", f"{bot.config.stop_loss:.2%}")
    strategy.add_row("Max active", str(bot.max_active_positions))
    strategy.add_row("Min market cap", f"{bot.min_market_cap_sol:.2f} SOL")
    strategy.add_row("Dry run", "yes" if bot.dry_run else "no")
    strategy.add_row("Paper trade", "yes" if bot.paper_trade else "no")

    wallet_val = getattr(bot, "wallet_balance_sol", None)
    if wallet_val is None:
        wallet_val = getattr(bot, "wallet_value", None)
    if wallet_val is None:
        wallet_val = getattr(bot, "wallet_balance", None)
    if wallet_val is not None:
        try:
            wallet_str = f"{float(wallet_val):.4f} SOL"
        except (ValueError, TypeError):
            wallet_str = str(wallet_val)
    else:
        wallet_str = "0.0000 SOL"
    strategy.add_row("Wallet value", wallet_str)

    stagnant_val = getattr(bot.config, "stagnant_timeout_seconds", None)
    if stagnant_val is not None:
        try:
            stagnant_str = f"{float(stagnant_val):.1f}s"
        except (ValueError, TypeError):
            stagnant_str = str(stagnant_val)
    else:
        stagnant_str = "n/a"
    strategy.add_row("Stagnant timeout", stagnant_str)

    risk = Table.grid(expand=True)
    risk.add_column(justify="left")
    risk.add_column(justify="right")
    risk.add_row("Max total exposure", f"{bot.config.max_total_exposure_sol:.2f} SOL")
    risk.add_row("Max position size", f"{bot.config.max_position_size_sol:.2f} SOL")
    risk.add_row("Max loss / trade", f"{bot.config.max_loss_per_trade_sol:.2f} SOL")
    risk.add_row("Daily drawdown", f"{bot.config.max_daily_drawdown_pct:.2%}")
    risk.add_row("Reserve balance", f"{bot.config.reserve_balance_sol:.2f} SOL")
    risk.add_row("Health timeout", f"{bot.config.health_check_timeout_seconds}s")
    risk.add_row("Risk killed", "yes" if bot._risk_killed else "no")
    risk.add_row("Equity guard", "enabled" if not bot.dry_run else "dry-run")

    from pumpfun_trading.bot.risk import DailyEquityTracker

    tracker = getattr(bot, "daily_equity_tracker", None)
    if isinstance(tracker, DailyEquityTracker) and hasattr(
        tracker, "realized_daily_pnl_sol"
    ):
        pnl = float(tracker.realized_daily_pnl_sol or 0.0)
        # Realized PnL is net of fees, tips and rent since Sprint 24B (FEAT-49).
        risk.add_row("Daily PnL (net)", format_sol_amount(pnl))
        risk.add_row(
            "Daily PnL (gross)",
            format_sol_amount(float(tracker.realized_daily_gross_pnl_sol or 0.0)),
        )
        risk.add_row(
            "Costs today",
            format_sol_amount(float(tracker.realized_daily_costs_sol or 0.0)),
        )
        totals = getattr(bot, "_pnl_totals", None)
        if isinstance(totals, PnlTotals):
            risk.add_row("Session net PnL", format_sol_amount(totals.net_pnl_sol))
        breaker_status = "LOCKED" if tracker.circuit_breaker_engaged else "ok"
        risk.add_row("Circuit breaker", breaker_status)
        risk.add_row("Reconciliation", _reconciliation_text(bot))
    else:
        risk.add_row("", "")
        risk.add_row("", "")

    uptime_val = None
    if hasattr(bot, "uptime_seconds"):
        try:
            uptime_val = bot.uptime_seconds
        except Exception:
            uptime_val = None
    if uptime_val is None:
        start = (
            getattr(bot, "_start_time", None)
            or getattr(bot, "_started_at", None)
            or getattr(bot, "start_time", None)
        )
        if start is not None:
            try:
                uptime_val = max(0.0, time.monotonic() - float(start))
            except Exception:
                uptime_val = 0.0
        elif hasattr(bot, "uptime") and isinstance(bot.uptime, (int, float)):
            uptime_val = float(bot.uptime)
        elif hasattr(bot, "uptime") and isinstance(bot.uptime, str):
            uptime_str = bot.uptime
        else:
            uptime_val = 0.0

    if "uptime_str" not in locals():
        uptime_str = format_uptime(uptime_val)

    bot_status = Table.grid(expand=True)
    bot_status.add_column(justify="left")
    bot_status.add_column(justify="right")
    bot_status.add_row("State", str(bot.state.value))
    bot_status.add_row("Uptime", uptime_str)
    bot_status.add_row("Health", "ok" if bot._health_ok else "degraded")
    bot_status.add_row("Risk killed", "yes" if bot._risk_killed else "no")
    bot_status.add_row("Active positions", str(len(bot.active_positions)))
    bot_status.add_row("Last event", bot._last_event)
    bot_status.add_row("Status", str(bot._last_status))
    bot_status.add_row(
        "Last message",
        (
            f"{max(0.0, time.monotonic() - bot._last_message_at):.1f}s ago"
            if bot._last_message_at
            else "never"
        ),
    )
    bot_status.add_row("Stream URL", bot.stream_url)
    if (
        getattr(bot, "geyser_endpoint", None)
        and bot.geyser_endpoint != bot.stream_url
        and bot.geyser_endpoint != "http://127.0.0.1:10000"
    ):
        bot_status.add_row("Geyser endpoint", str(bot.geyser_endpoint))
    bot_status.add_row("Audit log", str(bot.audit_log_path))
    bot_status.add_row("Last new token", bot._last_new_token_name)

    health = Table.grid(expand=True)
    health.add_column(justify="left")
    health.add_column(justify="right")
    health.add_row(
        "Heartbeat", f"{max(0.0, time.monotonic() - bot._last_health_check):.1f}s ago"
    )
    health.add_row(
        "Last message",
        (
            f"{max(0.0, time.monotonic() - bot._last_message_at):.1f}s ago"
            if bot._last_message_at
            else "never"
        ),
    )
    health.add_row("Health timeout", f"{bot.config.health_check_timeout_seconds}s")
    health.add_row("API/WS health", "ok" if bot._health_ok else "degraded")
    health.add_row("Risk killed", "yes" if bot._risk_killed else "no")
    health.add_row("Stop requested", "yes" if bot._stop_requested else "no")
    health.add_row("Last status", str(bot._last_status))
    health.add_row("Last event", bot._last_event)

    overview_height = (
        max(
            len(strategy.rows),
            len(risk.rows),
            len(bot_status.rows),
            len(health.rows),
        )
        + 2
    )

    overview = Table.grid(expand=True)
    overview.add_column(ratio=1)
    overview.add_column(ratio=1)
    overview.add_column(ratio=1)
    overview.add_column(ratio=1)
    overview.add_row(
        Panel(strategy, title="Strategy", border_style="cyan", height=overview_height),
        Panel(risk, title="Risk", border_style="red", height=overview_height),
        Panel(
            bot_status, title="Bot Status", border_style="blue", height=overview_height
        ),
        Panel(
            health, title="Health Check", border_style="yellow", height=overview_height
        ),
    )

    positions_table = Table(show_lines=True, expand=True)
    positions_table.add_column("Name", style="cyan")
    positions_table.add_column("Mint", style="green")
    positions_table.add_column("Entry MC", justify="right")
    positions_table.add_column("Current MC", justify="right")
    positions_table.add_column("Cost / Spend", justify="right")
    positions_table.add_column("Token Amount", justify="right")
    positions_table.add_column("Unit Token Price", justify="right")
    positions_table.add_column("Perf / PnL", justify="right")
    positions_table.add_column("Reason", style="yellow")

    if bot.active_positions:
        for mint, position in bot.active_positions.items():
            if isinstance(position, dict):
                name = str(position.get("name") or mint)
                entry = float(position.get("entry_market_cap", 0.0) or 0.0)
                current = float(position.get("current_market_cap", 0.0) or 0.0)
                cost = float(
                    position.get("cost_sol")
                    or position.get("entry_sol", 0.0)
                    or getattr(bot.config, "buy_amount_sol", 0.0)
                    or 0.0
                )
                raw_tokens = (
                    position.get("remaining_token_amount")
                    if position.get("remaining_token_amount") is not None
                    else (
                        position.get("token_amount")
                        or position.get("initial_token_amount")
                        or 0
                    )
                )
                unit_price = float(
                    position.get("buy_price")
                    or position.get("entry_price")
                    or position.get("price")
                    or (
                        cost / float(raw_tokens)
                        if raw_tokens and float(raw_tokens) > 0 and cost > 0
                        else (entry / 1_000_000_000 if entry > 0 else 0.0)
                    )
                    or 0.0
                )
                reason = str(
                    position.get("entry_reason") or position.get("reason") or "watch"
                )
            else:
                name = str(getattr(position, "name", mint) or mint)
                entry = float(getattr(position, "entry_market_cap", 0.0) or 0.0)
                current = float(getattr(position, "current_market_cap", 0.0) or 0.0)
                cost = float(
                    getattr(position, "cost_sol", None)
                    or getattr(position, "entry_sol", 0.0)
                    or getattr(bot.config, "buy_amount_sol", 0.0)
                    or 0.0
                )
                raw_tokens = (
                    getattr(position, "remaining_token_amount", None)
                    if getattr(position, "remaining_token_amount", None) is not None
                    else (
                        getattr(position, "token_amount", None)
                        or getattr(position, "initial_token_amount", 0)
                    )
                )
                unit_price = float(
                    getattr(position, "buy_price", None)
                    or getattr(position, "entry_price", None)
                    or getattr(position, "price", None)
                    or (
                        cost / float(raw_tokens)
                        if raw_tokens and float(raw_tokens) > 0 and cost > 0
                        else (entry / 1_000_000_000 if entry > 0 else 0.0)
                    )
                    or 0.0
                )
                reason = str(
                    getattr(position, "entry_reason", None)
                    or getattr(position, "reason", None)
                    or "watch"
                )

            if unit_price > 0:
                if unit_price < 0.001:
                    unit_price_str = f"{unit_price * 1_000_000:.4f} µSOL"
                else:
                    unit_price_str = f"{unit_price:.4f} SOL"
            else:
                unit_price_str = "-"

            tokens_str = format_compact_tokens(raw_tokens)

            if entry > 0:
                pnl_pct = (current - entry) / entry
            else:
                pnl_pct = 0.0

            if abs(pnl_pct) < 1e-9:
                pnl_str = "0.00%"
            elif pnl_pct > 0:
                pnl_str = f"+{pnl_pct:.2%}"
            else:
                pnl_str = f"{pnl_pct:.2%}"

            positions_table.add_row(
                name[:18],
                mint[:8] + "...",
                f"{entry:.2f} SOL",
                f"{current:.2f} SOL",
                f"{cost:.4f} SOL",
                tokens_str,
                unit_price_str,
                pnl_str,
                reason,
            )
    else:
        positions_table.add_row(
            "No active positions.", "-", "-", "-", "-", "-", "-", "-", "-"
        )

    runtime = Table.grid(expand=True)
    runtime.add_column(justify="left")
    runtime.add_column(justify="right")
    runtime.add_row(
        "Last message",
        (
            f"{max(0.0, time.monotonic() - bot._last_message_at):.1f}s ago"
            if bot._last_message_at
            else "never"
        ),
    )
    runtime.add_row("Last token", bot._last_new_token_name)
    runtime.add_row("Stream URL", bot.stream_url)
    if (
        getattr(bot, "geyser_endpoint", None)
        and bot.geyser_endpoint != bot.stream_url
        and bot.geyser_endpoint != "http://127.0.0.1:10000"
    ):
        runtime.add_row("Geyser endpoint", str(bot.geyser_endpoint))
    observed_count = getattr(bot, "_observed_tokens_count", 0) or len(
        getattr(bot, "_seen_mints", {})
    )
    runtime.add_row("Observed", str(observed_count))

    metrics = bot._metrics_snapshot()
    metrics_table = Table.grid(expand=True)
    metrics_table.add_column(justify="left")
    metrics_table.add_column(justify="right")
    for key in (
        "buys",
        "sells",
        "failures",
        "retries",
        "connection_loss",
        "stale_data",
    ):
        metrics_table.add_row(key, str(metrics.get(key, 0)))
    metrics_table.add_row("latency avg", f"{metrics['latency_ms']['avg_ms']} ms")

    events = list(bot._recent_events)[-6:]
    event_lines = [f"• {event}" for event in events] or ["No events yet."]

    ledger_lines: list[str] = []
    for record in reversed(bot._trade_ledger[-5:]):
        action = record.get("action", "trade")
        reason = record.get("reason") or "unknown"
        mint = record.get("mint", "-")[:8]
        if action == "buy" or "buy" in action:
            buy_val = float(
                record.get("buy_price")
                or record.get("entry_price")
                or record.get("entry")
                or 0.0
            )
            if 0 < buy_val < 0.001:
                buy_val_str = f"{buy_val * 1_000_000:.4f} µSOL"
            else:
                buy_val_str = f"{buy_val:.4f} SOL"
            ledger_lines.append(f"{action.upper()} {mint} @ {buy_val_str} | {reason}")
        else:
            sell_val = float(
                record.get("sell_price")
                or record.get("exit_price")
                or record.get("exit")
                or 0.0
            )
            if 0 < sell_val < 0.001:
                sell_val_str = f"{sell_val * 1_000_000:.4f} µSOL"
            else:
                sell_val_str = f"{sell_val:.4f} SOL"
            ledger_lines.append(f"{action.upper()} {mint} -> {sell_val_str} | {reason}")
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
