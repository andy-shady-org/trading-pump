"""Trade-stream handlers of the trading runtime.

Geyser trade events and PumpPortal trade messages, the follow-on demand they
record, the confirmed-momentum entry they can trigger and the FEAT-58 shadow
variants evaluated on them. `TradingBot` (`bot/run.py`) keeps a thin
delegating method for each function (`bot._handle_trade_update`, ...).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from pumpfun_trading.bot.handlers.curve import (
    RAW_TOKEN_UNITS_THRESHOLD,
    curve_market_cap,
)
from pumpfun_trading.strategies.shadow import ShadowSignal, shadow_fill_record
from pumpfun_trading.streams.geyser import TradeEventUpdate

if TYPE_CHECKING:
    from pumpfun_trading.bot.run import TradingBot

# Shadow fills waiting for their delayed curve read; more are counted and
# skipped so a burst of signals can't pile up RPC reads (FEAT-58).
MAX_PENDING_SHADOW_FILLS = 50


async def handle_trade_event_update(bot: TradingBot, update: TradeEventUpdate) -> None:
    if bot._stop_requested:
        return

    bot._last_message_at = time.monotonic()
    latency_ms = max(0.0, (time.time() - update.received_at) * 1000.0)
    bot._record_metric("latency_ms", latency_ms)

    mint = update.mint
    bot._observed_tokens_count += 1
    ts = float(update.timestamp if update.timestamp > 0 else update.received_at)
    bot.order_flow_engine.record_trade(
        mint=mint,
        is_buy=update.is_buy,
        sol_amount=update.sol_amount,
        user=update.user,
        timestamp=ts,
    )

    if bot.config.enable_cross_venue_arbitrage and update.virtual_sol_reserves > 0:
        await bot._evaluate_and_execute_arbitrage(
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

    if bot.replay_recorder is not None:
        bot.replay_recorder.record_snapshot(
            {
                "timestamp": ts,
                "mint": mint,
                "name": bot.active_positions.get(mint, {}).get("name")
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

    if mint in bot.active_positions:
        if current_market_cap <= 0:
            return

        if (
            not update.is_buy
            and bot.config.enable_copy_trading
            and bot.config.copy_trading_mirror_sells
            and bot.copy_trade_engine.is_tracked_wallet(update.user)
        ):
            wallet_obj = bot.copy_trade_engine.registry.get_wallet(update.user)
            wallet_label = (
                wallet_obj.label if wallet_obj and wallet_obj.label else update.user[:8]
            )
            bot._log(
                f"Smart money sell detected on held token {mint} by {wallet_label}... executing mirrored exit."
            )
            bot._last_event = f"copy-trade exit {mint[:8]}"
            await bot._sell_token(mint, reason=f"copy_trade_mirror_exit_{wallet_label}")
            return

        await bot._evaluate_and_execute_exit(mint, current_market_cap)
        await bot._check_and_enforce_circuit_breaker()
        return

    if current_market_cap <= 0:
        return

    # Smart Money Copy-Trading Entry Evaluation
    if (
        update.is_buy
        and bot.config.enable_copy_trading
        and bot.copy_trade_engine.is_tracked_wallet(update.user)
        and mint not in bot.active_positions
        and not bot._is_recently_seen(mint)
    ):
        signal = bot.copy_trade_engine.record_and_evaluate(
            user=update.user,
            mint=mint,
            sol_amount=update.sol_amount,
            is_buy=True,
            timestamp=ts,
        )
        if signal.triggered and signal.is_buy and signal.computed_copy_size_sol > 0:
            async with bot._trade_lock:
                if mint in bot.active_positions or bot._is_recently_seen(mint):
                    return

                wallet_obj = bot.copy_trade_engine.registry.get_wallet(update.user)
                wallet_label = (
                    wallet_obj.label
                    if wallet_obj and wallet_obj.label
                    else update.user[:8]
                )
                reason_label = f"copy_trade_{wallet_label}"

                screening_verdict = None
                if bot.config.copy_trading_require_anti_rug_screen:
                    screening_verdict = await bot._enrich_and_screen_token(mint)
                    if not screening_verdict.passed:
                        bot._log(
                            f"Copy-trade buy rejected for {mint} by {wallet_label}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                        )
                        return

                if not bot._should_buy(
                    mint,
                    current_market_cap,
                    screening_verdict=screening_verdict,
                    proposed_entry_sol=signal.computed_copy_size_sol,
                ):
                    return

                bot._log(
                    f"Executing copy-trade buy for {mint} mirroring wallet {wallet_label} ({signal.reason}) with {signal.computed_copy_size_sol:.3f} SOL"
                )
                bot._last_event = f"copy-trade buy {mint[:8]}"
                bought = await bot._buy_token(
                    mint,
                    current_market_cap,
                    None,
                    screening_verdict=screening_verdict,
                    reason=reason_label,
                    buy_amount_sol=signal.computed_copy_size_sol,
                )
                if bought:
                    bot._record_event(f"bought copy-trade {mint[:8]}")
                    return

    # Momentum Spikes Evaluation
    if (
        bot.config.enable_momentum_signals
        and mint not in bot.active_positions
        and not bot._is_recently_seen(mint)
    ):
        mom_signal = bot.order_flow_engine.evaluate_momentum_signal(
            mint,
            window_seconds=bot.config.momentum_window_seconds,
            min_buy_ratio=bot.config.momentum_min_buy_ratio,
            min_z_score=bot.config.momentum_min_z_score,
            min_unique_buyers=bot.config.momentum_min_unique_buyers,
            min_net_inflow_sol=bot.config.momentum_min_net_inflow_sol,
            baseline_window_seconds=bot.config.momentum_baseline_window_seconds,
            max_token_age_seconds=bot.config.momentum_max_token_age_seconds,
        )

        if mom_signal.triggered:
            async with bot._trade_lock:
                if mint in bot.active_positions or bot._is_recently_seen(mint):
                    return

                screening_verdict = await bot._enrich_and_screen_token(mint)
                if not screening_verdict.passed:
                    bot._log(
                        f"Momentum buy skipped for {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                    )
                    bot._last_event = f"screen_rejected {mint[:8]}"
                    return

                if not bot._should_buy(
                    mint, current_market_cap, screening_verdict=screening_verdict
                ):
                    if getattr(bot.config, "enable_capital_rotation", True):
                        displaced = await bot._evaluate_and_trigger_displacement(
                            candidate_mint=mint,
                            market_cap_sol=current_market_cap,
                            candidate_signal=mom_signal,
                            conviction_percentile=0.95,
                            screening_verdict=screening_verdict,
                        )
                        if displaced:
                            bot._record_event(f"displaced for momentum {mint[:8]}")
                    return

                bot._log(
                    f"Momentum breakout detected for {mint}: {mom_signal.reason} (Z={mom_signal.z_score:.2f}, BuyRatio={mom_signal.buy_sell_ratio:.1f}x, Inflow={mom_signal.net_sol_inflow:.2f} SOL)"
                )
                bot._last_event = f"momentum breakout {mint[:8]}"
                bought = await bot._buy_token(
                    mint,
                    current_market_cap,
                    None,
                    screening_verdict=screening_verdict,
                    reason="momentum_spike",
                )
                if bought:
                    bot._record_event(f"bought momentum {mint[:8]}")


async def handle_trade_update(
    bot: TradingBot, data: dict[str, Any], websocket: Any = None
) -> None:
    if bot._stop_requested:
        return

    bot._last_message_at = time.monotonic()
    mint = data.get("mint")
    if not mint:
        return

    bot._observed_tokens_count += 1
    token_name = data.get("name")
    if token_name:
        bot._last_new_token = mint
        bot._last_new_token_name = (
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
    bot.order_flow_engine.record_trade(
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

    if bot.replay_recorder is not None:
        bot.replay_recorder.record_snapshot(
            {
                "timestamp": ts,
                "mint": mint,
                "name": (
                    token_name
                    or bot.active_positions.get(mint, {}).get("name")
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
                    data.get("token_amount", 0.0) or data.get("tokenAmount", 0.0) or 0.0
                ),
                "user": user,
                "signal": "buy" if is_buy else "sell",
            }
        )

    bot._evaluate_shadow_variants(mint, current_market_cap, now=ts)
    if mint in bot.active_positions:
        bot._note_follow_on_buy(mint, is_buy, sol_amount, user, ts)
    elif bot._entry_mode() == "confirmed":
        entry = bot.order_flow_engine.get_watch(mint)
        if entry is not None and entry.subscribed:
            await bot._maybe_buy_confirmed_momentum(
                mint, current_market_cap, token_name, now=ts
            )
            return

    if mint in bot.active_positions:
        if not bot.dry_run or current_market_cap <= 0.0:
            try:
                curve = await bot.execution.get_bonding_curve_state(mint)
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
            and bot.config.enable_copy_trading
            and bot.config.copy_trading_mirror_sells
            and bot.copy_trade_engine.is_tracked_wallet(user)
        ):
            wallet_obj = bot.copy_trade_engine.registry.get_wallet(user)
            wallet_label = (
                wallet_obj.label if wallet_obj and wallet_obj.label else user[:8]
            )
            bot._log(
                f"Smart money sell detected on held token {mint} by {wallet_label}... executing mirrored exit."
            )
            bot._last_event = f"copy-trade exit {mint[:8]}"
            await bot._sell_token(mint, reason=f"copy_trade_mirror_exit_{wallet_label}")
            return

        await bot._evaluate_and_execute_exit(
            mint, current_market_cap, websocket=websocket
        )
        return

    # Smart Money Copy-Trading Entry Evaluation via WS
    if (
        is_buy
        and bot.config.enable_copy_trading
        and bot.copy_trade_engine.is_tracked_wallet(user)
        and mint not in bot.active_positions
        and not bot._is_recently_seen(mint)
    ):
        signal = bot.copy_trade_engine.record_and_evaluate(
            user=user,
            mint=mint,
            sol_amount=sol_amount,
            is_buy=True,
            timestamp=ts,
        )
        if signal.triggered and signal.is_buy and signal.computed_copy_size_sol > 0:
            async with bot._trade_lock:
                if mint in bot.active_positions or bot._is_recently_seen(mint):
                    return

                wallet_obj = bot.copy_trade_engine.registry.get_wallet(user)
                wallet_label = (
                    wallet_obj.label if wallet_obj and wallet_obj.label else user[:8]
                )
                reason_label = f"copy_trade_{wallet_label}"

                screening_verdict = None
                if bot.config.copy_trading_require_anti_rug_screen:
                    screening_verdict = await bot._enrich_and_screen_token(
                        mint, token_data=data
                    )
                    if not screening_verdict.passed:
                        bot._log(
                            f"Copy-trade buy rejected for {mint} by {wallet_label}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                        )
                        return

                if not bot._should_buy(
                    mint,
                    current_market_cap,
                    screening_verdict=screening_verdict,
                    proposed_entry_sol=signal.computed_copy_size_sol,
                ):
                    return

                bot._log(
                    f"Executing copy-trade buy for {mint} mirroring wallet {wallet_label} ({signal.reason}) with {signal.computed_copy_size_sol:.3f} SOL"
                )
                bot._last_event = f"copy-trade buy {mint[:8]}"
                bought = await bot._buy_token(
                    mint,
                    current_market_cap,
                    data.get("name") or mint,
                    screening_verdict=screening_verdict,
                    reason=reason_label,
                    buy_amount_sol=signal.computed_copy_size_sol,
                )
                if bought and websocket:
                    await bot._subscribe_to_token_trades(websocket, mint)
                return


def note_follow_on_buy(
    bot: TradingBot, mint: str, is_buy: bool, sol_amount: float, user: str, ts: float
) -> None:
    """Remember the last buy by another wallet big enough to count as demand
    for the buy-flow stagnation exit (FEAT-52)."""
    if not is_buy or sol_amount < float(bot.config.stagnant_min_buy_sol):
        return
    if user and user == bot._own_wallet():
        return
    position = bot.active_positions.get(mint)
    if position is not None:
        position["last_qualifying_buy_at"] = float(ts)


async def maybe_buy_confirmed_momentum(
    bot: TradingBot,
    mint: str,
    market_cap_sol: float,
    token_name: str | None,
    *,
    now: float,
) -> bool:
    """Buy a promoted watched mint once its order flow confirms demand."""
    engine = bot.order_flow_engine
    entry = engine.get_watch(mint)
    if entry is None:
        return False
    if market_cap_sol <= 0.0:
        market_cap_sol = entry.market_cap_sol
    exclude = frozenset(u for u in (entry.creator, bot._own_wallet()) if u)
    signal = bot.strategy.evaluate_momentum(
        engine,
        mint,
        token_creation_timestamp=entry.created_at,
        current_time=now,
        exclude_users=exclude,
    )
    age = max(0.0, now - entry.created_at)
    if not bot.strategy.should_buy_momentum(
        momentum_signal=signal,
        active_positions=len(bot.active_positions),
        buy_attempts=bot._buy_attempts.get(mint, 0),
        token_age_seconds=age,
        market_cap_sol=market_cap_sol,
    ):
        return False
    metrics = {
        "unique_buyers": signal.unique_buyers,
        "net_inflow_sol": signal.net_sol_inflow,
        "buy_sell_ratio": signal.buy_sell_ratio,
        "z_score": signal.z_score,
        "token_age_seconds": round(age, 1),
        "market_cap_sol": round(market_cap_sol, 4),
        "sol_growth": round(entry.sol_growth, 6),
    }
    # Recorded for offline tests of the FEAT-56 filters; they gate nothing.
    flow = engine.buy_flow_concentration(mint, exclude_users=exclude, current_time=now)
    metrics["top_buyer_share"] = flow["top_buyer_share"]
    metrics["wallet_diversity"] = flow["wallet_diversity"]
    # FEAT-57 wash-trade inputs, recorded only until they beat a random cut.
    metrics.update(
        engine.round_trip_flow(mint, exclude_users=exclude, current_time=now)
    )
    if entry.first_polled_real_sol is not None and entry.start_real_sol is not None:
        # SOL added between the create and the first curve poll (a few
        # seconds): a proxy for sniper volume, since no capture sees the
        # first slots' trades.
        metrics["first_poll_sol_growth"] = round(
            entry.first_polled_real_sol - entry.start_real_sol, 6
        )
        metrics["first_poll_age_seconds"] = round(
            max(0.0, entry.first_polled_at - entry.created_at), 1
        )
    async with bot._trade_lock:
        if mint in bot.active_positions or not engine.is_watched(mint):
            return False
        bot._count_watch("confirmed")
        bought = await bot._buy_token(
            mint,
            market_cap_sol,
            token_name=token_name,
            screening_verdict=entry.screening_verdict,
            reason="momentum_confirmed",
            strategy="momentum",
            entry_metrics=metrics,
        )
        if bought:
            # Keep the trade subscription: the position needs it now.
            engine.unwatch(mint)
            bot._count_watch("bought")
        elif str(getattr(bot, "_last_buy_error", "") or "").startswith("entry_drift"):
            # The move already happened: stop watching (replay does the same).
            bot._count_watch("drift_refused")
            engine.unwatch(mint)
            if entry.subscribed:
                await bot._unsubscribe_from_token_trades(None, mint)
        return bought


def evaluate_shadow_variants(
    bot: TradingBot, mint: str, market_cap_sol: float, *, now: float
) -> None:
    """Evaluate the shadow variants on a trade of a subscribed watched mint,
    or of a mint seen that way before (bought since, or still trading)."""
    if bot.replay_recorder is None or bot._entry_mode() != "confirmed":
        return  # the result only exists in the capture
    book = bot._shadow_book()
    if book is None:
        return
    entry = bot.order_flow_engine.get_watch(mint)
    if entry is not None and entry.subscribed:
        book.remember(mint, created_at=entry.created_at, creator=entry.creator)
    elif not book.knows(mint):
        return
    own = bot._own_wallet()
    for shadow in book.evaluate(
        bot.order_flow_engine,
        mint,
        now=now,
        market_cap_sol=market_cap_sol,
        exclude_users=frozenset({own}) if own else frozenset(),
    ):
        bot._schedule_shadow_fill(shadow)


def schedule_shadow_fill(bot: TradingBot, shadow: ShadowSignal) -> None:
    tasks: set[asyncio.Task[None]] | None = getattr(bot, "_shadow_fill_tasks", None)
    if tasks is None:
        tasks = set()
        bot._shadow_fill_tasks = tasks
    if len(tasks) >= MAX_PENDING_SHADOW_FILLS:
        bot._count_watch("shadow_skipped")
        return
    bot._count_watch("shadow_signals")
    task = asyncio.get_running_loop().create_task(bot._record_shadow_fill(shadow))
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def record_shadow_fill(bot: TradingBot, shadow: ShadowSignal) -> None:
    """Read the curve when a paper buy would land and record the shadow fill."""
    delay = float(getattr(bot.config, "paper_entry_delay_seconds", 0.0) or 0.0)
    if delay > 0:
        await asyncio.sleep(delay)
    market_cap: float | None = None
    error: str | None = None
    curve: Any = None
    try:
        curve = await asyncio.wait_for(
            bot.execution.get_bonding_curve_state(shadow.mint), timeout=5.0
        )
        market_cap = curve_market_cap(curve)
    except Exception as exc:
        error = f"curve_error: {type(exc).__name__}"
    fill_time = time.time()
    if bot.replay_recorder is None:
        return
    if market_cap:
        bot._record_curve_poll(
            shadow.mint,
            market_cap,
            ts=fill_time,
            source="shadow_fill",
            real_sol=int(curve.get("real_sol_reserves", 0) or 0) / 1e9,
            virtual_sol=int(curve.get("virtual_sol_reserves", 0) or 0) / 1e9,
        )
    bot.replay_recorder.record_snapshot(
        shadow_fill_record(
            shadow,
            fill_market_cap_sol=market_cap,
            fill_time=fill_time,
            error=error,
        )
    )
