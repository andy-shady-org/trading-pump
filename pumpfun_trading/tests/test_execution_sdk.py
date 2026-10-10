import asyncio

import pytest

from solders.keypair import Keypair

from pumpfun_trading.sdk.execution import PumpFunExecutionClient


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
