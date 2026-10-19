"""Unit tests for ``sdk/transport.py``: compute budget and Jito tip instructions, sending,
Jito bundles with RPC fallback, confirmation and transaction costs (FEAT-49)."""

from __future__ import annotations

import json
import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import base58
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from pumpfun_trading.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from pumpfun_trading.sdk.execution import (
    SYSTEM_PROGRAM_ID,
    PumpFunExecutionClient,
)
from pumpfun_trading.sdk.jito import JitoBundleStatus, JitoClient
from pumpfun_trading.tests.support.constants import (
    SAMPLE_PRIVATE_KEY,
)

# The real getTransaction cost reader is under test here (see tests/conftest.py).
USES_REAL_TRANSACTION_COSTS = True


def _client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


async def test_build_sol_transfer_tx_is_a_tipless_system_transfer() -> None:
    """FEAT-42 profit sweep: compute budget, one system transfer, no Jito tip."""
    client = _client()
    client.compute_unit_limit = 200_000
    client.priority_fee_lamports = 10_000
    destination = Pubkey.new_unique()

    with patch.object(
        client,
        "get_latest_blockhash",
        AsyncMock(return_value=str(Hash.default())),
    ):
        tx = await client.build_sol_transfer_tx(str(destination), 150_000_000)

    message = tx.message
    keys = list(message.account_keys)
    programs = [keys[ix.program_id_index] for ix in message.instructions]
    assert programs.count(Pubkey.from_string(SYSTEM_PROGRAM_ID)) == 1
    assert len(message.instructions) == 3  # CU limit, CU price, transfer
    transfer_ix = message.instructions[-1]
    assert keys[transfer_ix.accounts[1]] == destination
    assert struct.unpack("<IQ", bytes(transfer_ix.data)) == (2, 150_000_000)
    assert keys[0] == client.wallet


@pytest.mark.parametrize("lamports", [0, -1])
async def test_build_sol_transfer_tx_rejects_non_positive_amount(lamports: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        await _client().build_sol_transfer_tx(str(Pubkey.new_unique()), lamports)


async def test_build_sol_transfer_tx_rejects_own_wallet() -> None:
    client = _client()

    with pytest.raises(ValueError, match="wallet itself"):
        await client.build_sol_transfer_tx(str(client.wallet), 1_000)


async def test_transfer_sol_sends_the_built_transaction() -> None:
    client = _client()
    tx = MagicMock()
    with (
        patch.object(client, "build_sol_transfer_tx", AsyncMock(return_value=tx)),
        patch.object(client, "send_transaction", AsyncMock(return_value="Sig")) as send,
    ):
        assert await client.transfer_sol("Dest", 5) == "Sig"

    send.assert_awaited_once_with(tx)


# --- BUG-96 token-account close and FEAT-49 transaction costs ---------------------


MINT = str(Pubkey.new_unique())


def test_model_trade_costs_uses_priority_fee_and_static_tip() -> None:
    client = PumpFunExecutionClient(
        private_key_b58=str(Keypair()),
        priority_fee_lamports=20_000,
        compute_unit_limit=200_000,
        jito_tip_lamports=100_000,
    )

    costs = client.model_trade_costs(rent_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS)

    assert costs.priority_fee_lamports == 20_000
    assert costs.network_fee_lamports == 25_000
    assert costs.tip_lamports == 100_000
    assert costs.rent_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"compute_unit_limit": 0}, 0),
        ({"priority_fee_lamports": 0}, 0),
        ({"compute_unit_price_micro_lamports": 50_000}, 10_000),
    ],
)
def test_modelled_priority_fee_variants(kwargs: dict[str, Any], expected: int) -> None:
    client = PumpFunExecutionClient(private_key_b58=str(Keypair()), **kwargs)
    assert client.modelled_priority_fee_lamports() == expected
    assert client.model_trade_costs().tip_lamports == 0


async def test_get_transaction_costs_polls_until_transaction_is_indexed() -> None:
    client = _client()
    mint = str(Pubkey.new_unique())
    ata = client.wallet_token_accounts(mint)[0]
    tip = next(iter(client.tip_account_set()))
    tx = {
        "meta": {
            "fee": 10_000,
            "err": None,
            "preBalances": [1_000_000_000, 0, 0],
            "postBalances": [1_000_000_000 - 12_000_000 - 2_039_280, 2_039_280, 1_000],
        },
        "transaction": {"message": {"accountKeys": [str(client.wallet), ata, tip]}},
    }
    request = AsyncMock(
        side_effect=[{"result": None}, RuntimeError("429"), {"result": tx}]
    )

    with patch.object(client.rpc_pool, "request", request):
        costs = await client.get_transaction_costs(
            "Sig", mint, is_buy=True, delay_seconds=0
        )

    assert request.await_count == 3
    assert costs.signature == "Sig"
    assert costs.rent_lamports == 2_039_280
    assert costs.tip_lamports == 1_000
    assert costs.swap_lamports == 12_000_000 - 10_000 - 1_000


async def test_get_transaction_costs_gives_up_and_propagates_bad_meta() -> None:
    client = _client()
    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value={"result": None})
    ):
        with pytest.raises(RuntimeError, match="unavailable"):
            await client.get_transaction_costs(
                "Sig", MINT, is_buy=False, attempts=2, delay_seconds=0
            )

    failed = {"meta": {"err": {"Custom": 6001}}, "transaction": {}}
    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value={"result": failed})
    ):
        with pytest.raises(ValueError, match="failed on-chain"):
            await client.get_transaction_costs("Sig", MINT, is_buy=False)


def test_tip_account_set_includes_refreshed_client_accounts() -> None:
    client = PumpFunExecutionClient(private_key_b58=str(Keypair()), use_jito=True)
    assert client.jito_client is not None
    client.jito_client.tip_accounts = ["CustomTip111"]
    assert "CustomTip111" in client.tip_account_set()


# --- RPC lookups and failure modes ------------------------------------------------


def _rpc_value(value: Any) -> dict[str, Any]:
    return {"result": {"value": value}}


async def test_get_latest_blockhash_missing_hash_raises() -> None:
    client = _client()

    with patch.object(
        client.rpc_pool, "request", AsyncMock(return_value=_rpc_value({}))
    ):
        with pytest.raises(RuntimeError, match="Invalid blockhash"):
            await client.get_latest_blockhash()


async def test_calculate_dynamic_jito_tip_without_client_uses_static_tip() -> None:
    client = PumpFunExecutionClient(
        private_key_b58=str(Keypair()), jito_tip_lamports=42_000
    )
    client.jito_client = None

    assert await client.calculate_dynamic_jito_tip(0.1) == 42_000


async def test_calculate_dynamic_jito_tip_floor_failure_uses_config_default() -> None:
    client = PumpFunExecutionClient(private_key_b58=str(Keypair()), use_jito=True)
    assert client.jito_client is not None

    with patch.object(
        client.jito_client, "fetch_tip_floor", AsyncMock(side_effect=OSError("x"))
    ):
        tip = await client.calculate_dynamic_jito_tip(0.1)

    assert tip == client.jito_tip_config.default_tip_lamports


# --- transaction assembly and submission ---------------------------------------------


async def _signed_tx(client: PumpFunExecutionClient) -> VersionedTransaction:
    with patch.object(
        client, "get_latest_blockhash", AsyncMock(return_value=str(Hash.new_unique()))
    ):
        return await client._build_tx_with_instructions([])


async def test_build_tx_without_compute_budget_has_wallet_as_only_signer() -> None:
    client = PumpFunExecutionClient(
        private_key_b58=str(Keypair()), compute_unit_limit=0, priority_fee_lamports=0
    )

    tx = await _signed_tx(client)

    assert list(tx.message.instructions) == []
    assert tx.message.account_keys[0] == client.wallet
    assert len(tx.signatures) == 1


def _post_response(status: int, body: str) -> AsyncMock:
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=body)
    resp.__aenter__.return_value = resp
    resp.__aexit__.return_value = None
    return resp


async def test_send_jito_bundle_empty_result_raises() -> None:
    client = _client()
    tx = await _signed_tx(client)

    with patch(
        "aiohttp.ClientSession.post",
        return_value=_post_response(200, '{"result": null}'),
    ):
        with pytest.raises(RuntimeError, match="Invalid Jito bundle response"):
            await client.send_jito_bundle([tx], endpoint_url="https://jito.invalid")


async def test_send_jito_bundle_failed_status_without_fallback_raises() -> None:
    client = PumpFunExecutionClient(
        private_key_b58=str(Keypair()), use_jito=True, jito_fallback_to_rpc=False
    )
    tx = await _signed_tx(client)
    jito = client.jito_client
    assert jito is not None
    failed = JitoBundleStatus(bundle_id="B1", status="Failed", err={"Custom": 1})

    with (
        patch.object(jito, "send_bundle", AsyncMock(return_value="B1")),
        patch.object(
            jito, "wait_for_bundle_confirmation", AsyncMock(return_value=failed)
        ),
    ):
        with pytest.raises(RuntimeError, match="B1 failed"):
            await client.send_jito_bundle_with_fallback([tx])


async def test_send_jito_bundle_unconfirmed_falls_back_to_rpc() -> None:
    client = _client()
    client.jito_client = None
    tx = await _signed_tx(client)
    send = AsyncMock(return_value="RpcSig")

    with (
        patch.object(client, "send_jito_bundle", AsyncMock(return_value="B2")),
        patch.object(client, "confirm_transaction", AsyncMock(return_value=False)),
        patch.object(client, "send_transaction", send),
    ):
        sig = await client.send_jito_bundle_with_fallback([tx], timeout_seconds=1)

    assert sig == "RpcSig"
    send.assert_awaited_once_with(tx)
    assert client.failed_execution_attempts == 1
    assert client.execution_health_score == 95.0


async def test_confirm_transaction_on_chain_failure_is_reraised() -> None:
    client = _client()
    rpc = AsyncMock(side_effect=RuntimeError("On-chain transaction failed: 6001"))

    with patch.object(client, "_request_rpc_json", rpc):
        with pytest.raises(RuntimeError, match="On-chain transaction failed"):
            await client.confirm_transaction("Sig", max_retries=3, interval=0)

    assert rpc.await_count == 1


async def test_confirm_transaction_unconfirmed_or_transient_errors_return_false() -> (
    None
):
    client = _client()
    rpc = AsyncMock(
        side_effect=[
            _rpc_value([{"confirmationStatus": None, "err": None}]),
            RuntimeError("RPC request failed after retries: 503"),
        ]
    )

    with patch.object(client, "_request_rpc_json", rpc):
        confirmed = await client.confirm_transaction("Sig", max_retries=2, interval=0)

    assert confirmed is False
    assert rpc.await_count == 2


@pytest.fixture
def client():
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        __import__("base58").b58encode(keypair.to_bytes()).decode(),
        "https://example.com",
    )


def test_compute_budget_and_jito_instructions(client):
    limit_ix = client.build_set_compute_unit_limit_instruction(150_000)
    assert len(limit_ix.data) == 5
    assert limit_ix.data[0] == 2

    price_ix = client.build_set_compute_unit_price_instruction(10_000)
    assert len(price_ix.data) == 9
    assert price_ix.data[0] == 3

    tip_ix = client.build_jito_tip_instruction(100_000)
    assert tip_ix.data[:4] == bytes([2, 0, 0, 0])
    with pytest.raises(ValueError):
        client.build_jito_tip_instruction(0)


SAMPLE_BLOCKHASH = str(Hash.default())


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


@pytest.mark.regression("BUG-34")
async def test_jito_send_bundle_declares_base64_encoding(monkeypatch):
    captured: dict = {}

    async def fake_send_json_rpc(self, payload, endpoint_url=None):
        captured.update(payload)
        return "bundle-id"

    monkeypatch.setattr(JitoClient, "_send_json_rpc", fake_send_json_rpc)
    bundle_id = await JitoClient().send_bundle(["AAAA"])

    assert bundle_id == "bundle-id"
    assert captured["params"] == [["AAAA"], {"encoding": "base64"}]


def _client_regressions(**kwargs) -> PumpFunExecutionClient:
    key = base58.b58encode(Keypair().to_bytes()).decode()
    return PumpFunExecutionClient(key, "https://mock-rpc.invalid", **kwargs)


@pytest.mark.regression("BUG-53")
async def test_jito_pending_bundle_falls_back_instead_of_reporting_success():
    client = _client_regressions(use_jito=True, jito_fallback_to_rpc=True)
    tx = MagicMock()
    tx.signatures = ["sig1"]
    client.jito_client.send_bundle = AsyncMock(return_value="bundle")
    client.jito_client.wait_for_bundle_confirmation = AsyncMock(
        return_value=JitoBundleStatus(bundle_id="bundle", status="Pending")
    )
    client.send_transaction = AsyncMock(return_value="rpc_sig")
    assert await client.send_jito_bundle_with_fallback([tx]) == "rpc_sig"
    client.send_transaction.assert_awaited_once()
    await client.close()
