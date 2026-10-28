"""Unit tests for Pump.fun constant-product bonding curve math and price impact calculations (BUG-13)."""

import pytest

from pumpfun_trading.sdk.curve import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RAW,
    TOTAL_TOKEN_SUPPLY_RAW,
    calculate_buy_execution_slippage,
    calculate_buy_price_impact,
    calculate_buy_tokens_out,
    calculate_market_cap_sol,
    calculate_sell_execution_slippage,
    calculate_sell_price_impact,
    calculate_sell_sol_out,
    calculate_spot_price,
    curve_reserve_anomaly,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.tests.support.payloads import (
    NON_STANDARD_CURVE_RESERVES,
    STANDARD_CURVE_RESERVES,
)


def test_spot_price_and_market_cap():
    # Initial Pump.fun curve reserves: 30 SOL and 1.073B tokens
    x_sol = 30.0
    y_tokens = 1_073_000_000.0
    p0 = calculate_spot_price(x_sol, y_tokens)
    assert p0 == pytest.approx(30.0 / 1_073_000_000.0, rel=1e-6)

    mc_sol = calculate_market_cap_sol(x_sol, y_tokens, total_supply=1_000_000_000.0)
    assert mc_sol == pytest.approx(27.958993476, rel=1e-5)

    # In raw on-chain units (Lamports & raw token units with 6 decimals)
    p0_raw = calculate_spot_price(
        INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW
    )
    assert p0_raw > 0
    mc_raw = calculate_market_cap_sol(
        INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW, TOTAL_TOKEN_SUPPLY_RAW
    )
    assert mc_raw == pytest.approx(27.958993476, rel=1e-5)

    # Edge cases: zero or negative reserves
    assert calculate_spot_price(0, 100) == 0.0
    assert calculate_spot_price(100, 0) == 0.0
    assert calculate_spot_price(-10, 100) == 0.0
    assert calculate_market_cap_sol(0, 100) == 0.0
    assert calculate_market_cap_sol(100, 0) == 0.0
    assert calculate_market_cap_sol(100, 100, total_supply=0) == 0.0


def test_buy_tokens_out_and_constant_product_invariant():
    x = 30_000_000_000  # 30 SOL in Lamports
    y = 1_073_000_000_000_000  # 1.073B tokens in raw units
    dx = 300_000_000  # 0.3 SOL buy

    tokens_out = calculate_buy_tokens_out(dx, x, y)
    # Expected: (1_073_000_000_000_000 * 300_000_000) // (30_300_000_000)
    expected_out = (y * dx) // (x + dx)
    assert tokens_out == expected_out
    assert tokens_out == 10_623_762_376_237  # ~10.62M tokens

    # Verify constant product invariant: (x + dx) * (y - dy) == x * y (within integer rounding)
    k_initial = x * y
    k_post = (x + dx) * (y - tokens_out)
    assert abs(k_post - k_initial) < (
        x + dx
    )  # Difference is within 1 discrete unit of precision

    # Test slippage adjustment
    tokens_out_slippage = calculate_buy_tokens_out(
        dx, x, y, slippage_bps=500
    )  # 5% slippage
    assert tokens_out_slippage == int(tokens_out * 0.95)

    # Edge cases
    assert calculate_buy_tokens_out(0, x, y) == 0
    assert calculate_buy_tokens_out(-100, x, y) == 0
    assert calculate_buy_tokens_out(dx, 0, y) == 0
    assert calculate_buy_tokens_out(dx, x, 0) == 0


def test_sell_sol_out_and_constant_product_invariant():
    x = 30_000_000_000  # 30 SOL in Lamports
    y = 1_073_000_000_000_000  # 1.073B tokens in raw units
    dy = 10_000_000_000_000  # 10M tokens

    sol_out = calculate_sell_sol_out(dy, y, x)
    expected_out = (x * dy) // (y + dy)
    assert sol_out == expected_out
    assert sol_out == 277_008_310  # ~0.277 SOL

    # Verify constant product invariant: (x - dx) * (y + dy) == x * y (within rounding)
    k_initial = x * y
    k_post = (x - sol_out) * (y + dy)
    assert abs(k_post - k_initial) < (y + dy)

    # Test slippage adjustment
    sol_out_slippage = calculate_sell_sol_out(dy, y, x, slippage_bps=500)
    assert sol_out_slippage == int(sol_out * 0.95)

    # Edge cases
    assert calculate_sell_sol_out(0, y, x) == 0
    assert calculate_sell_sol_out(-100, y, x) == 0
    assert calculate_sell_sol_out(dy, 0, x) == 0
    assert calculate_sell_sol_out(dy, y, 0) == 0


@pytest.mark.regression("BUG-13")
def test_buy_price_impact_positive():
    """BUG-13: Buying tokens must yield positive price impact (P_1 > P_0)."""
    x = 30.0  # 30 SOL
    y = 1_073_000_000.0  # 1.073B tokens

    # 1. Buy 0.3 SOL (1.0% SOL addition)
    impact_03 = calculate_buy_price_impact(0.3, x, y)
    # Expected: ((30.3 / 30.0)^2) - 1.0 = (1.01)^2 - 1.0 = +0.0201 (+2.01%)
    assert impact_03 == pytest.approx(0.0201, rel=1e-5)
    assert impact_03 > 0.0

    # 2. Buy 3.0 SOL (10.0% SOL addition)
    impact_30 = calculate_buy_price_impact(3.0, x, y)
    # Expected: ((33.0 / 30.0)^2) - 1.0 = (1.10)^2 - 1.0 = +0.21 (+21.00%)
    assert impact_30 == pytest.approx(0.2100, rel=1e-5)
    assert impact_30 > 0.0

    # Works identically with Lamport / raw integer units
    impact_raw = calculate_buy_price_impact(
        300_000_000, INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW
    )
    assert impact_raw == pytest.approx(0.0201, rel=1e-5)

    # Edge cases: zero or negative
    assert calculate_buy_price_impact(0, x, y) == 0.0
    assert calculate_buy_price_impact(-1.0, x, y) == 0.0
    assert calculate_buy_price_impact(0.3, 0, y) == 0.0
    assert calculate_buy_price_impact(0.3, x, 0) == 0.0


@pytest.mark.regression("BUG-13")
def test_sell_price_impact_negative():
    """BUG-13: Selling tokens must yield negative price impact (P_1 < P_0)."""
    x = 30.0  # 30 SOL
    y = 1_073_000_000.0  # 1.073B tokens

    # Sell 10M tokens (~0.93% token addition)
    dy = 10_000_000.0
    impact_sell = calculate_sell_price_impact(dy, x, y)
    # Expected: (1_073_000_000 / 1_083_000_000)^2 - 1.0 ~= -0.018382 (-1.84%)
    expected_impact = (y / (y + dy)) ** 2 - 1.0
    assert impact_sell == pytest.approx(expected_impact, rel=1e-5)
    assert impact_sell < 0.0
    assert impact_sell == pytest.approx(-0.018382, rel=1e-3)

    # Works identically with raw units
    impact_raw = calculate_sell_price_impact(
        10_000_000_000_000, INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW
    )
    assert impact_raw == pytest.approx(expected_impact, rel=1e-5)

    # Edge cases: zero or negative
    assert calculate_sell_price_impact(0, x, y) == 0.0
    assert calculate_sell_price_impact(-1000, x, y) == 0.0
    assert calculate_sell_price_impact(dy, 0, y) == 0.0
    assert calculate_sell_price_impact(dy, x, 0) == 0.0


def test_execution_slippage():
    x = 30.0
    y = 1_073_000_000.0

    buy_slip = calculate_buy_execution_slippage(0.3, x)
    assert buy_slip == pytest.approx(0.01, rel=1e-5)  # +1.0%

    sell_slip = calculate_sell_execution_slippage(10_000_000.0, y)
    assert sell_slip == pytest.approx(
        -10_000_000.0 / 1_083_000_000.0, rel=1e-5
    )  # -0.92%

    assert calculate_buy_execution_slippage(0, x) == 0.0
    assert calculate_buy_execution_slippage(-1, x) == 0.0
    assert calculate_buy_execution_slippage(1, 0) == 0.0

    assert calculate_sell_execution_slippage(0, y) == 0.0
    assert calculate_sell_execution_slippage(-1, y) == 0.0
    assert calculate_sell_execution_slippage(1, 0) == 0.0


def test_execution_client_static_method_bindings():
    """Verify that PumpFunExecutionClient binds all curve methods statically."""
    client = PumpFunExecutionClient
    assert hasattr(client, "calculate_buy_price_impact")
    assert hasattr(client, "calculate_sell_price_impact")
    assert hasattr(client, "calculate_buy_tokens_out")
    assert hasattr(client, "calculate_sell_sol_out")
    assert hasattr(client, "calculate_sell_sol_output")
    assert hasattr(client, "calculate_spot_price")
    assert hasattr(client, "calculate_market_cap_sol")
    assert hasattr(client, "calculate_buy_execution_slippage")
    assert hasattr(client, "calculate_sell_execution_slippage")

    # Call through client
    impact = client.calculate_buy_price_impact(0.3, 30.0, 1_073_000_000.0)
    assert impact == pytest.approx(0.0201, rel=1e-5)

    sell_impact = client.calculate_sell_price_impact(
        10_000_000.0, 30.0, 1_073_000_000.0
    )
    assert sell_impact < 0.0

    tokens_out = client.calculate_buy_tokens_out(
        300_000_000, 30_000_000_000, 1_073_000_000_000_000
    )
    assert tokens_out > 0

    sol_out = client.calculate_sell_sol_output(
        10_000_000_000_000, 1_073_000_000_000_000, 30_000_000_000
    )
    assert sol_out > 0


@pytest.mark.regression("BUG-66")
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


# --- BUG-104: non-standard curve variants -----------------------------------------


@pytest.mark.regression("BUG-104")
@pytest.mark.parametrize("virtual_sol, real_sol", NON_STANDARD_CURVE_RESERVES)
def test_curve_reserve_anomaly_mainnet_variant_is_reported(
    virtual_sol: int, real_sol: int
) -> None:
    reason = curve_reserve_anomaly(virtual_sol, INITIAL_VIRTUAL_TOKEN_RAW, real_sol)

    assert reason is not None
    assert "virtual SOL offset" in reason


@pytest.mark.parametrize(
    "virtual_sol, real_sol",
    [*STANDARD_CURVE_RESERVES, (INITIAL_VIRTUAL_SOL_LAMPORTS, 0)],
)
def test_curve_reserve_anomaly_standard_curve_passes(
    virtual_sol: int, real_sol: int
) -> None:
    assert (
        curve_reserve_anomaly(virtual_sol, INITIAL_VIRTUAL_TOKEN_RAW, real_sol) is None
    )


@pytest.mark.parametrize(
    "virtual_sol, virtual_token, complete",
    [
        (105_860_003_350_032, INITIAL_VIRTUAL_TOKEN_RAW, True),
        (0, INITIAL_VIRTUAL_TOKEN_RAW, False),
        (105_860_003_350_032, 0, False),
    ],
)
def test_curve_reserve_anomaly_complete_or_empty_curve_is_not_judged(
    virtual_sol: int, virtual_token: int, complete: bool
) -> None:
    assert (
        curve_reserve_anomaly(virtual_sol, virtual_token, 0, complete=complete) is None
    )


def test_curve_reserve_anomaly_tolerance_bounds_the_offset() -> None:
    within = INITIAL_VIRTUAL_SOL_LAMPORTS + INITIAL_VIRTUAL_SOL_LAMPORTS // 200
    beyond = INITIAL_VIRTUAL_SOL_LAMPORTS + INITIAL_VIRTUAL_SOL_LAMPORTS // 50

    assert curve_reserve_anomaly(within, INITIAL_VIRTUAL_TOKEN_RAW, 0) is None
    assert curve_reserve_anomaly(beyond, INITIAL_VIRTUAL_TOKEN_RAW, 0) is not None


@pytest.mark.regression("BUG-137")
def test_market_cap_from_reserves_takes_explicit_units() -> None:
    from pumpfun_trading.sdk.curve import (
        LAUNCH_MARKET_CAP_SOL,
        market_cap_sol_from_reserves,
    )

    launch = market_cap_sol_from_reserves(
        INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW
    )
    assert launch == pytest.approx(27.959, abs=1e-3)
    assert LAUNCH_MARKET_CAP_SOL == pytest.approx(launch)
    # The launch market cap is not the 30 SOL virtual reserve.
    assert LAUNCH_MARKET_CAP_SOL != pytest.approx(30.0)
    # A small lamport value is still lamports here (the guessing helper would
    # read 500,000 lamports as 500,000 SOL).
    assert market_cap_sol_from_reserves(500_000, TOTAL_TOKEN_SUPPLY_RAW) == (
        pytest.approx(0.0005)
    )
    assert calculate_market_cap_sol(500_000, TOTAL_TOKEN_SUPPLY_RAW) == (
        pytest.approx(500_000.0)
    )
    for bad in ((0, 1), (1, 0), (-1, 1)):
        assert market_cap_sol_from_reserves(*bad) == 0.0
    assert market_cap_sol_from_reserves(1, 1, total_supply_raw=0) == 0.0
