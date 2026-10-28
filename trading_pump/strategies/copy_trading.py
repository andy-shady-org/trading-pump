"""Smart money tracking and copy-trading engine for Pump.fun tokens.

This module provides wallet registration, dynamic performance profiling,
proportional/scaled position sizing, and copy-trade signal generation
from Yellowstone Geyser and WebSocket on-chain trade streams.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class TrackedWallet:
    """Configuration and dynamic performance metrics for a smart money wallet."""

    address: str
    label: str = ""
    win_rate: float = 0.60
    total_trades: int = 0
    avg_return_pct: float = 0.0
    risk_score: float = 20.0
    reference_bankroll_sol: float = 10.0
    max_allocation_sol: float = 0.05
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert tracked wallet to dictionary for configuration export/logging."""
        return {
            "address": self.address,
            "label": self.label,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "avg_return_pct": self.avg_return_pct,
            "risk_score": self.risk_score,
            "reference_bankroll_sol": self.reference_bankroll_sol,
            "max_allocation_sol": self.max_allocation_sol,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackedWallet:
        """Construct TrackedWallet instance from dictionary configuration."""
        return cls(
            address=str(data.get("address", "")).strip(),
            label=str(data.get("label", "")),
            win_rate=float(data.get("win_rate", 0.60)),
            total_trades=int(data.get("total_trades", 0)),
            avg_return_pct=float(data.get("avg_return_pct", 0.0)),
            risk_score=float(data.get("risk_score", 20.0)),
            reference_bankroll_sol=float(data.get("reference_bankroll_sol", 10.0)),
            max_allocation_sol=float(data.get("max_allocation_sol", 0.05)),
            enabled=bool(data.get("enabled", True)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )

    def record_trade_outcome(
        self,
        return_pct: float,
        is_win: Optional[bool] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Update historical win rate and return metrics dynamically."""
        now = float(timestamp if timestamp is not None else time.time())
        prev_trades = self.total_trades
        self.total_trades += 1

        # Determine win/loss
        win = is_win if is_win is not None else (return_pct > 0.0)
        prev_wins = self.win_rate * prev_trades
        new_wins = prev_wins + (1.0 if win else 0.0)
        self.win_rate = round(new_wins / self.total_trades, 4)

        # Update average return %
        prev_total_return = self.avg_return_pct * prev_trades
        self.avg_return_pct = round(
            (prev_total_return + return_pct) / self.total_trades, 4
        )

        # Dynamic risk score adjustment (penalize large drawdowns)
        if return_pct < -20.0:
            self.risk_score = min(100.0, self.risk_score + 5.0)
        elif return_pct > 20.0 and self.risk_score > 10.0:
            self.risk_score = max(0.0, self.risk_score - 2.0)

        self.updated_at = now


@dataclass(slots=True)
class CopyTradeSignal:
    """Signal generated when a tracked smart money wallet executes an on-chain trade."""

    triggered: bool
    mint: str
    wallet_address: str
    wallet_label: str
    is_buy: bool
    sol_amount: float
    computed_copy_size_sol: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert copy-trade signal to dictionary representation."""
        return {
            "triggered": self.triggered,
            "mint": self.mint,
            "wallet_address": self.wallet_address,
            "wallet_label": self.wallet_label,
            "is_buy": self.is_buy,
            "sol_amount": self.sol_amount,
            "computed_copy_size_sol": self.computed_copy_size_sol,
            "reason": self.reason,
        }


class WalletRegistry:
    """In-memory thread-safe registry of tracked smart money wallets."""

    def __init__(self) -> None:
        self._wallets: dict[str, TrackedWallet] = {}

    @property
    def wallet_count(self) -> int:
        """Total number of wallets in registry."""
        return len(self._wallets)

    def register_wallet(self, wallet: TrackedWallet) -> None:
        """Add or update a tracked wallet in the registry."""
        if not wallet.address:
            raise ValueError("Wallet address cannot be empty")
        self._wallets[wallet.address] = wallet

    def register_wallets(self, wallets: list[TrackedWallet | dict[str, Any]]) -> None:
        """Bulk register wallets from instances or dictionaries."""
        for item in wallets:
            if isinstance(item, TrackedWallet):
                self.register_wallet(item)
            elif isinstance(item, dict):
                self.register_wallet(TrackedWallet.from_dict(item))

    def get_wallet(self, address: str) -> Optional[TrackedWallet]:
        """Lookup a tracked wallet by address in O(1) time."""
        return self._wallets.get(address)

    def remove_wallet(self, address: str) -> bool:
        """Remove a wallet from tracking."""
        if address in self._wallets:
            del self._wallets[address]
            return True
        return False

    def list_wallets(self, only_enabled: bool = False) -> list[TrackedWallet]:
        """Return list of tracked wallets."""
        if only_enabled:
            return [w for w in self._wallets.values() if w.enabled]
        return list(self._wallets.values())

    def get_ranked_wallets(
        self, min_win_rate: float = 0.0, max_risk_score: float = 100.0
    ) -> list[TrackedWallet]:
        """Return enabled wallets sorted by win rate and average return."""
        qualifying = [
            w
            for w in self._wallets.values()
            if w.enabled
            and w.win_rate >= min_win_rate
            and w.risk_score <= max_risk_score
        ]
        return sorted(
            qualifying, key=lambda w: (w.win_rate, w.avg_return_pct), reverse=True
        )

    def update_wallet_performance(
        self,
        address: str,
        return_pct: float,
        is_win: Optional[bool] = None,
        timestamp: Optional[float] = None,
    ) -> Optional[TrackedWallet]:
        """Record trade result for an existing wallet."""
        wallet = self._wallets.get(address)
        if wallet is not None:
            wallet.record_trade_outcome(return_pct, is_win=is_win, timestamp=timestamp)
        return wallet

    def clear(self) -> None:
        """Clear all registered wallets."""
        self._wallets.clear()


class CopyTradeEngine:
    """Real-time copy-trading and smart money execution engine."""

    def __init__(
        self,
        registry: Optional[WalletRegistry] = None,
        base_buy_amount_sol: float = 0.02,
        max_position_size_sol: float = 0.05,
        sizing_mode: str = "proportional",
        scale_factor: float = 1.0,
        min_wallet_win_rate: float = 0.60,
        max_wallet_risk_score: float = 40.0,
        mirror_sells: bool = True,
        enabled: bool = True,
    ) -> None:
        self.registry = registry if registry is not None else WalletRegistry()
        self.base_buy_amount_sol = max(0.001, base_buy_amount_sol)
        self.max_position_size_sol = max(
            self.base_buy_amount_sol, max_position_size_sol
        )
        self.sizing_mode = sizing_mode.lower()
        self.scale_factor = max(0.1, scale_factor)
        self.min_wallet_win_rate = min_wallet_win_rate
        self.max_wallet_risk_score = max_wallet_risk_score
        self.mirror_sells = mirror_sells
        self.enabled = enabled

    def is_tracked_wallet(self, address: str) -> bool:
        """Return True if wallet address is registered and enabled."""
        wallet = self.registry.get_wallet(address)
        return wallet is not None and wallet.enabled

    def calculate_copy_size(self, wallet: TrackedWallet, trade_sol: float) -> float:
        """Calculate dynamic entry size in SOL based on wallet sizing mode and constraints."""
        mode = self.sizing_mode
        base = self.base_buy_amount_sol
        scale = self.scale_factor

        if mode == "proportional":
            ref_bankroll = max(0.1, wallet.reference_bankroll_sol)
            ratio = max(0.01, trade_sol / ref_bankroll)
            computed = base * scale * ratio
        elif mode == "scaled":
            # Scale conviction factor from win rate (0.50 -> 1.0x, 0.75 -> 1.5x)
            conviction = max(0.5, min(2.0, wallet.win_rate / 0.50))
            computed = base * scale * conviction
        else:  # "fixed" or fallback
            computed = base * scale

        # Enforce wallet-specific max allocation and global max position size caps
        max_cap = min(wallet.max_allocation_sol, self.max_position_size_sol)
        if max_cap <= 0:
            max_cap = self.max_position_size_sol

        final_size = round(min(max_cap, max(0.001, computed)), 4)
        return final_size

    def evaluate_copy_signal(
        self,
        wallet: TrackedWallet,
        mint: str,
        sol_amount: float,
        is_buy: bool,
    ) -> CopyTradeSignal:
        """Evaluate a tracked wallet's trade against qualification criteria."""
        if not self.enabled:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason="copy_trading_disabled",
            )

        if not wallet.enabled:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason="wallet_disabled",
            )

        if wallet.win_rate < self.min_wallet_win_rate:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason=f"win_rate_{wallet.win_rate:.2f}_below_min_{self.min_wallet_win_rate:.2f}",
            )

        if wallet.risk_score > self.max_wallet_risk_score:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason=f"risk_score_{wallet.risk_score:.1f}_exceeds_max_{self.max_wallet_risk_score:.1f}",
            )

        if not is_buy and not self.mirror_sells:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                is_buy=False,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason="mirror_sells_disabled",
            )

        # Qualified buy or sell
        copy_size = self.calculate_copy_size(wallet, sol_amount) if is_buy else 0.0
        action_name = "buy" if is_buy else "sell"
        reason = f"smart_money_{action_name}_{wallet.label or wallet.address[:8]}"

        return CopyTradeSignal(
            triggered=True,
            mint=mint,
            wallet_address=wallet.address,
            wallet_label=wallet.label,
            is_buy=is_buy,
            sol_amount=sol_amount,
            computed_copy_size_sol=copy_size,
            reason=reason,
        )

    def record_and_evaluate(
        self,
        user: str,
        mint: str,
        sol_amount: float,
        is_buy: bool,
        timestamp: Optional[float] = None,
    ) -> CopyTradeSignal:
        """Fast-path evaluation for incoming trade stream events."""
        if not user or not self.enabled:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=user,
                wallet_label="",
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason="copy_trading_disabled_or_empty_user",
            )

        wallet = self.registry.get_wallet(user)
        if wallet is None:
            return CopyTradeSignal(
                triggered=False,
                mint=mint,
                wallet_address=user,
                wallet_label="",
                is_buy=is_buy,
                sol_amount=sol_amount,
                computed_copy_size_sol=0.0,
                reason="untracked_wallet",
            )

        return self.evaluate_copy_signal(
            wallet=wallet,
            mint=mint,
            sol_amount=sol_amount,
            is_buy=is_buy,
        )


__all__ = [
    "TrackedWallet",
    "CopyTradeSignal",
    "WalletRegistry",
    "CopyTradeEngine",
]
