"""Record-only curve observations of the trading runtime (rc.3, rc.5).

Lists of curves polled for the capture only (see ``strategies/observation.py``):

* confirmed mode only: a deterministic sample of screen-rejected launches and
  curves past ``graduation_discovery_min_real_sol`` found by a bounded Pump.fun
  API scan (rc.3);
* both entry modes (rc.5, FEAT-72): a deterministic sample of every standard
  Pump.fun launch from its create event, and every fully closed position for
  ``post_exit_observation_seconds`` after the sell.

They run in their own task (started by the watch poll loop), never take a
trade subscription and never buy, so a run with them trades exactly like one
without. A mint in several lists is read once per poll and gets one row per
list.
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
    LAUNCH_SAMPLE_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
    POST_EXIT_SOURCE,
    REJECT_SAMPLE_SOURCE,
    CurveObservationList,
    discovery_candidates,
    in_launch_sample,
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
# Create-event fields copied onto a launch sample's observation_start row.
LAUNCH_EVENT_FIELDS = {
    "traderPublicKey": "creator",
    "solAmount": "creator_buy_sol",
    "initialBuy": "creator_buy_tokens",
    "symbol": "symbol",
    "name": "name",
}
# Longest exit reason kept on post-exit rows.
EXIT_REASON_CHARS = 120


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


def launch_sample_list(bot: TradingBot) -> CurveObservationList | None:
    """The launch sample (rc.5), or ``None`` when ``launch_sample_pct`` is 0."""
    share = float(getattr(bot.config, "launch_sample_pct", 0.0) or 0.0)
    if share <= 0.0:
        return None
    book: CurveObservationList | None = getattr(bot, "_launch_sample_list", None)
    if book is None:
        book = bot._launch_sample_list = CurveObservationList(
            source=LAUNCH_SAMPLE_SOURCE,
            max_mints=int(bot.config.launch_sample_max_mints),
            ttl_seconds=float(bot.config.launch_sample_ttl_seconds),
            poll_interval_seconds=float(bot.config.launch_sample_poll_interval_seconds),
        )
    return book


def post_exit_list(bot: TradingBot) -> CurveObservationList | None:
    """Closed positions (rc.5), or ``None`` when ``post_exit_observation_seconds`` is 0."""
    seconds = float(getattr(bot.config, "post_exit_observation_seconds", 0.0) or 0.0)
    if seconds <= 0.0:
        return None
    book: CurveObservationList | None = getattr(bot, "_post_exit_list", None)
    if book is None:
        book = bot._post_exit_list = CurveObservationList(
            source=POST_EXIT_SOURCE,
            max_mints=int(bot.config.post_exit_max_mints),
            ttl_seconds=seconds,
            poll_interval_seconds=float(bot.config.post_exit_poll_interval_seconds),
        )
    return book


def active_lists(bot: TradingBot) -> list[CurveObservationList]:
    """The lists that run in this entry mode (the rc.3 ones need the watch list)."""
    books = [launch_sample_list(bot), post_exit_list(bot)]
    if bot._entry_mode() == "confirmed":
        books = [reject_sample_list(bot), discovery_list(bot), *books]
    return [b for b in books if b is not None]


def observations_enabled(bot: TradingBot) -> bool:
    """Observations only exist in the capture: off without a recorder."""
    if bot.replay_recorder is None:
        return False
    return bool(active_lists(bot))


def observation_interval(bot: TradingBot) -> float:
    """Loop interval: the shortest poll interval of the lists that are on (>= 1 s)."""
    intervals = [float(b.poll_interval_seconds) for b in active_lists(bot)]
    base = float(bot.config.observation_poll_interval_seconds)
    return max(1.0, min([base, *intervals]))


def observation_status(bot: TradingBot) -> dict[str, Any]:
    """Status-snapshot fields (only for the lists that are on)."""
    status: dict[str, Any] = {}
    for key, book in (
        ("reject_sample", getattr(bot, "_reject_sample_list", None)),
        ("discovery", getattr(bot, "_discovery_list", None)),
        ("launch_sample", getattr(bot, "_launch_sample_list", None)),
        ("post_exit", getattr(bot, "_post_exit_list", None)),
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


def _created_at(data: dict[str, Any], now: float) -> float:
    created_at = float(data.get("timestamp") or now)
    return created_at / 1000.0 if created_at > 1e12 else created_at  # ms


def _guarded(bot: TradingBot, what: str, call: Any) -> bool:
    """Record-only hooks run inside the buy and sell paths: a failure is
    counted and logged, never raised into trading."""
    try:
        return bool(call())
    except Exception as exc:
        bot._count_watch("observation_hook_errors")
        bot._log(f"{what} failed: {exc}", level=logging.DEBUG)
        return False


def maybe_sample_launch(
    bot: TradingBot, mint: str, data: dict[str, Any], market_cap_sol: float
) -> bool:
    """Observe a standard Pump.fun launch from its create event if it falls in
    the launch sample (rc.5). Called before screening, in both entry modes;
    never raises."""
    return _guarded(
        bot,
        "Launch sample",
        lambda: _sample_launch(bot, mint, data, market_cap_sol),
    )


def _sample_launch(
    bot: TradingBot, mint: str, data: dict[str, Any], market_cap_sol: float
) -> bool:
    if bot.replay_recorder is None:
        return False
    book = launch_sample_list(bot)
    if book is None or not in_launch_sample(mint, float(bot.config.launch_sample_pct)):
        return False
    now = time.time()
    created_at = _created_at(data, now)
    if book.add(mint, now=now, created_at=created_at) is None:
        return False
    row: dict[str, Any] = {
        "timestamp": now,
        "mint": mint,
        "event": OBSERVATION_START_EVENT,
        "source": LAUNCH_SAMPLE_SOURCE,
        "created_at": created_at,
        "market_cap_sol": round(float(market_cap_sol or 0.0), 6),
        "entry_mode": bot._entry_mode(),
    }
    for key, name in LAUNCH_EVENT_FIELDS.items():
        if data.get(key) is not None:
            row[name] = data[key]
    _record(bot, row)
    bot._count_watch("launch_sampled")
    return True


def start_post_exit(
    bot: TradingBot,
    mint: str,
    position: dict[str, Any],
    *,
    reason: str,
    now: float | None = None,
) -> bool:
    """Keep polling a coin after its position fully closed (rc.5); never raises."""
    return _guarded(
        bot,
        "Post-exit observation",
        lambda: _start_post_exit(bot, mint, position, reason=reason, now=now),
    )


def _start_post_exit(
    bot: TradingBot,
    mint: str,
    position: dict[str, Any],
    *,
    reason: str,
    now: float | None,
) -> bool:
    if bot.replay_recorder is None:
        return False
    book = post_exit_list(bot)
    if book is None:
        return False
    now = time.time() if now is None else float(now)
    entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
    exit_mc = float(position.get("current_market_cap", 0.0) or entry_mc)
    entry_time = float(position.get("entry_time", 0.0) or 0.0)
    tags = {
        "exit_reason": str(reason)[:EXIT_REASON_CHARS],
        "entry_market_cap_sol": round(entry_mc, 6),
        "exit_market_cap_sol": round(exit_mc, 6),
    }
    if book.add(mint, now=now, tags=tags) is None:
        return False
    _record(
        bot,
        {
            "timestamp": now,
            "mint": mint,
            "event": OBSERVATION_START_EVENT,
            "source": POST_EXIT_SOURCE,
            **tags,
            "strategy": position.get("strategy"),
            "held_seconds": (
                round(max(0.0, now - entry_time), 1) if entry_time > 0 else None
            ),
        },
    )
    bot._count_watch("post_exit_observed")
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
    now = time.time()
    books = active_lists(bot)
    discovery = discovery_list(bot) if bot._entry_mode() == "confirmed" else None
    if discovery is not None:
        await scan_discovery(bot, discovery, now)
    # A mint in several lists is read once and recorded once per list.
    due: dict[str, list[CurveObservationList]] = {}
    for book in books:
        for mint in book.expired(now):
            end_observation(bot, book, mint, "ttl", now)
        for mint in book.due(now):
            due.setdefault(mint, []).append(book)
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
        for book in due.get(mint, ()):
            _record_polled(bot, book, mint, state, now, skip_mayhem)
    for mint, reason in rejected.items():
        for rejected_book in due.get(mint, ()):
            entry = rejected_book.get(mint)
            if (
                reason == "missing"
                and entry is not None
                and now - entry.added_at < MISSING_ACCOUNT_GRACE_SECONDS
            ):
                continue
            end_observation(bot, rejected_book, mint, reason, now)


def _record_polled(
    bot: TradingBot,
    book: CurveObservationList,
    mint: str,
    state: dict[str, Any],
    now: float,
    skip_mayhem: bool,
) -> None:
    """One list's row for one polled curve, or the end of its observation."""
    from pumpfun_trading.bot.handlers.watch import record_curve_poll

    if state.get("complete"):
        end_observation(bot, book, mint, "complete", now)
        return
    if skip_mayhem and state.get("is_mayhem_mode"):
        end_observation(bot, book, mint, "mayhem", now)
        return
    v_sol = int(state.get("virtual_sol_reserves", 0) or 0) / 1e9
    v_tok = int(state.get("virtual_token_reserves", 0) or 0) / 1e6
    real_sol = int(state.get("real_sol_reserves", 0) or 0) / 1e9
    market_cap = v_sol * (1_000_000_000.0 / v_tok) if v_tok > 0 else 0.0
    entry = book.get(mint)
    extra: dict[str, Any] = {}
    if entry is not None:
        if entry.reasons:
            extra["reject_reasons"] = list(entry.reasons)
        extra.update(entry.tags)
    record_curve_poll(
        bot,
        mint,
        market_cap,
        ts=now,
        source=book.source,
        real_sol=real_sol,
        virtual_sol=v_sol,
        extra=extra or None,
    )
    cause = book.update(mint, real_sol=real_sol, now=now)
    if cause is not None:
        end_observation(bot, book, mint, cause, now)


async def run_observation_loop(bot: TradingBot) -> None:
    """Polls the observation lists in their own task until the bot stops."""
    interval = observation_interval(bot)
    while not bot._stop_requested:
        try:
            await asyncio.sleep(interval)
            await poll_observations(bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            bot._log(f"Observation poll exception: {exc}", level=logging.DEBUG)


__all__ = [
    "active_lists",
    "discovery_list",
    "end_observation",
    "launch_sample_list",
    "maybe_sample_launch",
    "maybe_sample_rejected",
    "observation_interval",
    "observation_status",
    "observations_enabled",
    "poll_observations",
    "post_exit_list",
    "reject_sample_list",
    "run_observation_loop",
    "scan_discovery",
    "start_post_exit",
]
