"""Paper fills on the PumpSwap pool, and the live gate.

:class:`PaperExecutor` fills an order the way the pool would: it reads the
pool again at fill time (never a cached or default price), swaps through the
constant-product curve with the pool's fee, and books what a live trade
would pay on top (network fee, priority fee, Jito tip, token-account rent,
refunded on a full exit). It refuses wherever a live trade would fail: no
pool, a drained pool, an unreadable fee, a zero quote, a price beyond the
limit (pumpfun BUG-145/152: a paper fill must never succeed where a live one
could not).

Costs are split so every component the venue charges is visible in the audit
trail: ``swap_fee`` (the pool's LP, protocol and creator fee), ``fee`` (the
base network fee), ``priority_fee``, ``tip`` and ``rent``. ``Fill.notional``
is the SOL that went through the curve, before those costs.

:class:`LiveExecutor` refuses every order: live PumpSwap buys need a buy
builder checked against mainnet transactions first (FEAT-76 phase 3; the
sell builder exists since BUG-123 but has not landed a transaction yet).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from trading_core.module.base import (
    COST_SOURCE_MODELLED,
    ExecutionRefused,
    Fill,
    OrderRequest,
    Side,
    TradeCosts,
)

from trading_pump.config.settings import ExecutionSettings
from trading_pump.market import (
    BPS,
    LAMPORTS_PER_SOL,
    TOKEN_UNITS,
    PoolReading,
    PoolSource,
    SwapFee,
    buy_tokens_out,
    sell_lamports_gross,
    sell_lamports_out,
)
from trading_pump.sdk.costs import (
    BASE_FEE_LAMPORTS_PER_SIGNATURE,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
)

# OrderRequest.metadata key trading-core sets on a sell that closes the
# position (MODULE-GUIDE §2); the token account is closed and its rent
# refunded.
CLOSES_POSITION = "closes_position"
LIVE_REFUSAL = (
    "live PumpSwap trading is not built yet: the buy builder must be checked "
    "against mainnet transactions first (FEAT-76 phase 3)"
)


def _sol(lamports: int) -> float:
    return int(lamports) / LAMPORTS_PER_SOL


@dataclass
class Holdings:
    """Raw tokens the module believes it holds per mint (from its own fills)."""

    raw: dict[str, int] = field(default_factory=dict)

    def get(self, mint: str) -> int:
        return int(self.raw.get(mint, 0))

    def add(self, mint: str, amount: int) -> None:
        self.raw[mint] = self.get(mint) + int(amount)

    def remove(self, mint: str, amount: int) -> None:
        left = self.get(mint) - int(amount)
        if left > 0:
            self.raw[mint] = left
        else:
            self.raw.pop(mint, None)


@dataclass
class PaperExecutor:
    """Fills paper orders against a fresh pool read; see the module docstring."""

    source: PoolSource
    settings: ExecutionSettings
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], Awaitable[Any]] | None = None
    holdings: Holdings = field(default_factory=Holdings)
    fills: int = 0

    def _costs(self, swap_fee_lamports: int, rent_lamports: int) -> TradeCosts:
        priority = int(self.settings.priority_fee_lamports)
        tip = int(self.settings.jito_tip_lamports) if self.settings.use_jito else 0
        return TradeCosts(
            {
                "swap_fee": _sol(swap_fee_lamports),
                "fee": _sol(BASE_FEE_LAMPORTS_PER_SIGNATURE),
                "priority_fee": _sol(priority),
                "tip": _sol(tip),
                "rent": _sol(rent_lamports),
            },
            source=COST_SOURCE_MODELLED,
        )

    async def _read(self, mint: str) -> tuple[PoolReading, SwapFee]:
        moment = self.clock()
        try:
            readings, rejected = await self.source.read_pools([mint], now=moment)
        except Exception as exc:
            raise ExecutionRefused(f"pool read failed: {exc}") from exc
        reading = readings.get(mint)
        if reading is None:
            reason = rejected.get(mint, "missing")
            raise ExecutionRefused(f"no PumpSwap pool ({reason})")
        if reading.drained:
            raise ExecutionRefused("PumpSwap pool is drained")
        try:
            fee = await self.source.swap_fee(reading)
        except Exception as exc:
            raise ExecutionRefused(f"PumpSwap fee unknown: {exc}") from exc
        return reading, fee

    @staticmethod
    def _metadata(reading: PoolReading, fee: SwapFee, **extra: Any) -> dict[str, Any]:
        return {
            "pool": reading.pool,
            "fee_bps": fee.bps,
            "fee_source": fee.source,
            "base_reserve": reading.base_reserve,
            "quote_reserve": reading.quote_reserve,
            "market_cap_sol": round(reading.market_cap_sol, 6),
            "pool_sol": round(reading.pool_sol, 9),
            **extra,
        }

    async def execute(self, order: OrderRequest) -> Fill:
        if order.side is Side.BUY:
            return await self.buy(order)
        return await self.sell(order)

    async def buy(self, order: OrderRequest) -> Fill:
        if order.notional is None:
            raise ExecutionRefused("a PumpSwap buy is sized in SOL (notional)")
        delay = float(self.settings.paper_entry_delay_seconds)
        if delay > 0:
            await (self.sleep or asyncio.sleep)(delay)
        reading, fee = await self._read(order.instrument_id)
        lamports_in = int(round(float(order.notional) * LAMPORTS_PER_SOL))
        tokens = buy_tokens_out(reading, lamports_in, fee.bps)
        if tokens <= 0:
            raise ExecutionRefused("PumpSwap quote returned zero tokens")
        swapped = (lamports_in * BPS) // (BPS + fee.bps)
        size = tokens / TOKEN_UNITS
        all_in_price = _sol(lamports_in) / size
        if order.limit_price is not None and all_in_price > float(order.limit_price):
            raise ExecutionRefused(
                f"fill price {all_in_price:.3e} above the limit "
                f"{float(order.limit_price):.3e} SOL per token"
            )
        rent = (
            TOKEN_ACCOUNT_RENT_LAMPORTS
            if self.holdings.get(order.instrument_id) <= 0
            else 0
        )
        self.holdings.add(order.instrument_id, tokens)
        self.fills += 1
        return Fill(
            instrument_id=order.instrument_id,
            side=Side.BUY,
            size=size,
            price=_sol(swapped) / size,
            notional=_sol(swapped),
            costs=self._costs(lamports_in - swapped, rent),
            reference=f"paper-{self.fills}",
            timestamp=self.clock(),
            simulated=True,
            metadata=self._metadata(
                reading, fee, spot_price=reading.price, tokens_raw=tokens
            ),
        )

    async def sell(self, order: OrderRequest) -> Fill:
        reading, fee = await self._read(order.instrument_id)
        # trading-core sizes every sell in units (OrderRequest refuses others).
        tokens = int(round(float(order.size or 0.0) * TOKEN_UNITS))
        held = self.holdings.get(order.instrument_id)
        # Float sizes can miss the raw total by a unit: within one, it is all.
        closes = bool(order.metadata.get(CLOSES_POSITION)) or (
            held > 0 and tokens + 1 >= held
        )
        if closes and held > tokens:
            tokens = held  # leave no dust behind a closed position
        gross = sell_lamports_gross(reading, tokens)
        net = sell_lamports_out(reading, tokens, fee.bps)
        if tokens <= 0 or net <= 0:
            raise ExecutionRefused("PumpSwap quote returned zero SOL")
        size = tokens / TOKEN_UNITS
        self.holdings.remove(order.instrument_id, tokens)
        self.fills += 1
        return Fill(
            instrument_id=order.instrument_id,
            side=Side.SELL,
            size=size,
            price=_sol(gross) / size,
            notional=_sol(gross),
            costs=self._costs(
                gross - net, -TOKEN_ACCOUNT_RENT_LAMPORTS if closes else 0
            ),
            reference=f"paper-{self.fills}",
            timestamp=self.clock(),
            simulated=True,
            metadata=self._metadata(
                reading, fee, spot_price=reading.price, closes_position=closes
            ),
        )


class LiveExecutor:
    """Refuses every live order until the live gate (see the module docstring)."""

    async def execute(self, order: OrderRequest) -> Fill:
        raise ExecutionRefused(LIVE_REFUSAL)


__all__ = [
    "CLOSES_POSITION",
    "LIVE_REFUSAL",
    "Holdings",
    "LiveExecutor",
    "PaperExecutor",
]
