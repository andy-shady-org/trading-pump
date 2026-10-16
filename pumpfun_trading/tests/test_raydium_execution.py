"""Unit tests for Raydium instruction serialization, pool decoders, and execution client."""

import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

from pumpfun_trading.sdk.execution import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    WSOL_MINT_STR,
    PumpFunExecutionClient,
)
from pumpfun_trading.sdk.raydium import (
    RAYDIUM_AMM_PROGRAM_ID,
    RAYDIUM_AUTHORITY_V4,
    SERUM_PROGRAM_ID_V3,
    WSOL_MINT,
    SWAP_BASE_IN_DISCRIMINATOR,
    RaydiumPoolKeys,
    build_raydium_swap_instruction,
    calculate_raydium_swap_out,
    parse_raydium_initialize2_accounts,
    parse_raydium_pool_from_tx,
)
from pumpfun_trading.strategies.presets import resolve_strategy_config


def make_test_pool_keys() -> RaydiumPoolKeys:
    return RaydiumPoolKeys(
        amm_id=str(Keypair().pubkey()),
        amm_authority=RAYDIUM_AUTHORITY_V4,
        amm_open_orders=str(Keypair().pubkey()),
        amm_target_orders=str(Keypair().pubkey()),
        pool_coin_token_account=str(Keypair().pubkey()),
        pool_pc_token_account=str(Keypair().pubkey()),
        serum_program_id=SERUM_PROGRAM_ID_V3,
        serum_market=str(Keypair().pubkey()),
        serum_bids=str(Keypair().pubkey()),
        serum_asks=str(Keypair().pubkey()),
        serum_event_queue=str(Keypair().pubkey()),
        serum_coin_vault=str(Keypair().pubkey()),
        serum_pc_vault=str(Keypair().pubkey()),
        serum_vault_signer=str(Keypair().pubkey()),
        coin_mint=str(Keypair().pubkey()),
        pc_mint=WSOL_MINT,
        lp_mint=str(Keypair().pubkey()),
    )


def test_calculate_raydium_swap_out():
    # 1 SOL in with 85 SOL pool reserve and 200M token reserve
    amount_in = 1_000_000_000  # 1 SOL
    reserve_in = 85_000_000_000  # 85 SOL
    reserve_out = 200_000_000_000_000  # 200M tokens

    expected_out, min_out = calculate_raydium_swap_out(
        amount_in=amount_in,
        reserve_in=reserve_in,
        reserve_out=reserve_out,
        slippage_bps=500,  # 5%
    )

    assert expected_out > 0
    assert min_out > 0
    assert min_out == int(expected_out * 0.95)

    # Edge cases
    assert calculate_raydium_swap_out(0, reserve_in, reserve_out) == (0, 0)
    assert calculate_raydium_swap_out(amount_in, 0, reserve_out) == (0, 0)


def test_build_raydium_swap_instruction():
    pool_keys = make_test_pool_keys()
    user_kp = Keypair()
    source_ata = Keypair().pubkey()
    dest_ata = Keypair().pubkey()

    amount_in = 50_000_000  # 0.05 SOL
    min_out = 1_000_000

    ix = build_raydium_swap_instruction(
        pool_keys=pool_keys,
        user_wallet=user_kp.pubkey(),
        user_source_token_account=source_ata,
        user_destination_token_account=dest_ata,
        amount_in_lamports=amount_in,
        min_amount_out=min_out,
    )

    assert str(ix.program_id) == RAYDIUM_AMM_PROGRAM_ID
    assert len(ix.accounts) == 18
    assert ix.accounts[0].is_writable is False  # Token Program
    assert str(ix.accounts[1].pubkey) == pool_keys.amm_id  # AMM ID
    assert ix.accounts[1].is_writable is True
    assert str(ix.accounts[17].pubkey) == str(user_kp.pubkey())  # User wallet
    assert ix.accounts[17].is_signer is True

    # Data check
    assert ix.data[0] == SWAP_BASE_IN_DISCRIMINATOR
    parsed_in = int.from_bytes(ix.data[1:9], "little")
    parsed_out = int.from_bytes(ix.data[9:17], "little")
    assert parsed_in == amount_in
    assert parsed_out == min_out


def test_parse_raydium_initialize2_accounts():
    accounts_21 = [
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # 0: token_program
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # 1: ata_program
        "11111111111111111111111111111111",  # 2: sys_program
        "SysvarRent111111111111111111111111111111111",  # 3: rent
        "AmmId11111111111111111111111111111111111111",  # 4: amm_id
        "AmmAuth111111111111111111111111111111111111",  # 5: amm_authority
        "AmmOpenOrders111111111111111111111111111111",  # 6: open_orders
        "LpMint1111111111111111111111111111111111111",  # 7: lp_mint
        "CoinMint11111111111111111111111111111111111",  # 8: coin_mint
        "PcMint1111111111111111111111111111111111111",  # 9: pc_mint
        "PoolCoin11111111111111111111111111111111111",  # 10: pool_coin
        "PoolPc1111111111111111111111111111111111111",  # 11: pool_pc
        "AmmTargetOrders1111111111111111111111111111",  # 12: target_orders
        "SerumProg1111111111111111111111111111111111",  # 13: serum_prog
        "SerumMarket11111111111111111111111111111111",  # 14: serum_market
        "SerumCoinVault11111111111111111111111111111",  # 15: serum_coin_vault
        "SerumPcVault1111111111111111111111111111111",  # 16: serum_pc_vault
        "SerumVaultSigner111111111111111111111111111",  # 17: serum_vault_signer
        "SerumEventQueue1111111111111111111111111111",  # 18: serum_event_queue
        "SerumBids1111111111111111111111111111111111",  # 19: serum_bids
        "SerumAsks1111111111111111111111111111111111",  # 20: serum_asks
    ]

    keys = parse_raydium_initialize2_accounts(accounts_21)
    assert keys is not None
    assert keys.amm_id == "AmmId11111111111111111111111111111111111111"
    assert keys.coin_mint == "CoinMint11111111111111111111111111111111111"
    assert keys.lp_mint == "LpMint1111111111111111111111111111111111111"
    assert keys.serum_bids == "SerumBids1111111111111111111111111111111111"

    # From tx dictionary
    parsed_tx = parse_raydium_pool_from_tx({"accounts": accounts_21})
    assert parsed_tx is not None
    assert parsed_tx.amm_id == keys.amm_id


@pytest.mark.asyncio
async def test_execution_client_raydium_buy_tx():
    kp = Keypair()
    b58_key = base58.b58encode(kp.to_bytes()).decode()
    client = PumpFunExecutionClient(
        b58_key,
        "http://127.0.0.1:8899",
        priority_fee_lamports=100_000,
        compute_unit_limit=300_000,
        jito_tip_lamports=50_000,
    )

    # Mock get_latest_blockhash and get_ata_exists
    async def mock_blockhash():
        return "4uQeVj5tqViQh7yWWGStvkEG1Zmhx6uasJtWCJziofM"

    async def mock_ata_exists(mint, owner=None):
        return False

    client.get_latest_blockhash = mock_blockhash  # type: ignore
    client.get_ata_exists = mock_ata_exists  # type: ignore

    async def mock_reserves(pool_keys):
        return 1_000_000_000_000, 100_000_000_000  # coin, pc (WSOL)

    async def mock_token_program(mint):
        return TOKEN_PROGRAM_ID

    client._raydium_reserves = mock_reserves  # type: ignore
    client.get_token_program_for_mint = mock_token_program  # type: ignore

    pool_keys = make_test_pool_keys()
    tx = await client.build_raydium_buy_tx(
        pool_keys=pool_keys,
        sol_amount=0.02,
        slippage_bps=500,
        min_amount_out=500_000,
    )

    assert tx is not None
    assert len(tx.signatures) == 1

    # BUG-51: WSOL create -> transfer -> SyncNative -> token ATA -> swap -> close
    instructions = await _raydium_instructions(client, "buy", pool_keys)
    programs = [str(ix.program_id) for ix in instructions]
    assert programs[0] == ASSOCIATED_TOKEN_PROGRAM_ID
    assert programs[1] == SYSTEM_PROGRAM_ID
    assert programs[2] == str(TOKEN_PROGRAM_ID)
    assert instructions[2].data == bytes([17])  # SyncNative
    assert programs[3] == ASSOCIATED_TOKEN_PROGRAM_ID
    assert instructions[-1].data == bytes([9])  # CloseAccount
    swap = instructions[-2]
    expected_out, expected_min = calculate_raydium_swap_out(
        20_000_000, 100_000_000_000, 1_000_000_000_000, slippage_bps=500
    )
    assert int.from_bytes(swap.data[9:17], "little") == expected_min > 500_000
    wsol_ata = get_associated_token_address(
        client.wallet, Pubkey.from_string(WSOL_MINT_STR), TOKEN_PROGRAM_ID
    )
    token_ata = get_associated_token_address(
        client.wallet, Pubkey.from_string(pool_keys.coin_mint), TOKEN_PROGRAM_ID
    )
    metas = [m.pubkey for m in swap.accounts]
    assert metas.index(wsol_ata) < metas.index(token_ata)

    # BUG-36: sell swaps token ATA -> WSOL ATA and unwraps
    sell_ixs = await _raydium_instructions(client, "sell", pool_keys)
    sell_swap = sell_ixs[-2]
    sell_metas = [m.pubkey for m in sell_swap.accounts]
    assert sell_metas.index(token_ata) < sell_metas.index(wsol_ata)
    assert sell_ixs[-1].data == bytes([9])
    assert all(str(ix.program_id) != SYSTEM_PROGRAM_ID for ix in sell_ixs)


async def _raydium_instructions(client, side, pool_keys):
    captured = {}

    async def capture(instructions, *, tip_lamports=None):
        captured["ixs"] = list(instructions)
        return None

    client._build_tx_with_instructions = capture  # type: ignore
    if side == "buy":
        await client.build_raydium_buy_tx(pool_keys, 0.02, slippage_bps=500)
    else:
        await client.build_raydium_sell_tx(pool_keys, 1_000_000, slippage_bps=500)
    return captured["ixs"]


def test_graduation_presets_and_config():
    cfg_cons = resolve_strategy_config("conservative")
    assert cfg_cons.enable_raydium_migration_sniping is True
    assert cfg_cons.raydium_buy_amount_sol == 0.01
    assert cfg_cons.raydium_slippage_bps == 300
    assert cfg_cons.raydium_pre_migration_sol_threshold == 82.0

    cfg_bal = resolve_strategy_config("balanced")
    assert cfg_bal.enable_raydium_migration_sniping is True
    assert cfg_bal.raydium_buy_amount_sol == 0.02
    assert cfg_bal.raydium_slippage_bps == 500
    assert cfg_bal.raydium_pre_migration_sol_threshold == 80.0

    cfg_agg = resolve_strategy_config("aggressive")
    assert cfg_agg.enable_raydium_migration_sniping is True
    assert cfg_agg.raydium_buy_amount_sol == 0.05
    assert cfg_agg.raydium_slippage_bps == 800
    assert cfg_agg.raydium_priority_fee_lamports == 200_000

    # Dict export
    d = cfg_bal.to_dict()
    assert d["enable_raydium_migration_sniping"] is True
    assert d["raydium_buy_amount_sol"] == 0.02
