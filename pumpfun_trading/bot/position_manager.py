from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import (
    ExitDecision,
    PositionExitState,
    evaluate_exit_strategy,
)

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position in a token."""

    mint: str
    name: str
    entry_market_cap: float
    current_market_cap: float
    peak_market_cap: float
    initial_token_amount: int
    remaining_token_amount: int
    cost_sol: float = 0.0
    entry_sol: float = 0.0
    buy_signature: str | None = None
    first_seen: float = field(default_factory=time.time)
    entry_reason: str = "entry"
    dry_run: bool = False
    tier_1_executed: bool = False
    tier_2_executed: bool = False
    moonbag_active: bool = False
    trailing_stop_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_amount(self) -> int:
        return self.remaining_token_amount

    @token_amount.setter
    def token_amount(self, value: int) -> None:
        self.remaining_token_amount = int(value)

    @property
    def performance(self) -> float:
        if self.entry_market_cap <= 0:
            return 1.0
        return self.current_market_cap / self.entry_market_cap

    @property
    def peak_performance(self) -> float:
        if self.entry_market_cap <= 0:
            return 1.0
        return self.peak_market_cap / self.entry_market_cap

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entry_market_cap": self.entry_market_cap,
            "current_market_cap": self.current_market_cap,
            "peak_market_cap": self.peak_market_cap,
            "initial_token_amount": self.initial_token_amount,
            "remaining_token_amount": self.remaining_token_amount,
            "token_amount": self.remaining_token_amount,
            "cost_sol": self.cost_sol,
            "entry_sol": self.entry_sol or self.cost_sol,
            "buy_signature": self.buy_signature,
            "first_seen": self.first_seen,
            "entry_reason": self.entry_reason,
            "dry_run": self.dry_run,
            "tier_1_executed": self.tier_1_executed,
            "tier_2_executed": self.tier_2_executed,
            "moonbag_active": self.moonbag_active,
            "trailing_stop_active": self.trailing_stop_active,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, mint: str, data: Mapping[str, Any]) -> Position:
        entry_mc = float(data.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = float(data.get("current_market_cap", entry_mc) or entry_mc)
        peak_mc = float(
            data.get("peak_market_cap", max(entry_mc, curr_mc))
            or max(entry_mc, curr_mc)
        )
        initial_tokens = int(
            data.get("initial_token_amount")
            or data.get("token_amount")
            or data.get("initial_units", 0)
            or (100_000_000 if bool(data.get("dry_run")) else 0)
        )
        remaining_tokens = int(
            data.get("remaining_token_amount")
            or data.get("token_amount")
            or data.get("remaining_units", initial_tokens)
            or initial_tokens
        )
        cost_sol = float(data.get("cost_sol") or data.get("entry_sol", 0.0) or 0.0)
        entry_sol = float(data.get("entry_sol") or data.get("cost_sol", 0.0) or 0.0)

        return cls(
            mint=str(mint),
            name=str(data.get("name") or mint),
            entry_market_cap=entry_mc,
            current_market_cap=curr_mc,
            peak_market_cap=peak_mc,
            initial_token_amount=initial_tokens,
            remaining_token_amount=remaining_tokens,
            cost_sol=cost_sol,
            entry_sol=entry_sol,
            buy_signature=data.get("buy_signature"),
            first_seen=float(data.get("first_seen") or time.time()),
            entry_reason=str(data.get("entry_reason") or "entry"),
            dry_run=bool(data.get("dry_run", False)),
            tier_1_executed=bool(data.get("tier_1_executed", False)),
            tier_2_executed=bool(data.get("tier_2_executed", False)),
            moonbag_active=bool(data.get("moonbag_active", False)),
            trailing_stop_active=bool(data.get("trailing_stop_active", False)),
            metadata=dict(data.get("metadata", {}) or {}),
        )


class PositionManager:
    """Manages active trading positions, exit evaluations, and persistence lifecycle."""

    def __init__(self, config: TradingBotConfig) -> None:
        self.config = config
        self._positions: dict[str, dict[str, Any]] = {}

    def __len__(self) -> int:
        return len(self._positions)

    def __contains__(self, mint: str) -> bool:
        return mint in self._positions

    def __getitem__(self, mint: str) -> dict[str, Any]:
        return self._positions[mint]

    def __setitem__(self, mint: str, value: dict[str, Any]) -> None:
        self._positions[mint] = value

    def __iter__(self) -> Iterator[str]:
        return iter(self._positions)

    def keys(self) -> Any:
        return self._positions.keys()

    def values(self) -> Any:
        return self._positions.values()

    def items(self) -> Any:
        return self._positions.items()

    def count(self) -> int:
        return len(self._positions)

    def has_position(self, mint: str) -> bool:
        return mint in self._positions

    def get_position(self, mint: str) -> dict[str, Any] | None:
        return self._positions.get(mint)

    def get_all_positions(self) -> dict[str, dict[str, Any]]:
        return self._positions

    def get_mints(self) -> list[str]:
        return list(self._positions.keys())

    def record_buy(
        self,
        mint: str,
        token_amount: int,
        cost_sol: float,
        entry_market_cap: float,
        name: str = "",
        buy_signature: str | None = None,
        reason: str = "entry",
        dry_run: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pos_dict: dict[str, Any] = {
            "name": name.strip() or mint,
            "entry_market_cap": float(entry_market_cap or 30.0),
            "current_market_cap": float(entry_market_cap or 30.0),
            "peak_market_cap": float(entry_market_cap or 30.0),
            "initial_token_amount": int(token_amount),
            "remaining_token_amount": int(token_amount),
            "token_amount": int(token_amount),
            "cost_sol": float(cost_sol),
            "entry_sol": float(cost_sol),
            "buy_signature": buy_signature,
            "first_seen": time.time(),
            "entry_reason": reason or "entry",
            "dry_run": bool(dry_run),
            "tier_1_executed": False,
            "tier_2_executed": False,
            "moonbag_active": False,
            "trailing_stop_active": False,
        }
        if metadata:
            pos_dict.update(metadata)
        self._positions[mint] = pos_dict
        return pos_dict

    def record_sell(
        self,
        mint: str,
        sold_tokens: int,
        proceeds_sol: float = 0.0,
        target_tier: int | None = None,
        is_partial: bool = False,
    ) -> tuple[bool, int]:
        """Records a token sell. Returns (is_fully_closed, remaining_tokens)."""
        if mint not in self._positions:
            return True, 0

        pos = self._positions[mint]
        current_remaining = int(
            pos.get("remaining_token_amount") or pos.get("token_amount") or 0
        )
        new_remaining = max(0, current_remaining - int(sold_tokens))
        pos["remaining_token_amount"] = new_remaining
        pos["token_amount"] = new_remaining

        if target_tier == 1:
            pos["tier_1_executed"] = True
        elif target_tier == 2:
            pos["tier_2_executed"] = True
            pos["moonbag_active"] = True

        if (
            not is_partial
            or new_remaining <= 0
            or (
                not self.config.dry_run
                and new_remaining <= self.config.min_sell_balance
            )
        ):
            self.remove_position(mint)
            return True, 0

        return False, new_remaining

    def update_price(
        self, mint: str, current_market_cap: float
    ) -> tuple[float, float, float]:
        """Updates current and peak market cap for an active position.

        Returns (entry_market_cap, current_market_cap, peak_market_cap).
        """
        if mint not in self._positions:
            return 0.0, current_market_cap, current_market_cap

        pos = self._positions[mint]
        mc = max(0.0, float(current_market_cap))
        pos["current_market_cap"] = mc

        entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
        if entry_mc <= 0:
            entry_mc = mc
            pos["entry_market_cap"] = entry_mc

        peak_mc = float(
            pos.get("peak_market_cap", max(entry_mc, mc)) or max(entry_mc, mc)
        )
        if mc > peak_mc:
            peak_mc = mc
        pos["peak_market_cap"] = peak_mc

        return entry_mc, mc, peak_mc

    def get_exit_state(self, mint: str) -> PositionExitState | None:
        if mint not in self._positions:
            return None
        return PositionExitState.from_dict(self._positions[mint])

    def evaluate_exit(
        self,
        mint: str,
        current_market_cap: float | None = None,
        token_balance: int | None = None,
    ) -> ExitDecision | None:
        """Evaluates exit conditions against current position state and configuration."""
        if mint not in self._positions:
            return None

        if current_market_cap is not None:
            self.update_price(mint, current_market_cap)

        pos = self._positions[mint]
        exit_state = PositionExitState.from_dict(pos)
        decision = evaluate_exit_strategy(
            self.config,
            exit_state,
            current_market_cap=current_market_cap,
            token_balance=token_balance,
        )

        pos["trailing_stop_active"] = exit_state.trailing_stop_active
        pos["tier_1_executed"] = exit_state.tier_1_executed
        pos["tier_2_executed"] = exit_state.tier_2_executed
        pos["moonbag_active"] = exit_state.moonbag_active

        return decision

    def calculate_unrealized_pnl(
        self, mint: str, current_market_cap: float | None = None
    ) -> float:
        if mint not in self._positions:
            return 0.0
        pos = self._positions[mint]
        entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
        curr_mc = (
            float(current_market_cap)
            if current_market_cap is not None
            else float(pos.get("current_market_cap", 0.0) or 0.0)
        )
        cost_sol = float(
            pos.get("cost_sol")
            or pos.get("entry_sol", self.config.buy_amount_sol)
            or self.config.buy_amount_sol
        )
        if entry_mc <= 0:
            return 0.0
        current_value = cost_sol * (curr_mc / entry_mc)
        return current_value - cost_sol

    def calculate_total_open_value(self) -> float:
        total = 0.0
        for pos in self._positions.values():
            entry_mc = float(pos.get("entry_market_cap", 0.0) or 0.0)
            curr_mc = float(pos.get("current_market_cap", 0.0) or 0.0)
            cost_sol = float(
                pos.get("cost_sol")
                or pos.get("entry_sol", self.config.buy_amount_sol)
                or self.config.buy_amount_sol
            )
            if entry_mc > 0 and curr_mc > 0:
                total += cost_sol * (curr_mc / entry_mc)
            else:
                total += cost_sol
        return total

    def remove_position(self, mint: str) -> dict[str, Any] | None:
        return self._positions.pop(mint, None)

    def clear(self) -> None:
        self._positions.clear()

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {mint: dict(pos) for mint, pos in self._positions.items()}

    def restore_from_dict(self, data: dict[str, Any]) -> None:
        restored_positions: dict[str, dict[str, Any]] = {}
        for mint, position in data.items():
            if not isinstance(position, dict):
                continue
            normalized = {
                key: value
                for key, value in dict(position).items()
                if key
                not in {"entry_market_cap", "current_market_cap", "peak_market_cap"}
            }
            entry_mc = float(position.get("entry_market_cap", 0.0) or 0.0)
            curr_mc = float(position.get("current_market_cap", 0.0) or 0.0)
            peak_mc = float(
                position.get("peak_market_cap", max(entry_mc, curr_mc))
                or max(entry_mc, curr_mc)
            )
            normalized["entry_market_cap"] = entry_mc
            normalized["current_market_cap"] = curr_mc
            normalized["peak_market_cap"] = peak_mc
            restored_positions[str(mint)] = normalized
        self._positions = restored_positions
