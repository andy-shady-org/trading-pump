"""Unit tests for ``sdk/pumpswap_execution.py``: resolving a graduated coin's
PumpSwap pool over RPC, pricing it and building / sending the sell (BUG-123).
RPC answers are the mainnet accounts in ``tests/support/payloads.py``."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.sdk import pumpswap as ps
from pumpfun_trading.sdk.execution import (
    PumpFunExecutionClient,
    PumpSwapPoolUnavailableError,
)
from pumpfun_trading.tests.support.payloads import (
    GRADUATED_BASE_VAULT_ADDRESS,
    GRADUATED_BASE_VAULT_B64,
    GRADUATED_BASE_VAULT_OWNER,
    GRADUATED_GLOBAL_CONFIG_ADDRESS,
    GRADUATED_GLOBAL_CONFIG_B64,
    GRADUATED_GLOBAL_CONFIG_OWNER,
    GRADUATED_MINT,
    GRADUATED_POOL,
    GRADUATED_POOL_B64,
    GRADUATED_POOL_OWNER,
    GRADUATED_QUOTE_VAULT_ADDRESS,
    GRADUATED_QUOTE_VAULT_B64,
    GRADUATED_QUOTE_VAULT_OWNER,
)
from pumpfun_trading.tests.support.constants import SAMPLE_PUMP_MINT

BASE_RESERVE = 193_377_869_697_216
QUOTE_RESERVE = 73_700_738_380 + 17_584_505_289


def _accounts() -> dict[str, dict[str, Any] | None]:
    def account(owner: str, data: str) -> dict[str, Any]:
        return {"owner": owner, "data": [data, "base64"]}

    return {
        GRADUATED_POOL: account(GRADUATED_POOL_OWNER, GRADUATED_POOL_B64),
        GRADUATED_GLOBAL_CONFIG_ADDRESS: account(
            GRADUATED_GLOBAL_CONFIG_OWNER, GRADUATED_GLOBAL_CONFIG_B64
        ),
        GRADUATED_BASE_VAULT_ADDRESS: account(
            GRADUATED_BASE_VAULT_OWNER, GRADUATED_BASE_VAULT_B64
        ),
        GRADUATED_QUOTE_VAULT_ADDRESS: account(
            GRADUATED_QUOTE_VAULT_OWNER, GRADUATED_QUOTE_VAULT_B64
        ),
    }


def _rpc(accounts: dict[str, dict[str, Any] | None]) -> AsyncMock:
    async def answer(payload: dict[str, Any], **_: Any) -> dict[str, Any]:
        assert payload["method"] == "getMultipleAccounts"
        return {"result": {"value": [accounts.get(a) for a in payload["params"][0]]}}

    return AsyncMock(side_effect=answer)


def _client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


async def test_market_state_prices_the_pool_on_the_curve_basis() -> None:
    client = _client()
    with patch.object(client, "_request_rpc_json", _rpc(_accounts())):
        state = await client.get_pumpswap_market_state(GRADUATED_MINT)
    assert state["pool"] == GRADUATED_POOL
    assert state["base_reserve"] == BASE_RESERVE
    assert state["quote_reserve"] == QUOTE_RESERVE
    assert state["fee_bps"] == 30
    assert state["base_token_program"] == GRADUATED_BASE_VAULT_OWNER
    assert state["market_cap_sol"] == pytest.approx(
        ps.pumpswap_market_cap_sol(BASE_RESERVE, QUOTE_RESERVE)
    )


async def test_quote_uses_live_reserves_and_fees() -> None:
    client = _client()
    with patch.object(client, "_request_rpc_json", _rpc(_accounts())):
        quoted = await client.quote_pumpswap_sell(
            GRADUATED_MINT, 1_000_000_000, slippage_bps=100
        )
    assert quoted == ps.pumpswap_sell_quote(
        1_000_000_000, BASE_RESERVE, QUOTE_RESERVE, fee_bps=30, slippage_bps=100
    )


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({GRADUATED_POOL: None}, "pool for .* not found"),
        ({GRADUATED_GLOBAL_CONFIG_ADDRESS: None}, "global_config for .* not found"),
        (
            {GRADUATED_POOL: {"owner": "x", "data": [GRADUATED_POOL_B64, "base64"]}},
            "not owned by the PumpSwap program",
        ),
        ({GRADUATED_BASE_VAULT_ADDRESS: None}, "vaults"),
    ],
)
async def test_pool_lookup_refuses_missing_or_foreign_accounts(
    change: dict[str, Any], match: str
) -> None:
    accounts = {**_accounts(), **change}
    client = _client()
    with (
        patch.object(client, "_request_rpc_json", _rpc(accounts)),
        pytest.raises(PumpSwapPoolUnavailableError, match=match),
    ):
        await client.get_pumpswap_pool(GRADUATED_MINT)


async def test_pool_lookup_refuses_a_pool_that_pairs_another_mint() -> None:
    client = _client()
    # Serve the graduated pool's bytes at the PDA of a different mint.
    other_pool = str(ps.canonical_pool_address(SAMPLE_PUMP_MINT))
    accounts = {**_accounts(), other_pool: _accounts()[GRADUATED_POOL]}
    with (
        patch.object(client, "_request_rpc_json", _rpc(accounts)),
        pytest.raises(PumpSwapPoolUnavailableError, match="does not pair"),
    ):
        await client.get_pumpswap_pool(SAMPLE_PUMP_MINT)


async def test_market_state_refuses_an_empty_pool() -> None:
    accounts = _accounts()
    empty = bytearray(64 + 8)
    accounts[GRADUATED_BASE_VAULT_ADDRESS] = {
        "owner": GRADUATED_BASE_VAULT_OWNER,
        "data": [base64.b64encode(bytes(empty)).decode(), "base64"],
    }
    client = _client()
    with (
        patch.object(client, "_request_rpc_json", _rpc(accounts)),
        pytest.raises(PumpSwapPoolUnavailableError, match="empty"),
    ):
        await client.get_pumpswap_market_state(GRADUATED_MINT)


async def test_build_sell_tx_unwraps_and_closes_the_token_account() -> None:
    client = _client()
    build = AsyncMock(return_value="tx")
    with (
        patch.object(client, "_request_rpc_json", _rpc(_accounts())),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        tx = await client.build_pumpswap_sell_tx(
            GRADUATED_MINT, 1_000_000_000, slippage_bps=300, close_token_account=True
        )
    assert tx == "tx"
    instructions = list(build.await_args.args[0]) if build.await_args else []
    # create WSOL ATA, PumpSwap sell, close WSOL ATA, close token account.
    assert len(instructions) == 4
    sell = instructions[1]
    assert str(sell.program_id) == ps.PUMP_AMM_PROGRAM_ID
    min_out = int.from_bytes(bytes(sell.data)[16:24], "little")
    assert min_out == ps.pumpswap_sell_quote(
        1_000_000_000, BASE_RESERVE, QUOTE_RESERVE, fee_bps=30, slippage_bps=300
    )
    # Token-2022 mint: the base program comes from the vault owner.
    assert str(sell.accounts[11].pubkey) == GRADUATED_BASE_VAULT_OWNER
    assert str(instructions[3].program_id) == GRADUATED_BASE_VAULT_OWNER


async def test_build_sell_tx_falls_back_to_the_mint_program_and_refuses_zero_out() -> (
    None
):
    accounts = _accounts()
    accounts[GRADUATED_BASE_VAULT_ADDRESS] = {
        **dict(accounts[GRADUATED_BASE_VAULT_ADDRESS] or {}),
        "owner": "",
    }
    client = _client()
    build = AsyncMock(return_value="tx")
    program = AsyncMock(return_value=Pubkey.from_string(GRADUATED_BASE_VAULT_OWNER))
    with (
        patch.object(client, "_request_rpc_json", _rpc(accounts)),
        patch.object(client, "_build_tx_with_instructions", build),
        patch.object(client, "get_token_program_for_mint", program),
    ):
        await client.build_pumpswap_sell_tx(GRADUATED_MINT, 1_000_000_000)
        program.assert_awaited_once()
        assert build.await_args is not None
        assert len(build.await_args.args[0]) == 3
        with pytest.raises(PumpSwapPoolUnavailableError, match="zero output"):
            await client.build_pumpswap_sell_tx(GRADUATED_MINT, 0)


@pytest.mark.parametrize("use_jito", [False, True])
async def test_pumpswap_sell_sends_over_rpc_or_jito(use_jito: bool) -> None:
    client = _client()
    with (
        patch.object(client, "build_pumpswap_sell_tx", AsyncMock(return_value="tx")),
        patch.object(client, "send_transaction", AsyncMock(return_value="rpc-sig")),
        patch.object(
            client,
            "send_jito_bundle_with_fallback",
            AsyncMock(return_value="jito-sig"),
        ),
        patch.object(
            client, "calculate_dynamic_jito_tip", AsyncMock(return_value=1_000)
        ),
    ):
        sig = await client.pumpswap_sell(
            GRADUATED_MINT, 5, use_jito=use_jito, close_token_account=True
        )
        tip = client.build_pumpswap_sell_tx.await_args.kwargs["tip_lamports"]  # type: ignore[attr-defined]
    assert sig == ("jito-sig" if use_jito else "rpc-sig")
    assert tip == (1_000 if use_jito else None)
