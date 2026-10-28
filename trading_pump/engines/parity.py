"""Replay-vs-live parity: compare a live-fidelity replay with the audit trail.

The live bot records each run with ``--record-replay``; replaying that capture
with the same config should reproduce the live decisions. This module lines up
the replay trades with the audit-trail trades per mint and reports entries,
exit reasons and net PnL, so differences can be explained before a backtest is
trusted for tuning (Sprint 24C).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from trading_pump.bot.pnl import is_buy, is_sell, trade_net_pnl

# Live exit reasons are free text ("stagnant_curve_timeout (181.0s >= …)"); map
# their first token to the replay ``exit_type``.
_LIVE_REASON_TO_EXIT_TYPE = {
    "stop_loss_hit": "stop_loss",
    "stagnant_curve_timeout": "stagnant_timeout",
    "max_hold_time_exceeded": "max_hold_timeout",
    "take_profit_tier_1": "tier_1",
    "take_profit_tier_1_full": "tier_1",
    "take_profit_tier_2": "tier_2",
    "take_profit_tier_2_full": "tier_2",
    "moonbag_floor_hit": "moonbag_floor",
    "trailing_stop_hit": "trailing_stop",
    "take_profit_hit": "take_profit",
    # Emergency liquidation: the bot writes "circuit_breaker: <lock reason>".
    "circuit_breaker:": "circuit_breaker_liquidation",
    "emergency_circuit_breaker_liquidation": "circuit_breaker_liquidation",
}


def normalise_exit_reason(reason: Any) -> str:
    """Comparable exit category for a live or replay exit reason."""
    head = str(reason or "").strip().split(" ")[0].split("(")[0]
    if head.startswith("pre_graduation_tranche"):
        return "pre_graduation_tranche"
    return _LIVE_REASON_TO_EXIT_TYPE.get(head, head or "unknown")


@dataclass
class _MintSide:
    buys: int = 0
    sells: int = 0
    net_pnl_sol: float = 0.0
    exit_reasons: list[str] = field(default_factory=list)


def _collect(
    trades: Iterable[dict[str, Any]], *, net_key: str | None
) -> dict[str, _MintSide]:
    sides: dict[str, _MintSide] = {}
    for trade in trades:
        mint = str(trade.get("mint") or "")
        if not mint:
            continue
        side = sides.setdefault(mint, _MintSide())
        selling = is_sell(trade)
        if not selling and not is_buy(trade):
            continue
        # Live buys book their own costs (fee, tip, rent) as a negative net on
        # the buy record; replay sells already carry them. Summing every
        # buy and sell record keeps both sides net of all costs (BUG-119).
        side.net_pnl_sol += (
            float(trade.get(net_key) or 0.0) if net_key else trade_net_pnl(trade)
        )
        if selling:
            side.sells += 1
            side.exit_reasons.append(normalise_exit_reason(trade.get("reason")))
        else:
            side.buys += 1
    return sides


def compare_replay_to_audit(
    replay_trades: Iterable[dict[str, Any]],
    audit_trades: Iterable[dict[str, Any]],
    *,
    tolerance_sol: float = 0.002,
    tolerance_pct: float = 0.10,
) -> dict[str, Any]:
    """Per-mint and total comparison of replay trades with live audit trades.

    ``within_tolerance`` is true when the net PnL gap is at most
    ``max(tolerance_sol, tolerance_pct * |live net PnL|)``.
    """
    replay = _collect(replay_trades, net_key="pnl")
    live = _collect(audit_trades, net_key=None)

    rows: list[dict[str, Any]] = []
    for mint in sorted(set(replay) | set(live)):
        r = replay.get(mint, _MintSide())
        lv = live.get(mint, _MintSide())
        if r.buys and lv.buys:
            status = "both"
        elif lv.buys:
            status = "live_only"
        elif r.buys:
            status = "replay_only"
        else:
            status = "no_entry"
        rows.append(
            {
                "mint": mint,
                "status": status,
                "live_buys": lv.buys,
                "replay_buys": r.buys,
                "live_exits": lv.exit_reasons,
                "replay_exits": r.exit_reasons,
                "exit_match": status == "both"
                and sorted(set(lv.exit_reasons)) == sorted(set(r.exit_reasons)),
                "live_net_pnl_sol": lv.net_pnl_sol,
                "replay_net_pnl_sol": r.net_pnl_sol,
                "gap_sol": r.net_pnl_sol - lv.net_pnl_sol,
            }
        )

    live_net = sum(side.net_pnl_sol for side in live.values())
    replay_net = sum(side.net_pnl_sol for side in replay.values())
    gap = replay_net - live_net
    allowed = max(float(tolerance_sol), float(tolerance_pct) * abs(live_net))
    both = [row for row in rows if row["status"] == "both"]
    return {
        "mints": rows,
        "counts": {
            "both": len(both),
            "live_only": sum(1 for row in rows if row["status"] == "live_only"),
            "replay_only": sum(1 for row in rows if row["status"] == "replay_only"),
            "exit_match": sum(1 for row in both if row["exit_match"]),
        },
        "live_net_pnl_sol": live_net,
        "replay_net_pnl_sol": replay_net,
        "gap_sol": gap,
        "allowed_gap_sol": allowed,
        "within_tolerance": abs(gap) <= allowed,
    }


def provenance_notes(
    audit_records: Iterable[Mapping[str, Any]], replay_config_path: str | None
) -> list[str]:
    """What the audit trail says produced the run, and whether the replay matches.

    Reads the ``run_started`` records (FEAT-68). A replay config whose file
    hash differs from the run's means parity compares different settings.
    """
    from trading_pump.ops.provenance import (
        PROVENANCE_RECORD_TYPE,
        file_sha256,
        short_build_label,
    )

    runs = [
        dict(r.get("payload") or {})
        for r in audit_records
        if r.get("type") == PROVENANCE_RECORD_TYPE
    ]
    if not runs:
        return ["audit trail has no run provenance (written before rc.4)"]
    replay_hash = file_sha256(replay_config_path)
    notes: list[str] = []
    for run in runs:
        run_hash = run.get("config_file_sha256")
        notes.append(
            f"run {run.get('started_at_utc') or '?'}: {short_build_label(run)}, "
            f"{run.get('mode') or '?'}, config {run.get('config_path') or '-'} "
            f"({str(run_hash or '-')[:12]})"
        )
        if run.get("git_dirty"):
            notes.append("  built from a checkout with modified tracked files")
        if replay_hash and run_hash and replay_hash != run_hash:
            notes.append(
                f"  replay config {replay_config_path} ({replay_hash[:12]}) differs "
                "from the run's config file: parity compares different settings"
            )
    return notes


__all__ = ["compare_replay_to_audit", "normalise_exit_reason", "provenance_notes"]
