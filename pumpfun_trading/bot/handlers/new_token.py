"""New-token handlers of the trading runtime.

A create event is screened, then bought at launch (`entry_mode: "launch"`) or
put on the watch list (`entry_mode: "confirmed"`). `TradingBot` (`bot/run.py`)
keeps a thin delegating method for each function
(`bot._handle_new_token_event`, `bot._watch_token`).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pumpfun_trading.bot.enrichment import mayhem_mode_reason, non_pump_launch_reason
from pumpfun_trading.bot.handlers import observe
from pumpfun_trading.bot.handlers.curve import RAW_TOKEN_UNITS_THRESHOLD
from pumpfun_trading.bot.strategy import TokenScreeningVerdict
from pumpfun_trading.ops.events import EventCategory, EventSeverity

if TYPE_CHECKING:
    from pumpfun_trading.bot.run import TradingBot


async def handle_new_token_event(
    bot: TradingBot, data: dict[str, Any], websocket: Any = None
) -> None:
    if bot._stop_requested:
        return

    bot._last_message_at = time.monotonic()
    mint = data.get("mint")
    if not mint:
        return

    bot._observed_tokens_count += 1
    bot._market_regime().record_launch()
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
    token_name = data.get("name") or mint
    bot._last_new_token = mint
    bot._last_new_token_name = (
        f"{token_name} ({mint[:6]}...)" if len(mint) > 6 else token_name
    )

    if hasattr(bot, "event_logger") and bot.event_logger is not None:
        bot.event_logger.emit(
            category=EventCategory.STREAM,
            severity=EventSeverity.DEBUG,
            event_name="new_token_event",
            mint=mint,
            mint_name=token_name,
            data={"market_cap_sol": current_market_cap},
        )

    if bot.replay_recorder is not None:
        price = current_market_cap / 1_000_000_000.0 if current_market_cap > 0 else 0.0
        bot.replay_recorder.record_snapshot(
            {
                "timestamp": time.time(),
                "mint": mint,
                "name": token_name,
                "price": price,
                "market_cap_sol": current_market_cap,
                "is_buy": True,
                "signal": "buy",
            }
        )

    not_pump = non_pump_launch_reason(
        mint,
        data,
        require_suffix=bool(getattr(bot.config, "require_pump_mint_suffix", True)),
    )
    if not_pump is not None:
        # Never screen or buy another launchpad's token (BUG-108).
        key = not_pump.split(",")[0]
        bot._non_pump_rejections[key] = bot._non_pump_rejections.get(key, 0) + 1
        bot._mark_seen(mint)
        bot._last_event = f"not_pump_fun {mint[:8]}"
        if hasattr(bot, "event_logger") and bot.event_logger is not None:
            bot.event_logger.emit(
                category=EventCategory.SCREENING,
                severity=EventSeverity.DEBUG,
                event_name="token_rejected_not_pump_fun",
                mint=mint,
                mint_name=token_name,
                data={"reason": not_pump, "pool": data.get("pool")},
            )
        return

    mayhem = (
        mayhem_mode_reason(data)
        if bool(getattr(bot.config, "skip_mayhem_mode", True))
        else None
    )
    if mayhem is not None:
        # Mayhem curves drift off the standard reserves; never screen them.
        bot._mayhem_rejections = getattr(bot, "_mayhem_rejections", 0) + 1
        bot._mark_seen(mint)
        bot._last_event = f"mayhem_mode {mint[:8]}"
        if hasattr(bot, "event_logger") and bot.event_logger is not None:
            bot.event_logger.emit(
                category=EventCategory.SCREENING,
                severity=EventSeverity.DEBUG,
                event_name="token_rejected_mayhem_mode",
                mint=mint,
                mint_name=token_name,
                data={"reason": mayhem},
            )
        return

    # rc.5 (FEAT-72): a sample of every standard launch, before any screening
    # or entry gate, so the capture is not shaped by what the bot would buy.
    observe.maybe_sample_launch(bot, mint, data, current_market_cap)

    confirmed = bot._entry_mode() == "confirmed"
    async with bot._trade_lock:
        if mint in bot.active_positions or bot._is_recently_seen(mint):
            return

        if confirmed:
            # Watch instead of buy: entry gates run again at confirmation.
            if not bot._may_watch(mint):
                return
        elif not bot._should_buy(mint, current_market_cap):
            return

        screening_verdict = await bot._enrich_and_screen_token(
            mint,
            token_data=data,
            token_name=token_name,
            market_cap_sol=current_market_cap,
        )
        if not screening_verdict.passed:
            bot._log(
                f"Skipping new token {mint}: failed anti-rug screening (score={screening_verdict.risk_score:.1f}, reasons={screening_verdict.reasons})"
            )
            reasons_str = (
                "; ".join(screening_verdict.reasons)
                if screening_verdict.reasons
                else "anti-rug"
            )
            bot._last_event = f"screen_rejected {mint[:8]}"
            bot._record_event(
                f"screen_rejected {mint[:8]}: {reasons_str}",
                alert=False,
            )
            if confirmed:
                # rc.3: poll a sample of rejects for the capture only.
                observe.maybe_sample_rejected(bot, mint, data, screening_verdict)
            return

        if confirmed:
            bot._watch_token(mint, data, current_market_cap, screening_verdict)
            return

        bought = await bot._buy_token(
            mint,
            current_market_cap,
            token_name=token_name,
            screening_verdict=screening_verdict,
        )
        if bought and websocket:
            await bot._subscribe_to_token_trades(websocket, mint)


def watch_token(
    bot: TradingBot,
    mint: str,
    data: dict[str, Any],
    market_cap_sol: float,
    verdict: TokenScreeningVerdict,
) -> None:
    """Put a screened launch on the watch list instead of buying it."""
    v_sol = float(data.get("vSolInBondingCurve", 0.0) or 0.0)
    if v_sol > 1_000_000:
        v_sol /= 1_000_000_000.0
    now = time.time()
    created_at = float(data.get("timestamp") or now)
    if created_at > 1e12:  # milliseconds
        created_at /= 1000.0
    bot.order_flow_engine.watch(
        mint,
        created_at=created_at,
        creator=str(data.get("traderPublicKey") or "") or None,
        verdict=verdict,
        now=now,
        real_sol=max(0.0, v_sol - 30.0) if v_sol > 0 else None,
        market_cap_sol=market_cap_sol,
    )
    bot._count_watch("watched")
    bot._last_event = f"watching {mint[:8]}"
