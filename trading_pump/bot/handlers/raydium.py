"""Graduation handlers of the trading runtime: Raydium, PumpSwap, arbitrage.

Raydium pool creation (graduation sniping and AMM exits), the PumpSwap exit
of a held coin that migrated (BUG-123) with its backfill loop, and the
cross-venue arbitrage evaluated on curve, trade and pool updates. `TradingBot`
(`bot/run.py`) keeps a thin delegating method for each function.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

from trading_pump.bot.handlers import observe
from trading_pump.bot.strategy import ArbitrageOpportunity, RaydiumPoolKeys
from trading_pump.ops.events import EventCategory
from trading_pump.sdk.costs import (
    BASE_FEE_LAMPORTS_PER_SIGNATURE,
    LAMPORTS_PER_SOL,
    TransactionCosts,
    model_transaction_costs,
)

if TYPE_CHECKING:
    from trading_pump.bot.run import TradingBot

# Upper bound on the post-landing ``getTransaction`` cost lookup of an arbitrage
# bundle (BUG-99); on timeout the modelled costs are booked instead.
ARBITRAGE_COST_LOOKUP_TIMEOUT_SECONDS = 8.0


async def handle_raydium_pool_update(
    bot: TradingBot, pool_keys: RaydiumPoolKeys
) -> None:
    """Handle Raydium AMM pool creation and dispatch graduation breakout buys."""
    if bot._stop_requested:
        return

    mint = pool_keys.coin_mint
    bot._log(f"Raydium AMM pool initialized for {mint}: amm_id={pool_keys.amm_id}")
    bot._last_event = f"raydium pool {mint[:8]}"
    bot.graduation_engine.record_raydium_pool(mint=mint, pool_keys=pool_keys)

    if mint in bot.active_positions:
        # Attach the pool to the held position and exit through the AMM (BUG-44).
        bot._raydium_exit_pools[mint] = pool_keys
        if mint in bot._migrating_mints:
            await bot._sell_token(mint, reason="bonding_curve_graduated")
        return

    if not bot.config.enable_raydium_migration_sniping:
        return

    signal = bot.graduation_engine.evaluate_graduation_signal(
        mint=mint,
    )

    if signal.triggered and signal.stage == "raydium_pool_ready":
        async with bot._trade_lock:
            if mint in bot.active_positions or bot._is_recently_seen(mint):
                return

            screening_verdict = await bot._enrich_and_screen_token(mint)
            if not screening_verdict.passed:
                bot._log(
                    f"Raydium migration snipe skipped for {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f})"
                )
                bot._last_event = f"screen_rejected {mint[:8]}"
                return

            buy_amount = bot.config.raydium_buy_amount_sol
            if not bot._should_buy(
                mint,
                market_cap_sol=69.0,
                screening_verdict=screening_verdict,
                proposed_entry_sol=buy_amount,
            ):
                return

            bot._log(
                f"Executing Raydium graduation snipe for {mint} with {buy_amount:.3f} SOL"
            )
            bot._last_event = f"sniping raydium {mint[:8]}"
            bought = await bot._buy_raydium_token(
                mint,
                pool_keys=pool_keys,
                screening_verdict=screening_verdict,
                reason="raydium_graduation_snipe",
            )
            if bought:
                bot._record_event(f"bought raydium {mint[:8]}")

    # Check for immediate cross-venue arbitrage on newly listed Raydium pool
    if bot.config.enable_cross_venue_arbitrage:
        cand = bot.graduation_engine.get_candidate(mint)
        if cand:
            virt_sol = int(round((cand.real_sol_reserves + 30.0) * 1_000_000_000))
            virt_tok = int(200_000_000_000_000)
            await bot._evaluate_and_execute_arbitrage(
                mint=mint,
                virtual_sol=virt_sol,
                virtual_token=virt_tok,
            )


async def arbitrage_costs(
    bot: TradingBot, opp: ArbitrageOpportunity, signature: str | None
) -> TransactionCosts:
    """Fee, priority fee and tip of a landed arbitrage bundle (BUG-99)."""
    getter = getattr(bot.execution, "get_transaction_costs", None)
    if signature and not (bot.dry_run or bot.paper_trade) and callable(getter):
        try:
            costs = await asyncio.wait_for(
                getter(signature, opp.mint, is_buy=True),
                timeout=ARBITRAGE_COST_LOOKUP_TIMEOUT_SECONDS,
            )
            if isinstance(costs, TransactionCosts):
                return costs
        except Exception as exc:
            bot._log(
                f"[ARBITRAGE] could not read costs of {signature}: {exc}; "
                "booking modelled costs",
                level=logging.WARNING,
            )
    gas_lamports = int(round(float(opp.estimated_fees_sol) * LAMPORTS_PER_SOL))
    return model_transaction_costs(
        priority_fee_lamports=max(0, gas_lamports - BASE_FEE_LAMPORTS_PER_SIGNATURE),
        tip_lamports=int(round(float(opp.estimated_jito_tip_sol) * LAMPORTS_PER_SOL)),
        signature=signature,
    )


async def evaluate_and_execute_arbitrage(
    bot: TradingBot,
    mint: str,
    virtual_sol: int,
    virtual_token: int,
    trade_sol: float = 0.0,
    is_buy: bool = True,
) -> None:
    """Evaluate cross-venue disparity and execute atomic Jito arbitrage bundle."""
    if not bot.config.enable_cross_venue_arbitrage or bot._stop_requested:
        return

    candidate = bot.graduation_engine.get_candidate(mint)
    if not candidate or not candidate.pool_keys:
        return

    pool_keys = candidate.pool_keys
    # Derive Raydium pool reserves from candidate real reserves
    ray_sol = int(round((candidate.real_sol_reserves or 80.0) * 1_000_000_000))
    ray_tokens = int(200_000_000_000_000)

    opp: Optional[ArbitrageOpportunity] = None
    if bot.config.enable_mempool_backrunning and trade_sol >= 1.0:
        opp = bot.backrun_engine.evaluate_whale_transaction(
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
        opp = bot.arb_monitor.evaluate_spread(
            mint=mint,
            pump_virtual_sol=virtual_sol,
            pump_virtual_token=virtual_token,
            raydium_sol_reserve=ray_sol,
            raydium_token_reserve=ray_tokens,
            raydium_keys=pool_keys,
        )

    if opp is not None and opp.is_profitable:
        bot._log(
            f"[ARBITRAGE] Found {opp.direction} spread {opp.spread_pct * 100:.2f}% on {mint[:8]}! "
            f"Optimal size: {opp.optimal_input_sol:.4f} SOL -> Est Profit: {opp.net_profit_sol:.4f} SOL"
        )
        if hasattr(bot, "event_logger") and bot.event_logger:
            bot.event_logger.emit(
                category=EventCategory.ARBITRAGE,
                event_name="arbitrage_opportunity_detected",
                mint=mint,
                data=opp.to_dict(),
            )

        if not opp.reserves_verified:
            # Reserves above are placeholders (curve SOL + a constant token
            # lot), so the spread is not real: never execute or bank it, in
            # live or dry-run (BUG-59).
            bot._log(
                f"[ARBITRAGE] {mint[:8]} not executed: reserves are estimates, "
                "not on-chain reads",
                level=logging.WARNING,
            )
            return
        res = await bot.arb_executor.execute_arbitrage(opp)
        if res.get("success"):
            # Book net of the bundle's network fee, priority fee and Jito tip
            # (BUG-99): read from the landed transaction, modelled otherwise.
            signature = res.get("signature")
            arb_costs = await bot._arbitrage_costs(
                opp, signature if isinstance(signature, str) else None
            )
            gross_profit = float(opp.expected_output_sol) - float(opp.optimal_input_sol)
            bot._record_trade(
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
            if bot.dry_run or bot.paper_trade:
                bot.wallet_balance_sol += gross_profit
            bot._book_trade_costs(
                gross_profit - arb_costs.total_cost_sol, arb_costs.total_cost_sol
            )
            if hasattr(bot, "event_logger") and bot.event_logger:
                bot.event_logger.emit(
                    category=EventCategory.ARBITRAGE,
                    event_name="arbitrage_bundle_landed",
                    mint=mint,
                    data=res,
                )
        else:
            if hasattr(bot, "event_logger") and bot.event_logger:
                bot.event_logger.emit(
                    category=EventCategory.ARBITRAGE,
                    event_name="arbitrage_bundle_reverted",
                    mint=mint,
                    data=res,
                )


# Waits between PumpSwap pool reads of one migrated coin after a failure:
# doubling from the first value to the cap (BUG-148, BUG-151).
POOL_RETRY_FIRST_SECONDS = 2.0
POOL_RETRY_MAX_SECONDS = 60.0


def _pool_errors(bot: TradingBot) -> dict[str, str]:
    errors: dict[str, str] | None = getattr(bot, "_pool_read_errors", None)
    if errors is None:
        errors = bot._pool_read_errors = {}
    return errors


async def pumpswap_exit_market_cap(bot: TradingBot, mint: str) -> float | None:
    """Market cap of a migrated coin's PumpSwap pool; ``None`` while it is missing.

    Why a read failed is kept in ``bot._pool_read_errors`` for the warning
    :func:`note_pool_unavailable` logs (BUG-148).
    """
    getter = getattr(bot.execution, "get_pumpswap_market_state", None)
    if getter is None:
        _pool_errors(bot)[mint] = "no PumpSwap client"
        return None
    try:
        state = await asyncio.wait_for(getter(mint), timeout=5.0)
        mc = float(state.get("market_cap_sol", 0.0) or 0.0)
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        _pool_errors(bot)[mint] = reason[:200]
        bot._log(
            f"PumpSwap pool for {mint[:8]} not ready: {reason}", level=logging.DEBUG
        )
        return None
    if mc <= 0.0:
        _pool_errors(bot)[mint] = "pool has no price"
        return None
    _pool_errors(bot).pop(mint, None)
    return mc


def pool_read_due(bot: TradingBot, mint: str, now: float) -> bool:
    """Whether a migrated coin's pool may be read again (after a failure's wait)."""
    retry = getattr(bot, "_pool_retry", {}).get(mint)
    return retry is None or now >= float(retry["next_at"])


def note_pool_unavailable(
    bot: TradingBot, mint: str, position: dict[str, Any], now: float
) -> None:
    """A migrated coin's pool could not be read: back off, flag the price stale.

    The wait doubles from ``POOL_RETRY_FIRST_SECONDS`` to
    ``POOL_RETRY_MAX_SECONDS``; a warning names the cause on the first
    failure and then at 2, 4, 8, ... failures, so a dead RPC is visible in
    ``bot.log`` without a line every second (BUG-148).
    """
    retries: dict[str, dict[str, Any]] | None = getattr(bot, "_pool_retry", None)
    if retries is None:
        retries = bot._pool_retry = {}
    entry = retries.setdefault(mint, {"failures": 0, "next_at": now})
    entry["failures"] = int(entry["failures"]) + 1
    failures = int(entry["failures"])
    wait = min(POOL_RETRY_MAX_SECONDS, POOL_RETRY_FIRST_SECONDS * 2 ** (failures - 1))
    entry["next_at"] = now + wait
    if not position.get("price_stale"):
        position["price_stale"] = True
        position["price_stale_since"] = time.time()
    bot._last_event = f"awaiting pool {mint[:8]}"
    if failures & (failures - 1) == 0:
        error = _pool_errors(bot).get(mint, "unknown error")
        bot._log(
            f"PumpSwap pool for {mint[:8]} unreadable ({failures} tries): {error}; "
            f"the position's value is stale and its exit waits; next try in "
            f"{wait:.0f}s",
            level=logging.WARNING,
        )
        if failures == 1:
            bot._record_event(f"awaiting pool {mint[:8]}: {error[:120]}", alert=False)


def note_pool_read(bot: TradingBot, mint: str, position: dict[str, Any]) -> None:
    """A pool read worked: clear the backoff and the stale flag."""
    entry = getattr(bot, "_pool_retry", {}).pop(mint, None)
    if position.pop("price_stale", None) or entry is not None:
        position.pop("price_stale_since", None)
        if entry is not None:
            bot._log(
                f"PumpSwap pool for {mint[:8]} readable again after "
                f"{entry['failures']} failed tries",
                level=logging.INFO,
            )


async def exit_graduated_position(bot: TradingBot, mint: str) -> bool:
    """A held curve completed: mark it migrating and sell the rest (BUG-123).

    Called from every curve refresh, so a pool that is not there yet is
    retried on the next pass.
    """
    if mint not in bot.active_positions:
        return False
    if mint not in bot._migrating_mints:
        bot._migrating_mints.add(mint)
        # A held coin whose migration event was missed is followed too (FEAT-73).
        observe.start_graduation(bot, mint)
        bot._exit_retry_queue.pop(mint, None)
        bot._market_regime().record_graduation(mint)
        bot.graduation_engine.record_graduation(
            mint=mint, bonding_curve="", timestamp=time.time()
        )
        bot._record_event(f"graduated while held {mint[:8]}", alert=False)
        bot._log(
            f"Held coin {mint} graduated: exiting through its PumpSwap pool",
            level=logging.INFO,
        )
    return await bot._sell_token(mint, reason="bonding_curve_graduated")


async def handle_ws_migration(bot: TradingBot, mint: str) -> None:
    """PumpPortal migration event: count it, follow its pool (record-only),
    drop a watched mint, exit a held one."""
    if bot._market_regime().record_graduation(mint) and (
        bot.replay_recorder is not None
    ):
        # No price field: replay skips it; regime analysis counts it.
        bot.replay_recorder.record_snapshot(
            {"timestamp": time.time(), "mint": mint, "event": "migration"}
        )
    observe.start_graduation(bot, mint)
    if bot._stop_requested:
        return
    engine = bot.order_flow_engine
    entry = engine.get_watch(mint) if engine.is_watched(mint) else None
    if entry is not None:
        bot._count_watch("dropped_complete")
        engine.unwatch(mint)
        if entry.subscribed and mint not in bot.active_positions:
            await bot._unsubscribe_from_token_trades(None, mint)
    if mint in bot.active_positions:
        await bot._exit_graduated_position(mint)


async def graduation_backfill_pass(bot: TradingBot) -> int:
    """Third graduation source: ask the Pump.fun API about each held mint.

    Catches a migration the curve refresh and ``subscribeMigration`` both
    missed (reconnect, restart). Bounded per mint; a failed lookup just
    waits for the next pass. Returns the number of graduations found.
    """
    found = 0
    for mint in list(bot.active_positions):
        if mint in bot._migrating_mints or bot._stop_requested:
            continue
        try:
            coin = await asyncio.wait_for(bot.api.get_coin(mint), timeout=5.0)
        except Exception as exc:
            bot._log(
                f"Graduation backfill lookup failed for {mint[:8]}: {exc}",
                level=logging.DEBUG,
            )
            continue
        if not isinstance(coin, dict) or not (
            coin.get("complete") is True or coin.get("pump_swap_pool")
        ):
            continue
        found += 1
        bot._count_watch("graduation_backfill")
        bot._record_event(
            f"graduation backfill: {mint[:8]} completed (missed by stream)",
            alert=False,
        )
        await bot._exit_graduated_position(mint)
    return found


async def run_graduation_backfill_loop(bot: TradingBot) -> None:
    interval = float(getattr(bot.config, "graduation_backfill_seconds", 0) or 0)
    if interval <= 0:
        return
    while not bot._stop_requested:
        try:
            await asyncio.sleep(interval)
            await bot._graduation_backfill_pass()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            bot._log(f"Graduation backfill exception: {exc}", level=logging.DEBUG)
