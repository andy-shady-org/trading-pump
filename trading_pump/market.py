"""PumpSwap pool readings and where they come from.

A :class:`PoolReading` is one read of a graduated coin's canonical PumpSwap
pool: its two reserves at a moment. Everything the module prices (quotes,
paper fills, exit value) and everything the lane decides on is computed from
readings, so a capture of readings replays the same way.

A :class:`PoolSource` produces readings and the fee a swap would pay. The
live one, :class:`RpcPoolSource`, batch-reads the pools over RPC through the
SDK (FEAT-73's ``get_pumpswap_pool_states``) and the fee from the PumpSwap
fee accounts, and the graduates' token names from their mint accounts
(``read_names``, for display only); ``trading_pump.replay`` has one that
answers from a capture.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from solders.pubkey import Pubkey

from trading_pump.names import TokenName, decode_token_name
from trading_pump.sdk.execution_types import (
    PUMP_FEE_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
)
from trading_pump.sdk.fee_config import decode_fee_config, select_fee_tier
from trading_pump.sdk.pumpswap import (
    PUMP_AMM_PROGRAM_ID,
    PUMP_TOTAL_SUPPLY_TOKENS,
    decode_global_config,
    fee_config_address,
    global_config_address,
    mint_supply,
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
# The fee accounts change rarely, and a mint's supply only falls (burns);
# read them again after this long.
FEE_TTL_SECONDS = 300.0
TOKEN_PROGRAMS = frozenset({TOKEN_PROGRAM_ID_STR, TOKEN_2022_PROGRAM_ID_STR})


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

    def fee_market_cap_lamports(self, mint_supply: int) -> int:
        """Market cap on the mint's real supply: what PumpSwap picks the fee
        tier by (BUG-162). Burns take the supply below the 1B tokens
        ``market_cap_sol`` assumes."""
        if self.drained:
            return 0
        return (self.quote_reserve * int(mint_supply)) // self.base_reserve

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

    async def read_names(self, mints: Sequence[str]) -> dict[str, TokenName]:
        """The token names it could read (display only; the rest are left out).

        Raises when the source itself failed.
        """


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

    async def get_signatures_for_address(
        self, address: str, *, limit: int, timeout_seconds: float = 5.0
    ) -> list[dict[str, Any]]: ...

    def remember_pumpswap_pool(
        self,
        mint: str,
        address: str,
        base_vault: str,
        quote_vault: str,
        *,
        sol_is_base: bool = False,
    ) -> None: ...


# SPL / Token-2022 mint: mint_authority COption (36), supply u64, decimals u8.
MINT_DECIMALS_OFFSET = 44


@dataclass(frozen=True)
class NewPoolInfo:
    """What one lookup says about a pool found by the new-pool feed (FEAT-80).

    ``created_at`` is the block time of the pool's oldest signature when its
    whole history fit in the lookup (``exact``); otherwise the oldest of the
    newest ``signatures``, an upper bound on its age. ``decimals`` is the
    base mint's (``None`` when unreadable): readings assume 6, as Pump.fun's
    mints have, so a price on another mint is off by a power of ten while
    its ratios are right.
    """

    created_at: float | None
    exact: bool
    signatures: int
    decimals: int | None


@dataclass
class RpcPoolSource:
    """Readings and fees over RPC through the SDK client."""

    client: PoolStateClient
    timeout_seconds: float = 10.0
    fee_bps_floor: int = 0
    clock: Callable[[], float] = time.monotonic
    _fees: tuple[float, Any, Any] | None = field(default=None, repr=False)
    _supplies: dict[str, tuple[float, int]] = field(default_factory=dict, repr=False)
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

    def register_pool(
        self,
        mint: str,
        address: str,
        base_vault: str,
        quote_vault: str,
        *,
        sol_is_base: bool = False,
    ) -> None:
        """Read ``mint`` from this pool (FEAT-80), not its canonical one."""
        self.client.remember_pumpswap_pool(
            mint, address, base_vault, quote_vault, sol_is_base=sol_is_base
        )

    async def inspect_new_pool(
        self, address: str, mint: str, *, limit: int
    ) -> NewPoolInfo:
        """When the pool was created (its signatures) and the mint's decimals,
        in two reads; a failed read raises."""
        signatures = await self.client.get_signatures_for_address(
            address, limit=limit, timeout_seconds=self.timeout_seconds
        )
        (mint_value,) = await self.client._get_accounts(
            [mint], timeout_seconds=self.timeout_seconds
        )
        times = [
            float(entry["blockTime"])
            for entry in signatures
            if isinstance(entry.get("blockTime"), int | float)
        ]
        return NewPoolInfo(
            created_at=min(times) if times else None,
            exact=len(signatures) < int(limit),
            signatures=len(signatures),
            decimals=_decode_mint_decimals(mint_value),
        )

    async def _fee_inputs(self, mint: str) -> tuple[Any, Any, int | None]:
        """(fee tiers or None, global config or None, the mint's supply or
        None), each cached for a while and read in one call when due."""
        moment = self.clock()
        fees_due = self._fees is None or moment - self._fees[0] >= FEE_TTL_SECONDS
        cached_supply = self._supplies.get(mint)
        supply_due = (
            cached_supply is None or moment - cached_supply[0] >= FEE_TTL_SECONDS
        )
        addresses = [str(fee_config_address()), str(global_config_address())]
        wanted = (addresses if fees_due else []) + ([mint] if supply_due else [])
        if wanted:
            values = await self.client._get_accounts(
                wanted, timeout_seconds=self.timeout_seconds
            )
            if fees_due:
                self._store_fees(moment, values[0], values[1])
            if supply_due:
                self._store_supply(mint, moment, values[-1])
        fees = self._fees
        assert fees is not None  # stored by the first read
        supply = self._supplies.get(mint)
        return fees[1], fees[2], supply[1] if supply is not None else None

    def _store_fees(self, moment: float, tiers_value: Any, config_value: Any) -> None:
        tiers = _decode(tiers_value, PUMP_FEE_PROGRAM_ID, decode_fee_config)
        config = _decode(config_value, PUMP_AMM_PROGRAM_ID, decode_global_config)
        if tiers is None and config is None and self._fees is not None:
            return  # keep the last good read; try again next time
        self._fees = (moment, tiers, config)
        self._count("fee_reads")

    def _store_supply(self, mint: str, moment: float, value: Any) -> None:
        supply = _decode_mint_supply(value)
        if supply is not None:
            self._supplies[mint] = (moment, supply)

    async def read_names(self, mints: Sequence[str]) -> dict[str, TokenName]:
        """Names from the mint accounts, in one ``getMultipleAccounts``."""
        if not mints:
            return {}
        values = await self.client._get_accounts(
            list(mints), timeout_seconds=self.timeout_seconds
        )
        self._count("name_reads")
        named = {
            mint: decode_token_name(value)
            for mint, value in zip(mints, values, strict=True)
        }
        return {mint: name for mint, name in named.items() if name is not None}

    async def swap_fee(self, reading: PoolReading) -> SwapFee:
        tiers, config, supply = await self._fee_inputs(reading.mint)
        fee = _fee_for(reading, tiers, config, supply)
        if fee.bps < self.fee_bps_floor:
            return SwapFee(int(self.fee_bps_floor), FEE_SOURCE_FLOOR)
        return fee


def _fee_for(
    reading: PoolReading, tiers: Any, config: Any, supply: int | None
) -> SwapFee:
    """The tier for the pool's market cap on the mint's supply, else the
    global config's flat fee; unknown is an error, never a guess."""
    if tiers is not None and tiers.fee_tiers:
        if supply is None:
            raise RuntimeError(
                f"supply of mint {reading.mint} could not be read: fee tier unknown"
            )
        chosen = select_fee_tier(
            tiers.fee_tiers, reading.fee_market_cap_lamports(supply)
        )
        total = chosen.lp_fee_bps + chosen.protocol_fee_bps + chosen.creator_fee_bps
        return SwapFee(int(total), FEE_SOURCE_TIER)
    if config is not None:
        return SwapFee(int(config.total_fee_bps), FEE_SOURCE_GLOBAL)
    raise RuntimeError("PumpSwap fee accounts could not be read")


def _decode_mint_supply(value: Mapping[str, Any] | None) -> int | None:
    """A mint account's supply, or ``None`` when absent, foreign or malformed."""
    if not value or str(value.get("owner") or "") not in TOKEN_PROGRAMS:
        return None
    try:
        supply = mint_supply(base64.b64decode((value.get("data") or [""])[0]))
    except Exception:
        return None
    return supply if supply > 0 else None


def _decode_mint_decimals(value: Mapping[str, Any] | None) -> int | None:
    """A mint account's decimals, or ``None`` when absent, foreign or short."""
    if not value or str(value.get("owner") or "") not in TOKEN_PROGRAMS:
        return None
    try:
        raw = base64.b64decode((value.get("data") or [""])[0])
    except Exception:
        return None
    return raw[MINT_DECIMALS_OFFSET] if len(raw) > MINT_DECIMALS_OFFSET else None


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
    "MINT_DECIMALS_OFFSET",
    "TOKEN_UNITS",
    "NewPoolInfo",
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
