"""Watch-list poller of the trading runtime (confirmed entries).

Polls the curves of watched mints over RPC, records the polls, promotes
mints to a trade subscription and feeds the near-graduation entry.
`TradingBot` (`bot/run.py`) keeps a thin delegating method for each function
(`bot._poll_watch_list`, `bot.watch_list_status`, ...).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pumpfun_trading.ops.events import EventCategory, EventSeverity
from pumpfun_trading.strategies.graduation import (
    GRADUATION_REAL_SOL,
    PRE_GRADUATION_MIN_POLLED_SAMPLES,
)
from pumpfun_trading.strategies.momentum import near_graduation_expiry

if TYPE_CHECKING:
    from pumpfun_trading.bot.run import TradingBot

# A near-graduation entry this close (curve share) below the pre-graduation
# entry band is polled at the normal watch interval again.
NEAR_GRADUATION_FAST_POLL_MARGIN = 0.10


def watch_list_status(bot: TradingBot) -> dict[str, Any]:
    """Watch list size, subscriptions and counters for status and dashboard."""
    engine = bot.order_flow_engine
    return {
        "entry_mode": bot._entry_mode(),
        "watched": engine.watch_count,
        "subscribed": engine.watch_subscribed_count,
        "near_graduation": engine.near_graduation_count,
        "max_mints": int(getattr(bot.config, "watch_max_mints", 300)),
        "subscription_budget": int(
            getattr(bot.config, "watch_max_trade_subscriptions", 20)
        ),
        "stats": dict(getattr(bot, "_watch_stats", {}) or {}),
    }


async def run_watch_poll_loop(bot: TradingBot) -> None:
    """Batch-polls watched curves in its own task (confirmed mode only)."""
    if bot._entry_mode() != "confirmed":
        return
    interval = max(0.1, float(bot.config.watch_poll_interval_seconds))
    while not bot._stop_requested:
        try:
            await asyncio.sleep(interval)
            await bot._poll_watch_list()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            bot._log(f"Watch poll exception: {exc}", level=logging.DEBUG)


def watch_poll_due(bot: TradingBot, mint: str, now: float) -> bool:
    """Near-graduation entries are polled slowly until they get close to the
    pre-graduation entry band, where acceleration needs every reading."""
    entry = bot.order_flow_engine.get_watch(mint)
    if entry is None or not entry.near_graduation:
        return True
    progress = (entry.last_real_sol or 0.0) / GRADUATION_REAL_SOL
    entry_pct = float(bot.config.pre_graduation_entry_progress_pct)
    entry_pct = entry_pct / 100.0 if entry_pct > 1.0 else entry_pct
    if progress >= entry_pct - NEAR_GRADUATION_FAST_POLL_MARGIN:
        return True
    interval = float(getattr(bot.config, "near_graduation_poll_interval_seconds", 6.0))
    return now - entry.last_polled_at >= interval


def record_curve_poll(
    bot: TradingBot,
    mint: str,
    market_cap_sol: float,
    *,
    ts: float,
    source: str,
    real_sol: float | None = None,
    virtual_sol: float | None = None,
) -> None:
    """Write one polled curve to the capture, so replay can rebuild the curve
    history the bot saw (fills, drift guard, pre-graduation lane)."""
    if (
        bot.replay_recorder is None
        or market_cap_sol <= 0.0
        or not getattr(bot.config, "capture_curve_polls", True)
    ):
        return
    row: dict[str, Any] = {
        "timestamp": ts,
        "mint": mint,
        "event": "curve_poll",
        "source": source,
        "price": market_cap_sol / 1_000_000_000.0,
        "market_cap_sol": round(market_cap_sol, 6),
    }
    if real_sol is not None:
        row["real_sol_reserves"] = round(real_sol, 9)
    if virtual_sol is not None:
        row["virtual_sol_reserves"] = round(virtual_sol, 9)
    bot.replay_recorder.record_snapshot(row)


async def poll_watch_list(bot: TradingBot) -> None:
    """One poll: expire, read curves, feed the engines, drop bad curves, promote."""
    engine = bot.order_flow_engine
    now = time.time()
    engine.expire_watch(
        ttl=float(bot.config.watch_ttl_seconds),
        now=now,
        **near_graduation_expiry(bot.config),
    )
    for moved, was_subscribed in engine.drain_near_graduation():
        # Past the TTL the momentum lane is done with it: free the billed
        # trade slot, keep polling the curve for the pre-graduation lane.
        bot._count_watch("near_graduation")
        if was_subscribed and moved.mint not in bot.active_positions:
            await bot._unsubscribe_from_token_trades(None, moved.mint)
    mints = [m for m in engine.watched_mints() if bot._watch_poll_due(m, now)]
    rejected: dict[str, str] = {}
    if mints:
        try:
            states = await asyncio.wait_for(
                bot.execution.get_bonding_curve_states(mints, rejected=rejected),
                timeout=10.0,
            )
        except Exception as exc:
            # Keep polling; the RPC degradation alert covers long outages.
            bot._count_watch("poll_errors")
            if getattr(bot, "event_logger", None) is not None:
                bot.event_logger.emit(
                    category=EventCategory.STRATEGY,
                    severity=EventSeverity.WARNING,
                    event_name="watch_poll_failed",
                    data={"mints": len(mints), "error": str(exc)[:200]},
                )
            states = {}
            rejected = {}
        skip_mayhem = bool(getattr(bot.config, "skip_mayhem_mode", True))
        for mint, state in states.items():
            if skip_mayhem and state.get("is_mayhem_mode"):
                rejected[mint] = "mayhem"
                continue
            if state.get("complete"):
                bot._market_regime().record_graduation(mint)
                rejected[mint] = "complete"
                continue
            v_sol = int(state.get("virtual_sol_reserves", 0) or 0) / 1e9
            v_tok = int(state.get("virtual_token_reserves", 0) or 0) / 1e6
            real_sol = int(state.get("real_sol_reserves", 0) or 0) / 1e9
            market_cap = v_sol * (1_000_000_000.0 / v_tok) if v_tok > 0 else 0.0
            bot._record_curve_poll(
                mint,
                market_cap,
                ts=now,
                source="watch",
                real_sol=real_sol,
                virtual_sol=v_sol,
            )
            bot.graduation_engine.update_bonding_curve(
                mint=mint,
                bonding_curve="",
                real_sol_reserves=real_sol,
                virtual_sol_reserves=v_sol,
                market_cap_sol=market_cap,
                timestamp=now,
            )
            engine.update_watch_curve(
                mint, real_sol=real_sol, market_cap_sol=market_cap, now=now
            )
            if bot.config.enable_pre_graduation_harvesting:
                # Pre-graduation lane on polled curves (FEAT-53): needs a
                # few readings before acceleration means anything.
                await bot._maybe_buy_pre_graduation(
                    mint,
                    market_cap,
                    now=now,
                    min_samples=PRE_GRADUATION_MIN_POLLED_SAMPLES,
                )
        grace = max(10.0, 3 * float(bot.config.watch_poll_interval_seconds))
        for mint, reason in rejected.items():
            entry = engine.get_watch(mint)
            if reason == "missing" and entry and now - entry.watched_at < grace:
                continue  # load-balanced RPCs lag on brand-new accounts
            bot._count_watch(f"dropped_{reason}")
            engine.unwatch(mint)
            if entry is not None and entry.subscribed:
                await bot._unsubscribe_from_token_trades(None, mint)
    for evicted in engine.drain_watch_evictions():
        bot._count_watch("expired")
        if evicted.subscribed and evicted.mint not in bot.active_positions:
            await bot._unsubscribe_from_token_trades(None, evicted.mint)
    await bot._promote_watched_mints()


async def promote_watched_mints(bot: TradingBot) -> None:
    """Subscribe growing watched mints to the billed trade feed, within budget."""
    if bot._active_ws is None or not bot.trade_feed_available():
        return  # breaker open: keep polling, promote once trades flow again
    engine = bot.order_flow_engine
    for mint in engine.promotable(
        min_sol_growth=float(bot.config.watch_promote_min_sol_growth),
        budget=int(bot.config.watch_max_trade_subscriptions),
    ):
        await bot._subscribe_to_token_trades(None, mint)
        engine.mark_watch_subscribed(mint)
        bot._count_watch("promoted")
