"""Deterministic constant-product AMM bonding curve pricing and price impact
calculations.

This module implements exact constant-product invariant (k = x * y) math for Pump.fun
bonding curves. In Pump.fun:
  - Initial virtual SOL reserve (x_0) = 30.0 SOL (30_000_000_000 Lamports)
  - Initial virtual token reserve (y_0) = 1,073,000,000 tokens (1_073_000_000_000_000
  raw units)
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

Number = int | float

INITIAL_VIRTUAL_SOL_LAMPORTS: int = 30_000_000_000
INITIAL_VIRTUAL_TOKEN_RAW: int = 1_073_000_000_000_000
TOTAL_TOKEN_SUPPLY_RAW: int = 1_000_000_000_000_000
CURVE_OFFSET_TOLERANCE: float = 0.01
# Market cap of a fresh curve: 30 SOL virtual x 1e9 supply / 1.073e9 virtual
# tokens, about 27.96 SOL. The 30 SOL figure is the virtual reserve, not a
# market cap (BUG-137).
LAUNCH_MARKET_CAP_SOL: float = (INITIAL_VIRTUAL_SOL_LAMPORTS / 1_000_000_000.0) * (
    TOTAL_TOKEN_SUPPLY_RAW / INITIAL_VIRTUAL_TOKEN_RAW
)
# Tokens a standard curve sells before it completes (793.1 M of the 1 B supply).
INITIAL_REAL_TOKEN_RAW: int = 793_100_000_000_000
# Market cap of a standard curve with every real token sold: about 410.88 SOL
# (115.0 SOL virtual over 279.9 M virtual tokens). A create event at this
# market cap is a coin whose creator bought the whole curve in the create
# transaction; it graduated before anyone else could buy (BUG-146).
COMPLETE_CURVE_MARKET_CAP_SOL: float = (
    INITIAL_VIRTUAL_SOL_LAMPORTS
    * INITIAL_VIRTUAL_TOKEN_RAW
    / (INITIAL_VIRTUAL_TOKEN_RAW - INITIAL_REAL_TOKEN_RAW)
    / 1_000_000_000.0
) * (TOTAL_TOKEN_SUPPLY_RAW / (INITIAL_VIRTUAL_TOKEN_RAW - INITIAL_REAL_TOKEN_RAW))


def curve_reserve_anomaly(
    virtual_sol_reserves: int,
    virtual_token_reserves: int,
    real_sol_reserves: int,
    *,
    complete: bool = False,
    tolerance: float = CURVE_OFFSET_TOLERANCE,
) -> str | None:
    """Why an active curve's reserves don't match the standard Pump.fun layout.

    On a standard curve ``virtual_sol - real_sol`` is always the 30 SOL
    initial virtual reserve. A curve variant seen on mainnet reports
    764-105,860 SOL of virtual reserves with no real SOL and decodes to market
    caps 25x-3,500x too high (BUG-104), so it must not be priced or traded.
    Returns ``None`` for a standard curve, and for complete or empty curves
    (handled elsewhere). The token side was standard on every variant seen.
    """
    if complete or virtual_sol_reserves <= 0 or virtual_token_reserves <= 0:
        return None
    sol_offset = virtual_sol_reserves - real_sol_reserves
    if abs(sol_offset - INITIAL_VIRTUAL_SOL_LAMPORTS) > (
        INITIAL_VIRTUAL_SOL_LAMPORTS * tolerance
    ):
        return (
            f"virtual SOL offset {sol_offset / 1e9:.4f} SOL "
            f"!= {INITIAL_VIRTUAL_SOL_LAMPORTS / 1e9:.1f} SOL"
        )
    return None


def calculate_spot_price(
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
) -> float:
    """Calculate instantaneous spot price P = virtual_sol_reserves /
    virtual_token_reserves.

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
    """Calculate market capitalization in SOL based on current spot price and total
    token supply.

    The SOL side is *guessed*: a value of at least 1,000,000 is read as lamports.
    ``virtual_token_reserves`` and ``total_supply`` must be in the same unit
    (raw by default), or the result is off by 10^6. Code that holds on-chain
    reserves should call :func:`market_cap_sol_from_reserves`, which takes
    explicit units (BUG-137).

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


def market_cap_sol_from_reserves(
    virtual_sol_lamports: Number,
    virtual_token_raw: Number,
    total_supply_raw: Number = TOTAL_TOKEN_SUPPLY_RAW,
) -> float:
    """Market cap in SOL from on-chain reserves with explicit units (BUG-137).

    Lamports and raw token units only, as the bonding-curve account stores
    them; no unit guessing. Returns 0.0 for empty or invalid reserves.
    """
    if virtual_sol_lamports <= 0 or virtual_token_raw <= 0 or total_supply_raw <= 0:
        return 0.0
    return (float(virtual_sol_lamports) / 1_000_000_000.0) * (
        float(total_supply_raw) / float(virtual_token_raw)
    )


def calculate_buy_tokens_out(
    sol_amount: Number,
    virtual_sol_reserves: Number,
    virtual_token_reserves: Number,
    *,
    slippage_bps: int = 0,
    fee_bps: int = 0,
) -> int:
    """Calculate output token amount for a given SOL (or Lamport) input.

    ``fee_bps`` is the total Pump.fun fee (protocol + creator) charged on top of
    the curve input; it is removed from ``sol_amount`` before pricing (BUG-66).

    Formula:
        Delta_y = (virtual_token_reserves * sol_amount) / (virtual_sol_reserves +
        sol_amount)

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

    if fee_bps > 0:
        sol_amount = (sol_amount * 10_000) // (10_000 + fee_bps)
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
    fee_bps: int = 0,
) -> int:
    """Calculate output SOL (or Lamport) amount for a given token input.

    ``fee_bps`` is the total Pump.fun fee deducted from the curve output (BUG-66).

    Formula:
        Delta_x = (virtual_sol_reserves * token_amount) / (virtual_token_reserves +
        token_amount)

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
    if fee_bps > 0:
        sol_out = int((sol_out * (10_000 - fee_bps)) // 10_000)
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
        Positive float representing relative spot price increase (e.g., 0.0201 for
        +2.01%).
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
        Negative float representing relative spot price decrease (e.g., -0.0184 for
        -1.84%).
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
