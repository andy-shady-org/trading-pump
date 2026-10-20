"""Selection quality of an entry rule: kept net against a random cut.

Every filter on a losing lane "improves" net PnL because it trades less
(AGENTS.md, "Beat A Random Cut"). A rule only shows an edge when the positions
it keeps did better than the same share of all positions would have, and it
should do so in both halves of a capture (tune on one, check on the other).

Rules read the metrics a buy recorded (``entry_metrics``, then
``market_regime``), never the outcome, so they can be applied before entry.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from pumpfun_trading.bot.pnl import (
    closes_position,
    is_buy,
    is_sell,
    position_key,
    trade_net_pnl,
)

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<=": operator.le,
    ">=": operator.ge,
    "!=": operator.ne,
    "==": operator.eq,
    "<": operator.lt,
    ">": operator.gt,
}
_RULE_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|!=|==|<|>)\s*(\S+)\s*$"
)
SEGMENT_ALL = "all"
SEGMENT_FIRST = "A"
SEGMENT_SECOND = "B"


@dataclass(frozen=True)
class KeepRule:
    """``metric <op> value``: the positions a filter would have kept."""

    metric: str
    op: str
    value: float

    @classmethod
    def parse(cls, text: str) -> KeepRule:
        match = _RULE_PATTERN.match(str(text))
        if match is None:
            raise ValueError(
                f"Bad rule {text!r}: use METRIC<OP>VALUE, e.g. top_buyer_share<0.3 "
                "(operators: < <= > >= == !=)"
            )
        metric, op, raw = match.groups()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"Bad rule {text!r}: {raw!r} is not a number") from exc
        return cls(metric=metric, op=op, value=value)

    @property
    def label(self) -> str:
        return f"{self.metric}{self.op}{self.value:g}"

    def keeps(self, position: Mapping[str, Any]) -> bool | None:
        """True / False, or ``None`` when the position did not record the metric."""
        value = metric_value(position, self.metric)
        if value is None:
            return None
        return _OPERATORS[self.op](value, self.value)


def metric_value(position: Mapping[str, Any], metric: str) -> float | None:
    """A recorded entry metric: ``entry_metrics`` first, then ``market_regime``."""
    for source in ("entry_metrics", "market_regime"):
        data = position.get(source)
        if isinstance(data, Mapping) and metric in data:
            raw = data[metric]
            if isinstance(raw, bool):
                return float(raw)
            if isinstance(raw, (int, float)):
                return float(raw)
            return None
    return None


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def closed_positions(trades: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Closed positions from audit trade payloads, in entry order.

    Each carries ``entry_ts``, ``mint``, ``strategy``, the buy's
    ``entry_metrics`` / ``market_regime``, ``net`` (buy and sells, net of all
    costs) and ``exit_reason`` (the first exit).
    """
    open_: dict[str, dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    for trade in trades:
        if not (is_buy(trade) or is_sell(trade)):
            continue
        key = position_key(trade)
        position = open_.get(key)
        if position is None:
            position = {
                "position_id": key,
                "mint": trade.get("mint"),
                "entry_ts": _float(trade.get("timestamp")),
                "strategy": trade.get("strategy"),
                "net": 0.0,
                "exit_reason": None,
            }
            open_[key] = position
        if is_buy(trade):
            for field_name in ("entry_metrics", "market_regime"):
                if isinstance(trade.get(field_name), dict):
                    position[field_name] = dict(trade[field_name])
            position["strategy"] = trade.get("strategy") or position["strategy"]
        elif position["exit_reason"] is None:
            reason = str(trade.get("reason") or "").strip()
            position["exit_reason"] = reason.split(" ")[0].split("(")[0] or "unknown"
        position["net"] += trade_net_pnl(trade)
        if closes_position(trade):
            closed.append(open_.pop(key))
    closed.sort(key=lambda p: p["entry_ts"])
    return closed


def resolve_split(
    split_at: str | float | None, start: float, end: float
) -> float | None:
    """``None`` (no split), ``"mid"`` (middle of ``start``..``end``) or a timestamp."""
    if split_at is None or split_at == "":
        return None
    if isinstance(split_at, str) and split_at.strip().lower() == "mid":
        return (float(start) + float(end)) / 2.0
    return float(split_at)


def segments(
    items: Sequence[Mapping[str, Any]], split: float | None, *, key: str = "entry_ts"
) -> dict[str, list[Mapping[str, Any]]]:
    """``all``, plus halves ``A`` (before ``split``) and ``B`` when split."""
    out: dict[str, list[Mapping[str, Any]]] = {SEGMENT_ALL: list(items)}
    if split is not None:
        out[SEGMENT_FIRST] = [item for item in items if _float(item.get(key)) < split]
        out[SEGMENT_SECOND] = [item for item in items if _float(item.get(key)) >= split]
    return out


def cut_stats(
    *, kept: int, kept_net: float, total: int, total_net: float
) -> dict[str, Any]:
    """Kept net against the same share of the total (a random cut)."""
    random_cut = total_net * kept / total if total else 0.0
    return {
        "kept": kept,
        "total": total,
        "kept_net_sol": kept_net,
        "total_net_sol": total_net,
        "random_cut_net_sol": random_cut,
        "edge_sol": kept_net - random_cut,
    }


def beats_random_cut(by_segment: Mapping[str, Mapping[str, Any]]) -> bool:
    """Positive edge in every half (or overall when not split) with positions."""
    halves = [s for s in (SEGMENT_FIRST, SEGMENT_SECOND) if s in by_segment]
    checked = [by_segment[s] for s in (halves or [SEGMENT_ALL])]
    checked = [row for row in checked if row["total"] > 0]
    return bool(checked) and all(row["edge_sol"] > 0 for row in checked)


def selection_report(
    positions: Sequence[Mapping[str, Any]],
    rules: Sequence[KeepRule],
    *,
    split_at: str | float | None = None,
) -> dict[str, Any]:
    """Each rule (and all rules together) against a random cut, per half."""
    start = min((_float(p.get("entry_ts")) for p in positions), default=0.0)
    end = max((_float(p.get("entry_ts")) for p in positions), default=0.0)
    split = resolve_split(split_at, start, end)
    parts = segments(positions, split)
    named: list[tuple[str, Callable[[Mapping[str, Any]], bool | None]]] = [
        (rule.label, rule.keeps) for rule in rules
    ]
    if len(rules) > 1:

        def combined(position: Mapping[str, Any]) -> bool | None:
            verdicts = [rule.keeps(position) for rule in rules]
            if any(v is None for v in verdicts):
                return None
            return all(verdicts)

        named.append((" & ".join(rule.label for rule in rules), combined))
    report_rules: list[dict[str, Any]] = []
    for label, keep in named:
        by_segment: dict[str, dict[str, Any]] = {}
        for segment, items in parts.items():
            verdicts = [(item, keep(item)) for item in items]
            kept = [item for item, verdict in verdicts if verdict]
            row = cut_stats(
                kept=len(kept),
                kept_net=sum(_float(item.get("net")) for item in kept),
                total=len(items),
                total_net=sum(_float(item.get("net")) for item in items),
            )
            row["missing"] = sum(1 for _, verdict in verdicts if verdict is None)
            by_segment[segment] = row
        report_rules.append(
            {
                "rule": label,
                "segments": by_segment,
                "beats_random_cut": beats_random_cut(by_segment),
            }
        )
    return {
        "positions": len(positions),
        "split_at": split,
        "segments": {
            name: {
                "positions": len(items),
                "net_sol": sum(_float(item.get("net")) for item in items),
            }
            for name, items in parts.items()
        },
        "rules": report_rules,
    }


__all__ = [
    "KeepRule",
    "beats_random_cut",
    "closed_positions",
    "cut_stats",
    "metric_value",
    "resolve_split",
    "segments",
    "selection_report",
]
