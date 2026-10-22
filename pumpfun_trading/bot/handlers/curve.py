"""Bonding-curve state handlers of the trading runtime.

Geyser curve-state and curve-complete events, the pre-graduation entry they
can trigger, and the RPC refresh that re-prices held positions from their
curves (and spots a graduation while held). `TradingBot` (`bot/run.py`) keeps
a thin delegating method for each function, so callers and tests still go
through `bot._handle_bonding_curve_state_update` and friends.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pumpfun_trading.bot.strategy import RaydiumPoolKeys
from pumpfun_trading.execution.sell_pipeline import mark_stop_crossing
from pumpfun_trading.streams.geyser import BondingCurveStateUpdate, CompleteEventUpdate

if TYPE_CHECKING:
    from pumpfun_trading.bot.run import TradingBot

# Raw base-unit virtual token reserves are ~1.07e15; UI units are ~1.07e9 (BUG-75).
RAW_TOKEN_UNITS_THRESHOLD = 1_000_000_000_000


def curve_market_cap(curve: Any) -> float | None:
    """Market cap (SOL) of a decoded curve, or ``None`` when it has no price."""
    if not isinstance(curve, dict) or curve.get("complete") is True:
        return None
    mc = float(curve.get("market_cap_sol", 0.0) or 0.0)
    if mc <= 0.0:
        vt = int(curve.get("virtual_token_reserves", 0) or 0)
        vs = int(curve.get("virtual_sol_reserves", 0) or 0)
        if vt > 0 and vs > 0:
            mc = (vs / 1_000_000_000.0) * (1_000_000_000.0 / (vt / 1_000_000.0))
    return mc if mc > 0.0 else None


def note_stop_crossing(
    bot: TradingBot, mint: str, market_cap_sol: float, *, source: str
) -> None:
    """Remember the first ``source`` price of a held mint at or below the stop
    (``record_stop_crossings``, rc.3); measures only, decides nothing."""
    if not getattr(bot.config, "record_stop_crossings", False):
        return
    position = bot.active_positions.get(mint)
    if position is None:
        return
    mark_stop_crossing(
        position,
        market_cap=market_cap_sol,
        stop_loss=float(bot.config.stop_loss),
        source=source,
        ts=time.time(),
    )


async def handle_bonding_curve_state_update(
    bot: TradingBot, update: BondingCurveStateUpdate
) -> None:
    if bot._stop_requested:
        return

    bot._last_message_at = time.monotonic()
    bot._last_status = "processing geyser stream"
    latency_ms = max(0.0, (time.time() - update.timestamp) * 1000.0)
    bot._record_metric("latency_ms", latency_ms)

    mint = update.mint
    bot._observed_tokens_count += 1
    bot._last_new_token = mint
    bot._last_new_token_name = f"{mint[:8]}..."
    current_market_cap = update.market_cap_sol

    real_sol = update.real_sol_reserves / 1_000_000_000.0
    virt_sol = update.virtual_sol_reserves / 1_000_000_000.0
    bot._feed_slippage_estimator(
        mint, update.virtual_sol_reserves, update.virtual_token_reserves
    )
    bot.graduation_engine.update_bonding_curve(
        mint=mint,
        bonding_curve=update.bonding_curve_pubkey,
        real_sol_reserves=real_sol,
        virtual_sol_reserves=virt_sol,
        market_cap_sol=current_market_cap,
        complete=update.complete,
        timestamp=update.timestamp,
    )

    if bot.config.enable_cross_venue_arbitrage:
        await bot._evaluate_and_execute_arbitrage(
            mint=mint,
            virtual_sol=update.virtual_sol_reserves,
            virtual_token=update.virtual_token_reserves,
        )

    if bot.replay_recorder is not None:
        price = current_market_cap / 1_000_000_000.0 if current_market_cap > 0 else 0.0
        bot.replay_recorder.record_snapshot(
            {
                "timestamp": update.timestamp,
                "mint": mint,
                "name": bot.active_positions.get(mint, {}).get("name")
                or f"{mint[:8]}...",
                "price": price,
                "market_cap_sol": current_market_cap,
                "volume": real_sol,
            }
        )

    if mint in bot.active_positions:
        await bot._evaluate_and_execute_exit(mint, current_market_cap)
        await bot._check_and_enforce_circuit_breaker()
        return

    if not update.complete and current_market_cap > 0:
        if (
            bot.daily_equity_tracker.circuit_breaker_engaged
            or await bot._check_and_enforce_circuit_breaker()
        ):
            bot._last_event = "circuit_breaker_active"
            return

        # Pre-graduation acceleration harvesting evaluation (FEAT-25)
        if await bot._maybe_buy_pre_graduation(
            mint, current_market_cap, now=update.timestamp
        ):
            return

        async with bot._trade_lock:
            if bot._is_recently_seen(mint):
                return

            screening_verdict = await bot._enrich_and_screen_token(mint)
            if not screening_verdict.passed:
                bot._log(
                    f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
                )
                reasons_str = (
                    "; ".join(screening_verdict.reasons)
                    if screening_verdict.reasons
                    else "anti-rug"
                )
                bot._record_event(
                    f"screen_rejected {mint[:8]}: {reasons_str}",
                    alert=False,
                )
                return

            if not bot._should_buy(
                mint, current_market_cap, screening_verdict=screening_verdict
            ):
                bot._log(f"Skipping new token {mint}: not eligible for buy")
                bot._last_event = f"skipped {mint}"
                return

            bot._log(
                f"New token detected via Geyser: {mint} | launch market cap: {current_market_cap:.2f} SOL"
            )
            bot._last_event = f"new token {mint}"
            bot._last_new_token = mint
            bot._last_new_token_name = mint[:8]
            bought = await bot._buy_token(
                mint,
                current_market_cap,
                None,
                screening_verdict=screening_verdict,
            )

        if bought:
            bot._record_event(
                f"bought {bot.active_positions.get(mint, {}).get('name', mint)}"
            )


async def handle_complete_event_update(
    bot: TradingBot, update: CompleteEventUpdate
) -> None:
    if bot._stop_requested:
        return

    mint = update.mint
    curve_key = getattr(update, "bonding_curve", None) or getattr(
        update, "bonding_curve_pubkey", ""
    )
    bot._log(
        f"Bonding curve completed / graduated for {mint}! Bonding curve: {curve_key}"
    )
    bot._last_event = f"graduated {mint[:8]}"
    bot._market_regime().record_graduation(mint)
    bot.graduation_engine.record_graduation(
        mint=mint,
        bonding_curve=str(curve_key),
        timestamp=update.timestamp,
    )

    if mint in bot.active_positions:
        # A completed curve rejects trades: exit on the AMM instead (BUG-44).
        bot._migrating_mints.add(mint)
        bot._exit_retry_queue.pop(mint, None)
        candidate = bot.graduation_engine.get_candidate(mint)
        pool = getattr(candidate, "pool_keys", None) if candidate else None
        if isinstance(pool, RaydiumPoolKeys):
            bot._raydium_exit_pools[mint] = pool
            await bot._sell_token(mint, reason="bonding_curve_graduated")
        elif not await bot._sell_token(mint, reason="bonding_curve_graduated"):
            bot._log(
                f"Position held for graduating token {mint}; waiting for the AMM pool to exit."
            )


async def maybe_buy_pre_graduation(
    bot: TradingBot,
    mint: str,
    market_cap_sol: float,
    *,
    now: float,
    min_samples: int = 0,
) -> bool:
    """Pre-graduation harvesting entry (FEAT-25, FEAT-53).

    Runs from the Geyser curve handler and from the watch-list poller.
    Returns ``True`` when the candidate was handled (bought, refused or
    already seen), so the caller must not fall through to a launch buy.
    """
    if (
        not bot.config.enable_pre_graduation_harvesting
        or mint in bot.active_positions
        or bot._is_recently_seen(mint)
    ):
        return False
    min_p = (
        bot.config.pre_graduation_entry_progress_pct * 100.0
        if bot.config.pre_graduation_entry_progress_pct <= 1.0
        else bot.config.pre_graduation_entry_progress_pct
    )
    max_p = (
        bot.config.pre_graduation_max_entry_progress_pct * 100.0
        if bot.config.pre_graduation_max_entry_progress_pct <= 1.0
        else bot.config.pre_graduation_max_entry_progress_pct
    )
    grad_sig = bot.graduation_engine.evaluate_pre_graduation_harvesting_entry(
        mint=mint,
        min_progress_pct=min_p,
        max_progress_pct=max_p,
        min_acceleration=bot.config.pre_graduation_min_acceleration,
        current_time=now,
        min_samples=min_samples,
    )
    if not grad_sig.triggered:
        return False
    async with bot._trade_lock:
        if mint in bot.active_positions or bot._is_recently_seen(mint):
            return True
        screening_verdict = await bot._enrich_and_screen_token(mint)
        if not screening_verdict.passed:
            return True
        if not bot._should_buy(
            mint, market_cap_sol, screening_verdict=screening_verdict
        ):
            if getattr(bot.config, "enable_capital_rotation", True):
                await bot._evaluate_and_trigger_displacement(
                    candidate_mint=mint,
                    market_cap_sol=market_cap_sol,
                    conviction_percentile=0.98,
                    screening_verdict=screening_verdict,
                )
            return True
        bot._log(
            f"Pre-graduation harvesting entry triggered for {mint}: {grad_sig.reason}"
        )
        bot._last_event = f"pre-grad entry {mint[:8]}"
        bought = await bot._buy_token(
            mint,
            market_cap_sol,
            None,
            screening_verdict=screening_verdict,
            reason="pre_graduation_harvesting_entry",
            strategy="pre_graduation",
            entry_metrics={
                "curve_progress_pct": (
                    grad_sig.trajectory.progress_pct if grad_sig.trajectory else None
                ),
                "acceleration_sol_per_sec2": (
                    round(grad_sig.trajectory.acceleration_sol_per_sec2, 6)
                    if grad_sig.trajectory
                    else None
                ),
                "real_sol_reserves": round(grad_sig.real_sol_reserves, 4),
                "market_cap_sol": round(market_cap_sol, 4),
            },
        )
        if bought:
            bot._record_event(f"bought pre-graduation {mint[:8]}")
            watched = bot.order_flow_engine.unwatch(mint)
            if watched is None or not watched.subscribed:
                await bot._subscribe_to_token_trades(None, mint)
            return True
    return False


async def refresh_active_positions_market_caps(bot: TradingBot) -> None:
    """Periodically refresh active position market caps from on-chain bonding curve states."""
    if not bot.active_positions:
        return
    for mint in list(bot.active_positions.keys()):
        try:
            if mint in bot._migrating_mints:
                await bot._exit_graduated_position(mint)
                continue
            curve = await bot.execution.get_bonding_curve_state(mint)
            if isinstance(curve, dict) and curve.get("complete") is True:
                # Graduated while held: the curve has no reserves left to
                # price or sell against (BUG-123).
                await bot._exit_graduated_position(mint)
                continue
            mc = 0.0
            if isinstance(curve, dict):
                mc = float(curve.get("market_cap_sol", 0.0) or 0.0)
                bot._feed_slippage_estimator(
                    mint,
                    int(curve.get("virtual_sol_reserves", 0) or 0),
                    int(curve.get("virtual_token_reserves", 0) or 0),
                )
                if mc <= 0.0:
                    vt = int(curve.get("virtual_token_reserves", 0))
                    vs = int(curve.get("virtual_sol_reserves", 0))
                    if vt > 0 and vs > 0:
                        mc = (vs / 1_000_000_000.0) * (
                            1_000_000_000.0 / (vt / 1_000_000.0)
                        )
                # Paper exits price from this read: record it so replay
                # exits see the same curve.
                bot._record_curve_poll(
                    mint,
                    mc,
                    ts=time.time(),
                    source="position",
                    real_sol=int(curve.get("real_sol_reserves", 0) or 0) / 1e9,
                    virtual_sol=int(curve.get("virtual_sol_reserves", 0) or 0) / 1e9,
                )
                if bot._entry_mode() == "confirmed" and mc > 0.0:
                    # Keep curve progress fresh for held mints so the
                    # pre-graduation tranches sell before migration (FEAT-53).
                    bot.graduation_engine.update_bonding_curve(
                        mint=mint,
                        bonding_curve="",
                        real_sol_reserves=int(curve.get("real_sol_reserves", 0) or 0)
                        / 1_000_000_000.0,
                        virtual_sol_reserves=int(
                            curve.get("virtual_sol_reserves", 0) or 0
                        )
                        / 1_000_000_000.0,
                        market_cap_sol=mc,
                        complete=bool(curve.get("complete", False)),
                    )
            if mc > 0.0:
                note_stop_crossing(bot, mint, mc, source="refresh")
                await bot._evaluate_and_execute_exit(mint, mc)
            else:
                pos = bot.active_positions.get(mint, {})
                curr_mc = float(
                    pos.get("current_market_cap", 0.0)
                    or pos.get("entry_market_cap", 0.0)
                    or 0.0
                )
                if curr_mc > 0.0:
                    await bot._evaluate_and_execute_exit(mint, curr_mc)
        except Exception:
            try:
                pos = bot.active_positions.get(mint, {})
                curr_mc = float(
                    pos.get("current_market_cap", 0.0)
                    or pos.get("entry_market_cap", 0.0)
                    or 0.0
                )
                if curr_mc > 0.0:
                    await bot._evaluate_and_execute_exit(mint, curr_mc)
            except Exception:
                pass
