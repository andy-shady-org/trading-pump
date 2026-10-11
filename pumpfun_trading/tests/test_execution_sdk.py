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


def test_unit_conversions(client):
    assert client.sol_to_lamports(1.0) == 1_000_000_000
    assert client.sol_to_lamports(0.05) == 50_000_000
    assert client.lamports_to_sol(1_000_000_000) == 1.0
    assert client.lamports_to_sol(50_000_000) == 0.05
    with pytest.raises(ValueError):
        client.sol_to_lamports(-1.0)
    with pytest.raises(ValueError):
        client.lamports_to_sol(-100)


def test_bonding_curve_data_decoding_and_sell_calculation():
    # 8 discriminator bytes + 8 u64 virtual token + 8 u64 virtual sol + 8 u64 real token + 8 u64 real sol + 8 u64 supply + 1 bool complete
    raw = (
        b"\x17\xb7\xf8\x37\x60\xd8\xac\x60"
        + (1_073_000_000_000_000).to_bytes(8, "little")
        + (30_000_000_000).to_bytes(8, "little")
        + (793_100_000_000_000).to_bytes(8, "little")
        + (0).to_bytes(8, "little")
        + (1_000_000_000_000_000).to_bytes(8, "little")
        + bytes([0])
    )
    decoded = PumpFunExecutionClient.decode_bonding_curve_data(raw)
    assert decoded["virtual_token_reserves"] == 1_073_000_000_000_000
    assert decoded["virtual_sol_reserves"] == 30_000_000_000
    assert decoded["complete"] is False
    assert decoded["price_sol"] > 0
    assert decoded["market_cap_sol"] > 0

    with pytest.raises(ValueError):
        PumpFunExecutionClient.decode_bonding_curve_data(b"too_short")

    sol_out = PumpFunExecutionClient.calculate_sell_sol_output(
        token_amount=1_000_000_000,
        virtual_token_reserves=1_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        slippage_bps=500,
    )
    assert sol_out > 0


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
