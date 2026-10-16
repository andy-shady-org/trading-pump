"""Property tests for the bonding-curve maths in ``sdk/curve.py``.

Reserves are drawn up to the u64 range the on-chain account can hold, so the
integer maths is exercised far beyond a fresh curve (AGENTS.md: no 64-bit
overflow on token/SOL conversions).
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from pumpfun_trading.sdk.curve import (
    calculate_buy_price_impact,
    calculate_buy_tokens_out,
    calculate_sell_price_impact,
    calculate_sell_sol_out,
    calculate_spot_price,
)

U64 = 2**64 - 1
reserve = st.integers(min_value=1, max_value=U64)
amount = st.integers(min_value=1, max_value=U64)
bps = st.integers(min_value=0, max_value=10_000)


@given(sol=amount, v_sol=reserve, v_tokens=reserve)
def test_buy_tokens_out_never_drains_the_curve(
    sol: int, v_sol: int, v_tokens: int
) -> None:
    out = calculate_buy_tokens_out(sol, v_sol, v_tokens)

    assert isinstance(out, int)
    assert 0 <= out < v_tokens


@given(sol=amount, extra=amount, v_sol=reserve, v_tokens=reserve)
def test_buy_tokens_out_is_monotonic_in_sol_in(
    sol: int, extra: int, v_sol: int, v_tokens: int
) -> None:
    assert calculate_buy_tokens_out(sol, v_sol, v_tokens) <= calculate_buy_tokens_out(
        sol + extra, v_sol, v_tokens
    )


@given(tokens=amount, v_sol=reserve, v_tokens=reserve)
def test_sell_sol_out_never_drains_the_curve(
    tokens: int, v_sol: int, v_tokens: int
) -> None:
    out = calculate_sell_sol_out(tokens, v_tokens, v_sol)

    assert isinstance(out, int)
    assert 0 <= out < v_sol


@given(tokens=amount, extra=amount, v_sol=reserve, v_tokens=reserve)
def test_sell_sol_out_is_monotonic_in_tokens_in(
    tokens: int, extra: int, v_sol: int, v_tokens: int
) -> None:
    assert calculate_sell_sol_out(tokens, v_tokens, v_sol) <= calculate_sell_sol_out(
        tokens + extra, v_tokens, v_sol
    )


@given(sol=amount, v_sol=reserve, v_tokens=reserve, fee=bps, slippage=bps)
def test_buy_fee_and_slippage_only_reduce_tokens_out(
    sol: int, v_sol: int, v_tokens: int, fee: int, slippage: int
) -> None:
    plain = calculate_buy_tokens_out(sol, v_sol, v_tokens)
    charged = calculate_buy_tokens_out(
        sol, v_sol, v_tokens, fee_bps=fee, slippage_bps=slippage
    )

    assert 0 <= charged <= plain


@given(tokens=amount, v_sol=reserve, v_tokens=reserve, fee=bps, slippage=bps)
def test_sell_fee_and_slippage_only_reduce_sol_out(
    tokens: int, v_sol: int, v_tokens: int, fee: int, slippage: int
) -> None:
    plain = calculate_sell_sol_out(tokens, v_tokens, v_sol)
    charged = calculate_sell_sol_out(
        tokens, v_tokens, v_sol, fee_bps=fee, slippage_bps=slippage
    )

    assert 0 <= charged <= plain


@given(sol=amount, v_sol=reserve, v_tokens=reserve)
def test_buy_then_sell_round_trip_never_returns_more_sol(
    sol: int, v_sol: int, v_tokens: int
) -> None:
    tokens = calculate_buy_tokens_out(sol, v_sol, v_tokens)
    assume(tokens > 0)

    sol_back = calculate_sell_sol_out(tokens, v_tokens - tokens, v_sol + sol)

    assert sol_back <= sol


@given(
    v_sol=st.integers(min_value=1, max_value=10**15),
    v_tokens=st.integers(min_value=1, max_value=10**18),
    sol=st.integers(min_value=1, max_value=10**15),
)
def test_buy_raises_and_sell_lowers_the_spot_price(
    v_sol: int, v_tokens: int, sol: int
) -> None:
    tokens = calculate_buy_tokens_out(sol, v_sol, v_tokens)
    assume(0 < tokens < v_tokens)
    before = calculate_spot_price(v_sol, v_tokens)

    assert calculate_spot_price(v_sol + sol, v_tokens - tokens) >= before
    assert calculate_buy_price_impact(sol, v_sol, v_tokens) > 0.0
    assert calculate_sell_price_impact(tokens, v_sol, v_tokens) < 0.0


@given(
    sol=st.integers(max_value=0),
    v_sol=st.integers(max_value=U64),
    v_tokens=st.integers(max_value=U64),
)
def test_non_positive_inputs_quote_zero(sol: int, v_sol: int, v_tokens: int) -> None:
    assert calculate_buy_tokens_out(sol, v_sol, v_tokens) == 0
    assert calculate_sell_sol_out(sol, v_tokens, v_sol) == 0
    assert calculate_buy_price_impact(sol, v_sol, v_tokens) == 0.0
