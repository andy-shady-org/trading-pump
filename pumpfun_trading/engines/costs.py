"""Per-trade cost model for replay, so backtests report profit after costs.

Uses the same modelled costs as paper mode (``sdk/costs.py``, FEAT-49): Pump.fun's
protocol fee on each side, the network base fee plus priority fee, the Jito tip,
and the token-account rent paid on a buy and refunded when a full exit closes the
account (BUG-96).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pumpfun_trading.sdk.costs import (
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
    model_transaction_costs,
)
from pumpfun_trading.sdk.execution import PUMP_DEFAULT_FEE_BPS

DEFAULT_JITO_TIP_LAMPORTS = 100_000


@dataclass(frozen=True)
class ReplayCostModel:
    """Modelled costs of one replayed buy or sell."""

    protocol_fee_bps: int = PUMP_DEFAULT_FEE_BPS
    priority_fee_lamports: int = 0
    tip_lamports: int = DEFAULT_JITO_TIP_LAMPORTS
    rent_lamports: int = TOKEN_ACCOUNT_RENT_LAMPORTS
    close_token_account_on_full_exit: bool = True

    def buy_costs(self) -> TransactionCosts:
        """A fresh position pays the token-account rent."""
        return model_transaction_costs(
            priority_fee_lamports=self.priority_fee_lamports,
            tip_lamports=self.tip_lamports,
            rent_lamports=self.rent_lamports,
        )

    def sell_costs(self, *, full_exit: bool) -> TransactionCosts:
        """A full exit that closes the account gets the rent back."""
        refund = (
            -self.rent_lamports
            if full_exit and self.close_token_account_on_full_exit
            else 0
        )
        return model_transaction_costs(
            priority_fee_lamports=self.priority_fee_lamports,
            tip_lamports=self.tip_lamports,
            rent_lamports=refund,
        )

    def round_trip_fixed_costs_sol(self) -> float:
        """Fixed SOL of one buy plus one full exit: network and priority fees,
        tips, and rent that a closing sell does not refund. The Pump.fun fee is
        proportional to size, so it is not part of it."""
        return (
            self.buy_costs().total_cost_sol
            + self.sell_costs(full_exit=True).total_cost_sol
        )

    @classmethod
    def from_env(
        cls,
        *,
        close_token_account_on_full_exit: bool = True,
        priority_fee_lamports: int | None = None,
        tip_lamports: int | None = None,
    ) -> ReplayCostModel:
        """The tip the live bot would pay: ``PUMPFUN_JITO_TIP_LAMPORTS`` when
        ``PUMPFUN_USE_JITO`` is on (the live defaults), else no tip."""
        if tip_lamports is None:
            use_jito = os.getenv("PUMPFUN_USE_JITO", "true").strip().lower() not in {
                "false",
                "0",
                "no",
            }
            try:
                env_tip = int(
                    os.getenv(
                        "PUMPFUN_JITO_TIP_LAMPORTS", str(DEFAULT_JITO_TIP_LAMPORTS)
                    )
                )
            except ValueError:
                env_tip = DEFAULT_JITO_TIP_LAMPORTS
            tip_lamports = env_tip if use_jito else 0
        return cls(
            priority_fee_lamports=max(0, int(priority_fee_lamports or 0)),
            tip_lamports=max(0, int(tip_lamports)),
            close_token_account_on_full_exit=close_token_account_on_full_exit,
        )


__all__ = ["DEFAULT_JITO_TIP_LAMPORTS", "ReplayCostModel"]
