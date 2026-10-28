"""Per-transaction cost accounting for net PnL (FEAT-49, Sprint 24B).

Costs are read from the confirmed transaction's ``meta`` (``getTransaction``) or,
in paper/dry-run mode, modelled from the client's fee and tip settings. All
amounts are lamports; ``rent_lamports`` is signed: positive when rent was paid
(token account created), negative when it was refunded (account closed, BUG-96).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

LAMPORTS_PER_SOL = 1_000_000_000
BASE_FEE_LAMPORTS_PER_SIGNATURE = 5_000
# Rent-exempt minimum of a Pump.fun token account, used only for paper/modelled
# costs (live trades read the real rent from the transaction). Mainnet rent was
# lowered: ``getMinimumBalanceForRentExemption`` returns 1,513,840 lamports for a
# 170-byte Token-2022 ATA and 1,488,440 for a 165-byte SPL ATA (checked 2026-10-16;
# it was 2,039,280 before). Pump.fun mints are Token-2022.
TOKEN_ACCOUNT_RENT_LAMPORTS = 1_513_840

COST_SOURCE_TRANSACTION_META = "transaction_meta"
COST_SOURCE_MODELLED = "modelled"

@dataclass(frozen=True)
class TransactionCosts:
    """Costs of one confirmed (or simulated) trade transaction."""

    signature: str | None = None
    network_fee_lamports: int = 0
    priority_fee_lamports: int = 0
    tip_lamports: int = 0
    rent_lamports: int = 0
    wallet_delta_lamports: int | None = None
    swap_lamports: int | None = None
    source: str = COST_SOURCE_MODELLED

    @property
    def total_cost_lamports(self) -> int:
        """Network fee (base + priority) plus tip plus net rent."""
        return self.network_fee_lamports + self.tip_lamports + self.rent_lamports

    @property
    def fee_sol(self) -> float:
        return self.network_fee_lamports / LAMPORTS_PER_SOL

    @property
    def priority_fee_sol(self) -> float:
        return self.priority_fee_lamports / LAMPORTS_PER_SOL

    @property
    def tip_sol(self) -> float:
        return self.tip_lamports / LAMPORTS_PER_SOL

    @property
    def rent_sol(self) -> float:
        return self.rent_lamports / LAMPORTS_PER_SOL

    @property
    def total_cost_sol(self) -> float:
        return self.total_cost_lamports / LAMPORTS_PER_SOL

    @property
    def swap_sol(self) -> float | None:
        if self.swap_lamports is None:
            return None
        return self.swap_lamports / LAMPORTS_PER_SOL

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "fee_sol": self.fee_sol,
                "priority_fee_sol": self.priority_fee_sol,
                "tip_sol": self.tip_sol,
                "rent_sol": self.rent_sol,
                "costs_sol": self.total_cost_sol,
                "swap_sol": self.swap_sol,
            }
        )
        return data


def model_transaction_costs(
    *,
    priority_fee_lamports: int = 0,
    tip_lamports: int = 0,
    rent_lamports: int = 0,
    signatures: int = 1,
    signature: str | None = None,
) -> TransactionCosts:
    """Modelled costs for paper/dry-run trades, so paper PnL is comparable to live."""
    priority = max(0, int(priority_fee_lamports))
    return TransactionCosts(
        signature=signature,
        network_fee_lamports=BASE_FEE_LAMPORTS_PER_SIGNATURE * max(1, signatures)
        + priority,
        priority_fee_lamports=priority,
        tip_lamports=max(0, int(tip_lamports)),
        rent_lamports=int(rent_lamports),
        source=COST_SOURCE_MODELLED,
    )


def _account_keys(tx: dict[str, Any]) -> list[str]:
    message = ((tx.get("transaction") or {}).get("message")) or {}
    keys: list[str] = []
    for key in message.get("accountKeys") or []:
        # jsonParsed encoding returns objects, json encoding returns strings.
        keys.append(str(key.get("pubkey")) if isinstance(key, dict) else str(key))
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(str(k) for k in loaded.get("writable") or [])
    keys.extend(str(k) for k in loaded.get("readonly") or [])
    return keys


def parse_transaction_costs(
    tx: dict[str, Any],
    *,
    wallet: str,
    is_buy: bool,
    token_accounts: Iterable[str] = (),
    tip_accounts: Iterable[str] = (),
    signature: str | None = None,
) -> TransactionCosts:
    """Splits a confirmed trade's wallet SOL delta into swap, fees, tip and rent.

    ``wallet_delta = ±swap - fee - tip - rent`` (``+`` for sells), so the swap
    amount is recovered exactly instead of being estimated from balances (BUG-48).
    Raises ``ValueError`` when the payload has no usable ``meta``.
    """
    meta = tx.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("transaction has no meta")
    if meta.get("err") is not None:
        raise ValueError(f"transaction failed on-chain: {meta.get('err')}")
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    keys = _account_keys(tx)
    if not keys or len(pre) != len(post) or len(pre) > len(keys):
        raise ValueError("transaction balances do not match its account keys")

    def delta(index: int) -> int:
        return int(post[index]) - int(pre[index])

    try:
        wallet_index = keys.index(wallet)
    except ValueError as exc:
        raise ValueError(f"wallet {wallet} not in transaction") from exc

    tips = set(tip_accounts)
    token_set = set(token_accounts)
    tip = sum(delta(i) for i, key in enumerate(keys[: len(pre)]) if key in tips)
    rent = sum(delta(i) for i, key in enumerate(keys[: len(pre)]) if key in token_set)
    fee = int(meta.get("fee") or 0)
    message = ((tx.get("transaction") or {}).get("message")) or {}
    header = message.get("header") or {}
    signatures = int(header.get("numRequiredSignatures") or 1)
    priority = max(0, fee - BASE_FEE_LAMPORTS_PER_SIGNATURE * signatures)

    wallet_delta = delta(wallet_index)
    signed_swap = wallet_delta + fee + max(0, tip) + rent
    swap = -signed_swap if is_buy else signed_swap
    return TransactionCosts(
        signature=signature,
        network_fee_lamports=fee,
        priority_fee_lamports=priority,
        tip_lamports=max(0, tip),
        rent_lamports=rent,
        wallet_delta_lamports=wallet_delta,
        swap_lamports=swap,
        source=COST_SOURCE_TRANSACTION_META,
    )
