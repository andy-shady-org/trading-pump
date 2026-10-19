"""Unit tests for ``sdk/raydium_execution.py``: Raydium swap instructions, wrapped-SOL
handling and graduated-token buy/sell transactions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from pumpfun_trading.infra.rpc_pool import RpcConnectionPool, RpcEndpoint
from pumpfun_trading.sdk.execution import (
    TOKEN_PROGRAM_ID_STR,
    PumpFunExecutionClient,
    TokenBalanceUnavailableError,
)
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys, calculate_raydium_swap_out
from pumpfun_trading.tests.support.constants import (
    SAMPLE_MINT,
    SAMPLE_PRIVATE_KEY,
)
from pumpfun_trading.tests.support.factories import make_pool_keys

# The real getTransaction cost reader is under test here (see tests/conftest.py).
USES_REAL_TRANSACTION_COSTS = True


def _client() -> PumpFunExecutionClient:
    return PumpFunExecutionClient(private_key_b58=str(Keypair()))


# --- RPC lookups and failure modes ------------------------------------------------


def _rpc_value(value: Any) -> dict[str, Any]:
    return {"result": {"value": value}}


# --- Raydium builders ------------------------------------------------------------------


def _pool() -> RaydiumPoolKeys:
    fields = {name: str(Pubkey.new_unique()) for name in RaydiumPoolKeys.__slots__}
    fields["pc_mint"] = "So11111111111111111111111111111111111111112"
    return RaydiumPoolKeys(**fields)


def _vaults(coin: str, pc: str) -> AsyncMock:
    return AsyncMock(
        side_effect=[_rpc_value({"amount": coin}), _rpc_value({"amount": pc})]
    )


async def test_build_raydium_buy_tx_quotes_min_out_from_vault_reserves() -> None:
    client = _client()
    pool = _pool()
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client, "_request_rpc_json", _vaults("1000000000000", "50000000000")
        ),
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        await client.build_raydium_buy_tx(pool, 0.1, slippage_bps=100)

    instructions = list(build.await_args.args[0]) if build.await_args else []
    # create WSOL ATA, wrap transfer, sync, create coin ATA, swap, close WSOL
    assert len(instructions) == 6
    _, quoted = calculate_raydium_swap_out(
        100_000_000, 50_000_000_000, 1_000_000_000_000, slippage_bps=100
    )
    swap_data = bytes(instructions[4].data)
    assert int.from_bytes(swap_data[1:9], "little") == 100_000_000
    assert int.from_bytes(swap_data[9:17], "little") == quoted


async def test_build_raydium_buy_tx_empty_pool_raises_zero_quote() -> None:
    client = _client()

    with patch.object(client, "_request_rpc_json", _vaults("0", "0")):
        with pytest.raises(RuntimeError, match="zero output"):
            await client.build_raydium_buy_tx(_pool(), 0.1)


async def test_raydium_reserves_missing_vault_amount_raises() -> None:
    client = _client()
    rpc = AsyncMock(side_effect=[_rpc_value({"amount": "5"}), _rpc_value(None)])

    with patch.object(client, "_request_rpc_json", rpc):
        with pytest.raises(RuntimeError, match="vault balance unavailable"):
            await client._raydium_reserves(_pool())


async def test_build_raydium_sell_tx_float_min_output_converted_to_lamports() -> None:
    client = _client()
    build = AsyncMock(return_value="tx")

    with (
        patch.object(
            client,
            "get_token_program_for_mint",
            AsyncMock(return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)),
        ),
        patch.object(client, "_build_tx_with_instructions", build),
    ):
        await client.build_raydium_sell_tx(_pool(), 1_000, min_sol_output=0.5)

    instructions = list(build.await_args.args[0]) if build.await_args else []
    # create WSOL ATA (no wrap), swap, close WSOL
    assert len(instructions) == 3
    swap_data = bytes(instructions[1].data)
    assert int.from_bytes(swap_data[1:9], "little") == 1_000
    assert int.from_bytes(swap_data[9:17], "little") == 500_000_000


@pytest.fixture
def client():
    keypair = Keypair.from_seed(b"01234567890123456789012345678901")
    return PumpFunExecutionClient(
        __import__("base58").b58encode(keypair.to_bytes()).decode(),
        "https://example.com",
    )


@pytest.mark.regression("BUG-35")
async def test_sdk_execution_extended_coverage():
    from solders.instruction import Instruction
    from solders.message import MessageV0

    client = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        use_jito=False,
    )

    # get_ata_exists with mock accounts
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    "not_dict",
                    {"account": "not_dict"},
                    {"account": {"data": "not_dict"}},
                    {"account": {"data": {"parsed": "not_dict"}}},
                    {"account": {"data": {"parsed": {"info": "not_dict"}}}},
                    {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": "other_mint",
                                        "owner": "other_owner",
                                    }
                                }
                            }
                        }
                    },
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
                    },
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is True

    # getTokenAccountBalance with missing amount: unreadable balance raises instead of reading as 0 (BUG-35)
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": {}}})
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(SAMPLE_MINT)

    # send_transaction with rpc_pool (endpoint_count > 1)
    ep1 = RpcEndpoint(url="https://rpc1.solana.com")
    ep2 = RpcEndpoint(url="https://rpc2.solana.com")
    pool = RpcConnectionPool(endpoints=[ep1, ep2])
    pool.broadcast_transaction = AsyncMock(
        return_value="sig_broadcast_12345678901234567890"
    )
    client.rpc_pool = pool

    msg = MessageV0.try_compile(
        payer=client.wallet,
        instructions=[Instruction(program_id=Pubkey.default(), accounts=[], data=b"")],
        address_lookup_table_accounts=[],
        recent_blockhash=Hash.default(),
    )
    tx = VersionedTransaction.populate(msg, [client.keypair.sign_message(bytes(msg))])

    sig = await client.send_transaction(tx)
    assert sig == "sig_broadcast_12345678901234567890"

    # confirm_transaction branches: None result, [None] status, err in status
    client._request_rpc_json = AsyncMock(
        side_effect=[
            {"result": {"value": None}},
            {"result": {"value": [None]}},
            {
                "result": {
                    "value": [
                        {
                            "confirmationStatus": "confirmed",
                            "err": {"InstructionError": 1},
                        }
                    ]
                }
            },
        ]
    )
    assert (
        await client.confirm_transaction("sig_test", max_retries=3, interval=0.01)
        is False
    )

    # raydium_buy with should_jito=False
    pool_keys = make_pool_keys(unique=False)
    client.build_raydium_buy_tx = AsyncMock(return_value=tx)
    client.send_transaction = AsyncMock(return_value="sig_ray_buy_12345678901234567890")
    res_sig = await client.raydium_buy(pool_keys, 0.05, use_jito=False)
    assert res_sig == "sig_ray_buy_12345678901234567890"

    await client.close()
    await pool.close()
