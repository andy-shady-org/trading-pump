"""Pump.fun fee program ``FeeConfig``: market-cap fee tiers (BUG-138).

Since 2025-09-01 the bonding-curve fee is not a flat protocol fee. The Pump fee
program's ``fee_config`` PDA holds tiers keyed by the curve's market cap in
lamports; a trade pays the matching tier's ``protocol_fee_bps`` +
``creator_fee_bps`` (no LP fee on the bonding curve). Without a fee config the
program falls back to ``Global.fee_basis_points`` + ``creator_fee_basis_points``.

Layout from the official ``pump_fees`` IDL (``pump-fun/pump-public-docs``,
``idl/pump_fees.json``), Anchor / Borsh:

    discriminator   [143, 52, 146, 187, 219, 123, 76, 155]
    bump            u8
    admin           pubkey
    flat_fees       Fees
    fee_tiers       vec<FeeTier>
    stable_fee_tiers vec<FeeTier>
    exotic_flat_fees Fees

    FeeTier = { market_cap_lamports_threshold: u128, fees: Fees }
    Fees    = { lp_fee_bps: u64, protocol_fee_bps: u64, creator_fee_bps: u64 }

Tier selection follows the published ``calculateFeeTier``: below the first
threshold the first tier applies; otherwise the highest tier whose threshold
the market cap meets. The tests pin this to synthetic bytes built from the
IDL; check it against the real mainnet account before relying on it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from solders.pubkey import Pubkey

FEE_CONFIG_DISCRIMINATOR = bytes([143, 52, 146, 187, 219, 123, 76, 155])
# Sanity bound on a decoded fee: anything above 10% is a decoding error.
MAX_PLAUSIBLE_FEE_BPS = 1_000


@dataclass(frozen=True)
class Fees:
    lp_fee_bps: int
    protocol_fee_bps: int
    creator_fee_bps: int

    @property
    def bonding_curve_bps(self) -> int:
        """What a bonding-curve trade pays: protocol + creator, no LP fee."""
        return self.protocol_fee_bps + self.creator_fee_bps


@dataclass(frozen=True)
class FeeTier:
    market_cap_lamports_threshold: int
    fees: Fees


@dataclass(frozen=True)
class FeeConfig:
    bump: int
    admin: str
    flat_fees: Fees
    fee_tiers: tuple[FeeTier, ...]
    stable_fee_tiers: tuple[FeeTier, ...]
    exotic_flat_fees: Fees | None = None


class _Reader:
    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.offset = offset

    def take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("fee config account is too short")
        chunk = self.data[self.offset : end]
        self.offset = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int(struct.unpack("<I", self.take(4))[0])

    def u64(self) -> int:
        return int(struct.unpack("<Q", self.take(8))[0])

    def u128(self) -> int:
        return int.from_bytes(self.take(16), "little")

    def fees(self) -> Fees:
        return Fees(self.u64(), self.u64(), self.u64())

    def tiers(self) -> tuple[FeeTier, ...]:
        count = self.u32()
        if count > 64:
            raise ValueError(f"implausible fee tier count {count}")
        return tuple(FeeTier(self.u128(), self.fees()) for _ in range(count))


def decode_fee_config(data: bytes) -> FeeConfig:
    """Decode the raw ``fee_config`` account; raises ``ValueError`` if malformed."""
    if data[:8] != FEE_CONFIG_DISCRIMINATOR:
        raise ValueError("not a FeeConfig account (discriminator mismatch)")
    reader = _Reader(data, 8)
    bump = reader.u8()
    admin = str(Pubkey.from_bytes(reader.take(32)))
    flat_fees = reader.fees()
    fee_tiers = reader.tiers()
    stable_fee_tiers = reader.tiers()
    # Older, shorter accounts end before this field (``extend_fee_config``).
    exotic = reader.fees() if reader.offset + 24 <= len(data) else None
    config = FeeConfig(bump, admin, flat_fees, fee_tiers, stable_fee_tiers, exotic)
    for tier in config.fee_tiers:
        if tier.fees.bonding_curve_bps > MAX_PLAUSIBLE_FEE_BPS:
            raise ValueError(f"implausible fee tier {tier}")
    return config


def curve_market_cap_lamports(
    virtual_sol_lamports: int, virtual_token_raw: int, mint_supply_raw: int
) -> int:
    """``virtualSolReserves * mintSupply / virtualTokenReserves`` (lamports)."""
    if virtual_token_raw <= 0:
        raise ValueError("virtual token reserves must be positive")
    return int(virtual_sol_lamports) * int(mint_supply_raw) // int(virtual_token_raw)


def select_fee_tier(tiers: tuple[FeeTier, ...], market_cap_lamports: int) -> Fees:
    """The tier a curve at ``market_cap_lamports`` pays (``calculateFeeTier``)."""
    if not tiers:
        raise ValueError("no fee tiers")
    # The last tier whose threshold the market cap meets; below the first
    # threshold, the first tier.
    chosen = tiers[0].fees
    for tier in tiers:
        if market_cap_lamports >= tier.market_cap_lamports_threshold:
            chosen = tier.fees
    return chosen


def bonding_curve_fee_bps(
    config: FeeConfig,
    virtual_sol_lamports: int,
    virtual_token_raw: int,
    mint_supply_raw: int,
) -> int:
    """Total fee in bps a bonding-curve trade pays at these reserves."""
    market_cap = curve_market_cap_lamports(
        virtual_sol_lamports, virtual_token_raw, mint_supply_raw
    )
    return select_fee_tier(config.fee_tiers, market_cap).bonding_curve_bps


__all__ = [
    "FEE_CONFIG_DISCRIMINATOR",
    "FeeConfig",
    "FeeTier",
    "Fees",
    "bonding_curve_fee_bps",
    "curve_market_cap_lamports",
    "decode_fee_config",
    "select_fee_tier",
]
