"""Regression tests for SDK / Jito / RPC-pool contract bugs (Batch 2)."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.infra.rpc_pool import RpcConnectionPool
from pumpfun_trading.sdk.curve import calculate_buy_tokens_out, calculate_sell_sol_out
from pumpfun_trading.sdk.execution import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    CurveStateUnavailableError,
    PumpFunExecutionClient,
    TokenBalanceUnavailableError,
    TokenProgramUnavailableError,
)
from pumpfun_trading.sdk.jito import JitoBundleStatus

MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def _client(**kwargs) -> PumpFunExecutionClient:
    key = base58.b58encode(Keypair().to_bytes()).decode()
    return PumpFunExecutionClient(key, "https://mock-rpc.invalid", **kwargs)


# BUG-35 -------------------------------------------------------------------


async def test_token_balance_rpc_failure_raises_not_zero():
    client = _client()
    client._request_rpc_json = AsyncMock(side_effect=RuntimeError("timeout"))
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(MINT)


async def test_token_balance_error_payload_raises():
    client = _client()
    client._request_rpc_json = AsyncMock(
        return_value={"error": {"code": -32005, "message": "node behind"}}
    )
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(MINT)


async def test_token_balance_confirmed_zero_cases():
    client = _client()
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": []}})
    assert await client.get_token_balance(MINT) == 0

    client._request_rpc_json = AsyncMock(
        side_effect=[
            RuntimeError("primary down"),
            {
                "error": {
                    "code": -32602,
                    "message": "Invalid param: could not find account",
                }
            },
        ]
    )
    client.get_ata_address = AsyncMock(return_value=str(Pubkey.new_unique()))
    assert await client.get_token_balance(MINT) == 0


# BUG-53 -------------------------------------------------------------------


def test_jito_confirmed_bundle_with_error_is_failed_not_landed():
    status = JitoBundleStatus(
        bundle_id="b",
        status="Landed",
        confirmation_status="confirmed",
        err={"Err": {"InstructionError": [2, {"Custom": 6002}]}},
    )
    assert status.is_failed and not status.is_landed


def test_jito_ok_null_err_counts_as_landed():
    status = JitoBundleStatus(
        bundle_id="b",
        status="Landed",
        confirmation_status="finalized",
        err={"Ok": None},
    )
    assert status.is_landed and not status.is_failed


async def test_jito_get_bundle_statuses_parses_ok_and_err():
    from pumpfun_trading.sdk.jito import JitoClient

    jito = JitoClient()
    jito._send_json_rpc = AsyncMock(
        return_value={
            "value": [
                {
                    "bundle_id": "a",
                    "confirmation_status": "confirmed",
                    "err": {"Ok": None},
                },
                {
                    "bundle_id": "b",
                    "confirmation_status": "confirmed",
                    "err": {"Err": 1},
                },
            ]
        }
    )
    ok, bad = await jito.get_bundle_statuses(["a", "b"])
    assert ok.status == "Landed" and ok.is_landed
    assert bad.status == "Failed" and not bad.is_landed
    await jito.close()


async def test_jito_pending_bundle_falls_back_instead_of_reporting_success():
    client = _client(use_jito=True, jito_fallback_to_rpc=True)
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


# BUG-54 -------------------------------------------------------------------


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_buy_uses_idempotent_ata_create_when_lookup_fails():
    client = _client()
    client.get_ata_exists = AsyncMock(side_effect=RuntimeError("rpc down"))
    captured = {}

    async def capture(instructions, *, tip_lamports=None):
        captured["ixs"] = instructions

    client._build_tx_with_instructions = capture
    curve, _ = client.get_bonding_curve_pda(MINT)
    await client.build_buy_tx(MINT, curve, 0.01)
    create = captured["ixs"][0]
    assert str(create.program_id) == ASSOCIATED_TOKEN_PROGRAM_ID
    assert create.data == bytes([1])  # CreateIdempotent


# BUG-66 -------------------------------------------------------------------


def test_curve_quotes_apply_fee_bps():
    v_sol, v_tok = 30_000_000_000, 1_073_000_000_000_000
    assert calculate_buy_tokens_out(
        10_000_000, v_sol, v_tok, fee_bps=125
    ) < calculate_buy_tokens_out(10_000_000, v_sol, v_tok)
    gross = calculate_sell_sol_out(1_000_000_000, v_tok, v_sol)
    assert (
        calculate_sell_sol_out(1_000_000_000, v_tok, v_sol, fee_bps=125)
        == (gross * 9_875) // 10_000
    )


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_build_buy_quote_includes_fee():
    client = _client()
    client.get_ata_exists = AsyncMock(return_value=True)
    captured = {}

    async def capture(instructions, *, tip_lamports=None):
        captured["ixs"] = instructions

    client._build_tx_with_instructions = capture
    curve, _ = client.get_bonding_curve_pda(MINT)
    await client.build_buy_tx(MINT, curve, 0.01, slippage_bps=0)
    amount = int.from_bytes(captured["ixs"][0].data[8:16], "little")
    expected = calculate_buy_tokens_out(
        10_000_000, 30_000_000_000, 1_073_000_000_000_000, fee_bps=125
    )
    assert amount == expected


# BUG-67 -------------------------------------------------------------------


def _pool_with_responses(*bodies):
    pool = RpcConnectionPool(endpoints=["https://a.invalid", "https://b.invalid"])
    responses = []
    for body in bodies:
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value=json.dumps(body))
        responses.append(resp)

    class Ctx:
        def __init__(self, resp):
            self.resp = resp

        async def __aenter__(self):
            return self.resp

        async def __aexit__(self, *exc):
            return None

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(side_effect=[Ctx(r) for r in responses])
    pool._session = session
    return pool


async def test_rpc_pool_node_error_records_failure_and_fails_over():
    pool = _pool_with_responses(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32005, "message": "Node is behind"},
        },
        {"jsonrpc": "2.0", "id": 1, "result": 42},
    )
    parsed = await pool.request({"method": "getSlot"}, max_retries=2)
    assert parsed["result"] == 42
    assert sum(ep.consecutive_failures for ep in pool._endpoints) == 1


async def test_rpc_pool_deterministic_error_returned_without_failover():
    pool = _pool_with_responses(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32002, "message": "compute unit limit exceeded"},
        },
    )
    parsed = await pool.request({"method": "sendTransaction"}, max_retries=2)
    assert parsed["error"]["code"] == -32002
    assert all(ep.consecutive_failures == 0 for ep in pool._endpoints)


# BUG-68 / BUG-69 -------------------------------------------------------------


async def test_missing_creator_aborts_trade_build():
    client = _client()
    client.rpc_pool.request = AsyncMock(return_value={"result": {"value": None}})
    with pytest.raises(CurveStateUnavailableError):
        await client._fetch_trade_curve_state(MINT)


async def test_trade_curve_state_returns_decoded_creator():
    client = _client()
    creator = str(Pubkey.new_unique())
    client.rpc_pool.request = AsyncMock(
        return_value={"result": {"value": {"data": [base64.b64encode(b"x").decode()]}}}
    )
    client.decode_bonding_curve_data = MagicMock(
        return_value={"creator": creator, "virtual_sol_reserves": 1}
    )
    state = await client._fetch_trade_curve_state(MINT)
    assert state["creator"] == creator


async def test_token_program_errors_raise_and_success_is_cached():
    client = _client()
    client.rpc_pool.request = AsyncMock(side_effect=RuntimeError("down"))
    with pytest.raises(TokenProgramUnavailableError):
        await client.get_token_program_for_mint(MINT)

    client.rpc_pool.request = AsyncMock(
        return_value={"result": {"value": {"owner": TOKEN_2022_PROGRAM_ID_STR}}}
    )
    first = await client.get_token_program_for_mint(MINT)
    second = await client.get_token_program_for_mint(MINT)
    assert str(first) == str(second) == TOKEN_2022_PROGRAM_ID_STR
    assert client.rpc_pool.request.await_count == 1


# BUG-74 / BUG-93 -------------------------------------------------------------


async def test_get_coins_by_mints_reuses_own_session():
    api = PumpFunApiClient()
    api.post = AsyncMock(return_value=[{"mint": MINT}])
    assert await api.get_coins_by_mints([MINT]) == [{"mint": MINT}]
    api.post.assert_awaited_once_with(
        "https://frontend-api-v3.pump.fun/coins-v2/mints", json={"mints": [MINT]}
    )


def test_associated_bonding_curve_is_curve_ata():
    client = _client()
    curve, assoc = client.get_bonding_curve_pda(MINT)
    expected = get_associated_token_address(
        Pubkey.from_string(curve),
        Pubkey.from_string(MINT),
        Pubkey.from_string(TOKEN_PROGRAM_ID_STR),
    )
    assert assoc == str(expected)
    _, assoc_2022 = client.get_bonding_curve_pda(MINT, TOKEN_2022_PROGRAM_ID_STR)
    assert assoc_2022 != assoc
