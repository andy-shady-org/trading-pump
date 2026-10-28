"""Sell sizing, proceeds and record helpers for the runtime sell path.

`TradingBot._sell_token_locked` (`bot/run.py`) orchestrates a sell: locks,
lifecycle transitions, balance reads and order dispatch. The arithmetic it
needs — how many tokens to sell, whether the sell is partial, what the sell
returned and what to record — lives here so it can be tested on its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

# Paper sells of a position with no recorded token amount assume this many.
DRY_RUN_PLACEHOLDER_TOKENS = 100_000_000


@dataclass(frozen=True)
class SellSize:
    """Tokens to sell now and whether the position stays open afterwards."""

    tokens_to_sell: int
    is_partial: bool


def position_token_amounts(
    position: Mapping[str, Any], *, dry_run: bool
) -> tuple[int, int]:
    """Initial and remaining token amounts recorded on a position."""
    initial_tokens = int(
        position.get("initial_token_amount")
        or position.get("token_amount")
        or (DRY_RUN_PLACEHOLDER_TOKENS if dry_run else 0)
    )
    remaining_tokens = int(
        position.get("remaining_token_amount")
        or position.get("token_amount")
        or initial_tokens
    )
    return initial_tokens, remaining_tokens


def plan_sell_size(
    *,
    initial_tokens: int,
    remaining_tokens: int,
    sell_amount_tokens: int | None,
    sell_fraction: float,
    min_sell_balance: float,
) -> SellSize:
    """Size a sell; a remainder at or below `min_sell_balance` is sold too."""
    if sell_amount_tokens is not None and sell_amount_tokens > 0:
        tokens_to_sell = min(sell_amount_tokens, remaining_tokens)
    elif sell_fraction < 1.0:
        tokens_to_sell = int((initial_tokens or remaining_tokens) * sell_fraction)
        tokens_to_sell = max(1, min(tokens_to_sell, remaining_tokens))
    else:
        tokens_to_sell = remaining_tokens

    remaining_after = remaining_tokens - tokens_to_sell
    is_partial = (tokens_to_sell < remaining_tokens) and (
        remaining_after > min_sell_balance
    )
    if not is_partial:
        tokens_to_sell = remaining_tokens
    return SellSize(tokens_to_sell=tokens_to_sell, is_partial=is_partial)


def sold_fraction(
    tokens_to_sell: int, initial_tokens: int, remaining_tokens: int
) -> float:
    """Share of the original position this sell closes, clamped to [0, 1]."""
    frac = float(tokens_to_sell) / float(
        initial_tokens or remaining_tokens or tokens_to_sell
    )
    return max(0.0, min(1.0, frac))


def position_entry_sol(position: Mapping[str, Any], buy_amount_sol: float) -> float:
    """SOL paid for the position; `buy_price` is a unit price, never this (BUG-45)."""
    return float(
        position.get("cost_sol") or position.get("entry_sol") or buy_amount_sol or 0.0
    )


def estimate_sell_proceeds(
    exec_res: Any,
    *,
    dry_run: bool,
    cost_sol: float,
    fraction: float,
    entry_market_cap: float,
    current_market_cap: float,
    paper_fee_factor: float,
) -> float:
    """SOL received for a sell.

    Paper sells price the sold share of the cost basis by the market-cap move
    and apply the Pump.fun fee on both legs (FEAT-49). Live sells use the
    executor's swap amount and fall back to the same market-cap estimate.
    """
    if dry_run:
        if entry_market_cap > 0 and current_market_cap > 0 and cost_sol > 0:
            return (
                (cost_sol * fraction)
                * (current_market_cap / entry_market_cap)
                * paper_fee_factor
            )
        if cost_sol > 0:
            return cost_sol * fraction * paper_fee_factor
        return float(getattr(exec_res, "amount_sol", 0.0) or 0.0)

    proceeds = float(
        getattr(exec_res, "amount_sol", 0.0)
        or getattr(exec_res, "sol_amount", 0.0)
        or (
            float(getattr(exec_res, "min_sol_lamports", 0)) / 1e9
            if getattr(exec_res, "min_sol_lamports", 0) > 0
            else 0.0
        )
        or 0.0
    )
    if proceeds <= 0.0:
        if entry_market_cap > 0 and current_market_cap > 0 and cost_sol > 0:
            proceeds = (cost_sol * fraction) * (current_market_cap / entry_market_cap)
        elif cost_sol > 0:
            proceeds = cost_sol * fraction
    return proceeds


def position_id(position: Mapping[str, Any]) -> Any:
    return position.get("position_id") or position.get("id") or position.get("trade_id")


def mark_stop_crossing(
    position: MutableMapping[str, Any],
    *,
    market_cap: float,
    stop_loss: float,
    source: str,
    ts: float,
) -> bool:
    """Remember the first price from ``source`` at or below the stop level
    (rc.3, ``record_stop_crossings``); True when this call recorded it."""
    entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
    if entry_mc <= 0 or market_cap <= 0 or stop_loss <= 0:
        return False
    ratio = float(market_cap) / entry_mc
    if ratio > stop_loss:
        return False
    crossings = position.get("stop_crossings")
    if not isinstance(crossings, dict):
        crossings = position["stop_crossings"] = {}
    if source in crossings:
        return False
    crossings[source] = {"at": round(float(ts), 3), "ratio": round(ratio, 6)}
    return True


def stop_exit_metrics(
    position: Mapping[str, Any],
    *,
    stop_loss: float,
    sold_at: float,
    proceeds_sol: float,
    cost_sol: float,
) -> dict[str, Any] | None:
    """How far a full exit sold below the first stop crossing of each price
    source, or ``None`` when no source crossed the stop. Measures only."""
    crossings = position.get("stop_crossings")
    if not isinstance(crossings, Mapping) or not crossings:
        return None
    entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
    current_mc = float(position.get("current_market_cap", 0.0) or 0.0)
    metrics: dict[str, Any] = {
        "stop_level": float(stop_loss),
        # The price the exit fired at, and what the sell returned per SOL paid
        # (fees and the paper exit haircut included).
        "trigger_ratio": (
            round(current_mc / entry_mc, 6) if entry_mc > 0 and current_mc > 0 else None
        ),
        "fill_ratio": round(proceeds_sol / cost_sol, 6) if cost_sol > 0 else None,
    }
    for source in sorted(crossings):
        crossing = crossings[source]
        if not isinstance(crossing, Mapping):
            continue
        at = float(crossing.get("at", 0.0) or 0.0)
        metrics[f"{source}_cross_ratio"] = crossing.get("ratio")
        metrics[f"{source}_cross_at"] = at
        metrics[f"{source}_lead_seconds"] = round(max(0.0, sold_at - at), 3)
    return metrics


def sell_replay_snapshot(
    *,
    mint: str,
    name: str,
    position: Mapping[str, Any],
    proceeds_sol: float,
    tokens_sold: int,
    reason: str,
    default_reason: str,
    timestamp: float | None = None,
    exit_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay-capture record of one of the bot's own sells (FEAT-21)."""
    current_mc = float(
        position.get("current_market_cap", 0.0)
        or position.get("entry_market_cap", 0.0)
        or 0.0
    )
    row: dict[str, Any] = {
        "timestamp": time.time() if timestamp is None else timestamp,
        "mint": mint,
        "name": name,
        "price": current_mc / 1_000_000_000.0 if current_mc > 0 else 0.0,
        "market_cap_sol": current_mc,
        "is_buy": False,
        "sol_amount": float(proceeds_sol),
        "token_amount": int(tokens_sold),
        "signal": "sell",
        "reason": reason or default_reason,
    }
    if exit_metrics:
        row["exit_metrics"] = dict(exit_metrics)
    return row
