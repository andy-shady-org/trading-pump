"""Treasury profit sweep to a cold wallet (FEAT-42, Sprint 24D).

Disabled by default (``profit_sweep_enabled``). When on, the bot periodically
moves the hot wallet's SOL above a floor to ``profit_sweep_destination``, so a
compromised or misbehaving hot wallet can only lose what it needs to trade.

The floor never drops below what trading needs: ``reserve_balance_sol`` plus
``max_total_exposure_sol`` plus a fee buffer. Sweeps below
``profit_sweep_min_sol`` are skipped (fees and dust). Every sweep is written to
the audit trail as a ``sweep`` record whose ``cash_flow_sol`` the whole-wallet
reconciliation subtracts, and moves the daily breaker's baseline down by the
amount, so a withdrawal is never mistaken for a drawdown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LAMPORTS_PER_SOL = 1_000_000_000
# Room for a few transaction fees and token-account rent above the trading needs.
SWEEP_FEE_BUFFER_SOL = 0.01


def effective_sweep_floor(config: Any) -> float:
    """The SOL kept in the hot wallet: the configured floor or the trading need."""
    trading_need = (
        float(getattr(config, "reserve_balance_sol", 0.0) or 0.0)
        + float(getattr(config, "max_total_exposure_sol", 0.0) or 0.0)
        + SWEEP_FEE_BUFFER_SOL
    )
    return max(
        float(getattr(config, "profit_sweep_hot_floor_sol", 0.0) or 0.0), trading_need
    )


def validate_sweep_config(config: Any, wallet_pubkey: str | None) -> list[str]:
    """Problems that make an enabled sweep unsafe; empty when it may run."""
    if not getattr(config, "profit_sweep_enabled", False):
        return []
    from pumpfun_trading.sdk.execution import PumpFunExecutionClient

    destination = str(getattr(config, "profit_sweep_destination", "") or "").strip()
    problems: list[str] = []
    if not destination:
        problems.append("profit_sweep_destination is not set")
    elif not PumpFunExecutionClient.is_valid_pubkey(destination):
        problems.append("profit_sweep_destination is not a valid Solana address")
    elif wallet_pubkey and destination == wallet_pubkey:
        problems.append("profit_sweep_destination is the trading wallet itself")
    if float(getattr(config, "profit_sweep_min_sol", 0.0) or 0.0) <= 0:
        problems.append("profit_sweep_min_sol must be positive")
    if float(getattr(config, "profit_sweep_interval_seconds", 0.0) or 0.0) <= 0:
        problems.append("profit_sweep_interval_seconds must be positive")
    return problems


@dataclass(frozen=True)
class SweepPlan:
    balance_sol: float
    floor_sol: float
    lamports: int
    skip_reason: str = ""

    @property
    def amount_sol(self) -> float:
        return self.lamports / LAMPORTS_PER_SOL


def plan_sweep(
    *, balance_sol: float, floor_sol: float, min_sweep_sol: float
) -> SweepPlan:
    """How much to move: everything above the floor, in whole lamports, or nothing."""
    excess_lamports = int((float(balance_sol) - float(floor_sol)) * LAMPORTS_PER_SOL)
    if excess_lamports <= 0:
        return SweepPlan(balance_sol, floor_sol, 0, "balance at or below the floor")
    if excess_lamports < int(float(min_sweep_sol) * LAMPORTS_PER_SOL):
        return SweepPlan(balance_sol, floor_sol, 0, "excess below profit_sweep_min_sol")
    return SweepPlan(balance_sol, floor_sol, excess_lamports)


@dataclass
class SweepState:
    total_swept_sol: float = 0.0
    sweeps: int = 0
    last_sweep_at: float | None = None
    last_signature: str = ""
    last_error: str = ""
    last_check_at: float | None = None

    def record_success(self, amount_sol: float, signature: str, now: float) -> None:
        self.total_swept_sol += float(amount_sol)
        self.sweeps += 1
        self.last_sweep_at = now
        self.last_signature = signature
        self.last_error = ""

    def describe(self) -> str:
        if self.last_error:
            return f"ERROR ({self.last_error[:40]})"
        if not self.sweeps:
            return "none yet"
        return f"{self.total_swept_sol:.4f} SOL in {self.sweeps}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "SweepState":
        if not isinstance(data, dict):
            return cls()

        def _opt(value: Any) -> float | None:
            return float(value) if isinstance(value, (int, float)) else None

        try:
            sweeps = int(data.get("sweeps") or 0)
            total = float(data.get("total_swept_sol") or 0.0)
        except (TypeError, ValueError):
            sweeps, total = 0, 0.0
        return cls(
            total_swept_sol=total,
            sweeps=sweeps,
            last_sweep_at=_opt(data.get("last_sweep_at")),
            last_signature=str(data.get("last_signature") or ""),
            last_error=str(data.get("last_error") or ""),
            last_check_at=_opt(data.get("last_check_at")),
        )


def sweep_payloads(records: Any) -> list[dict[str, Any]]:
    """Payloads of the ``sweep`` records in raw audit records."""
    return [
        record["payload"]
        for record in records or ()
        if isinstance(record, dict)
        and (record.get("type") or record.get("record_type")) == "sweep"
        and isinstance(record.get("payload"), dict)
    ]


def sweep_cash_flow(record: dict[str, Any]) -> float:
    """Wallet SOL change of a ``sweep`` audit record (negative: it leaves)."""
    try:
        return float(record.get("cash_flow_sol") or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "SWEEP_FEE_BUFFER_SOL",
    "SweepPlan",
    "SweepState",
    "effective_sweep_floor",
    "plan_sweep",
    "sweep_cash_flow",
    "sweep_payloads",
    "validate_sweep_config",
]
