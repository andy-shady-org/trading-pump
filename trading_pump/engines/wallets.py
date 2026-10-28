"""FEAT-54 phase 1: score wallets on what copying them would have made us.

A wallet's win rate says nothing about what we would earn following it: we
see its buy late, pay our own fees, tip and rent, and fill after our delay.
So each wallet is scored by a **copy simulation** on a capture:

* every first buy of the wallet on a mint (never the mint's creator) is copied
  with ``buy_amount_sol`` at the first recorded price at least
  ``delay_seconds`` later, cut by the paper penalty (``penalty_bps``);
* the copy exits fully at the first recorded price at least ``delay_seconds``
  after the wallet's first sell of that mint; a wallet whose sell the capture
  never saw is marked at the mint's last recorded price (``open_at_end``).
  Captures stop recording a mint once the bot unsubscribes, so those marks are
  stale: wallets are ranked on their **closed** copies only and open marks are
  reported apart;
* both sides pay the Pump.fun fee and the modelled costs (``ReplayCostModel``).

Prices come from the capture's market trades and curve polls. The trade size
is small next to the curve, so price impact is ignored. Captures only hold
trades of the mints the bot subscribed to, so a wallet's score covers those
mints only: discovery on one capture must be checked on another
(:func:`validate_wallets`) before a wallet goes on the reviewed list.
"""

from __future__ import annotations

import bisect
import random
from typing import Any, Iterable, Mapping, Sequence

from rich.console import Console
from rich.table import Table

from trading_pump.bot.selection import cut_stats
from trading_pump.engines.costs import ReplayCostModel
from trading_pump.engines.cuts import CaptureIndex

DEFAULT_COPY_DELAY_SECONDS = 1.5


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _price(record: Mapping[str, Any]) -> float:
    price = _float(record.get("price"))
    if price > 0:
        return price
    return _float(record.get("market_cap_sol")) / 1_000_000_000.0


class PriceBook:
    """Recorded prices per mint (market trades and curve polls), by time."""

    def __init__(self, records: Iterable[Mapping[str, Any]]) -> None:
        series: dict[str, list[tuple[float, float]]] = {}
        for record in records:
            mint = record.get("mint")
            if not mint or "reason" in record:
                continue
            event = record.get("event")
            if event not in (None, "curve_poll"):
                continue
            price = _price(record)
            if price > 0:
                series.setdefault(str(mint), []).append(
                    (_float(record.get("timestamp")), price)
                )
        self._times: dict[str, list[float]] = {}
        self._prices: dict[str, list[float]] = {}
        for mint, rows in series.items():
            rows.sort()
            self._times[mint] = [ts for ts, _ in rows]
            self._prices[mint] = [p for _, p in rows]

    def at_or_after(self, mint: str, ts: float) -> tuple[float, float] | None:
        times = self._times.get(mint)
        if not times:
            return None
        i = bisect.bisect_left(times, ts)
        if i >= len(times):
            return None
        return times[i], self._prices[mint][i]

    def last(self, mint: str) -> tuple[float, float] | None:
        times = self._times.get(mint)
        if not times:
            return None
        return times[-1], self._prices[mint][-1]


def wallet_round_trips(index: CaptureIndex) -> dict[str, list[dict[str, Any]]]:
    """Per wallet: its first buy on each mint and its first sell after it."""
    out: dict[str, list[dict[str, Any]]] = {}
    for mint, trades in index.trades.items():
        creator = index.creator(mint)
        opened: dict[str, dict[str, Any]] = {}
        for trade in trades:
            user = str(trade.get("user") or "")
            if not user or user == creator:
                continue
            ts = _float(trade.get("timestamp"))
            sol = _float(trade.get("sol_amount"))
            if trade.get("is_buy"):
                if user in opened:
                    opened[user]["own_buy_sol"] += sol
                    continue
                trip: dict[str, Any] = {
                    "mint": mint,
                    "buy_ts": ts,
                    "sell_ts": None,
                    "own_buy_sol": sol,
                    "own_sell_sol": 0.0,
                }
                opened[user] = trip
                out.setdefault(user, []).append(trip)
            elif user in opened:
                trip = opened[user]
                trip["own_sell_sol"] += sol
                if trip["sell_ts"] is None:
                    trip["sell_ts"] = ts
    return out


def copy_trip(
    trip: Mapping[str, Any],
    prices: PriceBook,
    *,
    buy_amount_sol: float,
    delay_seconds: float,
    penalty_bps: int,
    cost_model: ReplayCostModel | None,
) -> dict[str, Any] | None:
    """Our net from copying one wallet round trip, or ``None`` if never filled."""
    mint = str(trip["mint"])
    entry = prices.at_or_after(mint, _float(trip["buy_ts"]) + delay_seconds)
    if entry is None:
        return None
    entry_ts, entry_price = entry
    exit_point = None
    reason = "copied_sell"
    if trip.get("sell_ts") is not None:
        exit_point = prices.at_or_after(
            mint, max(entry_ts, _float(trip["sell_ts"]) + delay_seconds)
        )
    if exit_point is None:
        exit_point = prices.last(mint)
        reason = "open_at_end"
    if exit_point is None:  # pragma: no cover - entry exists, so last() does too
        return None
    exit_ts, exit_price = exit_point
    fee = (cost_model.protocol_fee_bps if cost_model else 0) / 10_000.0
    fill = entry_price / max(1e-9, 1.0 - min(5_000, max(0, penalty_bps)) / 10_000.0)
    tokens = buy_amount_sol * (1.0 - fee) / fill
    proceeds = tokens * exit_price * (1.0 - fee)
    fixed = cost_model.round_trip_fixed_costs_sol() if cost_model else 0.0
    return {
        "mint": mint,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "net": proceeds - buy_amount_sol - fixed,
        "exit_reason": reason,
        "hold_seconds": exit_ts - entry_ts,
    }


def score_wallets(
    records: Sequence[Mapping[str, Any]],
    *,
    buy_amount_sol: float,
    delay_seconds: float = DEFAULT_COPY_DELAY_SECONDS,
    penalty_bps: int = 0,
    cost_model: ReplayCostModel | None = None,
    min_copies: int = 1,
) -> dict[str, Any]:
    """Copy-simulation score of every wallet in a capture, best first.

    ``copies`` / ``copy_net_sol`` (per wallet and in total) count closed
    copies only; ``creators`` lists wallets that launched mints in the capture
    (their own coins are never copied).
    """
    index = CaptureIndex.from_records(records)
    prices = PriceBook(records)
    wallets: list[dict[str, Any]] = []
    all_copies = 0
    all_net = 0.0
    for wallet, trips in wallet_round_trips(index).items():
        copies = [
            c
            for c in (
                copy_trip(
                    trip,
                    prices,
                    buy_amount_sol=buy_amount_sol,
                    delay_seconds=delay_seconds,
                    penalty_bps=penalty_bps,
                    cost_model=cost_model,
                )
                for trip in trips
            )
            if c is not None
        ]
        closed_copies = [c for c in copies if c["exit_reason"] != "open_at_end"]
        if not closed_copies:
            continue
        net = sum(c["net"] for c in closed_copies)
        all_copies += len(closed_copies)
        all_net += net
        if len(closed_copies) < min_copies:
            continue
        closed = [t for t in trips if t["sell_ts"] is not None]
        wallets.append(
            {
                "wallet": wallet,
                "mints": len(trips),
                "copies": len(closed_copies),
                "copy_net_sol": net,
                "copy_win_rate": sum(1 for c in closed_copies if c["net"] > 0)
                / len(closed_copies),
                "copy_expectancy_sol": net / len(closed_copies),
                "open_at_end": len(copies) - len(closed_copies),
                "open_mark_sol": sum(
                    c["net"] for c in copies if c["exit_reason"] == "open_at_end"
                ),
                "own_round_trips": len(closed),
                "own_gross_sol": sum(
                    t["own_sell_sol"] - t["own_buy_sol"] for t in closed
                ),
                "median_hold_seconds": sorted(c["hold_seconds"] for c in closed_copies)[
                    len(closed_copies) // 2
                ],
            }
        )
    wallets.sort(key=lambda w: (-w["copy_net_sol"], w["wallet"]))
    return {
        "buy_amount_sol": buy_amount_sol,
        "delay_seconds": delay_seconds,
        "penalty_bps": penalty_bps,
        "copies": all_copies,
        "copy_net_sol": all_net,
        "wallets": wallets,
        "creators": _launch_counts(index),
    }


def _launch_counts(index: CaptureIndex) -> dict[str, int]:
    counts: dict[str, int] = {}
    for creator in index.creators.values():
        counts[creator] = counts.get(creator, 0) + 1
    return counts


def validate_wallets(
    selected: Sequence[str],
    scores: Mapping[str, Any],
    *,
    seed: int = 7,
    draws: int = 200,
) -> dict[str, Any]:
    """The selected wallets' copy net on another capture, against chance.

    ``random_cut_net_sol`` is the same share of all copies on that capture;
    ``random_wallets_mean_sol`` / ``random_wallets_beaten`` compare with
    ``draws`` random sets of as many wallets (seeded, reproducible).
    """
    rows = {w["wallet"]: w for w in scores.get("wallets", [])}
    chosen = [rows[w] for w in selected if w in rows]
    kept = sum(w["copies"] for w in chosen)
    kept_net = sum(w["copy_net_sol"] for w in chosen)
    stats = cut_stats(
        kept=kept,
        kept_net=kept_net,
        total=int(scores.get("copies", 0)),
        total_net=float(scores.get("copy_net_sol", 0.0)),
    )
    pool = list(rows.values())
    means: list[float] = []
    if chosen and len(pool) > len(chosen):
        rng = random.Random(seed)
        for _ in range(draws):
            sample = rng.sample(pool, len(chosen))
            means.append(sum(w["copy_net_sol"] for w in sample))
    return {
        **stats,
        "selected": len(selected),
        "seen": len(chosen),
        "wallets": chosen,
        "random_wallets_mean_sol": sum(means) / len(means) if means else None,
        "random_wallets_beaten": (
            sum(1 for m in means if kept_net > m) / len(means) if means else None
        ),
    }


def render_wallet_scores(
    scores: Mapping[str, Any],
    console: Console,
    *,
    top: int = 20,
    validation: Mapping[str, Any] | None = None,
    focus: Sequence[str] = (),
) -> None:
    console.print(
        f"Copy simulation: {scores['copies']} copies at "
        f"{scores['buy_amount_sol']:g} SOL, {scores['delay_seconds']:g} s delay, "
        f"{scores['penalty_bps']} bps penalty; all closed copies net "
        f"{scores['copy_net_sol']:+.4f} SOL"
    )
    table = Table(title=f"Top {top} wallets by copy net", header_style="bold cyan")
    for column in (
        "Wallet",
        "Copies",
        "Copy net",
        "Win",
        "Per copy",
        "Open (mark)",
        "Own gross",
        "Hold p50",
    ):
        table.add_column(column, justify="left" if column == "Wallet" else "right")
    rows = list(scores["wallets"][:top])
    rows += [w for w in scores["wallets"] if w["wallet"] in focus and w not in rows]
    for w in rows:
        table.add_row(
            w["wallet"],
            str(w["copies"]),
            f"{w['copy_net_sol']:+.4f}",
            f"{w['copy_win_rate']:.0%}",
            f"{w['copy_expectancy_sol']:+.5f}",
            f"{w['open_at_end']} ({w['open_mark_sol']:+.3f})",
            f"{w['own_gross_sol']:+.3f}",
            f"{w['median_hold_seconds']:.0f}s",
        )
    console.print(table)
    missing = [w for w in focus if w not in {r["wallet"] for r in scores["wallets"]}]
    launches = scores.get("creators") or {}
    for wallet in missing:
        launched = launches.get(wallet, 0)
        console.print(
            f"{wallet}: no closed copy on this capture"
            + (f" (launched {launched} screened mints)" if launched else "")
        )
    if validation is not None:
        beaten = validation.get("random_wallets_beaten")
        console.print(
            f"Validation: {validation['seen']}/{validation['selected']} selected "
            f"wallets traded there, {validation['kept']} copies, net "
            f"{validation['kept_net_sol']:+.4f} SOL vs random cut "
            f"{validation['random_cut_net_sol']:+.4f} (edge "
            f"{validation['edge_sol']:+.4f})"
            + (
                f"; beats {beaten:.0%} of random wallet sets"
                if beaten is not None
                else ""
            )
        )


__all__ = [
    "DEFAULT_COPY_DELAY_SECONDS",
    "PriceBook",
    "copy_trip",
    "render_wallet_scores",
    "score_wallets",
    "validate_wallets",
    "wallet_round_trips",
]
