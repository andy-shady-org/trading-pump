"""Unit tests for ``sdk/pumpfun_execution.py``: bonding-curve decoding and reads, PDA
derivation, buy/sell instruction layouts and token-account close (BUG-96)."""

from __future__ import annotations

import base64
import json
import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import base58
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from trading_pump.sdk.curve import calculate_buy_tokens_out
from trading_pump.sdk.execution import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    BUY_DISCRIMINATOR,
    BUYBACK_FEE_RECIPIENT,
    EVENT_AUTHORITY,
    FEE_RECIPIENT,
    GET_MULTIPLE_ACCOUNTS_LIMIT,
    GLOBAL_STATE,
    MAYHEM_FEE_RECIPIENT,
    PUMP_FEE_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    SELL_DISCRIMINATOR,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    CurveStateUnavailableError,
    NonStandardCurveError,
    NotPumpFunCurveError,
    PumpFunExecutionClient,
    TokenBalanceUnavailableError,
)
from trading_pump.tests.support.constants import (
    SAMPLE_MINT,
    SAMPLE_PRIVATE_KEY,
    WSOL_MINT,
)
from trading_pump.tests.support.payloads import (
    NON_STANDARD_CURVE_RESERVES,
    STANDARD_CURVE_RESERVES,
    account_data_b64,
    bonding_curve_bytes,
)

# The real getTransaction cost reader is under test here (see tests/conftest.py).
USES_REAL_TRANSACTION_COSTS = True


def _client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


# --- BUG-96 token-account close and FEAT-49 transaction costs ---------------------


MINT = str(Pubkey.new_unique())


def _curve_state() -> dict[str, Any]:
    return {
        "creator": str(Pubkey.new_unique()),
        "virtual_sol_reserves": 30_000_000_000,
        "virtual_token_reserves": 1_073_000_000_000_000,
        "is_mayhem_mode": False,
    }


@pytest.mark.regression("BUG-96")
@pytest.mark.parametrize("program", [TOKEN_PROGRAM_ID_STR, TOKEN_2022_PROGRAM_ID_STR])
async def test_build_sell_tx_closes_token_account_on_request(program: str) -> None:
    """BUG-96: a full exit appends CloseAccount (rent back to the wallet)."""
    client = _client()
    mint = str(Pubkey.new_unique())
    curve = str(Pubkey.new_unique())
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(program)),
        ),
        patch.object(
            client, "_fetch_trade_curve_state", AsyncMock(return_value=_curve_state())
        ),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        await client.build_sell_tx(mint, curve, 1_000, close_token_account=True)
        closing = list(build.await_args_list[-1].args[0])
        await client.build_sell_tx(mint, curve, 1_000)
        plain = list(build.await_args_list[-1].args[0])

    assert len(closing) == len(plain) + 1
    close_ix = closing[-1]
    ata = get_associated_token_address(
        client.wallet, Pubkey.from_string(mint), Pubkey.from_string(program)
    )
    assert close_ix.program_id == Pubkey.from_string(program)
    assert close_ix.data == bytes([9])
    assert [m.pubkey for m in close_ix.accounts] == [ata, client.wallet, client.wallet]


async def test_sell_forwards_close_flag_to_builder() -> None:
    client = _client()
    client.use_jito = False
    build = AsyncMock(return_value="tx")
    with (
        patch.object(client, "build_sell_tx", build),
        patch.object(client, "send_transaction", AsyncMock(return_value="Sig")),
    ):
        assert await client.sell("Mint", "Curve", 5, close_token_account=True) == "Sig"
    assert build.await_args_list[-1].kwargs["close_token_account"] is True


async def test_fetch_trade_curve_state_rpc_failure_raises_curve_unavailable() -> None:
    client = _client()

    with patch.object(
        client.rpc_pool, "request", AsyncMock(side_effect=RuntimeError("timeout"))
    ):
        with pytest.raises(CurveStateUnavailableError, match="timeout"):
            await client._fetch_trade_curve_state(MINT)


# --- Pump.fun transaction builders ---------------------------------------------------


def _empty_curve() -> dict[str, Any]:
    return {**_curve_state(), "virtual_sol_reserves": 0, "virtual_token_reserves": 0}


@pytest.mark.regression("BUG-101")
@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_build_tx_zero_reserves_refuses_to_quote(side: str) -> None:
    """BUG-101: no quote against placeholder initial-curve reserves."""
    client = _client()
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(
            client, "_fetch_trade_curve_state", AsyncMock(return_value=_empty_curve())
        ),
        patch.object(client, "get_ata_exists", AsyncMock(return_value=True)),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        with pytest.raises(CurveStateUnavailableError, match="no reserves"):
            if side == "buy":
                await client.build_buy_tx(
                    MINT, str(Pubkey.new_unique()), 0.01, slippage_bps=100
                )
            else:
                await client.build_sell_tx(
                    MINT, str(Pubkey.new_unique()), 1_000_000, slippage_bps=100
                )

    build.assert_not_awaited()


@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_build_tx_zero_reserves_with_explicit_limits_still_builds(
    side: str,
) -> None:
    """With the caller's own token amount / min output no curve quote is needed."""
    client = _client()
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(
            client, "_fetch_trade_curve_state", AsyncMock(return_value=_empty_curve())
        ),
        patch.object(client, "get_ata_exists", AsyncMock(return_value=True)),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        if side == "buy":
            await client.build_buy_tx(
                MINT, str(Pubkey.new_unique()), 0.01, token_amount=123, slippage_bps=100
            )
        else:
            await client.build_sell_tx(
                MINT,
                str(Pubkey.new_unique()),
                1_000_000,
                min_sol_output=10_000,
                slippage_bps=100,
            )

    instructions = list(build.await_args.args[0]) if build.await_args else []
    data = bytes(instructions[0].data)
    if side == "buy":
        assert int.from_bytes(data[8:16], "little") == 123
    else:
        assert int.from_bytes(data[16:24], "little") == 9_900


async def test_build_buy_tx_ata_lookup_errors_add_idempotent_create() -> None:
    client = _client()
    build = AsyncMock(return_value="tx")
    ata_lookup = AsyncMock(side_effect=[TypeError("old sig"), RuntimeError("down")])

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(
            client, "_fetch_trade_curve_state", AsyncMock(return_value=_curve_state())
        ),
        patch.object(client, "get_ata_exists", ata_lookup),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        await client.build_buy_tx(MINT, str(Pubkey.new_unique()), 0.01)

    assert ata_lookup.await_count == 2
    instructions = list(build.await_args.args[0]) if build.await_args else []
    assert len(instructions) == 2
    ata = get_associated_token_address(
        client.wallet,
        Pubkey.from_string(MINT),
        Pubkey.from_string(TOKEN_PROGRAM_ID_STR),
    )
    assert ata in [m.pubkey for m in instructions[0].accounts]


async def test_build_sell_tx_negative_min_output_raises() -> None:
    client = _client()

    with pytest.raises(ValueError, match="cannot be negative"):
        await client.build_sell_tx(
            MINT, str(Pubkey.new_unique()), 10, min_sol_output=-1
        )


@pytest.fixture
def client():
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        __import__("base58").b58encode(keypair.to_bytes()).decode(),
        "https://example.com",
    )


def test_get_bonding_curve_pda_format(client):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, associated = client.get_bonding_curve_pda(mint)
    assert isinstance(curve, str)
    assert isinstance(associated, str)
    assert len(curve) > 20
    assert len(associated) > 20


def test_build_buy_instruction_has_expected_prefix(client):
    ix = client.build_buy_instruction(
        "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9",
        "9xNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9",
        token_amount=123,
        max_sol_cost=456,
    )
    assert len(ix.data) > 8
    assert ix.data[:8] == b"\x66\x06\x3d\x12\x01\xda\xeb\xea"


def test_build_sell_instruction_has_expected_prefix(client):
    ix = client.build_sell_instruction(
        "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9",
        "9xNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9",
        token_amount=123,
        min_sol_output=456,
    )
    assert len(ix.data) > 8
    assert ix.data[:8] == b"\x33\xe6\x85\xa4\x01\x7f\x83\xad"


def test_sdk_validation_helpers(client):
    mint = "3JfNw9xJUP9VYdB4KJdQ69yX4dE3Ws5YQm1Yw7Gv2fM9"
    curve, associated = client.get_bonding_curve_pda(mint)
    assert client.is_valid_pubkey(curve)
    assert client.is_valid_pubkey(associated)
    assert client.is_valid_mint(mint)


@pytest.mark.regression("BUG-01", "BUG-03")
def test_bonding_curve_data_decoding_and_sell_calculation():
    # 8 discriminator bytes + 8 u64 virtual token + 8 u64 virtual sol + 8 u64 real token
    # + 8 u64 real sol + 8 u64 supply + 1 bool complete
    raw = (
        b"\x17\xb7\xf8\x37\x60\xd8\xac\x60"
        + (1_073_000_000_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (793_100_000_000_000).to_bytes(8, "little")
        + (0).to_bytes(8, "little")
        + (1_000_000_000_000_000).to_bytes(8, "little")
        + bytes([0])
    )
    decoded = PumpFunExecutionClient.decode_bonding_curve_data(raw)
    assert decoded["virtual_token_reserves"] == 1_073_000_000_000_000
    assert decoded["virtual_sol_reserves"] == 30_000_000_000
    assert decoded["complete"] is False
    assert decoded["price_sol"] > 0
    assert decoded["market_cap_sol"] > 0

    with pytest.raises(ValueError):
        PumpFunExecutionClient.decode_bonding_curve_data(b"too_short")

    sol_out = PumpFunExecutionClient.calculate_sell_sol_output(
        token_amount=1_000_000_000,
        virtual_token_reserves=1_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        slippage_bps=500,
    )
    assert sol_out > 0


SAMPLE_BLOCKHASH = str(Hash.default())


async def test_execution_client_account_and_balance_queries():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
    )
    # ATA derivation resolves the mint's token program over the RPC pool;
    # stub it so the test never reaches mainnet.
    client.get_token_program_for_mint = AsyncMock(
        return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)
    )

    # get_wallet_pubkey
    pubkey = client.get_wallet_pubkey()
    assert isinstance(pubkey, str)
    assert client.is_valid_pubkey(pubkey)
    assert not client.is_valid_pubkey("invalid-pubkey")
    assert client.is_valid_mint(SAMPLE_MINT)
    assert not client.is_valid_mint("short")

    # _u64
    assert client._u64(100) == (100).to_bytes(8, byteorder="little")
    with pytest.raises(ValueError):
        client._u64(-1)

    # get_balance_sol
    client._request_rpc_json = AsyncMock(
        return_value={"result": {"value": 2_500_000_000}}
    )
    balance = await client.get_balance_sol()
    assert balance == 2.5

    # get_ata_address
    ata = await client.get_ata_address(SAMPLE_MINT)
    assert isinstance(ata, str)
    ata_custom = await client.get_ata_address(SAMPLE_MINT, owner=str(client.wallet))
    assert ata == ata_custom

    # get_bonding_curve_state
    dummy_bytes = (
        b"\x17\xb7\xf8\x37\x60\xcb\x17\xe1"  # discriminator (8)
        + struct.pack("<Q", 1_000_000_000_000_000)  # v_token (8)
        + struct.pack("<Q", 30_000_000_000)  # v_sol (8)
        + struct.pack("<Q", 793_100_000_000_000)  # r_token (8)
        + struct.pack("<Q", 0)  # r_sol (8)
        + struct.pack("<Q", 1_000_000_000_000_000)  # supply (8)
        + b"\x00"  # complete (1)
    )
    b64_data = base64.b64encode(dummy_bytes).decode("ascii")

    client._request_rpc_json = AsyncMock(
        return_value={"result": {"value": {"data": [b64_data, "base64"]}}}
    )
    state = await client.get_bonding_curve_state(SAMPLE_MINT)
    assert state["virtual_sol_reserves"] == 30_000_000_000
    assert state["complete"] is False

    # bonding curve account not found
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    with pytest.raises(RuntimeError):
        await client.get_bonding_curve_state(SAMPLE_MINT)


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_execution_client_tx_builders():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        compute_unit_limit=200_000,
        compute_unit_price_micro_lamports=50_000,
        jito_tip_lamports=10_000,
    )

    client.get_latest_blockhash = AsyncMock(return_value=SAMPLE_BLOCKHASH)
    client.get_ata_exists = AsyncMock(return_value=False)

    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)

    # build_buy_tx
    buy_tx = await client.build_buy_tx(
        mint=SAMPLE_MINT,
        bonding_curve=pda,
        sol_amount=0.1,
    )
    assert buy_tx is not None

    # build_buy_tx with explicit token_amount vs auto-derived token_amount
    buy_tx_explicit = await client.build_buy_tx(
        mint=SAMPLE_MINT,
        bonding_curve=pda,
        sol_amount=0.005,
        token_amount=500_000,
    )
    assert buy_tx_explicit is not None

    # build_sell_tx
    sell_tx = await client.build_sell_tx(
        mint=SAMPLE_MINT,
        bonding_curve=pda,
        token_amount=1_000_000,
        min_sol_output=0.05,
    )
    assert sell_tx is not None

    # build_sell_tx with negative min_sol_output
    with pytest.raises(ValueError):
        await client.build_sell_tx(
            mint=SAMPLE_MINT,
            bonding_curve=pda,
            token_amount=1_000_000,
            min_sol_output=-1.0,
        )


async def test_execution_client_v2_instructions_and_creator():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
    )
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    creator_addr = "11111111111111111111111111111111"

    # build_buy_instruction_v2
    buy_ix = client.build_buy_instruction_v2(
        mint=SAMPLE_MINT,
        bonding_curve=pda,
        token_amount=1_000_000,
        max_sol_cost=100_000,
        creator=creator_addr,
        base_token_program="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    )
    assert buy_ix is not None
    assert len(buy_ix.accounts) == 18
    assert buy_ix.data[:8] == bytes([102, 6, 61, 18, 1, 218, 235, 234])

    # build_sell_instruction_v2
    sell_ix = client.build_sell_instruction_v2(
        mint=SAMPLE_MINT,
        bonding_curve=pda,
        token_amount=1_000_000,
        min_sol_output=100_000,
        creator=creator_addr,
        base_token_program="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    )
    assert sell_ix is not None
    assert len(sell_ix.accounts) == 16
    assert sell_ix.data[:8] == bytes([51, 230, 133, 164, 1, 127, 131, 173])

    # decode_bonding_curve_data with creator
    raw_data = (
        b"\x00" * 8
        + (100_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (100_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (1_000_000_000).to_bytes(8, "little")
        + b"\x00"
        + b"\x01" * 32
    )
    decoded = client.decode_bonding_curve_data(raw_data)
    assert decoded["creator"] is not None

    # get_token_program_for_mint
    client.rpc_pool.request = AsyncMock(
        return_value={
            "result": {
                "value": {"owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}
            }
        }
    )
    token_prog = await client.get_token_program_for_mint(SAMPLE_MINT)
    assert str(token_prog) == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

    # get_token_balance
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    {
                        "account": {
                            "data": {
                                "parsed": {"info": {"tokenAmount": {"amount": "777"}}}
                            }
                        }
                    }
                ]
            }
        }
    )
    bal = await client.get_token_balance(SAMPLE_MINT)
    assert bal == 777


MINT_LAYOUT = "6SdFRZBMcgFtJ8cUgrohtwJVg2CALT8W1bAmoyBnpump"


CREATOR = "C7bbBs42K6ktWUjwUcxSGvXAVUqeaEJ2y5PRHFzcPqWe"


FEE_CONFIG = "8Wf5TiAheLUqBrKXeYg2JtAFFMWtKdG2BSFgqUcPVwTt"


GLOBAL_VOLUME_ACCUMULATOR = "Hq2wp8uJ9jCPsYgNHex8RtqdvMPfVGoYwjvF1ATiwn2Y"


@pytest.fixture
def client_layout() -> PumpFunExecutionClient:
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        base58.b58encode(keypair.to_bytes()).decode(),
        "https://mock-rpc.solana.com",
    )


def _pda(seeds: list[bytes]) -> Pubkey:
    return Pubkey.find_program_address(seeds, Pubkey.from_string(PUMP_PROGRAM_ID))[0]


@pytest.mark.regression("BUG-34")
def test_buy_instruction_matches_mainnet_layout(client_layout: PumpFunExecutionClient):
    mint = Pubkey.from_string(MINT_LAYOUT)
    token_prog = Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)
    curve, _ = client_layout.get_bonding_curve_pda(MINT_LAYOUT)
    curve_pk = Pubkey.from_string(curve)

    ix = client_layout.build_buy_instruction(
        MINT_LAYOUT, curve, 1_000, 2_000, creator=CREATOR, base_token_program=token_prog
    )

    assert str(ix.program_id) == PUMP_PROGRAM_ID
    assert ix.data[:8] == BUY_DISCRIMINATOR
    assert int.from_bytes(ix.data[8:16], "little") == 1_000
    assert int.from_bytes(ix.data[16:24], "little") == 2_000

    expected = [
        (GLOBAL_STATE, False, False),
        (FEE_RECIPIENT, False, True),
        (MINT_LAYOUT, False, False),
        (curve, False, True),
        (str(get_associated_token_address(curve_pk, mint, token_prog)), False, True),
        (
            str(get_associated_token_address(client_layout.wallet, mint, token_prog)),
            False,
            True,
        ),
        (str(client_layout.wallet), True, True),
        (SYSTEM_PROGRAM_ID, False, False),
        (TOKEN_2022_PROGRAM_ID_STR, False, False),
        (
            str(_pda([b"creator-vault", bytes(Pubkey.from_string(CREATOR))])),
            False,
            True,
        ),
        (EVENT_AUTHORITY, False, False),
        (PUMP_PROGRAM_ID, False, False),
        (GLOBAL_VOLUME_ACCUMULATOR, False, False),
        (
            str(_pda([b"user_volume_accumulator", bytes(client_layout.wallet)])),
            False,
            True,
        ),
        (FEE_CONFIG, False, False),
        (PUMP_FEE_PROGRAM_ID, False, False),
        (str(_pda([b"bonding-curve-v2", bytes(mint)])), False, False),
        (BUYBACK_FEE_RECIPIENT, False, True),
    ]
    actual = [(str(m.pubkey), m.is_signer, m.is_writable) for m in ix.accounts]
    assert actual == expected


@pytest.mark.regression("BUG-34")
def test_sell_instruction_matches_mainnet_layout(client_layout: PumpFunExecutionClient):
    mint = Pubkey.from_string(MINT_LAYOUT)
    token_prog = Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)
    curve, _ = client_layout.get_bonding_curve_pda(MINT_LAYOUT)

    ix = client_layout.build_sell_instruction(
        MINT_LAYOUT, curve, 5_000, 10, creator=CREATOR, base_token_program=token_prog
    )

    assert ix.data[:8] == SELL_DISCRIMINATOR
    accounts = [(str(m.pubkey), m.is_writable) for m in ix.accounts]
    assert len(accounts) == 16
    assert accounts[6] == (str(client_layout.wallet), True)
    assert accounts[8] == (
        str(_pda([b"creator-vault", bytes(Pubkey.from_string(CREATOR))])),
        True,
    )
    assert accounts[9] == (TOKEN_2022_PROGRAM_ID_STR, False)
    assert accounts[12] == (FEE_CONFIG, False)
    assert accounts[14] == (str(_pda([b"bonding-curve-v2", bytes(mint)])), False)
    assert accounts[15] == (BUYBACK_FEE_RECIPIENT, True)


def test_mayhem_mode_curves_use_reserved_fee_recipient(
    client_layout: PumpFunExecutionClient,
):
    curve, _ = client_layout.get_bonding_curve_pda(MINT_LAYOUT)

    buy_ix = client_layout.build_buy_instruction(
        MINT_LAYOUT, curve, 1, 1, is_mayhem_mode=True
    )
    sell_ix = client_layout.build_sell_instruction(
        MINT_LAYOUT, curve, 1, 1, is_mayhem_mode=True
    )

    assert str(buy_ix.accounts[1].pubkey) == MAYHEM_FEE_RECIPIENT
    assert str(sell_ix.accounts[1].pubkey) == MAYHEM_FEE_RECIPIENT
    assert buy_ix.accounts[1].is_writable


def test_decode_bonding_curve_reads_mayhem_flag():
    creator = bytes(Pubkey.from_string(CREATOR))
    base = bytes(8) + (1).to_bytes(8, "little") * 5 + b"\x00" + creator

    decode = PumpFunExecutionClient.decode_bonding_curve_data

    assert decode(base)["is_mayhem_mode"] is False
    assert decode(base + b"\x00")["is_mayhem_mode"] is False
    assert decode(base + b"\x01")["is_mayhem_mode"] is True


async def test_build_buy_tx_routes_mayhem_curve_fees(
    client_layout: PumpFunExecutionClient, monkeypatch
):
    creator = bytes(Pubkey.from_string(CREATOR))
    raw = (
        bytes(8)
        + (1_073_000_000_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (793_100_000_000_000).to_bytes(8, "little")
        + bytes(8)
        + (1_000_000_000_000_000).to_bytes(8, "little")
        + b"\x00"
        + creator
        + b"\x01"
    )

    async def fake_request(payload, **_kwargs):
        if payload["method"] == "getAccountInfo":
            return {
                "result": {"value": {"data": [base64.b64encode(raw).decode(), "b"]}}
            }
        return {"result": {"value": {"blockhash": SYSTEM_PROGRAM_ID}}}

    async def fake_ata_exists(*_args, **_kwargs):
        return True

    async def fake_token_program(_mint):
        return Pubkey.from_string(TOKEN_2022_PROGRAM_ID_STR)

    async def fake_blockhash():
        return "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"

    monkeypatch.setattr(client_layout.rpc_pool, "request", fake_request)
    monkeypatch.setattr(client_layout, "get_ata_exists", fake_ata_exists)
    monkeypatch.setattr(client_layout, "get_token_program_for_mint", fake_token_program)
    monkeypatch.setattr(client_layout, "get_latest_blockhash", fake_blockhash)

    curve, _ = client_layout.get_bonding_curve_pda(MINT_LAYOUT)
    tx = await client_layout.build_buy_tx(MINT_LAYOUT, curve, 0.005, tip_lamports=0)

    keys = [str(k) for k in tx.message.account_keys]
    assert MAYHEM_FEE_RECIPIENT in keys
    assert FEE_RECIPIENT not in keys


MINT_REGRESSIONS = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def _client_regressions(**kwargs) -> PumpFunExecutionClient:
    key = base58.b58encode(Keypair().to_bytes()).decode()
    return PumpFunExecutionClient(key, "https://mock-rpc.invalid", **kwargs)


@pytest.mark.regression("BUG-54")
@pytest.mark.usefixtures("offline_trade_rpc")
async def test_buy_uses_idempotent_ata_create_when_lookup_fails():
    client = _client_regressions()
    client.get_ata_exists = AsyncMock(side_effect=RuntimeError("rpc down"))
    captured = {}

    async def capture(instructions, *, tip_lamports=None):
        captured["ixs"] = instructions

    client._build_tx_with_instructions = capture
    curve, _ = client.get_bonding_curve_pda(MINT_REGRESSIONS)
    await client.build_buy_tx(MINT_REGRESSIONS, curve, 0.01)
    create = captured["ixs"][0]
    assert str(create.program_id) == ASSOCIATED_TOKEN_PROGRAM_ID
    assert create.data == bytes([1])  # CreateIdempotent


@pytest.mark.regression("BUG-66")
@pytest.mark.usefixtures("offline_trade_rpc")
async def test_build_buy_quote_includes_fee():
    client = _client_regressions()
    client.get_ata_exists = AsyncMock(return_value=True)
    captured = {}

    async def capture(instructions, *, tip_lamports=None):
        captured["ixs"] = instructions

    client._build_tx_with_instructions = capture
    curve, _ = client.get_bonding_curve_pda(MINT_REGRESSIONS)
    await client.build_buy_tx(MINT_REGRESSIONS, curve, 0.01, slippage_bps=0)
    amount = int.from_bytes(captured["ixs"][0].data[8:16], "little")
    expected = calculate_buy_tokens_out(
        10_000_000, 30_000_000_000, 1_073_000_000_000_000, fee_bps=125
    )
    assert amount == expected


@pytest.mark.regression("BUG-68", "BUG-69")
async def test_missing_creator_aborts_trade_build():
    client = _client_regressions()
    client.rpc_pool.request = AsyncMock(return_value={"result": {"value": None}})
    with pytest.raises(CurveStateUnavailableError):
        await client._fetch_trade_curve_state(MINT_REGRESSIONS)


@pytest.mark.regression("BUG-68", "BUG-69")
async def test_trade_curve_state_returns_decoded_creator():
    client = _client_regressions()
    creator = str(Pubkey.new_unique())
    client.rpc_pool.request = AsyncMock(
        return_value={"result": {"value": {"data": [base64.b64encode(b"x").decode()]}}}
    )
    client.decode_bonding_curve_data = MagicMock(
        return_value={"creator": creator, "virtual_sol_reserves": 1}
    )
    state = await client._fetch_trade_curve_state(MINT_REGRESSIONS)
    assert state["creator"] == creator


@pytest.mark.regression("BUG-74", "BUG-93")
def test_associated_bonding_curve_is_curve_ata():
    client = _client_regressions()
    curve, assoc = client.get_bonding_curve_pda(MINT_REGRESSIONS)
    expected = get_associated_token_address(
        Pubkey.from_string(curve),
        Pubkey.from_string(MINT_REGRESSIONS),
        Pubkey.from_string(TOKEN_PROGRAM_ID_STR),
    )
    assert assoc == str(expected)
    _, assoc_2022 = client.get_bonding_curve_pda(
        MINT_REGRESSIONS, TOKEN_2022_PROGRAM_ID_STR
    )
    assert assoc_2022 != assoc


def test_sdk_instructions_and_decoding():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
    )

    # SetComputeUnitLimit and SetComputeUnitPrice
    limit_ix = client.build_set_compute_unit_limit_instruction(300_000)
    assert limit_ix is not None

    price_ix = client.build_set_compute_unit_price_instruction(100_000)
    assert price_ix is not None

    # Jito tip instruction
    tip_ix = client.build_jito_tip_instruction(
        tip_lamports=50_000,
        tip_account=WSOL_MINT,
    )
    assert tip_ix is not None

    # decode_bonding_curve_data invalid length
    with pytest.raises(ValueError):
        client.decode_bonding_curve_data(b"short_bytes")

    # classify_execution_error
    assert (
        client.classify_execution_error(Exception("signature failed"))
        == "transaction_failed"
    )
    assert (
        client.classify_execution_error(Exception("custom error string")) == "unknown"
    )

    # _to_pubkey when already Pubkey
    pk_obj = Pubkey.from_string(SAMPLE_MINT)
    assert client._to_pubkey(pk_obj) == pk_obj


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_sdk_tx_build_and_confirm_variations():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        compute_unit_limit=150_000,
        compute_unit_price_micro_lamports=25_000,
        jito_tip_lamports=5_000,
    )
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))

    # Build buy with ATA existing vs not existing
    client.get_ata_exists = AsyncMock(return_value=True)
    buy_tx_ata = await client.build_buy_tx(SAMPLE_MINT, pda, 0.05, token_amount=500000)
    assert buy_tx_ata is not None

    # Build sell with slippage and ATA not existing
    client.get_ata_exists = AsyncMock(return_value=False)
    sell_tx = await client.build_sell_tx(
        SAMPLE_MINT, pda, 500000, min_sol_output=10000, slippage_bps=300
    )
    assert sell_tx is not None

    # Jito bundle send error
    mock_jito_err = AsyncMock()
    mock_jito_err.status = 500
    mock_jito_err.text = AsyncMock(return_value="Jito Node Down")
    mock_jito_err.__aenter__.return_value = mock_jito_err
    mock_jito_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_jito_err):
        with pytest.raises(RuntimeError, match="Jito bundle submission failed"):
            await client.send_jito_bundle([])


def test_sdk_math_and_keypairs():
    # normalize_slippage_bps
    assert PumpFunExecutionClient.normalize_slippage_bps(None, default=400) == 400
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(True)
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(-10)
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(20000)

    # evaluate_fill_completion & should_reassess_partial_fill
    assert PumpFunExecutionClient.evaluate_fill_completion(100, 0)["status"] == "failed"
    assert PumpFunExecutionClient.evaluate_fill_completion(100, 100)["status"] == "full"
    assert (
        PumpFunExecutionClient.evaluate_fill_completion(100, 50)["status"] == "partial"
    )
    assert PumpFunExecutionClient.should_reassess_partial_fill(100, 50) is True
    assert PumpFunExecutionClient.should_reassess_partial_fill(100, 0) is False
    assert PumpFunExecutionClient.should_reassess_partial_fill(0, 50) is False

    # calculate_sell_sol_output
    assert PumpFunExecutionClient.calculate_sell_sol_output(0, 100, 100) == 0
    assert PumpFunExecutionClient.calculate_sell_sol_output(10, 0, 100) == 0
    assert (
        PumpFunExecutionClient.calculate_sell_sol_output(
            100, 1000, 1000, slippage_bps=500
        )
        > 0
    )

    # _decode_keypair 32-byte vs 64-byte
    kp = Keypair()
    b58_32 = __import__("base58").b58encode(bytes(kp)[:32]).decode("ascii")
    b58_64 = __import__("base58").b58encode(bytes(kp)).decode("ascii")

    kp1 = PumpFunExecutionClient._decode_keypair(b58_32)
    assert kp1 is not None
    kp2 = PumpFunExecutionClient._decode_keypair(b58_64)
    assert kp2 is not None

    with pytest.raises(ValueError):
        PumpFunExecutionClient._decode_keypair("short")


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_sdk_rpc_retry_recovery_and_tx_assembly():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        priority_fee_lamports=10000,
        compute_unit_limit=300000,
        compute_unit_price_micro_lamports=50000,
        jito_tip_lamports=10000,
    )

    # RPC retry recovery: fails once with 500 then returns valid blockhash
    attempt_count = 0

    class MockResp:
        def __init__(self):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                self.status = 500
                self._body = "Internal Server Error"
            else:
                self.status = 200
                self._body = json.dumps(
                    {"result": {"value": {"blockhash": str(Hash.default())}}}
                )

        async def text(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    with patch("aiohttp.ClientSession.post", side_effect=lambda *a, **k: MockResp()):
        with patch("asyncio.sleep", return_value=None):
            blockhash = await client.get_latest_blockhash()
            assert blockhash is not None

    # build_buy_tx and build_sell_tx with full instructions
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))
    client.get_ata_exists = AsyncMock(return_value=False)

    buy_tx = await client.build_buy_tx(SAMPLE_MINT, pda, 0.05)
    assert buy_tx is not None

    tx = await client.build_sell_tx(
        SAMPLE_MINT,
        pda,
        1000000,
        min_sol_output=0.05,  # float min sol output
        slippage_bps=200,
    )
    assert tx is not None

    # send_jito_bundle with bundle list
    mock_jito_resp = AsyncMock()
    mock_jito_resp.status = 200
    mock_jito_resp.text = AsyncMock(return_value=json.dumps({"result": "bundle_999"}))
    mock_jito_resp.__aenter__.return_value = mock_jito_resp
    mock_jito_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_jito_resp):
        bundle_id = await client.send_jito_bundle([tx])
        assert bundle_id == "bundle_999"

    # get_ata_exists non-dict item cases
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    "not_dict",
                    {"account": "not_dict"},
                    {"account": {"data": "not_dict"}},
                    {"account": {"data": {"parsed": "not_dict"}}},
                    {"account": {"data": {"parsed": {"info": "not_dict"}}}},
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is False


@pytest.mark.regression("BUG-35")
async def test_execution_sdk_all_branches():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
    )
    # The token-balance ATA fallback resolves the token program over the RPC
    # pool; stub it so the test never reaches mainnet.
    client.get_token_program_for_mint = AsyncMock(
        return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)
    )

    # _to_pubkey invalid
    with pytest.raises(ValueError):
        client._to_pubkey("invalid-pubkey")

    # get_balance_sol int and non-dict
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": 5000000000}})
    assert await client.get_balance_sol() == 5.0

    answers: list[dict[str, Any]] = [
        {"result": None},
        {"result": {}},
        {"result": {"value": "5"}},
    ]
    for answer in answers:
        client._request_rpc_json = AsyncMock(return_value=answer)
        with pytest.raises(RuntimeError, match="getBalance returned no balance"):
            await client.get_balance_sol()

    # get_token_balance
    client._request_rpc_json = AsyncMock(
        return_value={"result": {"value": {"amount": "50000000"}}}
    )
    assert await client.get_token_balance(SAMPLE_MINT) == 50000000

    # get_token_balance when no accounts found: unreadable balance raises instead of
    # reading as 0 (BUG-35)
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(SAMPLE_MINT)

    # get_ata_exists
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": SAMPLE_MINT,
                                        "owner": str(client.wallet),
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is True

    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    assert await client.get_ata_exists(SAMPLE_MINT) is False

    # send_transaction
    tx_mock = MagicMock()
    tx_mock.__bytes__ = MagicMock(return_value=b"tx_bytes_12345678901234567890")
    client._request_rpc_json = AsyncMock(
        return_value={"result": "valid_signature_hash_1234567890"}
    )
    sig = await client.send_transaction(tx_mock)
    assert sig == "valid_signature_hash_1234567890"

    # send_transaction invalid result
    client._request_rpc_json = AsyncMock(return_value={"result": "short"})
    with pytest.raises(RuntimeError):
        await client.send_transaction(tx_mock)

    # confirm_transaction with status error and HTTP non-200
    mock_resp_err = AsyncMock()
    mock_resp_err.status = 500
    mock_resp_err.__aenter__.return_value = mock_resp_err
    mock_resp_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp_err):
        assert (
            await client.confirm_transaction("sig_test", max_retries=1, interval=0.01)
            is False
        )

    # confirm_transaction on-chain transaction failed error
    mock_resp_tx_err = AsyncMock()
    mock_resp_tx_err.status = 200
    mock_resp_tx_err.json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    {
                        "confirmationStatus": "confirmed",
                        "err": {"InstructionError": [0, "Custom"]},
                    }
                ]
            }
        }
    )
    mock_resp_tx_err.__aenter__.return_value = mock_resp_tx_err
    mock_resp_tx_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp_tx_err):
        assert (
            await client.confirm_transaction("sig_test", max_retries=1, interval=0.01)
            is False
        )

    # buy and sell wrappers
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))
    client.get_ata_exists = AsyncMock(return_value=True)
    client.send_transaction = AsyncMock(return_value="tx_sig_wrapped_123")
    client._fetch_trade_curve_state = AsyncMock(
        return_value={"creator": str(Pubkey.new_unique()), "is_mayhem_mode": False}
    )

    buy_res = await client.buy(
        SAMPLE_MINT, pda, 0.05, token_amount=1000000, slippage_bps=200
    )
    assert buy_res == "tx_sig_wrapped_123"

    sell_res = await client.sell(SAMPLE_MINT, pda, 1000000, min_sol_output=1000)
    assert sell_res == "tx_sig_wrapped_123"


# --- BUG-104: non-standard curve variants -----------------------------------------


def _curve_account(virtual_sol: int, real_sol: int) -> dict[str, Any]:
    raw = bonding_curve_bytes(
        virtual_sol_reserves=virtual_sol,
        real_sol_reserves=real_sol,
        creator=str(Pubkey.new_unique()),
    )
    return {"result": {"value": {"data": account_data_b64(raw)}}}


@pytest.mark.regression("BUG-104")
@pytest.mark.parametrize("virtual_sol, real_sol", NON_STANDARD_CURVE_RESERVES)
async def test_get_bonding_curve_state_non_standard_curve_raises(
    virtual_sol: int, real_sol: int
) -> None:
    client = _client()
    client._request_rpc_json = AsyncMock(
        return_value=_curve_account(virtual_sol, real_sol)
    )

    with pytest.raises(NonStandardCurveError, match="virtual SOL offset"):
        await client.get_bonding_curve_state(SAMPLE_MINT)


@pytest.mark.parametrize("virtual_sol, real_sol", STANDARD_CURVE_RESERVES)
async def test_get_bonding_curve_state_standard_curve_is_decoded(
    virtual_sol: int, real_sol: int
) -> None:
    client = _client()
    client._request_rpc_json = AsyncMock(
        return_value=_curve_account(virtual_sol, real_sol)
    )

    state = await client.get_bonding_curve_state(SAMPLE_MINT)

    assert state["virtual_sol_reserves"] == virtual_sol
    assert state["market_cap_sol"] == pytest.approx(27.96, abs=0.01)


@pytest.mark.regression("BUG-104")
async def test_build_buy_tx_non_standard_curve_refuses_to_build() -> None:
    client = _client()
    curve = _curve_state()
    curve["virtual_sol_reserves"], curve["real_sol_reserves"] = (
        NON_STANDARD_CURVE_RESERVES[1]
    )
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(client, "_fetch_trade_curve_state", AsyncMock(return_value=curve)),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        with pytest.raises(NonStandardCurveError):
            await client.build_buy_tx(MINT, str(Pubkey.new_unique()), 0.01)

    build.assert_not_awaited()


# --- BUG-108: the curve must exist and be owned by the Pump.fun program -----------


@pytest.mark.regression("BUG-108")
async def test_get_bonding_curve_state_missing_account_is_not_pump_fun() -> None:
    client = _client()
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})

    with pytest.raises(NotPumpFunCurveError, match="not found"):
        await client.get_bonding_curve_state(SAMPLE_MINT)


@pytest.mark.regression("BUG-108")
async def test_get_bonding_curve_state_foreign_owner_is_not_pump_fun() -> None:
    client = _client()
    account = _curve_account(*STANDARD_CURVE_RESERVES[0])
    account["result"]["value"]["owner"] = "11111111111111111111111111111111"
    client._request_rpc_json = AsyncMock(return_value=account)

    with pytest.raises(NotPumpFunCurveError, match="not the Pump.fun program"):
        await client.get_bonding_curve_state(SAMPLE_MINT)


async def test_get_bonding_curve_state_pump_owner_is_decoded() -> None:
    client = _client()
    account = _curve_account(*STANDARD_CURVE_RESERVES[0])
    account["result"]["value"]["owner"] = PUMP_PROGRAM_ID
    client._request_rpc_json = AsyncMock(return_value=account)

    state = await client.get_bonding_curve_state(SAMPLE_MINT)

    assert state["market_cap_sol"] == pytest.approx(27.96, abs=0.01)


@pytest.mark.regression("BUG-108")
async def test_fetch_trade_curve_state_foreign_owner_refuses_to_build() -> None:
    client = _client()
    account = _curve_account(*STANDARD_CURVE_RESERVES[0])
    account["result"]["value"]["owner"] = "11111111111111111111111111111111"
    client.rpc_pool.request = AsyncMock(return_value=account)

    with pytest.raises(NotPumpFunCurveError):
        await client._fetch_trade_curve_state(SAMPLE_MINT)


# --- FEAT-51: batch curve reader for the watch list ---------------------------------


def _curve_value(virtual_sol: int, real_sol: int, owner: str = PUMP_PROGRAM_ID) -> dict:
    value = _curve_account(virtual_sol, real_sol)["result"]["value"]
    value["owner"] = owner
    return value


async def test_get_bonding_curve_states_decodes_good_curves_and_rejects_the_rest() -> (
    None
):
    client = _client()
    good, bad_owner, missing, odd, junk = (str(Pubkey.new_unique()) for _ in range(5))
    junk_value = {"owner": PUMP_PROGRAM_ID, "data": ["!!notbase64", "base64"]}
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    _curve_value(*STANDARD_CURVE_RESERVES[0]),
                    _curve_value(
                        *STANDARD_CURVE_RESERVES[0],
                        owner="11111111111111111111111111111111",
                    ),
                    None,
                    _curve_value(*NON_STANDARD_CURVE_RESERVES[0]),
                    junk_value,
                ]
            }
        }
    )
    rejected: dict[str, str] = {}

    states = await client.get_bonding_curve_states(
        [good, bad_owner, missing, odd, junk, good], rejected=rejected
    )

    assert list(states) == [good]
    assert states[good]["virtual_sol_reserves"] == STANDARD_CURVE_RESERVES[0][0]
    assert rejected == {
        bad_owner: "not_pump_fun",
        missing: "missing",
        odd: "non_standard",
        junk: "decode_error",
    }
    payload = client._request_rpc_json.await_args_list[0].args[0]
    assert payload["method"] == "getMultipleAccounts"
    assert len(payload["params"][0]) == 5


async def test_get_bonding_curve_states_reads_in_chunks_of_100() -> None:
    client = _client()
    mints = [str(Pubkey.new_unique()) for _ in range(GET_MULTIPLE_ACCOUNTS_LIMIT + 5)]

    async def reply(payload: dict, **_: Any) -> dict:
        count = len(payload["params"][0])
        return {"result": {"value": [None] * (count - 1)}}  # short answer

    client._request_rpc_json = AsyncMock(side_effect=reply)

    states = await client.get_bonding_curve_states(mints)

    assert states == {}
    sizes = [
        len(c.args[0]["params"][0]) for c in client._request_rpc_json.await_args_list
    ]
    assert sizes == [GET_MULTIPLE_ACCOUNTS_LIMIT, 5]


async def test_get_bonding_curve_states_raises_on_rpc_failure() -> None:
    client = _client()
    client._request_rpc_json = AsyncMock(
        side_effect=RuntimeError("RPC request failed after retries: timeout")
    )

    with pytest.raises(RuntimeError):
        await client.get_bonding_curve_states([SAMPLE_MINT])
    assert await client.get_bonding_curve_states([]) == {}


@pytest.mark.regression("BUG-161")
@pytest.mark.parametrize(
    "answer",
    [
        {"error": {"code": -32602, "message": "Invalid params"}},
        {"error": "node is behind"},
        {"result": None},
        {"result": {}},
        {},
    ],
)
async def test_an_rpc_error_is_a_failed_curve_read_not_every_curve_missing(
    answer: dict,
) -> None:
    client = _client()
    client._request_rpc_json = AsyncMock(return_value=answer)
    rejected: dict[str, str] = {}

    with pytest.raises(RuntimeError, match="getMultipleAccounts"):
        await client.get_bonding_curve_states([SAMPLE_MINT], rejected=rejected)
    assert rejected == {}
    call = client._request_rpc_json.await_args_list[0]
    assert call.kwargs["max_retries"] == 1


# --- BUG-124: non-SOL quote mints are refused, not mispriced -----------------------

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _quoted_curve(quote_mint: str | None) -> bytes:
    virtual_sol, real_sol = STANDARD_CURVE_RESERVES[0]
    data = bonding_curve_bytes(
        virtual_sol_reserves=virtual_sol,
        real_sol_reserves=real_sol,
        creator=str(Pubkey.new_unique()),
    )
    data += b"\x00\x00"  # is_mayhem_mode, is_cashback_coin
    if quote_mint is not None:
        data += bytes(Pubkey.from_string(quote_mint))
    return data


def test_decoder_reads_the_quote_mint() -> None:
    decode = PumpFunExecutionClient.decode_bonding_curve_data
    assert decode(_quoted_curve(None))["quote_mint"] is None
    assert decode(_quoted_curve(USDC_MINT))["quote_mint"] == USDC_MINT
    # SOL-quoted curves carry a zeroed quote mint on mainnet.
    zeroed = decode(_quoted_curve("11111111111111111111111111111111"))
    assert zeroed["quote_mint"] == "11111111111111111111111111111111"


@pytest.mark.regression("BUG-124")
async def test_non_sol_quoted_curves_are_refused_as_non_standard() -> None:
    client = _client()
    for quote_mint in (None, WSOL_MINT, "11111111111111111111111111111111"):
        state = client.decode_bonding_curve_data(_quoted_curve(quote_mint))
        client._reject_non_standard_curve(SAMPLE_MINT, state)  # no raise
    state = client.decode_bonding_curve_data(_quoted_curve(USDC_MINT))
    with pytest.raises(NonStandardCurveError, match="quote mint"):
        client._reject_non_standard_curve(SAMPLE_MINT, state)

    usdc = {
        "owner": PUMP_PROGRAM_ID,
        "data": account_data_b64(_quoted_curve(USDC_MINT)),
    }
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": [usdc]}})
    rejected: dict[str, str] = {}
    assert await client.get_bonding_curve_states([SAMPLE_MINT], rejected=rejected) == {}
    assert rejected == {SAMPLE_MINT: "non_standard"}


@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_curve_trades_go_through_a_jito_bundle_when_tipped(side: str) -> None:
    client = PumpFunExecutionClient(str(Keypair()), use_jito=True)
    client.resolve_trade_tip = AsyncMock(return_value=(True, 10_000))
    client.build_buy_tx = AsyncMock(return_value="buy-tx")
    client.build_sell_tx = AsyncMock(return_value="sell-tx")
    client.send_jito_bundle_with_fallback = AsyncMock(return_value="jito-sig")
    if side == "buy":
        sig = await client.buy(SAMPLE_MINT, "Curve", 0.01)
    else:
        sig = await client.sell(SAMPLE_MINT, "Curve", 1_000)
    assert sig == "jito-sig"
    client.send_jito_bundle_with_fallback.assert_awaited_once_with([f"{side}-tx"])


def test_curve_fee_falls_back_to_the_flat_fee_on_a_bad_tier_table() -> None:
    from trading_pump.sdk.fee_config import FeeConfig

    client = PumpFunExecutionClient(str(Keypair()))
    from trading_pump.sdk.fee_config import Fees

    flat = Fees(0, 95, 0)
    client._fee_config_cache = (0.0, FeeConfig(1, "admin", flat, (), (), None))
    assert client.curve_fee_bps(30_000_000_000, 1_073_000_000_000_000) == int(
        client.pump_fee_bps
    )
