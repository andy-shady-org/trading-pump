"""Unit tests for ``sdk/execution.py`` holder lookups (BUG-95)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair

from pumpfun_trading.sdk.execution import PumpFunExecutionClient


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
