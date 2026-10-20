"""Shadow-variant read-out of a paper capture (FEAT-58).

A paper capture with ``shadow_variants`` holds one ``event: "shadow_entry"``
row per variant and mint: the signal, the curve the paper fill would have read
after ``paper_entry_delay_seconds`` and whether the variant's drift guard would
have refused it. This module answers the capture's question per variant:

* how often it fired, what the fill drift was and what it refused;
* a modelled net PnL: each fill that was not refused is mirrored into the
  live-fidelity replay at its recorded fill price (with the paper penalty), and
  the live exit stack and cost model run on the capture's market data for that
  mint. Positions still open when the data ends are marked to market;
* the variant's net against a random cut of the baseline variant of the same
  size, per half when the capture is split (AGENTS.md, "Beat A Random Cut").

Every variant is judged on its own: the sizing caps are lifted, so a variant
never loses a fill to another variant's open positions (the live shadow book
also evaluates with empty capacity). Exits only see the data the capture holds
for the mint (trades while it was subscribed, watch and position curve polls).
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from typing import Any, Iterable, Mapping, Sequence

from rich.console import Console
from rich.table import Table

from pumpfun_trading.bot.selection import (
    SEGMENT_ALL,
    SEGMENT_FIRST,
    SEGMENT_SECOND,
    beats_random_cut,
    cut_stats,
    resolve_split,
    segments,
)
from pumpfun_trading.engines.costs import ReplayCostModel
from pumpfun_trading.engines.replay import NON_MARKET_EVENTS, PaperTradingEngine
from pumpfun_trading.strategies.base import TradingBotConfig

DEFAULT_BASELINE_VARIANT = "baseline"
DRIFT_BUCKETS = (0.05, 0.08, 0.10)
# Sizing caps lifted for the read-out; one buy per variant and mint.
_UNCAPPED = 1_000_000


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def shadow_entries(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The ``shadow_entry`` rows of a capture, in time order."""
    rows = [
        dict(r)
        for r in records
        if r.get("event") == "shadow_entry" and r.get("variant") and r.get("mint")
    ]
    rows.sort(key=lambda r: _float(r.get("timestamp")))
    return rows


def _is_filled(row: Mapping[str, Any]) -> bool:
    return not row.get("refused") and _float(row.get("fill_market_cap_sol")) > 0


def _market_rows(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Market data only: no analysis rows and none of the bot's own fills."""
    return [
        dict(r)
        for r in records
        if r.get("event") not in NON_MARKET_EVENTS
        and not PaperTradingEngine._is_live_fill(dict(r), "buy")
        and not PaperTradingEngine._is_live_fill(dict(r), "sell")
    ]


def _readout_config(config: TradingBotConfig) -> TradingBotConfig:
    """The capture's exits and costs with the sizing caps lifted."""
    buy = float(config.buy_amount_sol)
    return replace(
        config,
        max_active_positions=_UNCAPPED,
        max_total_exposure_sol=buy * _UNCAPPED,
        max_position_size_sol=max(buy, float(config.max_position_size_sol)),
        max_token_concentration_pct=1.0,
        reserve_balance_sol=0.0,
        max_buy_attempts_per_mint=0,
    )


def _fill_row(
    row: Mapping[str, Any], *, penalty_bps: int, creator: str | None
) -> dict[str, Any]:
    """A mirrored buy at the shadow fill (the paper penalty is applied by replay)."""
    market_cap = _float(row.get("fill_market_cap_sol"))
    return {
        "timestamp": _float(row.get("timestamp")),
        "mint": row["mint"],
        "price": market_cap / 1_000_000_000.0,
        "market_cap_sol": market_cap,
        "signal": "buy",
        "reason": f"shadow:{row['variant']}",
        "strategy": "momentum",
        "creator": creator,
        "entry_penalty_bps": penalty_bps,
        "entry_metrics": dict(row.get("entry_metrics") or {}),
    }


def simulate_fills(
    fills: Sequence[Mapping[str, Any]],
    market_rows: Sequence[Mapping[str, Any]],
    config: TradingBotConfig,
    *,
    cost_model: ReplayCostModel | None = None,
    creators: Mapping[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """One modelled position per fill: ``mint``, ``entry_ts``, ``net``, ``closed``,
    ``exit_reason``, ``fill_drift_pct``."""
    if not fills:
        return []
    creators = creators or {}
    sim_config = _readout_config(config)
    penalty = int(getattr(config, "paper_entry_slippage_bps", 0) or 0)
    mints = {str(f["mint"]) for f in fills}
    tagged: list[tuple[float, int, dict[str, Any]]] = [
        (_float(r.get("timestamp")), 0, dict(r))
        for r in market_rows
        if str(r.get("mint")) in mints
    ]
    tagged += [
        (
            _float(f.get("timestamp")),
            1,
            _fill_row(f, penalty_bps=penalty, creator=creators.get(str(f["mint"]))),
        )
        for f in fills
    ]
    tagged.sort(key=lambda item: (item[0], item[1]))
    rows = [item[2] for item in tagged]
    engine = PaperTradingEngine(
        initial_cash=float(config.buy_amount_sol) * (len(fills) + 1) * 2.0 + 1.0,
        strategy_config=sim_config,
        live_fidelity=True,
        cost_model=cost_model,
        entry_mode="live_fills",
    )
    summary = engine.run(rows)
    last_price: dict[str, float] = {}
    for row in rows:
        price = engine._snapshot_price(row)
        if price > 0:
            last_price[str(row.get("mint"))] = price
    by_mint: dict[str, dict[str, Any]] = {}
    for trade in summary["trades"]:
        mint = str(trade.get("mint"))
        if trade.get("action") == "buy":
            by_mint[mint] = {
                "mint": mint,
                "entry_ts": _float(trade.get("timestamp")),
                "net": 0.0,
                "closed": False,
                "exit_reason": None,
            }
        elif trade.get("action") == "sell" and mint in by_mint:
            position = by_mint[mint]
            position["net"] += _float(trade.get("pnl"))
            position["exit_reason"] = position["exit_reason"] or trade.get("reason")
            if not trade.get("partial"):
                position["closed"] = True
    for mint, held in summary["positions"].items():
        if mint not in by_mint:
            continue
        position = by_mint[mint]
        sell_cost = (
            cost_model.sell_costs(full_exit=True).total_cost_sol if cost_model else 0.0
        )
        value = engine._sell_value(
            _float(held.get("quantity")),
            last_price.get(mint, _float(held.get("entry_price"))),
        )
        position["net"] += (
            value
            - _float(held.get("cost_basis"))
            - _float(held.get("costs_sol"))
            - sell_cost
        )
        position["exit_reason"] = "open_at_end"
    drift = {str(f["mint"]): f.get("fill_drift_pct") for f in fills}
    for mint, position in by_mint.items():
        position["fill_drift_pct"] = drift.get(mint)
    return sorted(by_mint.values(), key=lambda p: p["entry_ts"])


def _percentile(values: Sequence[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return ordered[index]


def _segment_stats(
    rows: Sequence[Mapping[str, Any]], positions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    refused: dict[str, int] = {}
    for row in rows:
        if row.get("refused"):
            reason = str(row["refused"]).split(":")[0]
            refused[reason] = refused.get(reason, 0) + 1
    drifts = [
        _float(row.get("fill_drift_pct"))
        for row in rows
        if isinstance(row.get("fill_drift_pct"), (int, float))
    ]
    closed = [p for p in positions if p.get("closed")]
    exits: dict[str, int] = {}
    for position in positions:
        reason = str(position.get("exit_reason") or "none")
        exits[reason] = exits.get(reason, 0) + 1
    net = sum(_float(p.get("net")) for p in positions)
    return {
        "signals": len(rows),
        "refused": dict(sorted(refused.items())),
        "fills": sum(1 for row in rows if _is_filled(row)),
        "positions": len(positions),
        "closed": len(closed),
        "open_at_end": len(positions) - len(closed),
        "net_sol": net,
        "closed_net_sol": sum(_float(p.get("net")) for p in closed),
        "win_rate": (
            sum(1 for p in positions if _float(p.get("net")) > 0) / len(positions)
            if positions
            else 0.0
        ),
        "expectancy_sol": net / len(positions) if positions else 0.0,
        "drift_median": statistics.median(drifts) if drifts else None,
        "drift_p90": _percentile(drifts, 0.9),
        "drift_over": {
            f"{bucket:.2f}": (
                sum(1 for d in drifts if d > bucket) / len(drifts) if drifts else 0.0
            )
            for bucket in DRIFT_BUCKETS
        },
        "exit_reasons": dict(sorted(exits.items())),
    }


def build_shadow_report(
    records: Sequence[Mapping[str, Any]],
    config: TradingBotConfig,
    *,
    cost_model: ReplayCostModel | None = None,
    split_at: str | float | None = None,
    baseline: str = DEFAULT_BASELINE_VARIANT,
) -> dict[str, Any]:
    """Per variant: signals, drift, refusals, modelled net and the random cut."""
    entries = shadow_entries(records)
    stamps = [_float(r.get("timestamp")) for r in records if r.get("timestamp")]
    start, end = (min(stamps), max(stamps)) if stamps else (0.0, 0.0)
    split = resolve_split(split_at, start, end)
    market = _market_rows(records)
    creators = {
        mint: verdict.get("creator")
        for mint, verdict in PaperTradingEngine._screening_index(
            [dict(r) for r in records]
        ).items()
    }
    order = [str(v["name"]) for v in (config.shadow_variants or ()) if v.get("name")]
    for row in entries:
        if str(row["variant"]) not in order:
            order.append(str(row["variant"]))
    variants: dict[str, dict[str, Any]] = {}
    for name in order:
        rows = [r for r in entries if str(r["variant"]) == name]
        positions = simulate_fills(
            [r for r in rows if _is_filled(r)],
            market,
            config,
            cost_model=cost_model,
            creators=creators,
        )
        row_parts = segments(rows, split, key="signal_timestamp")
        position_parts = segments(positions, split)
        variants[name] = {
            "segments": {
                segment: _segment_stats(row_parts[segment], position_parts[segment])
                for segment in row_parts
            },
            "positions": positions,
        }
    base = variants.get(baseline)
    for name, variant in variants.items():
        for segment, stats in variant["segments"].items():
            if base is None or name == baseline:
                stats["random_cut"] = None
                continue
            base_stats = base["segments"][segment]
            stats["random_cut"] = cut_stats(
                kept=stats["positions"],
                kept_net=stats["net_sol"],
                total=base_stats["positions"],
                total_net=base_stats["net_sol"],
            )
        cuts = {
            s: st["random_cut"]
            for s, st in variant["segments"].items()
            if st["random_cut"] is not None
        }
        variant["beats_random_cut"] = beats_random_cut(cuts) if cuts else None
    return {
        "shadow_entries": len(entries),
        "baseline": baseline if base is not None else None,
        "capture_start": start,
        "capture_end": end,
        "split_at": split,
        "costs_modelled": cost_model is not None,
        "variants": variants,
    }


def _sol(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.4f}"


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.1%}"


def render_shadow_report(report: dict[str, Any], console: Console) -> None:
    """One table per segment (whole capture, then halves A and B when split)."""
    variants = report["variants"]
    if not variants:
        console.print(
            "[yellow]No shadow_entry rows in this capture: was it recorded with "
            "shadow_variants and --record-replay on paper?[/yellow]"
        )
        return
    first = next(iter(variants.values()))
    titles = {
        SEGMENT_ALL: "Whole capture",
        SEGMENT_FIRST: "Half A (before split)",
        SEGMENT_SECOND: "Half B (after split)",
    }
    for segment in first["segments"]:
        table = Table(
            title=f"Shadow variants: {titles[segment]}", header_style="bold cyan"
        )
        for column in (
            "Variant",
            "Signals",
            "Refused",
            "Positions",
            "Open",
            "Net SOL",
            "Win",
            "Drift med",
            "Drift p90",
            ">8%",
            "Random cut",
            "Edge",
        ):
            table.add_column(column, justify="left" if column == "Variant" else "right")
        for name, variant in variants.items():
            stats = variant["segments"][segment]
            cut = stats.get("random_cut")
            table.add_row(
                name,
                str(stats["signals"]),
                str(sum(stats["refused"].values())),
                str(stats["positions"]),
                str(stats["open_at_end"]),
                _sol(stats["net_sol"]),
                f"{stats['win_rate']:.0%}",
                _pct(stats["drift_median"]),
                _pct(stats["drift_p90"]),
                f"{stats['drift_over']['0.08']:.0%}",
                _sol(cut["random_cut_net_sol"]) if cut else "-",
                _sol(cut["edge_sol"]) if cut else "-",
            )
        console.print(table)
    verdicts = [
        f"{name}: {'beats' if v['beats_random_cut'] else 'does not beat'} a random cut"
        for name, v in variants.items()
        if v.get("beats_random_cut") is not None
    ]
    if report.get("baseline") is None:
        console.print(
            "[yellow]No baseline variant in the capture: random-cut columns are "
            "empty (pass --shadow-baseline NAME).[/yellow]"
        )
    elif verdicts:
        scope = "in both halves" if report.get("split_at") is not None else "overall"
        console.print(f"Against {report['baseline']} ({scope}): " + "; ".join(verdicts))
    console.print(
        "Modelled from recorded fill prices; exits see only the capture's data for "
        "each mint, and positions open at the end are marked to market."
        + ("" if report.get("costs_modelled") else " Costs are not modelled.")
    )


__all__ = [
    "DEFAULT_BASELINE_VARIANT",
    "build_shadow_report",
    "render_shadow_report",
    "shadow_entries",
    "simulate_fills",
]
