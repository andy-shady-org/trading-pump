"""Unit tests for ``sdk/execution.py``: holder lookups (BUG-95), token-account
close (BUG-96) and transaction costs (FEAT-49)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.instructions import get_associated_token_address

from pumpfun_trading.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from pumpfun_trading.sdk.execution import (
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    CurveStateUnavailableError,
    PumpFunExecutionClient,
    TokenProgramUnavailableError,
)
from pumpfun_trading.sdk.jito import JitoBundleStatus
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys, calculate_raydium_swap_out

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


def _curve_state() -> dict[str, Any]:
    return {
        "creator": str(Pubkey.new_unique()),
        "virtual_sol_reserves": 30_000_000_000,
        "virtual_token_reserves": 1_073_000_000_000_000,
        "is_mayhem_mode": False,
    }


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


async def test_fetch_trade_curve_state_rpc_failure_raises_curve_unavailable() -> None:
    client = _client()

    with patch.object(
        client.rpc_pool, "request", AsyncMock(side_effect=RuntimeError("timeout"))
    ):
        with pytest.raises(CurveStateUnavailableError, match="timeout"):
            await client._fetch_trade_curve_state(MINT)


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


# --- Pump.fun transaction builders ---------------------------------------------------


def _empty_curve() -> dict[str, Any]:
    return {**_curve_state(), "virtual_sol_reserves": 0, "virtual_token_reserves": 0}


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
