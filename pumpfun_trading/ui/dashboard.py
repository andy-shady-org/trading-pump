from __future__ import annotations

import time
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table


def format_compact_tokens(amount: int | float) -> str:
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
    strategy.add_row("", "")
    strategy.add_row("", "")

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
        risk.add_row("Daily PnL", f"{tracker.realized_daily_pnl_sol:+.4f} SOL")
        breaker_status = "LOCKED" if tracker.circuit_breaker_engaged else "ok"
        risk.add_row("Circuit breaker", breaker_status)
    else:
        risk.add_row("", "")
        risk.add_row("", "")

    bot_status = Table.grid(expand=True)
    bot_status.add_column(justify="left")
    bot_status.add_column(justify="right")
    bot_status.add_row("State", str(bot.state.value))
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
                position.get("initial_token_amount")
                or position.get("token_amount")
                or position.get("remaining_token_amount")
                or 0
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
            if unit_price > 0:
                microsol = unit_price * 1_000_000
                unit_price_str = f"{microsol:.4f} µSOL"
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

            reason = str(position.get("reason") or "watch")
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
            ledger_lines.append(
                f"{action.upper()} {mint} @ {buy_val:.4f} SOL | {reason}"
            )
        else:
            sell_val = float(
                record.get("sell_price")
                or record.get("exit_price")
                or record.get("exit")
                or 0.0
            )
            ledger_lines.append(
                f"{action.upper()} {mint} -> {sell_val:.4f} SOL | {reason}"
            )
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
