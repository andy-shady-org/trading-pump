"""Split-half config sweep: tune on one half of a capture, check on the other.

Each grid point is a full live-fidelity replay of the capture with some config
keys overridden (e.g. the stop-loss redesign keys). Positions are booked to
half A or B by their entry time, so state carries across the split as it did
live. A grid point only counts as better than the base config when its net is
higher in **both** halves (AGENTS.md, "Beat A Random Cut": what helps only on
the half it was picked on is noise).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import fields, replace
from typing import Any, Iterable, Mapping, Sequence

from rich.console import Console
from rich.table import Table

from trading_pump.bot.selection import (
    SEGMENT_ALL,
    SEGMENT_FIRST,
    SEGMENT_SECOND,
    resolve_split,
    segments,
)
from trading_pump.engines.costs import ReplayCostModel
from trading_pump.engines.replay import PaperTradingEngine
from trading_pump.strategies.base import TradingBotConfig

BASE_LABEL = "base"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parse_value(raw: str) -> Any:
    text = raw.strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_sweep_spec(text: str) -> tuple[str, list[Any]]:
    """``key=v1,v2,...`` → ``(key, [v1, v2, ...])``; the key must be a config field."""
    key, sep, values = str(text).partition("=")
    key = key.strip()
    names = {f.name for f in fields(TradingBotConfig)}
    if not sep or not key or not values.strip():
        raise ValueError(
            f"Bad sweep {text!r}: use KEY=V1,V2,... e.g. stop_loss=0.8,0.85"
        )
    if key not in names:
        raise ValueError(f"Bad sweep {text!r}: {key!r} is not a config key")
    return key, [_parse_value(v) for v in values.split(",") if v.strip()]


def sweep_grid(specs: Sequence[tuple[str, Sequence[Any]]]) -> list[dict[str, Any]]:
    """Every combination of the swept values (the cartesian product)."""
    if not specs:
        return []
    keys = [key for key, _ in specs]
    return [
        dict(zip(keys, combo))
        for combo in itertools.product(*(list(values) for _, values in specs))
    ]


def grid_label(overrides: Mapping[str, Any]) -> str:
    if not overrides:
        return BASE_LABEL
    return " ".join(f"{k}={v}" for k, v in overrides.items())


def apply_overrides(
    config: TradingBotConfig, overrides: Mapping[str, Any]
) -> TradingBotConfig:
    """The config with ``overrides`` applied, coerced to each field's type."""
    current = {f.name: getattr(config, f.name) for f in fields(TradingBotConfig)}
    coerced: dict[str, Any] = {}
    for key, value in overrides.items():
        old = current[key]
        if isinstance(old, bool):
            coerced[key] = bool(value)
        elif isinstance(old, int) and not isinstance(value, bool):
            coerced[key] = int(value)
        elif isinstance(old, float):
            coerced[key] = float(value)
        else:
            coerced[key] = value
    updated = replace(config, **coerced)
    if not 0 < updated.stop_loss < updated.take_profit:
        raise ValueError(
            f"{grid_label(overrides)}: stop_loss must be below take_profit"
        )
    floor = float(updated.stop_loss_hard_floor or 0.0)
    if floor and floor >= updated.stop_loss:
        raise ValueError(f"{grid_label(overrides)}: stop_loss_hard_floor >= stop_loss")
    return updated


def replay_positions(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per replayed position: ``mint``, ``entry_ts``, ``net`` (all its
    sells, net of every cost), ``exit_reason`` (first exit), ``closed`` and
    ``exit_ts`` (the closing sell, ``None`` while open)."""
    open_: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for trade in summary.get("trades", []):
        mint = str(trade.get("mint"))
        if trade.get("action") == "buy":
            position = {
                "mint": mint,
                "entry_ts": _float(trade.get("timestamp")),
                "strategy": trade.get("strategy"),
                "entry_metrics": dict(trade.get("entry_metrics") or {}),
                "net": 0.0,
                "exit_reason": None,
                "closed": False,
                "exit_ts": None,
            }
            open_[mint] = position
            rows.append(position)
        elif trade.get("action") == "sell" and mint in open_:
            position = open_[mint]
            value = trade.get("net_pnl_sol", trade.get("pnl"))
            position["net"] += _float(value)
            position["exit_reason"] = position["exit_reason"] or trade.get("reason")
            if not trade.get("partial"):
                position["closed"] = True
                position["exit_ts"] = _float(trade.get("timestamp"))
                open_.pop(mint)
    return rows


def _segment_row(positions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    exits: dict[str, int] = {}
    for position in positions:
        reason = str(position.get("exit_reason") or "open_at_end")
        exits[reason] = exits.get(reason, 0) + 1
    net = sum(_float(p.get("net")) for p in positions)
    return {
        "positions": len(positions),
        "net_sol": net,
        "win_rate": (
            sum(1 for p in positions if _float(p.get("net")) > 0) / len(positions)
            if positions
            else 0.0
        ),
        "open_at_end": sum(1 for p in positions if not p.get("closed")),
        "exit_reasons": dict(sorted(exits.items(), key=lambda kv: -kv[1])),
    }


def replay_config(
    records: Sequence[Mapping[str, Any]],
    config: TradingBotConfig,
    *,
    cost_model: ReplayCostModel | None,
    initial_cash: float = 100.0,
) -> dict[str, Any]:
    """One live-fidelity replay of ``records`` with ``config``."""
    engine = PaperTradingEngine(
        initial_cash=initial_cash,
        take_profit=config.take_profit,
        stop_loss=config.stop_loss,
        max_positions=config.max_active_positions,
        strategy_config=config,
        live_fidelity=True,
        cost_model=cost_model,
    )
    return engine.run([dict(r) for r in records])


def run_split_sweep(
    records: Iterable[Mapping[str, Any]],
    config: TradingBotConfig,
    specs: Sequence[tuple[str, Sequence[Any]]],
    *,
    cost_model: ReplayCostModel | None = None,
    split_at: str | float | None = "mid",
    initial_cash: float = 100.0,
) -> dict[str, Any]:
    """Replay the base config and every grid point; net per half against the base."""
    rows = [dict(r) for r in records]
    stamps = [_float(r.get("timestamp")) for r in rows if r.get("timestamp")]
    split = resolve_split(split_at, min(stamps, default=0.0), max(stamps, default=0.0))
    points: list[dict[str, Any]] = [{}] + [g for g in sweep_grid(specs) if g]
    results: list[dict[str, Any]] = []
    base_segments: dict[str, dict[str, Any]] | None = None
    for overrides in points:
        variant = apply_overrides(config, overrides)
        summary = replay_config(
            rows, variant, cost_model=cost_model, initial_cash=initial_cash
        )
        positions = replay_positions(summary)
        by_segment = {
            name: _segment_row(items)
            for name, items in segments(positions, split).items()
        }
        if base_segments is None:
            base_segments = by_segment
        for name, row in by_segment.items():
            row["delta_sol"] = row["net_sol"] - base_segments[name]["net_sol"]
        halves = [s for s in (SEGMENT_FIRST, SEGMENT_SECOND) if s in by_segment]
        checked = halves or [SEGMENT_ALL]
        results.append(
            {
                "label": grid_label(overrides),
                "overrides": dict(overrides),
                "segments": by_segment,
                "beats_base": bool(overrides)
                and all(by_segment[s]["delta_sol"] > 0 for s in checked),
            }
        )
    return {"split_at": split, "results": results}


def render_sweep(report: Mapping[str, Any], console: Console) -> None:
    split = report.get("split_at")
    halves = split is not None
    table = Table(
        title="Config sweep (net SOL; Δ against the base config)",
        header_style="bold cyan",
    )
    table.add_column("Grid point")
    table.add_column("Positions", justify="right")
    table.add_column("Net", justify="right")
    if halves:
        table.add_column("A net (Δ)", justify="right")
        table.add_column("B net (Δ)", justify="right")
    table.add_column("Top exits")
    table.add_column("Both halves")
    for result in report.get("results", []):
        seg = result["segments"]
        row = [
            result["label"],
            str(seg[SEGMENT_ALL]["positions"]),
            f"{seg[SEGMENT_ALL]['net_sol']:+.4f}",
        ]
        if halves:
            for name in (SEGMENT_FIRST, SEGMENT_SECOND):
                part = seg[name]
                row.append(
                    f"{part['net_sol']:+.4f} ({part['delta_sol']:+.4f}) /{part['positions']}"
                )
        exits = seg[SEGMENT_ALL]["exit_reasons"]
        row.append(", ".join(f"{k} {v}" for k, v in list(exits.items())[:3]))
        row.append(
            "-"
            if not result["overrides"]
            else ("yes" if result["beats_base"] else "no")
        )
        table.add_row(*row)
    console.print(table)


__all__ = [
    "apply_overrides",
    "grid_label",
    "parse_sweep_spec",
    "render_sweep",
    "replay_config",
    "replay_positions",
    "run_split_sweep",
    "sweep_grid",
]
