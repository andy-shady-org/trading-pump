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
