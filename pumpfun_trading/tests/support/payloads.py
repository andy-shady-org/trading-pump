"""Byte builders for Pump.fun account and event payloads.

The layouts mirror the parsers in ``streams/geyser.py``
(``BondingCurveBinaryParser``, ``TradeInstructionBinaryParser``); the
round-trip tests in ``tests/unit/test_support.py`` fail if either side drifts.
Pubkeys must be valid base58, so a payload never carries padded garbage.
"""

from __future__ import annotations

import base64
import struct

from solders.pubkey import Pubkey

from pumpfun_trading.streams.geyser import (
    BUY_DISCRIMINATOR,
    COMPLETE_EVENT_DISCRIMINATOR,
    SELL_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
)
from pumpfun_trading.tests.support.constants import (
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    SAMPLE_MINT,
    TOKEN_TOTAL_SUPPLY,
    WSOL_MINT,
)

BONDING_CURVE_DISCRIMINATOR = bytes([23, 108, 143, 219, 112, 126, 121, 100])
"""Anchor account discriminator of ``BondingCurve``."""

SAMPLE_USER = str(Pubkey.default())
SAMPLE_CURVE = WSOL_MINT
SAMPLE_TIMESTAMP = 1_728_600_000


NON_STANDARD_CURVE_RESERVES: tuple[tuple[int, int], ...] = (
    (8_233_357_569_630, 10),  # CEb8KGYB...pump, decoded to 7,673 SOL market cap
    (105_860_003_350_032, 0),  # 8CucYF88..., decoded to 98,658 SOL market cap
)
"""``(virtual_sol, real_sol)`` lamports of mainnet curves that broke paper
pricing in the v0.2.0 Stage 0 pilot (BUG-104); both had the standard
``virtual_token_reserves`` of 1.073e15 and ``real_token_reserves`` of 7.931e14."""

STANDARD_CURVE_RESERVES: tuple[tuple[int, int], ...] = (
    (30_001_716_240, 1_716_240),  # 4vfQCJJ1..., traded once
    (30_000_016_102, 16_102),  # bbrxy2Ke...
)
"""``(virtual_sol, real_sol)`` lamports of standard mainnet curves (same pilot)."""


def _pubkey_bytes(value: str) -> bytes:
    return bytes(Pubkey.from_string(value))


def bonding_curve_bytes(
    *,
    virtual_token_reserves: int = INITIAL_VIRTUAL_TOKEN_RESERVES,
    virtual_sol_reserves: int = INITIAL_VIRTUAL_SOL_RESERVES,
    real_token_reserves: int = INITIAL_REAL_TOKEN_RESERVES,
    real_sol_reserves: int = 0,
    token_total_supply: int = TOKEN_TOTAL_SUPPLY,
    complete: bool = False,
    creator: str | None = None,
) -> bytes:
    """Return a ``BondingCurve`` account buffer (fresh curve by default).

    Bytes 0..8 discriminator, five little-endian u64 reserves, the
    ``complete`` bool at 48, and with ``creator`` the creator pubkey at
    49..81 (where ``sdk/execution.py`` reads it).
    """
    data = BONDING_CURVE_DISCRIMINATOR + struct.pack(
        "<QQQQQ?",
        virtual_token_reserves,
        virtual_sol_reserves,
        real_token_reserves,
        real_sol_reserves,
        token_total_supply,
        complete,
    )
    if creator is not None:
        data += _pubkey_bytes(creator)
    return data


def account_data_b64(raw: bytes) -> list[str]:
    """Return ``[base64, "base64"]``, the RPC ``getAccountInfo`` data field."""
    return [base64.b64encode(raw).decode("ascii"), "base64"]


def trade_event_bytes(
    *,
    mint: str = SAMPLE_MINT,
    sol_amount: int = 1_000_000_000,
    token_amount: int = 35_000_000_000_000,
    is_buy: bool = True,
    user: str = SAMPLE_USER,
    timestamp: int = SAMPLE_TIMESTAMP,
    virtual_sol_reserves: int = 31_000_000_000,
    virtual_token_reserves: int = 1_038_000_000_000_000,
    real_sol_reserves: int = 1_000_000_000,
    real_token_reserves: int = 758_100_000_000_000,
) -> bytes:
    """Return an Anchor ``TradeEvent`` (discriminator + 121-byte payload)."""
    return TRADE_EVENT_DISCRIMINATOR + struct.pack(
        "<32sQQ?32sqQQQQ",
        _pubkey_bytes(mint),
        sol_amount,
        token_amount,
        is_buy,
        _pubkey_bytes(user),
        timestamp,
        virtual_sol_reserves,
        virtual_token_reserves,
        real_sol_reserves,
        real_token_reserves,
    )


def complete_event_bytes(
    *,
    user: str = SAMPLE_USER,
    mint: str = SAMPLE_MINT,
    bonding_curve: str = SAMPLE_CURVE,
    timestamp: int = SAMPLE_TIMESTAMP,
) -> bytes:
    """Return an Anchor ``CompleteEvent`` (curve graduated)."""
    return COMPLETE_EVENT_DISCRIMINATOR + struct.pack(
        "<32s32s32sq",
        _pubkey_bytes(user),
        _pubkey_bytes(mint),
        _pubkey_bytes(bonding_curve),
        timestamp,
    )


def buy_instruction_bytes(amount: int, max_sol_cost: int) -> bytes:
    """Return Pump.fun ``buy`` instruction data (amount, max SOL cost)."""
    return BUY_DISCRIMINATOR + struct.pack("<QQ", amount, max_sol_cost)


def sell_instruction_bytes(amount: int, min_sol_output: int) -> bytes:
    """Return Pump.fun ``sell`` instruction data (amount, min SOL output)."""
    return SELL_DISCRIMINATOR + struct.pack("<QQ", amount, min_sol_output)
