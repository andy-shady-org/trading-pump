"""Unit tests for ``sdk/pumpswap.py``: canonical pool PDA, pool and global-config
layouts, the sell quote and the ``sell`` instruction, pinned to mainnet accounts
of a graduated coin (BUG-123)."""

from __future__ import annotations

import base64
import dataclasses
import struct

import pytest
from solders.pubkey import Pubkey

from pumpfun_trading.sdk import pumpswap as ps
from pumpfun_trading.tests.support.payloads import (
    GRADUATED_BASE_VAULT_B64,
    GRADUATED_GLOBAL_CONFIG_ADDRESS,
    GRADUATED_GLOBAL_CONFIG_B64,
    GRADUATED_MINT,
    GRADUATED_POOL,
    GRADUATED_POOL_B64,
    GRADUATED_QUOTE_VAULT_B64,
)

TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# Accounts of the PumpSwap ``sell`` in mainnet transaction TKsTp2zn... selling
# the graduated coin above (from the same fixture). Index 5 is the seller's base
# token account, which that wallet did not hold at its ATA.
MAINNET_SELL_ACCOUNTS = [
    "B9WYSKaLDWnegupPNG1h99XiiokMUYj6k64Dbqv18qr8",
    "3nj6DtKAYLBun3vbWefYnhJXA4YZNgtS81PUcHPSLE4G",
    "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw",
    "DJGsptd7CEMEKrHdmVPastxKcPNSqGJT5K7HWcn5pump",
    "So11111111111111111111111111111111111111112",
    "nnRiVSSGCTgGGQbYbLNwNLgsvdRWpUppu2Wh7CAvU83",
    "8d8GETameoUafnPq4fFEXPxh9GQtt7FG46FWhFAWPRHj",
    "j6iUvMo6Z2yivpHmsME2nXrafjbhtbCJqdevsJstunV",
    "C3FQnUxE56fXfbTZTFLvddizyrQqXJsG7VRTvdSPk3uU",
    "FWsW1xNtWscwNmKv6wVsU1iTzRN6wmmk3MjxRP5tT7hz",
    "7xQYoUjUJF1Kg6WVczoTAkaNhn5syQYcbvjmFrhjWpx",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "11111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "GS4CU59F31iL7aR2Q8zVS8DRrcRnXX1yjQ66TqNVQnaR",
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "5iuB6dgptS5NAsZdRSMMMW93VLggz8b41Dff8yfV6uwt",
    "DvwaKr5uVYZUUzdmzEnXEBqvbJC6Fp6C7caDso4GhBA1",
    "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx",
    "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ",
    "2bo4oWgR4L67Lgghp7YQRUGvQGAa3mgnHMkK3GfjZRNK",
    "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD",
    "CASRL2zkwDnppxEFQ4LgdwgR9pdz5Q8R8nEMKVZ9QoLp",
]


def _pool() -> ps.PumpSwapPool:
    return ps.decode_pool(GRADUATED_POOL, base64.b64decode(GRADUATED_POOL_B64))


def _config() -> ps.PumpSwapGlobalConfig:
    return ps.decode_global_config(base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64))


@pytest.mark.regression("BUG-123")
def test_canonical_pool_is_derived_from_the_mint() -> None:
    assert str(ps.canonical_pool_address(GRADUATED_MINT)) == GRADUATED_POOL
    assert str(ps.global_config_address()) == GRADUATED_GLOBAL_CONFIG_ADDRESS


def test_decode_pool_reads_the_mainnet_layout() -> None:
    pool = _pool()
    assert pool.base_mint == GRADUATED_MINT
    assert pool.quote_mint == "So11111111111111111111111111111111111111112"
    assert pool.base_vault == "j6iUvMo6Z2yivpHmsME2nXrafjbhtbCJqdevsJstunV"
    assert pool.quote_vault == "C3FQnUxE56fXfbTZTFLvddizyrQqXJsG7VRTvdSPk3uU"
    assert pool.coin_creator == "AzAfVMVd7AdD4gZuvPTYa25K5z8Sk9hr7LAPz3wRo7Mf"
    assert pool.has_coin_creator
    assert not pool.is_mayhem_mode and not pool.is_cashback_coin
    assert pool.virtual_quote_reserves == 17_584_505_289


def test_decode_pool_defaults_fields_missing_from_older_layouts() -> None:
    raw = base64.b64decode(GRADUATED_POOL_B64)[: ps.POOL_MIN_LENGTH]
    pool = ps.decode_pool(GRADUATED_POOL, raw)
    assert not pool.has_coin_creator
    assert pool.virtual_quote_reserves == 0
    assert not pool.is_mayhem_mode and not pool.is_cashback_coin


def test_decode_rejects_short_accounts() -> None:
    with pytest.raises(ps.PumpSwapPoolUnavailableError):
        ps.decode_pool(GRADUATED_POOL, b"\x00" * 10)
    with pytest.raises(ps.PumpSwapPoolUnavailableError):
        ps.decode_global_config(b"\x00" * 10)
    with pytest.raises(ps.PumpSwapPoolUnavailableError):
        ps.token_account_amount(b"\x00" * 10)


def test_decode_global_config_reads_fees_and_recipients() -> None:
    config = _config()
    assert (config.lp_fee_bps, config.protocol_fee_bps) == (20, 5)
    assert config.coin_creator_fee_bps == 5
    assert config.total_fee_bps == 30
    assert (
        config.protocol_fee_recipient == "62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV"
    )
    assert (
        config.reserved_fee_recipient == "GesfTA3X2arioaHp8bbKdjG9vJtskViWACZoYvxp4twS"
    )
    assert (
        config.buyback_fee_recipient == "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD"
    )


def test_decode_global_config_without_recipients() -> None:
    raw = bytearray(base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64))
    truncated = bytes(raw[: ps.CONFIG_MIN_LENGTH])
    assert ps.decode_global_config(truncated).buyback_fee_recipient is None
    start = ps.CONFIG_PROTOCOL_RECIPIENTS_OFFSET
    raw[start : start + 32 * 8] = bytes(32 * 8)
    with pytest.raises(ps.PumpSwapPoolUnavailableError, match="fee recipient"):
        ps.decode_global_config(bytes(raw))


def test_vault_amounts_and_market_cap_on_the_curve_basis() -> None:
    base = ps.token_account_amount(base64.b64decode(GRADUATED_BASE_VAULT_B64))
    quote = ps.token_account_amount(base64.b64decode(GRADUATED_QUOTE_VAULT_B64))
    assert base == 193_377_869_697_216
    assert quote == 73_700_738_380
    quote_total = quote + _pool().virtual_quote_reserves
    mc = ps.pumpswap_market_cap_sol(base, quote_total)
    # (91.285 SOL / 193.38 M tokens) x 1e9 tokens
    assert mc == pytest.approx(472.06, rel=1e-3)
    assert ps.pumpswap_market_cap_sol(0, quote_total) == 0.0


def test_sell_quote_is_constant_product_net_of_fee_and_slippage() -> None:
    gross = (100 * 10) // (1_000 + 10)
    assert ps.pumpswap_sell_quote(10, 1_000, 100) == gross
    assert ps.pumpswap_sell_quote(10_000, 1_000_000, 1_000_000, fee_bps=30) == (
        (1_000_000 * 10_000 // 1_010_000) * 9_970 // 10_000
    )
    with_slip = ps.pumpswap_sell_quote(
        10_000, 1_000_000, 1_000_000, fee_bps=30, slippage_bps=500
    )
    assert with_slip == (
        ((1_000_000 * 10_000 // 1_010_000) * 9_970 // 10_000) * 9_500 // 10_000
    )
    assert ps.pumpswap_sell_quote(0, 1_000, 100) == 0
    assert ps.pumpswap_sell_quote(10, 0, 100) == 0


@pytest.mark.regression("BUG-123")
def test_sell_instruction_matches_a_mainnet_pumpswap_sell() -> None:
    config = dataclasses.replace(
        _config(),
        protocol_fee_recipient=MAINNET_SELL_ACCOUNTS[9],
        buyback_fee_recipient=MAINNET_SELL_ACCOUNTS[22],
    )
    user = Pubkey.from_string(MAINNET_SELL_ACCOUNTS[1])
    ix = ps.build_pumpswap_sell_instruction(
        pool=_pool(),
        config=config,
        user=user,
        base_token_program=TOKEN_2022,
        quote_token_program=TOKEN,
        user_quote_account=Pubkey.from_string(MAINNET_SELL_ACCOUNTS[6]),
        base_amount_in=123,
        min_quote_amount_out=45,
    )
    keys = [str(meta.pubkey) for meta in ix.accounts]
    assert len(keys) == len(MAINNET_SELL_ACCOUNTS)
    for index, (ours, theirs) in enumerate(zip(keys, MAINNET_SELL_ACCOUNTS)):
        if index != 5:
            assert ours == theirs, index
    assert str(ix.program_id) == ps.PUMP_AMM_PROGRAM_ID
    assert bytes(ix.data) == ps.PUMPSWAP_SELL_DISCRIMINATOR + struct.pack(
        "<QQ", 123, 45
    )
    assert ix.accounts[1].is_signer and ix.accounts[1].is_writable
    assert not ix.accounts[2].is_writable  # global_config


def test_sell_instruction_tail_for_mayhem_cashback_and_no_buyback() -> None:
    pool = dataclasses.replace(
        _pool(),
        is_mayhem_mode=True,
        is_cashback_coin=True,
        coin_creator=str(Pubkey.default()),
    )
    config = dataclasses.replace(_config(), buyback_fee_recipient=None)
    user = Pubkey.new_unique()
    ix = ps.build_pumpswap_sell_instruction(
        pool=pool,
        config=config,
        user=user,
        base_token_program=TOKEN,
        quote_token_program=TOKEN,
        user_quote_account=Pubkey.new_unique(),
        base_amount_in=1,
        min_quote_amount_out=1,
    )
    keys = [str(meta.pubkey) for meta in ix.accounts]
    # 21 IDL accounts + the cashback pair; no pool-v2, no buyback recipient.
    assert len(keys) == 23
    assert keys[9] == config.reserved_fee_recipient
    assert keys[22] == str(ps.amm_pda(b"user_volume_accumulator", bytes(user)))
