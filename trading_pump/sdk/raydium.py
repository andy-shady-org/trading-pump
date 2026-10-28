"""Raydium AMM v4 SDK for pool parsing, pricing calculation, and swap instruction building."""

from __future__ import annotations

from typing import Any, Optional, Union

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID

from trading_pump.strategies.graduation import RaydiumPoolKeys

RAYDIUM_AMM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
SERUM_PROGRAM_ID_V3 = "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"
WSOL_MINT = "So11111111111111111111111111111111111111112"
RAYDIUM_AUTHORITY_V4 = "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"
SWAP_BASE_IN_DISCRIMINATOR = 9


def _to_pubkey(value: Union[str, Pubkey]) -> Pubkey:
    if isinstance(value, Pubkey):
        return value
    return Pubkey.from_string(value)


def calculate_raydium_swap_out(
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    slippage_bps: int = 500,
    fee_numerator: int = 25,
    fee_denominator: int = 10000,
) -> tuple[int, int]:
    """Calculate expected output tokens and minimum tokens out accounting for AMM fee and slippage.

    Formula (Constant Product with Fee):
    amount_in_with_fee = amount_in * (fee_denominator - fee_numerator)
    amount_out = (amount_in_with_fee * reserve_out) / (reserve_in * fee_denominator + amount_in_with_fee)
    min_amount_out = amount_out * (10000 - slippage_bps) / 10000
    """
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0, 0

    amount_in_with_fee = amount_in * (fee_denominator - fee_numerator)
    numerator = amount_in_with_fee * reserve_out
    denominator = (reserve_in * fee_denominator) + amount_in_with_fee
    if denominator == 0:
        return 0, 0

    expected_out = numerator // denominator
    slippage_factor = max(0, 10000 - slippage_bps)
    min_out = (expected_out * slippage_factor) // 10000
    return int(expected_out), int(min_out)


def build_raydium_swap_instruction(
    pool_keys: RaydiumPoolKeys,
    user_wallet: Union[str, Pubkey],
    user_source_token_account: Union[str, Pubkey],
    user_destination_token_account: Union[str, Pubkey],
    amount_in_lamports: int,
    min_amount_out: int = 1,
) -> Instruction:
    """Build Raydium AMM v4 SwapBaseIn instruction (instruction index 9).

    Raydium AMM v4 accounts layout:
    0.  TOKEN_PROGRAM_ID (readonly)
    1.  amm_id (writable)
    2.  amm_authority (readonly)
    3.  amm_open_orders (writable)
    4.  amm_target_orders (writable)
    5.  pool_coin_token_account (writable)
    6.  pool_pc_token_account (writable)
    7.  serum_program_id (readonly)
    8.  serum_market (writable)
    9.  serum_bids (writable)
    10. serum_asks (writable)
    11. serum_event_queue (writable)
    12. serum_coin_vault (writable)
    13. serum_pc_vault (writable)
    14. serum_vault_signer (readonly)
    15. user_source_token_account (writable)
    16. user_destination_token_account (writable)
    17. user_wallet (signer, writable)
    """
    wallet_pk = _to_pubkey(user_wallet)
    source_pk = _to_pubkey(user_source_token_account)
    dest_pk = _to_pubkey(user_destination_token_account)

    accounts = [
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.amm_id), is_signer=False, is_writable=True
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.amm_authority),
            is_signer=False,
            is_writable=False,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.amm_open_orders),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.amm_target_orders),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.pool_coin_token_account),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.pool_pc_token_account),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_program_id),
            is_signer=False,
            is_writable=False,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_market), is_signer=False, is_writable=True
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_bids), is_signer=False, is_writable=True
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_asks), is_signer=False, is_writable=True
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_event_queue),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_coin_vault),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_pc_vault),
            is_signer=False,
            is_writable=True,
        ),
        AccountMeta(
            pubkey=_to_pubkey(pool_keys.serum_vault_signer),
            is_signer=False,
            is_writable=False,
        ),
        AccountMeta(pubkey=source_pk, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dest_pk, is_signer=False, is_writable=True),
        AccountMeta(pubkey=wallet_pk, is_signer=True, is_writable=True),
    ]

    data = (
        bytes([SWAP_BASE_IN_DISCRIMINATOR])
        + int(amount_in_lamports).to_bytes(8, byteorder="little", signed=False)
        + int(max(0, min_amount_out)).to_bytes(8, byteorder="little", signed=False)
    )

    return Instruction(
        program_id=_to_pubkey(RAYDIUM_AMM_PROGRAM_ID),
        accounts=accounts,
        data=data,
    )


def parse_raydium_initialize2_accounts(
    accounts: list[str],
    coin_mint: str = "",
    pc_mint: str = "",
) -> Optional[RaydiumPoolKeys]:
    """Parse Raydium AMM Initialize2 instruction accounts list into RaydiumPoolKeys.

    Expected standard Initialize2 account layout (~21 accounts):
    0:  token_program
    1:  associated_token_program
    2:  system_program
    3:  rent
    4:  amm_id
    5:  amm_authority
    6:  amm_open_orders
    7:  lp_mint
    8:  coin_mint
    9:  pc_mint
    10: pool_coin_token_account
    11: pool_pc_token_account
    12: amm_target_orders
    13: serum_program_id
    14: serum_market
    15: serum_coin_vault
    16: serum_pc_vault
    17: serum_vault_signer
    18: serum_event_queue
    19: serum_bids
    20: serum_asks
    """
    if len(accounts) < 18:
        return None

    try:
        # Standard Raydium Initialize2 format
        if len(accounts) >= 21:
            return RaydiumPoolKeys(
                amm_id=accounts[4],
                amm_authority=accounts[5],
                amm_open_orders=accounts[6],
                amm_target_orders=accounts[12],
                pool_coin_token_account=accounts[10],
                pool_pc_token_account=accounts[11],
                serum_program_id=accounts[13],
                serum_market=accounts[14],
                serum_bids=accounts[19],
                serum_asks=accounts[20],
                serum_event_queue=accounts[18],
                serum_coin_vault=accounts[15],
                serum_pc_vault=accounts[16],
                serum_vault_signer=accounts[17],
                coin_mint=accounts[8] if not coin_mint else coin_mint,
                pc_mint=accounts[9] if not pc_mint else pc_mint,
                lp_mint=accounts[7],
            )
        # Direct Raydium layout fallback
        return RaydiumPoolKeys(
            amm_id=accounts[0],
            amm_authority=accounts[1],
            amm_open_orders=accounts[2],
            amm_target_orders=accounts[3],
            pool_coin_token_account=accounts[4],
            pool_pc_token_account=accounts[5],
            serum_program_id=accounts[6],
            serum_market=accounts[7],
            serum_bids=accounts[8],
            serum_asks=accounts[9],
            serum_event_queue=accounts[10],
            serum_coin_vault=accounts[11],
            serum_pc_vault=accounts[12],
            serum_vault_signer=accounts[13],
            coin_mint=(
                accounts[14] if len(accounts) > 14 and not coin_mint else coin_mint
            ),
            pc_mint=(
                pc_mint or (accounts[15] if len(accounts) > 15 else "") or WSOL_MINT
            ),
            lp_mint=accounts[16] if len(accounts) > 16 else "",
        )
    except Exception:
        return None


def parse_raydium_pool_from_tx(tx_dict: dict[str, Any]) -> Optional[RaydiumPoolKeys]:
    """Parse Raydium AMM pool creation event from a Solana transaction dictionary."""
    if not isinstance(tx_dict, dict):
        return None

    # Check for direct poolKeys in dictionary payload
    if "poolKeys" in tx_dict and isinstance(tx_dict["poolKeys"], dict):
        return RaydiumPoolKeys.from_dict(tx_dict["poolKeys"])

    # Check for instruction accounts list
    accounts = tx_dict.get("accounts") or tx_dict.get("accountKeys")
    if isinstance(accounts, list) and len(accounts) >= 17:
        coin_mint = str(tx_dict.get("mint") or tx_dict.get("coin_mint") or "")
        return parse_raydium_initialize2_accounts(
            [str(a) for a in accounts], coin_mint=coin_mint
        )

    return None


__all__ = [
    "RAYDIUM_AMM_PROGRAM_ID",
    "SERUM_PROGRAM_ID_V3",
    "WSOL_MINT",
    "RAYDIUM_AUTHORITY_V4",
    "SWAP_BASE_IN_DISCRIMINATOR",
    "RaydiumPoolKeys",
    "calculate_raydium_swap_out",
    "build_raydium_swap_instruction",
    "parse_raydium_initialize2_accounts",
    "parse_raydium_pool_from_tx",
]
