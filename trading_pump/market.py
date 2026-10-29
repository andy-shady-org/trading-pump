"""PumpSwap pool readings and where they come from.

A :class:`PoolReading` is one read of a graduated coin's canonical PumpSwap
pool: its two reserves at a moment. Everything the module prices (quotes,
paper fills, exit value) and everything the lane decides on is computed from
readings, so a capture of readings replays the same way.

A :class:`PoolSource` produces readings and the fee a swap would pay. The
live one, :class:`RpcPoolSource`, batch-reads the pools over RPC through the
SDK (FEAT-73's ``get_pumpswap_pool_states``) and the fee from the PumpSwap
fee accounts; ``trading_pump.replay`` has one that answers from a capture.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from solders.pubkey import Pubkey

from trading_pump.sdk.execution_types import PUMP_FEE_PROGRAM_ID
from trading_pump.sdk.fee_config import decode_fee_config, select_fee_tier
from trading_pump.sdk.pumpswap import (
    PUMP_AMM_PROGRAM_ID,
    PUMP_TOTAL_SUPPLY_TOKENS,
    decode_global_config,
    fee_config_address,
    global_config_address,
    pumpswap_sell_quote,
)

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_UNITS = 1_000_000  # Pump.fun mints have 6 decimals
BPS = 10_000
# Where a fee came from (recorded on every fill).
FEE_SOURCE_TIER = "fee_config_tier"
FEE_SOURCE_GLOBAL = "global_config"
FEE_SOURCE_FLOOR = "floor"
FEE_SOURCE_REPLAY = "replay"
# The fee accounts change rarely; read them again after this long.
FEE_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class PoolReading:
    """One read of a canonical PumpSwap pool (reserves in raw units).

    ``quote_reserve`` includes the pool's virtual quote reserve, as the
    program prices with it. A drained pool (either reserve 0) is a reading
    too: a rug is the result, not a gap.
    """

    mint: str
    at: float
    base_reserve: int
    quote_reserve: int
    pool: str | None = None

    @property
    def drained(self) -> bool:
        return self.base_reserve <= 0 or self.quote_reserve <= 0

    @property
    def price(self) -> float:
        """Spot price in SOL per whole token; 0 for a drained pool."""
        if self.drained:
            return 0.0
        return (self.quote_reserve / LAMPORTS_PER_SOL) / (
            self.base_reserve / TOKEN_UNITS
        )

    @property
    def market_cap_sol(self) -> float:
        """On the bonding-curve basis (price x 1B tokens), as captures record it."""
        return self.price * PUMP_TOTAL_SUPPLY_TOKENS

    @property
    def market_cap_lamports(self) -> int:
        return int(round(self.market_cap_sol * LAMPORTS_PER_SOL))

    @property
    def pool_sol(self) -> float:
        return max(0, self.quote_reserve) / LAMPORTS_PER_SOL

    @property
    def pool_tokens(self) -> float:
        return max(0, self.base_reserve) / TOKEN_UNITS

    def age(self, now: float) -> float:
        return max(0.0, now - self.at)

    def capture_row(self, *, source: str) -> dict[str, Any]:
        """The capture's ``curve_poll`` row (pumpfun-trading's shape, FEAT-73)."""
        return {
            "timestamp": self.at,
            "mint": self.mint,
            "event": "curve_poll",
            "source": source,
            "price": self.market_cap_sol / 1_000_000_000.0,
            "market_cap_sol": round(self.market_cap_sol, 6),
            "pool_sol": round(self.pool_sol, 9),
            "pool_tokens": round(self.pool_tokens, 6),
        }


@dataclass(frozen=True)
class SwapFee:
    """The fee a swap pays, in basis points, and where the number came from."""

    bps: int
    source: str


def buy_tokens_out(reading: PoolReading, lamports_in: int, fee_bps: int) -> int:
    """Raw tokens a buy of ``lamports_in`` (fee included) receives.

    PumpSwap charges its fee on the quote side; a buy that spends
    ``lamports_in`` in total swaps ``lamports_in / (1 + fee)`` through the
    constant-product curve.
    """
    if reading.drained or lamports_in <= 0:
        return 0
    swapped = (int(lamports_in) * BPS) // (BPS + max(0, int(fee_bps)))
    return (reading.base_reserve * swapped) // (reading.quote_reserve + swapped)


def sell_lamports_out(reading: PoolReading, tokens_in: int, fee_bps: int) -> int:
    """Lamports a sell of ``tokens_in`` raw tokens receives, after the fee."""
    if reading.drained or tokens_in <= 0:
        return 0
    return pumpswap_sell_quote(
        int(tokens_in),
        reading.base_reserve,
        reading.quote_reserve,
        fee_bps=int(fee_bps),
    )


def sell_lamports_gross(reading: PoolReading, tokens_in: int) -> int:
    """Lamports out of the curve before the fee."""
    return sell_lamports_out(reading, tokens_in, 0)


class PoolSource(Protocol):
    """Where readings and fees come from (RPC live, a capture in replay)."""

    async def read_pools(
        self, mints: Sequence[str], *, now: float
    ) -> tuple[dict[str, PoolReading], dict[str, str]]:
        """Readings for ``mints`` and, for the rest, why not (``missing``, ...).

        Raises when the source itself failed (RPC down).
        """

    async def swap_fee(self, reading: PoolReading) -> SwapFee:
        """The fee a swap at this reading pays."""


class PoolStateClient(Protocol):
    """The SDK calls :class:`RpcPoolSource` needs (``PumpFunExecutionClient``)."""

    async def get_pumpswap_pool_states(
        self,
        mints: Sequence[str],
        *,
        rejected: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, dict[str, Any]]: ...

    async def _get_accounts(
        self, addresses: list[str], *, timeout_seconds: float = 5.0
    ) -> list[dict[str, Any] | None]: ...


@dataclass
class RpcPoolSource:
    """Readings and fees over RPC through the SDK client."""

    client: PoolStateClient
    timeout_seconds: float = 10.0
    fee_bps_floor: int = 0
    clock: Callable[[], float] = time.monotonic
    _fees: tuple[float, Any, Any] | None = field(default=None, repr=False)
    stats: dict[str, int] = field(default_factory=dict)

    def _count(self, key: str) -> None:
        self.stats[key] = self.stats.get(key, 0) + 1

    async def read_pools(
        self, mints: Sequence[str], *, now: float
    ) -> tuple[dict[str, PoolReading], dict[str, str]]:
        rejected: dict[str, str] = {}
        states = await self.client.get_pumpswap_pool_states(
            list(mints), rejected=rejected, timeout_seconds=self.timeout_seconds
        )
        self._count("pool_reads")
        readings = {
            mint: PoolReading(
                mint=mint,
                at=now,
                base_reserve=int(state.get("base_reserve") or 0),
                quote_reserve=int(state.get("quote_reserve") or 0),
                pool=state.get("pool"),
            )
            for mint, state in states.items()
        }
        return readings, rejected

    async def _fee_accounts(self) -> tuple[Any, Any]:
        """(fee tiers or None, global config or None), cached for a while."""
        cached = self._fees
        moment = self.clock()
        if cached is not None and moment - cached[0] < FEE_TTL_SECONDS:
            return cached[1], cached[2]
        tiers_value, config_value = await self.client._get_accounts(
            [str(fee_config_address()), str(global_config_address())],
            timeout_seconds=self.timeout_seconds,
        )
        tiers = _decode(tiers_value, PUMP_FEE_PROGRAM_ID, decode_fee_config)
        config = _decode(config_value, PUMP_AMM_PROGRAM_ID, decode_global_config)
        if tiers is None and config is None and cached is not None:
            return cached[1], cached[2]
        self._fees = (moment, tiers, config)
        self._count("fee_reads")
        return tiers, config

    async def swap_fee(self, reading: PoolReading) -> SwapFee:
        tiers, config = await self._fee_accounts()
        fee: SwapFee | None = None
        if tiers is not None and tiers.fee_tiers:
            chosen = select_fee_tier(tiers.fee_tiers, reading.market_cap_lamports)
            total = chosen.lp_fee_bps + chosen.protocol_fee_bps + chosen.creator_fee_bps
            fee = SwapFee(int(total), FEE_SOURCE_TIER)
        elif config is not None:
            fee = SwapFee(int(config.total_fee_bps), FEE_SOURCE_GLOBAL)
        if fee is None:
            raise RuntimeError("PumpSwap fee accounts could not be read")
        if fee.bps < self.fee_bps_floor:
            return SwapFee(int(self.fee_bps_floor), FEE_SOURCE_FLOOR)
        return fee


def _decode(value: Mapping[str, Any] | None, owner: str, decoder: Any) -> Any:
    """Decode an account read, or ``None`` when absent, foreign or malformed."""
    if not value or str(value.get("owner") or "") != owner:
        return None
    try:
        raw = base64.b64decode((value.get("data") or [""])[0])
        return decoder(raw)
    except Exception:
        return None


def is_valid_mint(value: str) -> bool:
    try:
        Pubkey.from_string(str(value))
    except Exception:
        return False
    return True


__all__ = [
    "BPS",
    "FEE_SOURCE_FLOOR",
    "FEE_SOURCE_GLOBAL",
    "FEE_SOURCE_REPLAY",
    "FEE_SOURCE_TIER",
    "LAMPORTS_PER_SOL",
    "TOKEN_UNITS",
    "PoolReading",
    "PoolSource",
    "PoolStateClient",
    "RpcPoolSource",
    "SwapFee",
    "buy_tokens_out",
    "is_valid_mint",
    "sell_lamports_gross",
    "sell_lamports_out",
]
