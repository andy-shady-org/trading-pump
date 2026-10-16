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
from dataclasses import asdict, dataclass
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


@dataclass
class PnlTotals:
    """Running gross/net PnL and cost totals (session or group)."""

    gross_pnl_sol: float = 0.0
    net_pnl_sol: float = 0.0
    fees_sol: float = 0.0
    tips_sol: float = 0.0
    rent_sol: float = 0.0
    costs_sol: float = 0.0
    buys: int = 0
    sells: int = 0
    winning_sells: int = 0

    def add(self, record: dict[str, Any]) -> None:
        self.gross_pnl_sol += trade_gross_pnl(record)
        self.net_pnl_sol += trade_net_pnl(record)
        self.fees_sol += _float(record.get("fee_sol"))
        self.tips_sol += _float(record.get("tip_sol"))
        self.rent_sol += _float(record.get("rent_sol"))
        self.costs_sol += _float(record.get("costs_sol"))
        if is_sell(record):
            self.sells += 1
            if trade_net_pnl(record) > 0:
                self.winning_sells += 1
        elif is_buy(record):
            self.buys += 1

    @property
    def win_rate(self) -> float:
        return self.winning_sells / self.sells if self.sells else 0.0

    @property
    def expectancy_sol(self) -> float:
        """Average net PnL per sell (entry costs included)."""
        return self.net_pnl_sol / self.sells if self.sells else 0.0

    @property
    def cost_share_of_gross(self) -> float | None:
        """Costs as a share of gross profit; ``None`` when gross is not positive."""
        if self.gross_pnl_sol <= 0:
            return None
        return self.costs_sol / self.gross_pnl_sol

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "win_rate": self.win_rate,
                "expectancy_sol": self.expectancy_sol,
                "cost_share_of_gross": self.cost_share_of_gross,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PnlTotals":
        data = data or {}
        totals = cls()
        for name in (
            "gross_pnl_sol",
            "net_pnl_sol",
            "fees_sol",
            "tips_sol",
            "rent_sol",
            "costs_sol",
        ):
            setattr(totals, name, _float(data.get(name)))
        for name in ("buys", "sells", "winning_sells"):
            try:
                setattr(totals, name, int(data.get(name) or 0))
            except (TypeError, ValueError):
                setattr(totals, name, 0)
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
    """
    totals = PnlTotals()
    groups: dict[str, PnlTotals] = {}
    sources: dict[str, int] = {}
    count = 0
    for trade in trades:
        count += 1
        totals.add(trade)
        source = str(trade.get("cost_source") or COST_SOURCE_NONE)
        sources[source] = sources.get(source, 0) + 1
        if group_by:
            groups.setdefault(_group_key(trade, group_by), PnlTotals()).add(trade)
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
    "cost_fields",
    "is_buy",
    "is_sell",
    "open_cost_basis",
    "summarize_pnl",
    "trade_cash_flow",
    "trade_gross_pnl",
    "trade_net_pnl",
    "trade_payloads",
]
