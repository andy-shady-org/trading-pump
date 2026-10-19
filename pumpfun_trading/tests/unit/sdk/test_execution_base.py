"""Unit tests for ``sdk/execution_base.py``: client construction, shared helpers and
account queries (holder lookups BUG-95/BUG-107, token balances BUG-35)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import base58
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.sdk.execution import (
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    PumpFunExecutionClient,
    TokenBalanceUnavailableError,
    TokenProgramUnavailableError,
)

# The real getTransaction cost reader is under test here (see tests/conftest.py).
USES_REAL_TRANSACTION_COSTS = True


def _client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


async def test_get_token_largest_accounts_parses_valid_entries() -> None:
    client = _client()
    response = {
        "result": {
            "value": [
                {"address": "Curve111", "amount": "800"},
                {"address": "Holder111", "amount": "30"},
                "not-a-dict",
                {"address": "BadAmount", "amount": "x"},
                {"address": "", "amount": "5"},
            ]
        }
    }
    request = AsyncMock(return_value=response)
    health_before = client.execution_health_score

    with patch.object(client.rpc_pool, "request", request):
        accounts = await client.get_token_largest_accounts("Mint111")

    assert accounts == [("Curve111", 800), ("Holder111", 30)]
    assert request.await_args is not None
    assert request.await_args.args[0]["method"] == "getTokenLargestAccounts"
    assert client.execution_health_score == health_before


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": -32602, "message": "Invalid param"}},
        {"result": {"value": None}},
        ["not", "a", "dict"],
    ],
)
async def test_get_token_largest_accounts_raises_on_bad_response(
    response: Any,
) -> None:
    client = _client()

    with patch.object(client.rpc_pool, "request", AsyncMock(return_value=response)):
        with pytest.raises(RuntimeError):
            await client.get_token_largest_accounts("Mint111")


# --- BUG-96 token-account close and FEAT-49 transaction costs ---------------------


MINT = str(Pubkey.new_unique())


# --- RPC lookups and failure modes ------------------------------------------------


def _rpc_value(value: Any) -> dict[str, Any]:
    return {"result": {"value": value}}


async def test_get_token_program_for_mint_missing_account_raises_after_retry() -> None:
    client = _client()
    request = AsyncMock(return_value=_rpc_value(None))

    with patch.object(client.rpc_pool, "request", request):
        with pytest.raises(TokenProgramUnavailableError, match="not found"):
            await client.get_token_program_for_mint(MINT)

    assert request.await_count == 2


async def test_get_ata_exists_owner_lookup_fails_falls_back_to_account_info() -> None:
    client = _client()
    rpc = AsyncMock(side_effect=[RuntimeError("down"), _rpc_value({"lamports": 1})])

    with patch.object(client, "_request_rpc_json", rpc):
        exists = await client.get_ata_exists(MINT, token_program=TOKEN_PROGRAM_ID_STR)

    assert exists is True
    assert rpc.await_args_list[1].args[0]["method"] == "getAccountInfo"


async def test_get_ata_exists_both_lookups_fail_returns_false() -> None:
    client = _client()
    rpc = AsyncMock(side_effect=RuntimeError("down"))

    with patch.object(client, "_request_rpc_json", rpc):
        exists = await client.get_ata_exists(MINT, token_program=TOKEN_PROGRAM_ID_STR)

    assert exists is False
    assert rpc.await_count == 2


async def test_close_without_jito_or_pool_is_noop() -> None:
    client = _client()
    client.jito_client = None
    client.rpc_pool = None  # type: ignore[assignment]

    await client.close()


async def test_get_token_balance_unparsed_accounts_fall_back_to_ata_balance() -> None:
    client = _client()
    unparsed: dict[str, Any] = {"account": {"data": {"parsed": {"info": {}}}}}
    rpc = AsyncMock(
        side_effect=[
            _rpc_value([unparsed, {"account": None}]),
            _rpc_value({"amount": "777"}),
        ]
    )

    with (
        patch.object(client, "_request_rpc_json", rpc),
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
    ):
        balance = await client.get_token_balance(MINT)

    assert balance == 777
    assert rpc.await_args_list[1].args[0]["method"] == "getTokenAccountBalance"


@pytest.fixture
def client():
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        __import__("base58").b58encode(keypair.to_bytes()).decode(),
        "https://example.com",
    )


def test_u64_serialization():
    assert PumpFunExecutionClient._u64(0) == bytes([0, 0, 0, 0, 0, 0, 0, 0])
    assert PumpFunExecutionClient._u64(1) == bytes([1, 0, 0, 0, 0, 0, 0, 0])
    assert PumpFunExecutionClient._u64(2**63) == bytes([0, 0, 0, 0, 0, 0, 0, 0x80])


def test_get_wallet_pubkey(client):
    assert isinstance(client.get_wallet_pubkey(), str)
    assert len(client.get_wallet_pubkey()) > 20


def test_slippage_normalizer_and_error_classification(client):
    assert client.normalize_slippage_bps(None, default=250) == 250
    assert client.normalize_slippage_bps(123) == 123
    with pytest.raises(ValueError):
        client.normalize_slippage_bps(10_001)
    assert client.classify_execution_error("RPC timeout") == "rpc_timeout"
    assert client.classify_execution_error("HTTP 503") == "server_error"
    assert client.classify_execution_error("transaction failed") == "transaction_failed"


def test_partial_fill_evaluation_and_reassessment(client):
    fill = client.evaluate_fill_completion(100, 40)
    assert fill["status"] == "partial"
    assert fill["remaining_amount"] == 60
    assert client.should_reassess_partial_fill(100, 40) is True
    assert client.should_reassess_partial_fill(100, 100) is False
    assert client.should_reassess_partial_fill(100, 0) is False


def test_execution_lock_and_health_score_update(client):
    assert client.execution_health_score == 100.0
    assert client.failed_execution_attempts == 0
    client.execution_health_score = 20.0
    client.failed_execution_attempts = 2
    assert client.execution_health_score < 100.0
    assert client.failed_execution_attempts == 2


def test_unit_conversions(client):
    assert client.sol_to_lamports(1.0) == 1_000_000_000
    assert client.sol_to_lamports(0.05) == 50_000_000
    assert client.lamports_to_sol(1_000_000_000) == 1.0
    assert client.lamports_to_sol(50_000_000) == 0.05
    with pytest.raises(ValueError):
        client.sol_to_lamports(-1.0)
    with pytest.raises(ValueError):
        client.lamports_to_sol(-100)


MINT_REGRESSIONS = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def _client_regressions(**kwargs) -> PumpFunExecutionClient:
    key = base58.b58encode(Keypair().to_bytes()).decode()
    return PumpFunExecutionClient(key, "https://mock-rpc.invalid", **kwargs)


@pytest.mark.regression("BUG-35")
async def test_token_balance_rpc_failure_raises_not_zero():
    client = _client_regressions()
    client._request_rpc_json = AsyncMock(side_effect=RuntimeError("timeout"))
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(MINT_REGRESSIONS)


@pytest.mark.regression("BUG-35")
async def test_token_balance_error_payload_raises():
    client = _client_regressions()
    client._request_rpc_json = AsyncMock(
        return_value={"error": {"code": -32005, "message": "node behind"}}
    )
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(MINT_REGRESSIONS)


@pytest.mark.regression("BUG-35")
async def test_token_balance_confirmed_zero_cases():
    client = _client_regressions()
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": []}})
    assert await client.get_token_balance(MINT_REGRESSIONS) == 0

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
    assert await client.get_token_balance(MINT_REGRESSIONS) == 0


@pytest.mark.regression("BUG-68", "BUG-69")
async def test_token_program_errors_raise_and_success_is_cached():
    client = _client_regressions()
    client.rpc_pool.request = AsyncMock(side_effect=RuntimeError("down"))
    with pytest.raises(TokenProgramUnavailableError):
        await client.get_token_program_for_mint(MINT_REGRESSIONS)

    client.rpc_pool.request = AsyncMock(
        return_value={"result": {"value": {"owner": TOKEN_2022_PROGRAM_ID_STR}}}
    )
    first = await client.get_token_program_for_mint(MINT_REGRESSIONS)
    second = await client.get_token_program_for_mint(MINT_REGRESSIONS)
    assert str(first) == str(second) == TOKEN_2022_PROGRAM_ID_STR
    assert client.rpc_pool.request.await_count == 1
