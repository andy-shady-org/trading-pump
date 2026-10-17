"""Net PnL accounting for trade records (FEAT-49, Sprint 24B).

Every trade record carries its transaction costs (network fee incl. priority fee,
Jito tip, net token-account rent) next to the gross figures:

* buys:  ``gross_pnl_sol = 0`` and ``net_pnl_sol = -costs_sol``
* sells: ``gross_pnl_sol = proceeds_sol - cost_sol`` and
  ``net_pnl_sol = gross_pnl_sol - costs_sol``

so the sum of ``net_pnl_sol`` over a session is the real realized result, and
``cash_flow_sol`` (the wallet SOL change of each trade) can be reconciled
against the chain.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Iterable

from pumpfun_trading.sdk.costs import TransactionCosts

COST_SOURCE_NONE = "none"


def cost_fields(costs: TransactionCosts | None) -> dict[str, Any]:
    """Audit-record cost fields for a trade's transaction costs."""
    if costs is None:
        return {
            "fee_sol": 0.0,
            "priority_fee_sol": 0.0,
            "tip_sol": 0.0,
            "rent_sol": 0.0,
            "costs_sol": 0.0,
            "cost_source": COST_SOURCE_NONE,
        }
    return {
        "fee_sol": costs.fee_sol,
        "priority_fee_sol": costs.priority_fee_sol,
        "tip_sol": costs.tip_sol,
        "rent_sol": costs.rent_sol,
        "costs_sol": costs.total_cost_sol,
        "cost_source": costs.source,
    }


def is_sell(record: dict[str, Any]) -> bool:
    return "sell" in str(record.get("action") or record.get("side") or "")


def is_buy(record: dict[str, Any]) -> bool:
    return not is_sell(record) and "buy" in str(
        record.get("action") or record.get("side") or ""
    )


def is_round_trip(record: dict[str, Any]) -> bool:
    """An arbitrage bundle: buy and sell in one record (BUG-99)."""
    return "arbitrage" in str(record.get("action") or "").lower()


def closes_position(record: dict[str, Any]) -> bool:
    """A full exit (or an arbitrage round trip), not a partial sell."""
    if is_round_trip(record):
        return True
    action = str(record.get("action") or record.get("side") or "")
    return is_sell(record) and "partial" not in action


def position_key(record: dict[str, Any]) -> str:
    return str(record.get("position_id") or record.get("mint") or "")


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def trade_gross_pnl(record: dict[str, Any]) -> float:
    if "gross_pnl_sol" in record:
        return _float(record.get("gross_pnl_sol"))
    if is_sell(record):
        # Legacy records (before Sprint 24B): proceeds minus cost fraction.
        return _float(record.get("proceeds_sol") or record.get("exit")) - _float(
            record.get("cost_sol") or record.get("entry")
        )
    return 0.0


def trade_net_pnl(record: dict[str, Any]) -> float:
    if "net_pnl_sol" in record:
        return _float(record.get("net_pnl_sol"))
    return trade_gross_pnl(record) - _float(record.get("costs_sol"))


def trade_cash_flow(record: dict[str, Any]) -> float:
    """Wallet SOL change caused by the trade."""
    if "cash_flow_sol" in record:
        return _float(record.get("cash_flow_sol"))
    costs = _float(record.get("costs_sol"))
    if is_sell(record):
        return _float(record.get("proceeds_sol") or record.get("exit")) - costs
    return -(_float(record.get("cost_sol") or record.get("entry")) + costs)


def build_pnl_fields(
    *, action: str, cost_sol: float, proceeds_sol: float, costs: TransactionCosts | None
) -> dict[str, Any]:
    """Cost, gross/net PnL and cash-flow fields for a new trade record."""
    fields = cost_fields(costs)
    total_costs = float(fields["costs_sol"])
    selling = "sell" in action
    # An arbitrage bundle is a closed round trip in one transaction: SOL in,
    # SOL out (BUG-99).
    round_trip = "arbitrage" in action.lower()
    gross = (proceeds_sol - cost_sol) if (selling or round_trip) else 0.0
    if round_trip:
        cash_flow = gross - total_costs
    elif selling:
        cash_flow = proceeds_sol - total_costs
    else:
        cash_flow = -(cost_sol + total_costs)
    fields.update(
        {
            "gross_pnl_sol": gross,
            "net_pnl_sol": gross - total_costs,
            "cash_flow_sol": cash_flow,
        }
    )
    return fields


_FLOAT_FIELDS = (
    "gross_pnl_sol",
    "net_pnl_sol",
    "fees_sol",
    "tips_sol",
    "rent_sol",
    "costs_sol",
    "closed_net_pnl_sol",
)
_INT_FIELDS = (
    "buys",
    "sells",
    "winning_sells",
    "positions_closed",
    "winning_positions",
)


@dataclass
class PnlTotals:
    """Running gross/net PnL and cost totals (session or group).

    Win rate and expectancy are per **position** (its buy plus all its sells):
    a buy books the token-account rent and a full exit refunds it, so scoring
    each sell on its own turns flat exits into wins (BUG-105). The per-sell
    figure stays available as ``sell_win_rate``.
    """

    gross_pnl_sol: float = 0.0
    net_pnl_sol: float = 0.0
    fees_sol: float = 0.0
    tips_sol: float = 0.0
    rent_sol: float = 0.0
    costs_sol: float = 0.0
    buys: int = 0
    sells: int = 0
    winning_sells: int = 0
    positions_closed: int = 0
    winning_positions: int = 0
    closed_net_pnl_sol: float = 0.0
    # Net PnL booked so far by each position that is still open.
    open_position_net: dict[str, float] = field(default_factory=dict)

    def add(self, record: dict[str, Any], *, track_positions: bool = True) -> None:
        net = trade_net_pnl(record)
        self.gross_pnl_sol += trade_gross_pnl(record)
        self.net_pnl_sol += net
        self.fees_sol += _float(record.get("fee_sol"))
        self.tips_sol += _float(record.get("tip_sol"))
        self.rent_sol += _float(record.get("rent_sol"))
        self.costs_sol += _float(record.get("costs_sol"))
        if is_sell(record):
            self.sells += 1
            if net > 0:
                self.winning_sells += 1
        elif is_buy(record):
            self.buys += 1
        if track_positions:
            self._track_position(record, net)

    def _track_position(self, record: dict[str, Any], net: float) -> None:
        if not (is_buy(record) or is_sell(record) or is_round_trip(record)):
            return
        key = position_key(record)
        booked = self.open_position_net.pop(key, 0.0) + net
        if closes_position(record):
            self.add_position(booked)
        else:
            self.open_position_net[key] = booked

    def add_position(self, net_pnl_sol: float) -> None:
        """Count one closed position with its total net PnL."""
        self.positions_closed += 1
        self.closed_net_pnl_sol += net_pnl_sol
        if net_pnl_sol > 0:
            self.winning_positions += 1

    @property
    def win_rate(self) -> float:
        """Share of closed positions with positive net PnL (BUG-105)."""
        if not self.positions_closed:
            return 0.0
        return self.winning_positions / self.positions_closed

    @property
    def sell_win_rate(self) -> float:
        """Share of sells with positive net PnL (detail only; see BUG-105)."""
        return self.winning_sells / self.sells if self.sells else 0.0

    @property
    def expectancy_sol(self) -> float:
        """Average net PnL per closed position, entry and exit costs included."""
        if not self.positions_closed:
            return 0.0
        return self.closed_net_pnl_sol / self.positions_closed

    @property
    def cost_share_of_gross(self) -> float | None:
        """Costs as a share of gross profit; ``None`` when gross is not positive."""
        if self.gross_pnl_sol <= 0:
            return None
        return self.costs_sol / self.gross_pnl_sol

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            f.name: getattr(self, f.name) for f in dataclass_fields(self)
        }
        data["open_position_net"] = dict(self.open_position_net)
        data.update(
            {
                "win_rate": self.win_rate,
                "sell_win_rate": self.sell_win_rate,
                "expectancy_sol": self.expectancy_sol,
                "cost_share_of_gross": self.cost_share_of_gross,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PnlTotals":
        data = data or {}
        totals = cls()
        for name in _FLOAT_FIELDS:
            setattr(totals, name, _float(data.get(name)))
        for name in _INT_FIELDS:
            try:
                setattr(totals, name, int(data.get(name) or 0))
            except (TypeError, ValueError):
                setattr(totals, name, 0)
        open_net = data.get("open_position_net")
        if isinstance(open_net, dict):
            totals.open_position_net = {
                str(key): _float(value) for key, value in open_net.items()
            }
        return totals


def trade_payloads(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trade payloads from raw audit records (``{"type": "trade", "payload": ...}``)."""
    trades: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_type = record.get("type") or record.get("record_type")
        payload = record.get("payload")
        if record_type == "trade" and isinstance(payload, dict):
            trades.append(payload)
        elif record_type is None and ("action" in record or "side" in record):
            trades.append(record)
    return trades


def _group_key(record: dict[str, Any], group_by: str) -> str:
    if group_by == "day":
        try:
            ts = float(record.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%d")
    if group_by == "reason":
        reason = str(record.get("reason") or "").strip()
        return reason.split(" ")[0].split("(")[0] or "unknown"
    if group_by == "strategy":
        return str(record.get("strategy") or record.get("strategy_preset") or "default")
    if group_by == "mint":
        return str(record.get("mint") or "unknown")
    raise ValueError(f"Unsupported group_by: {group_by}")


PNL_GROUPS = ("day", "reason", "strategy", "mint")


def summarize_pnl(
    trades: Iterable[dict[str, Any]], *, group_by: str | None = None
) -> dict[str, Any]:
    """Net PnL summary: totals plus optional per-day / per-reason groups.

    ``reason`` groups attribute buys to their entry reason and sells to their
    exit reason, so per-exit-reason rows show what each exit rule earns.

    Win rate and expectancy are per closed position (BUG-105). In groups, a
    position counts once, in the group of its first exit: the exit rule that
    started it for ``reason``, the closing day for ``day``.
    """
    totals = PnlTotals()
    groups: dict[str, PnlTotals] = {}
    sources: dict[str, int] = {}
    # Per open position: net booked so far and the group of its first exit.
    open_net: dict[str, float] = {}
    open_group: dict[str, str] = {}
    count = 0
    for trade in trades:
        count += 1
        totals.add(trade)
        source = str(trade.get("cost_source") or COST_SOURCE_NONE)
        sources[source] = sources.get(source, 0) + 1
        if not group_by:
            continue
        group = _group_key(trade, group_by)
        groups.setdefault(group, PnlTotals()).add(trade, track_positions=False)
        if not (is_buy(trade) or is_sell(trade) or is_round_trip(trade)):
            continue
        key = position_key(trade)
        net = open_net.pop(key, 0.0) + trade_net_pnl(trade)
        if group_by == "reason":
            if not is_buy(trade):
                open_group.setdefault(key, group)
        elif group_by != "day":
            open_group.setdefault(key, group)
        if closes_position(trade):
            target = group if group_by == "day" else open_group.get(key, group)
            open_group.pop(key, None)
            groups.setdefault(target, PnlTotals()).add_position(net)
        else:
            open_net[key] = net
    summary: dict[str, Any] = {
        "trades": count,
        "totals": totals.to_dict(),
        "cost_sources": dict(sorted(sources.items())),
    }
    if group_by:
        summary["group_by"] = group_by
        summary["groups"] = {key: groups[key].to_dict() for key in sorted(groups)}
    return summary


def open_cost_basis(trades: Iterable[dict[str, Any]]) -> dict[str, float]:
    """Cost basis still held per position, from buys minus sold cost fractions."""
    basis: dict[str, float] = {}
    for trade in trades:
        position = str(trade.get("position_id") or trade.get("mint") or "")
        if not position:
            continue
        cost = _float(trade.get("cost_sol") or trade.get("entry"))
        if is_buy(trade):
            basis[position] = basis.get(position, 0.0) + cost
        elif is_sell(trade):
            remaining = basis.get(position, 0.0) - cost
            if str(trade.get("action")) == "sell" or remaining <= 1e-12:
                basis.pop(position, None)
            else:
                basis[position] = remaining
    return basis


__all__ = [
    "COST_SOURCE_NONE",
    "PNL_GROUPS",
    "PnlTotals",
    "build_pnl_fields",
    "closes_position",
    "cost_fields",
    "is_buy",
    "is_round_trip",
    "is_sell",
    "open_cost_basis",
    "position_key",
    "summarize_pnl",
    "trade_cash_flow",
    "trade_gross_pnl",
    "trade_net_pnl",
    "trade_payloads",
]
