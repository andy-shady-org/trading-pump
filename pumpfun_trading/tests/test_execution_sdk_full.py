from __future__ import annotations

import base64
import json
import struct
from unittest.mock import AsyncMock, patch

import pytest
from solders.hash import Hash

from pumpfun_trading.sdk.execution import (
    PumpFunExecutionClient,
)

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_BLOCKHASH = str(Hash.default())


@pytest.mark.asyncio
async def test_execution_client_rpc_handling():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        compute_unit_limit=200_000,
        compute_unit_price_micro_lamports=50_000,
        jito_tip_lamports=10_000,
    )

    # 1. Valid RPC response
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(
        return_value=json.dumps({"result": {"value": {"blockhash": SAMPLE_BLOCKHASH}}})
    )
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        blockhash = await client.get_latest_blockhash()
        assert blockhash == SAMPLE_BLOCKHASH

    # 2. RPC HTTP error status
    mock_err_resp = AsyncMock()
    mock_err_resp.status = 500
    mock_err_resp.text = AsyncMock(return_value="Internal Error")
    mock_err_resp.__aenter__.return_value = mock_err_resp
    mock_err_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_err_resp):
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RuntimeError):
                await client._request_rpc_json({"method": "test"}, max_retries=1)

    # 3. RPC invalid JSON
    mock_bad_resp = AsyncMock()
    mock_bad_resp.status = 200
    mock_bad_resp.text = AsyncMock(return_value="not valid json")
    mock_bad_resp.__aenter__.return_value = mock_bad_resp
    mock_bad_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_bad_resp):
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RuntimeError):
                await client._request_rpc_json({"method": "test"}, max_retries=1)

    # 4. RPC response not a dict
    mock_array_resp = AsyncMock()
    mock_array_resp.status = 200
    mock_array_resp.text = AsyncMock(return_value="[1, 2, 3]")
    mock_array_resp.__aenter__.return_value = mock_array_resp
    mock_array_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_array_resp):
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RuntimeError):
                await client._request_rpc_json({"method": "test"}, max_retries=1)


@pytest.mark.asyncio
async def test_execution_client_account_and_balance_queries():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_execution_client_send_confirm_and_jito():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
    )

    # classify_execution_error
    assert client.classify_execution_error(Exception("timeout")) == "rpc_timeout"
    assert (
        client.classify_execution_error(Exception("429 Too Many Requests"))
        == "rate_limited"
    )
    assert (
        client.classify_execution_error(Exception("dns lookup failed"))
        == "network_error"
    )
    assert (
        client.classify_execution_error(Exception("http 503 service unavailable"))
        == "server_error"
    )
    assert (
        client.classify_execution_error(Exception("transaction failed"))
        == "transaction_failed"
    )
    assert (
        client.classify_execution_error(Exception("unknown random error")) == "unknown"
    )

    # confirm_transaction confirmed
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "result": {"value": [{"confirmationStatus": "confirmed", "err": None}]}
        }
    )
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        assert await client.confirm_transaction("tx_sig", max_retries=1) is True

    # confirm_transaction error
    mock_err_resp = AsyncMock()
    mock_err_resp.status = 200
    mock_err_resp.json = AsyncMock(
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
    mock_err_resp.__aenter__.return_value = mock_err_resp
    mock_err_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_err_resp):
        assert await client.confirm_transaction("tx_sig", max_retries=1) is False

    # Jito bundle send
    mock_jito_resp = AsyncMock()
    mock_jito_resp.status = 200
    mock_jito_resp.text = AsyncMock(
        return_value=json.dumps({"result": "bundle_id_123"})
    )
    mock_jito_resp.__aenter__.return_value = mock_jito_resp
    mock_jito_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_jito_resp):
        bundle_res = await client.send_jito_bundle([])
        assert bundle_res == "bundle_id_123"
