"""Entry features rebuilt from a capture, for random-cut tests of entry rules.

Captures older than v0.3.0-rc.2 carry no FEAT-56/57 ``entry_metrics``. This
module rebuilds them from the capture itself: for each position, only the
market trades recorded **before** its entry (creator left out) are scored,
with the same ``OrderFlowEngine`` methods the bot records with, so a rule
tested here can be applied before entry. It replaces the hand-run scripts in
``data/analysis-2026-10-20/`` (``feat_analysis.py``, ``filters.py``,
``wash.py``, ``combo.py``).

Features (added to a position's ``entry_metrics`` unless the buy recorded them):

* ``pre_entry_buys``, ``unique_buyers``, ``top_buyer_share``,
  ``wallet_diversity`` (FEAT-56, ``OrderFlowEngine.buy_flow_concentration``);
* ``round_trip_wallets``, ``round_trip_share``, ``quick_flips`` (FEAT-57,
  ``OrderFlowEngine.round_trip_flow``);
* ``early_sol``: real SOL that entered the curve between the create event and
  the first recorded trade (a sniper-volume proxy; the captures never see the
  first seconds), and ``first_trade_gap_seconds``;
* ``creator_prior_loss``: 1 when an earlier position on the same creator had
  already **closed** at a loss before this entry (the FEAT-55 book, walk-forward,
  so no outcome from the future leaks in), else 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from pumpfun_trading.engines.replay import real_sol_from_market_cap
from pumpfun_trading.strategies.momentum import OrderFlowEngine

FLOW_FEATURES = (
    "pre_entry_buys",
    "unique_buyers",
    "top_buyer_share",
    "wallet_diversity",
    "round_trip_wallets",
    "round_trip_share",
    "quick_flips",
)


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class CaptureIndex:
    """Per-mint creator, create event and market trades of a capture."""

    creators: dict[str, str] = field(default_factory=dict)
    creates: dict[str, dict[str, Any]] = field(default_factory=dict)
    trades: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> CaptureIndex:
        index = cls()
        for record in records:
            mint = record.get("mint")
            if not mint:
                continue
            mint = str(mint)
            if record.get("event") == "screening":
                creator = (record.get("screening") or {}).get("creator")
                if creator:
                    index.creators[mint] = str(creator)
                continue
            if record.get("event") or "reason" in record:
                # Curve polls, shadow rows, migrations and the bot's own fills.
                continue
            if record.get("user"):
                index.trades.setdefault(mint, []).append(dict(record))
            elif mint not in index.creates and _float(record.get("market_cap_sol")) > 0:
                index.creates[mint] = dict(record)
        for rows in index.trades.values():
            rows.sort(key=lambda t: _float(t.get("timestamp")))
        return index

    def creator(self, mint: str) -> str | None:
        return self.creators.get(mint)


def flow_features(
    index: CaptureIndex, mint: str, until: float
) -> dict[str, float | int] | None:
    """FEAT-56/57 features of the trades recorded before ``until``."""
    rows = [t for t in index.trades.get(mint, []) if _float(t.get("timestamp")) < until]
    if not rows:
        return None
    engine = OrderFlowEngine(max_retention_seconds=10**9)
    for trade in rows:
        engine.record_trade(
            mint,
            bool(trade.get("is_buy")),
            _float(trade.get("sol_amount")),
            str(trade.get("user") or ""),
            timestamp=_float(trade.get("timestamp")),
        )
    creator = index.creator(mint)
    exclude = frozenset({creator}) if creator else frozenset()
    concentration = engine.buy_flow_concentration(mint, exclude_users=exclude)
    wash = engine.round_trip_flow(mint, exclude_users=exclude)
    return {
        "pre_entry_buys": int(concentration["buys"]),
        "unique_buyers": int(concentration["unique_buyers"]),
        "top_buyer_share": float(concentration["top_buyer_share"]),
        "wallet_diversity": float(concentration["wallet_diversity"]),
        "round_trip_wallets": int(wash["round_trip_wallets"]),
        "round_trip_share": float(wash["round_trip_share"]),
        "quick_flips": int(wash["quick_flips"]),
    }


def early_inflow(index: CaptureIndex, mint: str) -> dict[str, float] | None:
    """Real SOL added before the first recorded trade, and the gap to it."""
    create = index.creates.get(mint)
    rows = index.trades.get(mint)
    if not create or not rows:
        return None
    first = rows[0]
    signed = _float(first.get("sol_amount")) * (1 if first.get("is_buy") else -1)
    before = real_sol_from_market_cap(_float(first.get("market_cap_sol"))) - signed
    at_create = real_sol_from_market_cap(_float(create.get("market_cap_sol")))
    return {
        "early_sol": round(before - at_create, 6),
        "first_trade_gap_seconds": round(
            _float(first.get("timestamp")) - _float(create.get("timestamp")), 3
        ),
    }


def creator_prior_losses(
    positions: Sequence[Mapping[str, Any]], creators: Mapping[str, str | None]
) -> list[int]:
    """Per position: 1 if the creator had a loss that closed before its entry."""
    losses: list[tuple[float, str]] = sorted(
        (_float(p.get("exit_ts")), str(creators.get(str(p.get("mint")))))
        for p in positions
        if p.get("closed", True)
        and p.get("exit_ts") is not None
        and _float(p.get("net")) < 0
        and creators.get(str(p.get("mint")))
    )
    flags: list[int] = []
    for position in positions:
        creator = creators.get(str(position.get("mint")))
        entry = _float(position.get("entry_ts"))
        flags.append(
            int(bool(creator) and any(c == creator and ts < entry for ts, c in losses))
        )
    return flags


def enrich_positions(
    positions: Sequence[Mapping[str, Any]], index: CaptureIndex
) -> list[dict[str, Any]]:
    """Copies of ``positions`` with the rebuilt features in ``entry_metrics``.

    A metric the buy already recorded wins over the rebuilt one; a position
    with no recorded trades before entry gets no flow features (rules count
    it as missing).
    """
    creators = {
        str(p.get("mint")): (p.get("creator") or index.creator(str(p.get("mint"))))
        for p in positions
    }
    prior = creator_prior_losses(positions, creators)
    out: list[dict[str, Any]] = []
    for position, flag in zip(positions, prior):
        mint = str(position.get("mint"))
        rebuilt: dict[str, Any] = {}
        rebuilt.update(
            flow_features(index, mint, _float(position.get("entry_ts"))) or {}
        )
        rebuilt.update(early_inflow(index, mint) or {})
        if creators.get(mint):
            rebuilt["creator_prior_loss"] = flag
        recorded = position.get("entry_metrics")
        merged = {
            **rebuilt,
            **(dict(recorded) if isinstance(recorded, Mapping) else {}),
        }
        out.append({**position, "creator": creators.get(mint), "entry_metrics": merged})
    return out


__all__ = [
    "FLOW_FEATURES",
    "CaptureIndex",
    "creator_prior_losses",
    "early_inflow",
    "enrich_positions",
    "flow_features",
]
