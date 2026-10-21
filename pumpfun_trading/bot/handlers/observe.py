"""Record-only curve observations of the trading runtime (rc.3).

Two lists of curves polled for the capture only (see
``strategies/observation.py``): a deterministic sample of screen-rejected
launches and curves past ``graduation_discovery_min_real_sol`` found by a
bounded Pump.fun API scan. They run in their own task (started by the watch
poll loop), never take a trade subscription and never buy, so a run with them
trades exactly like one without.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pumpfun_trading.ops.events import EventCategory, EventSeverity
from pumpfun_trading.strategies.graduation import GRADUATION_REAL_SOL
from pumpfun_trading.strategies.observation import (
    DISCOVERY_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
    REJECT_SAMPLE_SOURCE,
    CurveObservationList,
    discovery_candidates,
    in_reject_sample,
)

if TYPE_CHECKING:
    from pumpfun_trading.bot.run import TradingBot

# Coins per discovery scan page (one API request per scan).
DISCOVERY_SCAN_LIMIT = 50
# Bounded waits: an observation never holds its task longer than this.
OBSERVATION_RPC_TIMEOUT_SECONDS = 10.0
DISCOVERY_API_TIMEOUT_SECONDS = 10.0
# A brand-new account can lag on load-balanced RPCs; don't end it this early.
MISSING_ACCOUNT_GRACE_SECONDS = 15.0


def reject_sample_list(bot: TradingBot) -> CurveObservationList | None:
    """The reject sample, or ``None`` when ``screen_reject_sample_pct`` is 0."""
    share = float(getattr(bot.config, "screen_reject_sample_pct", 0.0) or 0.0)
    if share <= 0.0:
        return None
    book: CurveObservationList | None = getattr(bot, "_reject_sample_list", None)
    if book is None:
        book = bot._reject_sample_list = CurveObservationList(
            source=REJECT_SAMPLE_SOURCE,
            max_mints=int(bot.config.screen_reject_sample_max_mints),
            ttl_seconds=float(bot.config.screen_reject_sample_ttl_seconds),
            poll_interval_seconds=float(bot.config.observation_poll_interval_seconds),
        )
    return book


def discovery_list(bot: TradingBot) -> CurveObservationList | None:
    """Discovered curves, or ``None`` when the scan is off."""
    scan = float(getattr(bot.config, "graduation_discovery_scan_seconds", 0.0) or 0.0)
    if scan <= 0.0:
        return None
    book: CurveObservationList | None = getattr(bot, "_discovery_list", None)
    if book is None:
        book = bot._discovery_list = CurveObservationList(
            source=DISCOVERY_SOURCE,
            max_mints=int(bot.config.graduation_discovery_max_mints),
            ttl_seconds=float(bot.config.graduation_discovery_ttl_seconds),
            poll_interval_seconds=float(bot.config.observation_poll_interval_seconds),
            min_real_sol=float(bot.config.graduation_discovery_min_real_sol),
        )
    return book


def observations_enabled(bot: TradingBot) -> bool:
    """Observations only exist in the capture: off without a recorder."""
    if bot.replay_recorder is None or bot._entry_mode() != "confirmed":
        return False
    return reject_sample_list(bot) is not None or discovery_list(bot) is not None


def observation_status(bot: TradingBot) -> dict[str, Any]:
    """Status-snapshot fields (only for the lists that are on)."""
    status: dict[str, Any] = {}
    for key, book in (
        ("reject_sample", getattr(bot, "_reject_sample_list", None)),
        ("discovery", getattr(bot, "_discovery_list", None)),
    ):
        if isinstance(book, CurveObservationList):
            status[key] = book.snapshot()
    return status


def _record(bot: TradingBot, row: dict[str, Any]) -> None:
    if bot.replay_recorder is not None:
        bot.replay_recorder.record_snapshot(row)


def maybe_sample_rejected(
    bot: TradingBot, mint: str, data: dict[str, Any], verdict: Any
) -> bool:
    """Observe a screen-rejected launch if it falls in the sample."""
    if not observations_enabled(bot):
        return False
    book = reject_sample_list(bot)
    if book is None or not in_reject_sample(
        mint, float(bot.config.screen_reject_sample_pct)
    ):
        return False
    now = time.time()
    created_at = float(data.get("timestamp") or now)
    if created_at > 1e12:  # milliseconds
        created_at /= 1000.0
    reasons = list(getattr(verdict, "reasons", None) or [])
    entry = book.add(mint, now=now, created_at=created_at, reasons=reasons)
    if entry is None:
        return False
    _record(
        bot,
        {
            "timestamp": now,
            "mint": mint,
            "event": OBSERVATION_START_EVENT,
            "source": REJECT_SAMPLE_SOURCE,
            "created_at": created_at,
            "reject_reasons": reasons,
            "risk_score": float(getattr(verdict, "risk_score", 0.0) or 0.0),
        },
    )
    bot._count_watch("reject_sampled")
    return True


def end_observation(
    bot: TradingBot, book: CurveObservationList, mint: str, cause: str, now: float
) -> None:
    entry = book.remove(mint, cause)
    if entry is None:
        return
    _record(
        bot,
        {
            "timestamp": now,
            "mint": mint,
            "event": OBSERVATION_END_EVENT,
            "source": book.source,
            "cause": cause,
            "observed_seconds": round(max(0.0, now - entry.added_at), 1),
            "polls": entry.polls,
            "first_real_sol": entry.first_real_sol,
            "last_real_sol": entry.last_real_sol,
            "peak_real_sol": round(entry.peak_real_sol, 9),
        },
    )


async def scan_discovery(
    bot: TradingBot, book: CurveObservationList, now: float
) -> int:
    """One Pump.fun API scan for curves past the floor; returns mints added."""
    last = float(getattr(bot, "_discovery_scanned_at", 0.0) or 0.0)
    if now - last < float(bot.config.graduation_discovery_scan_seconds):
        return 0
    bot._discovery_scanned_at = now
    try:
        payload = await asyncio.wait_for(
            bot.api.scan_active_coins(limit=DISCOVERY_SCAN_LIMIT),
            timeout=DISCOVERY_API_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        bot._count_watch("discovery_scan_errors")
        bot._log(f"Discovery scan failed: {exc}", level=logging.DEBUG)
        return 0
    bot._count_watch("discovery_scans")
    reject_sample = reject_sample_list(bot)
    added = 0
    for mint, created_at in discovery_candidates(
        payload,
        min_real_sol=float(bot.config.graduation_discovery_min_real_sol),
        max_real_sol=GRADUATION_REAL_SOL,
    ):
        # Mints the bot already polls keep their own rows.
        if (
            mint in bot.active_positions
            or bot.order_flow_engine.is_watched(mint)
            or (reject_sample is not None and mint in reject_sample)
        ):
            continue
        if book.add(mint, now=now, created_at=created_at) is None:
            continue
        added += 1
        _record(
            bot,
            {
                "timestamp": now,
                "mint": mint,
                "event": OBSERVATION_START_EVENT,
                "source": DISCOVERY_SOURCE,
                "created_at": created_at,
            },
        )
    return added


async def poll_observations(bot: TradingBot) -> None:
    """Scan, expire and batch-poll the observation lists once."""
    from pumpfun_trading.bot.handlers.watch import record_curve_poll

    now = time.time()
    discovery = discovery_list(bot)
    books = [b for b in (reject_sample_list(bot), discovery) if b is not None]
    if discovery is not None:
        await scan_discovery(bot, discovery, now)
    due: dict[str, CurveObservationList] = {}
    for book in books:
        for mint in book.expired(now):
            end_observation(bot, book, mint, "ttl", now)
        for mint in book.due(now):
            due.setdefault(mint, book)
    if not due:
        return
    rejected: dict[str, str] = {}
    try:
        states = await asyncio.wait_for(
            bot.execution.get_bonding_curve_states(list(due), rejected=rejected),
            timeout=OBSERVATION_RPC_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        bot._count_watch("observation_poll_errors")
        if getattr(bot, "event_logger", None) is not None:
            bot.event_logger.emit(
                category=EventCategory.STRATEGY,
                severity=EventSeverity.DEBUG,
                event_name="observation_poll_failed",
                data={"mints": len(due), "error": str(exc)[:200]},
            )
        return
    skip_mayhem = bool(getattr(bot.config, "skip_mayhem_mode", True))
    for mint, state in states.items():
        polled = due.get(mint)
        if polled is None:
            continue
        book = polled
        if state.get("complete"):
            end_observation(bot, book, mint, "complete", now)
            continue
        if skip_mayhem and state.get("is_mayhem_mode"):
            end_observation(bot, book, mint, "mayhem", now)
            continue
        v_sol = int(state.get("virtual_sol_reserves", 0) or 0) / 1e9
        v_tok = int(state.get("virtual_token_reserves", 0) or 0) / 1e6
        real_sol = int(state.get("real_sol_reserves", 0) or 0) / 1e9
        market_cap = v_sol * (1_000_000_000.0 / v_tok) if v_tok > 0 else 0.0
        entry = book.get(mint)
        extra = (
            {"reject_reasons": list(entry.reasons)}
            if entry is not None and entry.reasons
            else None
        )
        record_curve_poll(
            bot,
            mint,
            market_cap,
            ts=now,
            source=book.source,
            real_sol=real_sol,
            virtual_sol=v_sol,
            extra=extra,
        )
        cause = book.update(mint, real_sol=real_sol, now=now)
        if cause is not None:
            end_observation(bot, book, mint, cause, now)
    for mint, reason in rejected.items():
        rejected_book = due.get(mint)
        if rejected_book is None:
            continue
        entry = rejected_book.get(mint)
        if (
            reason == "missing"
            and entry is not None
            and now - entry.added_at < MISSING_ACCOUNT_GRACE_SECONDS
        ):
            continue
        end_observation(bot, rejected_book, mint, reason, now)


async def run_observation_loop(bot: TradingBot) -> None:
    """Polls the observation lists in their own task until the bot stops."""
    interval = max(1.0, float(bot.config.observation_poll_interval_seconds))
    while not bot._stop_requested:
        try:
            await asyncio.sleep(interval)
            await poll_observations(bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            bot._log(f"Observation poll exception: {exc}", level=logging.DEBUG)


__all__ = [
    "discovery_list",
    "end_observation",
    "maybe_sample_rejected",
    "observation_status",
    "observations_enabled",
    "poll_observations",
    "reject_sample_list",
    "run_observation_loop",
    "scan_discovery",
]
