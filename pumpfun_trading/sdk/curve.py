"""Deterministic constant-product AMM bonding curve pricing and price impact calculations.

This module implements exact constant-product invariant (k = x * y) math for Pump.fun
bonding curves. In Pump.fun:
  - Initial virtual SOL reserve (x_0) = 30.0 SOL (30_000_000_000 Lamports)
  - Initial virtual token reserve (y_0) = 1,073,000,000 tokens (1_073_000_000_000_000 raw units)
  - Total token supply = 1,000,000,000 tokens (1_000_000_000_000_000 raw units)

When buying tokens with SOL:
  - SOL is added to the pool: x' = x + Delta_x
  - Tokens are removed from the pool: y' = y - Delta_y
  - Delta_y = (y * Delta_x) / (x + Delta_x)
  - Post-buy spot price increases: P_1 = x' / y' > P_0 (positive price impact)

When selling tokens for SOL:
  - Tokens are added to the pool: y' = y + Delta_y
  - SOL is removed from the pool: x' = x - Delta_x
  - Delta_x = (x * Delta_y) / (y + Delta_y)
  - Post-sell spot price decreases: P_1 = x' / y' < P_0 (negative price impact)
"""

from __future__ import annotations

from typing import Union

Number = Union[int, float]

INITIAL_VIRTUAL_SOL_LAMPORTS: int = 30_000_000_000
INITIAL_VIRTUAL_TOKEN_RAW: int = 1_073_000_000_000_000
TOTAL_TOKEN_SUPPLY_RAW: int = 1_000_000_000_000_000


def calculate_spot_price(
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
) -> float:
    """Calculate instantaneous spot price P = virtual_sol_reserves / virtual_token_reserves.

    Args:
        virtual_sol_reserves: Virtual SOL reserves (in SOL or Lamports).
        virtual_token_reserves: Virtual token reserves (in tokens or raw units).

    Returns:
        Spot price (SOL/token or Lamports/raw unit). Returns 0.0 if invalid reserves.
    """
    if virtual_token_reserves <= 0 or virtual_sol_reserves <= 0:
        return 0.0
    return float(virtual_sol_reserves) / float(virtual_token_reserves)


def calculate_market_cap_sol(
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
    total_supply: Number = TOTAL_TOKEN_SUPPLY_RAW,
) -> float:
    """Calculate market capitalization in SOL based on current spot price and total token supply.

    Args:
        virtual_sol_reserves: Virtual SOL reserves (SOL or Lamports).
        virtual_token_reserves: Virtual token reserves (tokens or raw units).
        total_supply: Total token supply (default: 1B tokens / 10^15 raw units).

    Returns:
        Market cap in SOL.
    """
    if virtual_token_reserves <= 0 or virtual_sol_reserves <= 0 or total_supply <= 0:
        return 0.0

    sol_amount = float(virtual_sol_reserves)
    if sol_amount >= 1_000_000:  # Lamports representation
        sol_amount = sol_amount / 1_000_000_000.0

    return sol_amount * (float(total_supply) / float(virtual_token_reserves))


def calculate_buy_tokens_out(
    sol_amount: Number,
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
    *,
    slippage_bps: int = 0,
) -> int:
    """Calculate output token amount for a given SOL (or Lamport) input.

    Formula:
        Delta_y = (virtual_token_reserves * sol_amount) / (virtual_sol_reserves + sol_amount)

    Args:
        sol_amount: SOL or Lamports input amount.
        virtual_sol_reserves: Virtual SOL reserves (same unit as sol_amount).
        virtual_token_reserves: Virtual token reserves.
        slippage_bps: Slippage tolerance in basis points (0-10,000).

    Returns:
        Output token amount (integer), adjusted for slippage if specified.
    """
    if sol_amount <= 0 or virtual_sol_reserves <= 0 or virtual_token_reserves <= 0:
        return 0

    tokens_out = int(
        (virtual_token_reserves * sol_amount) // (virtual_sol_reserves + sol_amount)
    )
    if slippage_bps > 0:
        tokens_out = max(0, int((tokens_out * (10_000 - slippage_bps)) // 10_000))
    return tokens_out


def calculate_sell_sol_out(
    token_amount: Number,
    virtual_token_reserves: Number,
    virtual_sol_reserves: Number,
    *,
    slippage_bps: int = 0,
) -> int:
    """Calculate output SOL (or Lamport) amount for a given token input.

    Formula:
        Delta_x = (virtual_sol_reserves * token_amount) / (virtual_token_reserves + token_amount)

    Args:
        token_amount: Token input amount.
        virtual_token_reserves: Virtual token reserves.
        virtual_sol_reserves: Virtual SOL reserves.
        slippage_bps: Slippage tolerance in basis points (0-10,000).

    Returns:
        Output SOL/Lamport amount (integer), adjusted for slippage if specified.
    """
    if token_amount <= 0 or virtual_sol_reserves <= 0 or virtual_token_reserves <= 0:
        return 0

    sol_out = int(
        (virtual_sol_reserves * token_amount) // (virtual_token_reserves + token_amount)
    )
    if slippage_bps > 0:
        sol_out = max(0, int((sol_out * (10_000 - slippage_bps)) // 10_000))
    return sol_out


def calculate_buy_price_impact(
    sol_amount: Number,
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
) -> float:
    """Calculate post-trade price impact for buying tokens with SOL.

    When buying with Delta_x SOL:
        x' = x + Delta_x
        y' = y - Delta_y = (x * y) / (x + Delta_x)
        P_0 = x / y
        P_1 = x' / y' = (x + Delta_x)^2 / (x * y)
        Price Impact = (P_1 - P_0) / P_0 = ((x + Delta_x) / x)^2 - 1.0

    Args:
        sol_amount: SOL or Lamports input amount.
        virtual_sol_reserves: Virtual SOL reserves (same unit as sol_amount).
        virtual_token_reserves: Virtual token reserves.

    Returns:
        Positive float representing relative spot price increase (e.g., 0.0201 for +2.01%).
    """
    if sol_amount <= 0 or virtual_sol_reserves <= 0 or virtual_token_reserves <= 0:
        return 0.0

    x = float(virtual_sol_reserves)
    dx = float(sol_amount)
    ratio = (x + dx) / x
    return (ratio * ratio) - 1.0


def calculate_sell_price_impact(
    token_amount: Number,
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
) -> float:
    """Calculate post-trade price impact for selling tokens into the bonding curve.

    When selling Delta_y tokens:
        y' = y + Delta_y
        x' = x - Delta_x = (x * y) / (y + Delta_y)
        P_0 = x / y
        P_1 = x' / y' = (x * y) / (y + Delta_y)^2
        Price Impact = (P_1 - P_0) / P_0 = (y / (y + Delta_y))^2 - 1.0

    Args:
        token_amount: Token input amount.
        virtual_sol_reserves: Virtual SOL reserves.
        virtual_token_reserves: Virtual token reserves.

    Returns:
        Negative float representing relative spot price decrease (e.g., -0.0184 for -1.84%).
    """
    if token_amount <= 0 or virtual_sol_reserves <= 0 or virtual_token_reserves <= 0:
        return 0.0

    y = float(virtual_token_reserves)
    dy = float(token_amount)
    ratio = y / (y + dy)
    return (ratio * ratio) - 1.0


def calculate_buy_execution_slippage(
    sol_amount: Number,
    virtual_sol_reserves: Number,
) -> float:
    """Calculate execution slippage relative to initial spot price for a buy.

    Execution price P_exec = Delta_x / Delta_y = (x + Delta_x) / y.
    Slippage = (P_exec - P_0) / P_0 = Delta_x / x.

    Args:
        sol_amount: SOL or Lamports input amount.
        virtual_sol_reserves: Virtual SOL reserves.

    Returns:
        Positive float representing execution slippage (e.g., 0.01 for +1.00%).
    """
    if sol_amount <= 0 or virtual_sol_reserves <= 0:
        return 0.0
    return float(sol_amount) / float(virtual_sol_reserves)


def calculate_sell_execution_slippage(
    token_amount: Number,
    virtual_token_reserves: Number,
) -> float:
    """Calculate execution slippage relative to initial spot price for a sell.

    Execution price P_exec = Delta_x / Delta_y = x / (y + Delta_y).
    Slippage = (P_exec - P_0) / P_0 = -Delta_y / (y + Delta_y).

    Args:
        token_amount: Token input amount.
        virtual_token_reserves: Virtual token reserves.

    Returns:
        Negative float representing execution slippage (e.g., -0.0092 for -0.92%).
    """
    if token_amount <= 0 or virtual_token_reserves <= 0:
        return 0.0
    y = float(virtual_token_reserves)
    dy = float(token_amount)
    return -dy / (y + dy)
