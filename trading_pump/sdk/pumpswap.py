"""PumpSwap AMM: where a Pump.fun coin trades once its bonding curve completes.

Pump.fun migrates a completed curve into a canonical PumpSwap pool, not into a
Raydium pool, so a position held through graduation can only exit here
(BUG-123). The pool is a PDA of the mint, so finding it needs no search.

Layouts follow the PumpSwap IDL (``pump_swap_idl.json``) and the Apache-2.0
reference in ``pumpfun-bonkfun-bot`` (``platforms/pumpfun/pumpswap_market.py``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from .execution_types import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    PUMP_FEE_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    WSOL_MINT_STR,
)

PUMP_AMM_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
# Anchor "global:sell": base_amount_in u64, min_quote_amount_out u64.
PUMPSWAP_SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])
PUMPSWAP_SELL_COMPUTE_UNITS = 200_000

# Pool, after the 8-byte discriminator: pool_bump u8, index u16, creator,
# base_mint, quote_mint, lp_mint, pool_base_token_account,
# pool_quote_token_account, lp_supply u64, coin_creator, is_mayhem_mode,
# is_cashback_coin, virtual_quote_reserves i128.
POOL_BASE_MINT_OFFSET = 43
POOL_QUOTE_MINT_OFFSET = 75
POOL_BASE_VAULT_OFFSET = 139
POOL_QUOTE_VAULT_OFFSET = 171
POOL_COIN_CREATOR_OFFSET = 211
POOL_MAYHEM_OFFSET = 243
POOL_CASHBACK_OFFSET = 244
POOL_VIRTUAL_QUOTE_OFFSET = 245
POOL_MIN_LENGTH = POOL_QUOTE_VAULT_OFFSET + 32

# GlobalConfig, after the discriminator: admin, lp/protocol fee bps (u64 each),
# disable_flags u8, protocol_fee_recipients[8], coin_creator_fee bps u64, two
# authorities, reserved_fee_recipient, mayhem flag, reserved_fee_recipients[7],
# cashback flag, buyback_fee_recipients[8].
CONFIG_LP_FEE_OFFSET = 40
CONFIG_PROTOCOL_FEE_OFFSET = 48
CONFIG_PROTOCOL_RECIPIENTS_OFFSET = 57
CONFIG_CREATOR_FEE_OFFSET = 313
CONFIG_RESERVED_RECIPIENT_OFFSET = 385
CONFIG_BUYBACK_RECIPIENTS_OFFSET = 643
CONFIG_MIN_LENGTH = CONFIG_RESERVED_RECIPIENT_OFFSET + 32

# SPL token account: mint (32), owner (32), amount (u64).
TOKEN_ACCOUNT_AMOUNT_OFFSET = 64
# SPL / Token-2022 mint: mint_authority COption<Pubkey> (36 bytes), then supply u64.
MINT_SUPPLY_OFFSET = 36
# Pump.fun mints 1e9 whole tokens with 6 decimals.
PUMP_TOTAL_SUPPLY_TOKENS = 1_000_000_000.0
_DEFAULT_PUBKEY = str(Pubkey.default())


class PumpSwapPoolUnavailableError(RuntimeError):
    """The canonical PumpSwap pool does not exist (yet) or failed to decode."""


def _amm_program() -> Pubkey:
    return Pubkey.from_string(PUMP_AMM_PROGRAM_ID)


def amm_pda(*seeds: bytes) -> Pubkey:
    """A PDA of the PumpSwap program."""
    return Pubkey.find_program_address(list(seeds), _amm_program())[0]


def global_config_address() -> Pubkey:
    return amm_pda(b"global_config")


def event_authority_address() -> Pubkey:
    return amm_pda(b"__event_authority")


def fee_config_address() -> Pubkey:
    return Pubkey.find_program_address(
        [b"fee_config", bytes(_amm_program())],
        Pubkey.from_string(PUMP_FEE_PROGRAM_ID),
    )[0]


def canonical_pool_address(mint: str, quote_mint: str = WSOL_MINT_STR) -> Pubkey:
    """The pool a Pump.fun migration creates: index 0, owned by the curve's pool
    authority.
    """
    base = Pubkey.from_string(mint)
    pool_authority = Pubkey.find_program_address(
        [b"pool-authority", bytes(base)], Pubkey.from_string(PUMP_PROGRAM_ID)
    )[0]
    return amm_pda(
        b"pool",
        struct.pack("<H", 0),
        bytes(pool_authority),
        bytes(base),
        bytes(Pubkey.from_string(quote_mint)),
    )


def _pubkey_at(data: bytes, offset: int) -> str:
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


@dataclass(frozen=True)
class PumpSwapPool:
    """A decoded canonical PumpSwap pool (addresses as base58 strings)."""

    address: str
    base_mint: str
    quote_mint: str
    base_vault: str
    quote_vault: str
    coin_creator: str
    is_mayhem_mode: bool = False
    is_cashback_coin: bool = False
    virtual_quote_reserves: int = 0

    @property
    def has_coin_creator(self) -> bool:
        return self.coin_creator != _DEFAULT_PUBKEY


def decode_pool(address: str, data: bytes) -> PumpSwapPool:
    """Decode a pool account. Fields added by later program versions default when
    absent.
    """
    if len(data) < POOL_MIN_LENGTH:
        raise PumpSwapPoolUnavailableError(
            f"PumpSwap pool {address} too short: {len(data)} bytes"
        )
    has = len(data)
    return PumpSwapPool(
        address=address,
        base_mint=_pubkey_at(data, POOL_BASE_MINT_OFFSET),
        quote_mint=_pubkey_at(data, POOL_QUOTE_MINT_OFFSET),
        base_vault=_pubkey_at(data, POOL_BASE_VAULT_OFFSET),
        quote_vault=_pubkey_at(data, POOL_QUOTE_VAULT_OFFSET),
        coin_creator=(
            _pubkey_at(data, POOL_COIN_CREATOR_OFFSET)
            if has >= POOL_COIN_CREATOR_OFFSET + 32
            else _DEFAULT_PUBKEY
        ),
        is_mayhem_mode=has > POOL_MAYHEM_OFFSET and bool(data[POOL_MAYHEM_OFFSET]),
        is_cashback_coin=has > POOL_CASHBACK_OFFSET
        and bool(data[POOL_CASHBACK_OFFSET]),
        virtual_quote_reserves=(
            int.from_bytes(
                data[POOL_VIRTUAL_QUOTE_OFFSET : POOL_VIRTUAL_QUOTE_OFFSET + 16],
                "little",
                signed=True,
            )
            if has >= POOL_VIRTUAL_QUOTE_OFFSET + 16
            else 0
        ),
    )


@dataclass(frozen=True)
class PumpSwapGlobalConfig:
    """Fee rates and fee recipients read from the PumpSwap ``global_config``."""

    lp_fee_bps: int
    protocol_fee_bps: int
    coin_creator_fee_bps: int
    protocol_fee_recipient: str
    reserved_fee_recipient: str
    buyback_fee_recipient: str | None = None

    @property
    def total_fee_bps(self) -> int:
        return self.lp_fee_bps + self.protocol_fee_bps + self.coin_creator_fee_bps


def _first_recipient(data: bytes, offset: int, count: int) -> str | None:
    for index in range(count):
        start = offset + 32 * index
        if len(data) < start + 32:
            return None
        key = _pubkey_at(data, start)
        if key != _DEFAULT_PUBKEY:
            return key
    return None


def decode_global_config(data: bytes) -> PumpSwapGlobalConfig:
    if len(data) < CONFIG_MIN_LENGTH:
        raise PumpSwapPoolUnavailableError(
            f"PumpSwap global_config too short: {len(data)} bytes"
        )
    protocol = _first_recipient(data, CONFIG_PROTOCOL_RECIPIENTS_OFFSET, 8)
    if protocol is None:
        raise PumpSwapPoolUnavailableError(
            "PumpSwap global_config has no fee recipient"
        )
    return PumpSwapGlobalConfig(
        lp_fee_bps=struct.unpack_from("<Q", data, CONFIG_LP_FEE_OFFSET)[0],
        protocol_fee_bps=struct.unpack_from("<Q", data, CONFIG_PROTOCOL_FEE_OFFSET)[0],
        coin_creator_fee_bps=struct.unpack_from("<Q", data, CONFIG_CREATOR_FEE_OFFSET)[
            0
        ],
        protocol_fee_recipient=protocol,
        reserved_fee_recipient=_pubkey_at(data, CONFIG_RESERVED_RECIPIENT_OFFSET),
        buyback_fee_recipient=_first_recipient(
            data, CONFIG_BUYBACK_RECIPIENTS_OFFSET, 8
        ),
    )


def token_account_amount(data: bytes) -> int:
    """The ``amount`` of an SPL / Token-2022 token account."""
    if len(data) < TOKEN_ACCOUNT_AMOUNT_OFFSET + 8:
        raise PumpSwapPoolUnavailableError("PumpSwap vault account too short")
    return int(struct.unpack_from("<Q", data, TOKEN_ACCOUNT_AMOUNT_OFFSET)[0])


def mint_supply(data: bytes) -> int:
    """The ``supply`` of an SPL / Token-2022 mint account (raw units).

    PumpSwap picks a pool's fee tier from the market cap on this supply, which
    burns lower below the 1B tokens a Pump.fun coin starts with (BUG-162).
    """
    if len(data) < MINT_SUPPLY_OFFSET + 8:
        raise PumpSwapPoolUnavailableError("mint account too short")
    return int(struct.unpack_from("<Q", data, MINT_SUPPLY_OFFSET)[0])


def pumpswap_sell_quote(
    base_amount_in: int,
    base_reserve: int,
    quote_reserve: int,
    *,
    fee_bps: int = 0,
    slippage_bps: int = 0,
) -> int:
    """Quote lamports out for selling ``base_amount_in`` raw tokens (constant product,
    fee on output).
    """
    if base_amount_in <= 0 or base_reserve <= 0 or quote_reserve <= 0:
        return 0
    gross = (quote_reserve * base_amount_in) // (base_reserve + base_amount_in)
    net = (gross * max(0, 10_000 - fee_bps)) // 10_000
    return (net * max(0, 10_000 - slippage_bps)) // 10_000


def pumpswap_market_cap_sol(base_reserve: int, quote_reserve: int) -> float:
    """Market cap in SOL, on the same basis as the bonding-curve market cap."""
    if base_reserve <= 0 or quote_reserve <= 0:
        return 0.0
    price = (quote_reserve / 1_000_000_000.0) / (base_reserve / 1_000_000.0)
    return price * PUMP_TOTAL_SUPPLY_TOKENS


def build_pumpswap_sell_instruction(
    *,
    pool: PumpSwapPool,
    config: PumpSwapGlobalConfig,
    user: Pubkey,
    base_token_program: Pubkey,
    quote_token_program: Pubkey,
    user_quote_account: Pubkey,
    base_amount_in: int,
    min_quote_amount_out: int,
) -> Instruction:
    """PumpSwap ``sell``: the IDL's 21 accounts, then the optional tail.

    The tail is the cashback pair on a cashback pool, ``pool-v2`` on a pool with a
    coin creator (every canonical pool has one) and the buyback recipient with
    its quote account last, which the program reads from the end of the list.
    """
    base_mint = Pubkey.from_string(pool.base_mint)
    quote_mint = Pubkey.from_string(pool.quote_mint)
    fee_recipient = Pubkey.from_string(
        config.reserved_fee_recipient
        if pool.is_mayhem_mode
        else config.protocol_fee_recipient
    )
    creator_vault = amm_pda(
        b"creator_vault", bytes(Pubkey.from_string(pool.coin_creator))
    )

    def quote_ata(owner: Pubkey) -> Pubkey:
        return get_associated_token_address(owner, quote_mint, quote_token_program)

    def meta(
        key: Pubkey, *, writable: bool = False, signer: bool = False
    ) -> AccountMeta:
        return AccountMeta(key, is_signer=signer, is_writable=writable)

    accounts = [
        meta(Pubkey.from_string(pool.address), writable=True),
        meta(user, writable=True, signer=True),
        meta(global_config_address()),
        meta(base_mint),
        meta(quote_mint),
        meta(
            get_associated_token_address(user, base_mint, base_token_program),
            writable=True,
        ),
        meta(user_quote_account, writable=True),
        meta(Pubkey.from_string(pool.base_vault), writable=True),
        meta(Pubkey.from_string(pool.quote_vault), writable=True),
        meta(fee_recipient),
        meta(quote_ata(fee_recipient), writable=True),
        meta(base_token_program),
        meta(quote_token_program),
        meta(Pubkey.from_string(SYSTEM_PROGRAM_ID)),
        meta(Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM_ID)),
        meta(event_authority_address()),
        meta(_amm_program()),
        meta(quote_ata(creator_vault), writable=True),
        meta(creator_vault),
        meta(fee_config_address()),
        meta(Pubkey.from_string(PUMP_FEE_PROGRAM_ID)),
    ]
    if pool.is_cashback_coin:
        accumulator = amm_pda(b"user_volume_accumulator", bytes(user))
        accounts += [
            meta(quote_ata(accumulator), writable=True),
            meta(accumulator, writable=True),
        ]
    if pool.has_coin_creator:
        accounts.append(meta(amm_pda(b"pool-v2", bytes(base_mint))))
    if config.buyback_fee_recipient:
        buyback = Pubkey.from_string(config.buyback_fee_recipient)
        accounts += [meta(buyback), meta(quote_ata(buyback), writable=True)]
    data = PUMPSWAP_SELL_DISCRIMINATOR + struct.pack(
        "<QQ", int(base_amount_in), int(min_quote_amount_out)
    )
    return Instruction(_amm_program(), data, accounts)
