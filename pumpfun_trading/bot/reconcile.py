"""Wallet vs. audit-trail reconciliation (FEAT-49, Sprint 24B).

Three checks, matching the canary criteria in ``docs/dev/RELEASE-GATE.md`` §3.4:

1. **Cash flow per trade:** for every live trade signature, the wallet's SOL change
   in the confirmed transaction (``getTransaction`` pre/post balances) must match
   the audit record's ``cash_flow_sol``.
2. **Token positions:** every mint the bot traded and closed must have no tokens
   left on-chain (lost position), and every position still open in the audit trail
   must hold tokens (phantom position).
3. **Whole wallet (optional):** with ``start_balance_sol``, the wallet SOL change
   since then must match the summed audit cash flow (catches unrecorded trades).

A gap above ``max(tolerance_abs_sol, tolerance_pct x |recorded cash flow|)`` fails.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from pumpfun_trading.bot.pnl import (
    is_buy,
    is_sell,
    open_cost_basis,
    trade_cash_flow,
)
from pumpfun_trading.bot.sweep import sweep_cash_flow

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_PROGRAM_IDS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
)
DEFAULT_TOLERANCE_ABS_SOL = 0.002
DEFAULT_TOLERANCE_PCT = 0.05
# Per-trade differences above this are listed as warnings (about 20 base fees).
TRADE_WARNING_THRESHOLD_SOL = 0.0001
# The last ``reconcile`` result is written here (next to the audit trail) so the
# dashboard and status snapshot can show it.
RECONCILE_STATUS_FILENAME = "reconcile_status.json"
# A result older than this is shown as stale (daily reconciliation, RUNBOOK §5.3).
RECONCILE_STALE_AFTER_SECONDS = 36 * 3600

RpcRequest = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class TradeCheck:
    signature: str
    mint: str
    action: str
    recorded_sol: float
    onchain_sol: float | None
    gap_sol: float | None
    error: str | None = None


@dataclass
class ReconciliationReport:
    wallet: str
    ok: bool = True
    tolerance_sol: float = DEFAULT_TOLERANCE_ABS_SOL
    trades_checked: int = 0
    trades_skipped: int = 0
    recorded_cash_flow_sol: float = 0.0
    onchain_cash_flow_sol: float = 0.0
    cash_flow_gap_sol: float = 0.0
    trade_mismatches: list[TradeCheck] = field(default_factory=list)
    unreadable_trades: list[TradeCheck] = field(default_factory=list)
    lost_positions: dict[str, int] = field(default_factory=dict)
    phantom_positions: list[str] = field(default_factory=list)
    open_cost_basis_sol: float = 0.0
    wallet_balance_sol: float | None = None
    start_balance_sol: float | None = None
    wallet_gap_sol: float | None = None
    # SOL moved out by the profit sweep, fees included (FEAT-42).
    swept_sol: float = 0.0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_live_signature(signature: Any) -> bool:
    return (
        isinstance(signature, str)
        and len(signature) >= 32
        and not signature.startswith("dry_run")
    )


def _wallet_delta_lamports(tx: dict[str, Any], wallet: str) -> int:
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    keys = [
        str(k.get("pubkey")) if isinstance(k, dict) else str(k)
        for k in message.get("accountKeys") or []
    ]
    if wallet not in keys:
        raise ValueError("wallet is not part of the transaction")
    index = keys.index(wallet)
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        raise ValueError("transaction has no balances for the wallet")
    return int(post[index]) - int(pre[index])


async def _fetch_transaction(rpc: RpcRequest, signature: str) -> dict[str, Any] | None:
    parsed = await rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "json",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
    )
    result = parsed.get("result") if isinstance(parsed, dict) else None
    return result if isinstance(result, dict) else None


async def fetch_wallet_token_balances(rpc: RpcRequest, wallet: str) -> dict[str, int]:
    """Raw token balance per mint held by ``wallet`` (both token programs)."""
    balances: dict[str, int] = {}
    for program in TOKEN_PROGRAM_IDS:
        parsed = await rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    wallet,
                    {"programId": program},
                    {"encoding": "jsonParsed", "commitment": "confirmed"},
                ],
            }
        )
        if not isinstance(parsed, dict) or "error" in parsed:
            raise RuntimeError(f"getTokenAccountsByOwner failed: {parsed}")
        for account in (parsed.get("result") or {}).get("value") or []:
            info = (
                ((account.get("account") or {}).get("data") or {}).get("parsed") or {}
            ).get("info") or {}
            mint = info.get("mint")
            amount = (info.get("tokenAmount") or {}).get("amount")
            if isinstance(mint, str) and amount is not None:
                balances[mint] = balances.get(mint, 0) + int(amount)
    return balances


async def fetch_wallet_balance_sol(rpc: RpcRequest, wallet: str) -> float:
    parsed = await rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [wallet]}
    )
    value = ((parsed or {}).get("result") or {}).get("value")
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"getBalance failed: {parsed}")
    return float(value) / LAMPORTS_PER_SOL


def _position_mints(trades: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """``(traded_mints, open_mints)`` from the audit trail."""
    open_positions = open_cost_basis(trades)
    position_mint: dict[str, str] = {}
    traded: set[str] = set()
    for trade in trades:
        mint = str(trade.get("mint") or "")
        if not mint:
            continue
        traded.add(mint)
        position = str(trade.get("position_id") or mint)
        position_mint[position] = mint
    open_mints = {position_mint[p] for p in open_positions if p in position_mint}
    return traded, open_mints


async def reconcile_wallet(
    trades: Iterable[dict[str, Any]],
    *,
    wallet: str,
    rpc: RpcRequest,
    tolerance_abs_sol: float = DEFAULT_TOLERANCE_ABS_SOL,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    start_balance_sol: float | None = None,
    check_tokens: bool = True,
    dust_raw_amount: int = 1,
    sweeps: Iterable[dict[str, Any]] = (),
) -> ReconciliationReport:
    """Reconciles audit trade records against the wallet on-chain.

    ``sweeps`` are the audit ``sweep`` records (FEAT-42): SOL the bot moved to
    the cold wallet on purpose, so the whole-wallet check counts them.
    """
    trade_list = [t for t in trades if is_buy(t) or is_sell(t)]
    report = ReconciliationReport(wallet=wallet, start_balance_sol=start_balance_sol)

    for trade in trade_list:
        signature = trade.get("signature")
        if trade.get("dry_run") or not _is_live_signature(signature):
            report.trades_skipped += 1
            continue
        recorded = trade_cash_flow(trade)
        check = TradeCheck(
            signature=str(signature),
            mint=str(trade.get("mint") or ""),
            action=str(trade.get("action") or ""),
            recorded_sol=recorded,
            onchain_sol=None,
            gap_sol=None,
        )
        try:
            tx = await _fetch_transaction(rpc, str(signature))
            if tx is None:
                raise RuntimeError("transaction not found")
            if (tx.get("meta") or {}).get("err") is not None:
                raise RuntimeError(f"transaction failed on-chain: {tx['meta']['err']}")
            onchain = _wallet_delta_lamports(tx, wallet) / LAMPORTS_PER_SOL
        except Exception as exc:
            check.error = str(exc)
            report.unreadable_trades.append(check)
            continue
        check.onchain_sol = onchain
        check.gap_sol = onchain - recorded
        report.trades_checked += 1
        report.recorded_cash_flow_sol += recorded
        report.onchain_cash_flow_sol += onchain
        if abs(check.gap_sol) > TRADE_WARNING_THRESHOLD_SOL:
            report.trade_mismatches.append(check)

    report.cash_flow_gap_sol = (
        report.onchain_cash_flow_sol - report.recorded_cash_flow_sol
    )
    report.tolerance_sol = max(
        tolerance_abs_sol, tolerance_pct * abs(report.recorded_cash_flow_sol)
    )
    if abs(report.cash_flow_gap_sol) > report.tolerance_sol:
        report.problems.append(
            f"cash-flow gap {report.cash_flow_gap_sol:+.6f} SOL exceeds "
            f"tolerance {report.tolerance_sol:.6f} SOL"
        )
    if report.trade_mismatches:
        # Individual differences only fail the run through the aggregate gap.
        report.warnings.append(
            f"{len(report.trade_mismatches)} trade(s) differ from the chain by more "
            f"than {TRADE_WARNING_THRESHOLD_SOL} SOL"
        )
    if report.unreadable_trades:
        report.problems.append(
            f"{len(report.unreadable_trades)} trade signature(s) could not be verified"
        )

    # Paper trades never touched the wallet, so they are left out of every check.
    live_trades = [
        t
        for t in trade_list
        if not t.get("dry_run") and _is_live_signature(t.get("signature"))
    ]
    report.open_cost_basis_sol = sum(open_cost_basis(live_trades).values())
    if check_tokens:
        traded, open_mints = _position_mints(live_trades)
        try:
            balances = await fetch_wallet_token_balances(rpc, wallet)
        except Exception as exc:
            report.problems.append(f"token balances unavailable: {exc}")
        else:
            for mint in sorted(traded - open_mints):
                amount = balances.get(mint, 0)
                if amount > dust_raw_amount:
                    report.lost_positions[mint] = amount
            report.phantom_positions = sorted(
                mint for mint in open_mints if balances.get(mint, 0) <= dust_raw_amount
            )
            if report.lost_positions:
                report.problems.append(
                    f"{len(report.lost_positions)} closed position(s) still hold tokens"
                )
            if report.phantom_positions:
                report.problems.append(
                    f"{len(report.phantom_positions)} open position(s) hold no tokens"
                )

    if start_balance_sol is not None:
        try:
            report.wallet_balance_sol = await fetch_wallet_balance_sol(rpc, wallet)
        except Exception as exc:
            report.problems.append(f"wallet balance unavailable: {exc}")
        else:
            recorded_total = sum(trade_cash_flow(t) for t in live_trades)
            live_sweeps = [
                s
                for s in sweeps
                if not s.get("dry_run") and _is_live_signature(s.get("signature"))
            ]
            report.swept_sol = -sum(sweep_cash_flow(s) for s in live_sweeps)
            recorded_total -= report.swept_sol
            report.wallet_gap_sol = (
                report.wallet_balance_sol - start_balance_sol
            ) - recorded_total
            wallet_tolerance = max(
                tolerance_abs_sol, tolerance_pct * abs(recorded_total)
            )
            if abs(report.wallet_gap_sol) > wallet_tolerance:
                report.problems.append(
                    f"wallet change differs from recorded cash flow by "
                    f"{report.wallet_gap_sol:+.6f} SOL (transfers or unrecorded trades?)"
                )

    report.ok = not report.problems
    return report


def reconcile_status_path(audit_log_path: str | os.PathLike[str] | None) -> Path | None:
    """Where the last reconciliation result for this audit trail is stored."""
    override = os.getenv("PUMPFUN_RECONCILE_STATUS_PATH")
    if override:
        return Path(override)
    if not audit_log_path:
        return None
    return Path(audit_log_path).with_name(RECONCILE_STATUS_FILENAME)


def reconciliation_status(
    report: ReconciliationReport, *, checked_at: float | None = None
) -> dict[str, Any]:
    """Compact, display-ready summary of a reconciliation run."""
    return {
        "checked_at": time.time() if checked_at is None else checked_at,
        "wallet": report.wallet,
        "ok": report.ok,
        "trades_checked": report.trades_checked,
        "cash_flow_gap_sol": report.cash_flow_gap_sol,
        "wallet_gap_sol": report.wallet_gap_sol,
        "tolerance_sol": report.tolerance_sol,
        "lost_positions": len(report.lost_positions),
        "phantom_positions": len(report.phantom_positions),
        "problems": list(report.problems),
    }


def write_reconciliation_status(
    report: ReconciliationReport,
    path: str | os.PathLike[str],
    *,
    checked_at: float | None = None,
) -> dict[str, Any]:
    """Atomically writes the reconciliation summary to ``path``."""
    status = reconciliation_status(report, checked_at=checked_at)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)
    return status


def load_reconciliation_status(
    path: str | os.PathLike[str] | None,
) -> dict[str, Any] | None:
    """The last stored reconciliation summary, or ``None`` if there is none."""
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "ok" in data else None


class ReconciliationStatusReader:
    """Reads the reconciliation status file, re-parsing only when it changes.

    The dashboard renders several times a second; this keeps it to one ``stat``.
    """

    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        self.path = Path(path) if path else None
        self._mtime: float | None = None
        self._status: dict[str, Any] | None = None

    def read(self) -> dict[str, Any] | None:
        if self.path is None:
            return None
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime, self._status = None, None
            return None
        if mtime != self._mtime:
            self._mtime = mtime
            self._status = load_reconciliation_status(self.path)
        return self._status


def describe_reconciliation_status(
    status: dict[str, Any] | None, *, now: float | None = None
) -> str:
    """One-line dashboard text, e.g. ``OK (12 trades, 3h ago)``."""
    if not status:
        return "not run"
    now = time.time() if now is None else now
    checked_at = status.get("checked_at")
    if isinstance(checked_at, (int, float)):
        age = max(0.0, now - float(checked_at))
        if age < 3600:
            age_text = f"{int(age // 60)}m ago"
        elif age < 2 * 86400:
            age_text = f"{int(age // 3600)}h ago"
        else:
            age_text = f"{int(age // 86400)}d ago"
    else:
        age, age_text = float("inf"), "time unknown"
    if not status.get("ok"):
        problems = status.get("problems") or []
        return f"GAP ({len(problems)} problem(s), {age_text})"
    label = "STALE" if age > RECONCILE_STALE_AFTER_SECONDS else "OK"
    return f"{label} ({int(status.get('trades_checked') or 0)} trades, {age_text})"


__all__ = [
    "DEFAULT_TOLERANCE_ABS_SOL",
    "DEFAULT_TOLERANCE_PCT",
    "RECONCILE_STATUS_FILENAME",
    "TRADE_WARNING_THRESHOLD_SOL",
    "ReconciliationReport",
    "TradeCheck",
    "describe_reconciliation_status",
    "fetch_wallet_balance_sol",
    "fetch_wallet_token_balances",
    "load_reconciliation_status",
    "reconcile_status_path",
    "reconcile_wallet",
    "reconciliation_status",
    "write_reconciliation_status",
]
