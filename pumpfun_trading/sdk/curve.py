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

import math
from collections import deque
from dataclasses import dataclass
from time import monotonic as _monotonic
from typing import Deque, Union

Number = Union[int, float]

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


@dataclass(frozen=True)
class CurveObservation:
    """Snapshot of bonding curve state at a specific point in time."""

    timestamp: float
    spot_price: float
    virtual_sol_reserves: float
    virtual_token_reserves: float
    sol_amount: float = 0.0
    is_buy: bool = True


class BondingCurveVolatilityEstimator:
    """Estimates real-time price velocity, rolling volatility, depth consumption, and dynamic slippage."""

    def __init__(
        self,
        window_seconds: float = 60.0,
        *,
        default_slippage_bps: int = 250,
        min_slippage_bps: int = 100,
        max_slippage_bps: int = 500,
        alpha_volatility: float = 1.0,
        beta_impact: float = 1.0,
    ) -> None:
        self.window_seconds = max(1.0, float(window_seconds))
        self.default_slippage_bps = int(default_slippage_bps)
        self.min_slippage_bps = int(min_slippage_bps)
        self.max_slippage_bps = int(max_slippage_bps)
        self.alpha_volatility = float(alpha_volatility)
        self.beta_impact = float(beta_impact)
        self._history: Deque[CurveObservation] = deque()

    def record_observation(
        self,
        virtual_sol_reserves: Number,
        virtual_token_reserves: Number,
        timestamp: float | None = None,
        *,
        sol_amount: float = 0.0,
        is_buy: bool = True,
    ) -> CurveObservation:
        """Record a curve reserve update or trade event and prune expired history."""
        ts = _monotonic() if timestamp is None else float(timestamp)
        spot = calculate_spot_price(virtual_sol_reserves, virtual_token_reserves)
        obs = CurveObservation(
            timestamp=ts,
            spot_price=spot,
            virtual_sol_reserves=float(virtual_sol_reserves),
            virtual_token_reserves=float(virtual_token_reserves),
            sol_amount=float(sol_amount),
            is_buy=bool(is_buy),
        )
        self._history.append(obs)
        self._prune(ts)
        return obs

    def _prune(self, current_time: float) -> None:
        cutoff = current_time - self.window_seconds
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    def get_observations(
        self, window_seconds: float | None = None, as_of: float | None = None
    ) -> list[CurveObservation]:
        """Return history snapshots within the requested time window."""
        ref_time = _monotonic() if as_of is None else float(as_of)
        win = self.window_seconds if window_seconds is None else float(window_seconds)
        cutoff = ref_time - win
        return [obs for obs in self._history if obs.timestamp >= cutoff]

    def calculate_price_velocity(
        self, window_seconds: float = 10.0, as_of: float | None = None
    ) -> float:
        """Calculate absolute price velocity (Delta P / Delta t) over the window."""
        obs = self.get_observations(window_seconds, as_of=as_of)
        if len(obs) < 2:
            return 0.0
        p_first = obs[0].spot_price
        p_last = obs[-1].spot_price
        dt = obs[-1].timestamp - obs[0].timestamp
        if dt <= 1e-6:
            return 0.0
        return (p_last - p_first) / dt

    def calculate_relative_velocity(
        self, window_seconds: float = 10.0, as_of: float | None = None
    ) -> float:
        """Calculate relative price velocity ((Delta P / P_0) / Delta t) per second."""
        obs = self.get_observations(window_seconds, as_of=as_of)
        if len(obs) < 2:
            return 0.0
        p_first = obs[0].spot_price
        if p_first <= 0.0:
            return 0.0
        p_last = obs[-1].spot_price
        dt = obs[-1].timestamp - obs[0].timestamp
        if dt <= 1e-6:
            return 0.0
        return ((p_last - p_first) / p_first) / dt

    def calculate_volatility(
        self, window_seconds: float = 30.0, as_of: float | None = None
    ) -> float:
        """Calculate rolling standard deviation of consecutive percentage price returns."""
        obs = self.get_observations(window_seconds, as_of=as_of)
        if len(obs) < 2:
            return 0.0
        returns: list[float] = []
        for i in range(1, len(obs)):
            p_prev = obs[i - 1].spot_price
            p_curr = obs[i].spot_price
            if p_prev > 0.0:
                ret = (p_curr - p_prev) / p_prev
                returns.append(ret)
        if not returns:
            return 0.0
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)

    def calculate_depth_consumption(
        self, sol_amount: float, virtual_sol_reserves: Number
    ) -> float:
        """Calculate fraction of virtual SOL reserve depth consumed (Delta x / x_virtual)."""
        if sol_amount <= 0.0 or virtual_sol_reserves <= 0:
            return 0.0
        return float(sol_amount) / float(virtual_sol_reserves)

    def estimate_dynamic_slippage(
        self,
        trade_amount_sol: float,
        virtual_sol_reserves: Number,
        virtual_token_reserves: Number,
        *,
        is_buy: bool = True,
        urgency_tier: str = "normal",
        base_slippage_bps: int | None = None,
        min_slippage_bps: int | None = None,
        max_slippage_bps: int | None = None,
    ) -> int:
        """Estimate dynamic slippage BPS scaled by volatility, price impact, and urgency."""
        base_bps = (
            self.default_slippage_bps
            if base_slippage_bps is None
            else int(base_slippage_bps)
        )
        min_bps = (
            self.min_slippage_bps if min_slippage_bps is None else int(min_slippage_bps)
        )
        max_bps = (
            self.max_slippage_bps if max_slippage_bps is None else int(max_slippage_bps)
        )

        vol = self.calculate_volatility(window_seconds=30.0)
        vol_bps = vol * 10_000.0 * self.alpha_volatility

        # The slippage a fill pays is the gap between its average price and
        # the pre-trade spot (dx/x on a buy), not the post-trade spot move,
        # which is about twice that (BUG-134).
        if is_buy:
            impact = calculate_buy_execution_slippage(
                trade_amount_sol, virtual_sol_reserves
            )
        else:
            token_est = 0.0
            if virtual_sol_reserves > 0:
                spot = calculate_spot_price(
                    virtual_sol_reserves, virtual_token_reserves
                )
                token_est = (trade_amount_sol / spot) if spot > 0 else 0.0
            impact = abs(
                calculate_sell_execution_slippage(token_est, virtual_token_reserves)
            )

        impact_bps = impact * 10_000.0 * self.beta_impact

        urgency = urgency_tier.lower()
        multiplier = 1.0
        if urgency in {"high_conviction", "high"}:
            multiplier = 1.25
        elif urgency in {"graduation", "graduation_snipe"}:
            multiplier = 1.5
        elif urgency in {"emergency", "emergency_exit"}:
            multiplier = 2.0

        raw_dynamic = (base_bps + vol_bps + impact_bps) * multiplier
        clamped = max(min_bps, min(int(round(raw_dynamic)), max_bps))
        return clamped

    def clear(self) -> None:
        """Clear observation history."""
        self._history.clear()
