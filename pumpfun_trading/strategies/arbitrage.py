"""FEAT-28: Cross-Venue Arbitrage & Mempool Back-Running Engine.

This module provides sub-millisecond price disparity tracking between Pump.fun
bonding curves and external DEX pools (Raydium AMM v4), closed-form optimal
arbitrage swap sizing math subject to constant-product invariants and fee friction,
and mempool whale back-running triggers.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Optional

from pumpfun_trading.sdk.raydium import (
    RaydiumPoolKeys,
    calculate_raydium_swap_out,
)

LAMPORTS_PER_SOL: int = 1_000_000_000
PUMP_FEE_PCT_DEFAULT: float = 0.01  # 1.0% Pump.fun trading fee
RAYDIUM_FEE_PCT_DEFAULT: float = 0.0025  # 0.25% Raydium AMM v4 fee
DEFAULT_GAS_ESTIMATE_SOL: float = 0.0003  # Priority fee + base tx fee
DEFAULT_MIN_JITO_TIP_SOL: float = 0.0001  # p95 validator tip floor
DEFAULT_TIP_SHARE_PCT: float = 0.50  # 50% validator profit share


@dataclass(frozen=True)
class ArbitrageOpportunity:
    """Dataclass capturing a detected cross-venue arbitrage opportunity."""

    mint: str
    direction: str  # "pump_to_raydium" | "raydium_to_pump"
    pump_spot_price: float  # SOL per token
    raydium_spot_price: float  # SOL per token
    spread_pct: float  # Absolute percentage spread (|Pa - Pb| / min(Pa, Pb))
    optimal_input_sol: float
    expected_output_sol: float
    gross_profit_sol: float
    estimated_fees_sol: float
    estimated_jito_tip_sol: float
    net_profit_sol: float
    timestamp: float
    pool_keys: Optional[RaydiumPoolKeys] = None
    pump_reserves: Optional[tuple[int, int]] = (
        None  # (virtual_sol_lamports, virtual_token_raw)
    )
    raydium_reserves: Optional[tuple[int, int]] = (
        None  # (sol_reserve_lamports, token_reserve_raw)
    )
    leg1_min_amount_out: int = 0
    leg2_min_amount_out: int = 0
    # True only when both venues' reserves were read from chain (BUG-59). Live
    # execution refuses opportunities built from placeholder reserves.
    reserves_verified: bool = False

    @property
    def is_profitable(self) -> bool:
        """Check if the opportunity yields positive net profit after all fees and tips."""
        return self.net_profit_sol > 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert opportunity to dictionary representation for logging and serialization."""
        return {
            "mint": self.mint,
            "direction": self.direction,
            "pump_spot_price": self.pump_spot_price,
            "raydium_spot_price": self.raydium_spot_price,
            "spread_pct": self.spread_pct,
            "optimal_input_sol": self.optimal_input_sol,
            "expected_output_sol": self.expected_output_sol,
            "gross_profit_sol": self.gross_profit_sol,
            "estimated_fees_sol": self.estimated_fees_sol,
            "estimated_jito_tip_sol": self.estimated_jito_tip_sol,
            "net_profit_sol": self.net_profit_sol,
            "timestamp": self.timestamp,
            "leg1_min_amount_out": self.leg1_min_amount_out,
            "leg2_min_amount_out": self.leg2_min_amount_out,
            "pool_keys": self.pool_keys.to_dict() if self.pool_keys else None,
        }


def calculate_cross_venue_spread(
    pump_spot_price: float,
    raydium_spot_price: float,
) -> tuple[float, str]:
    """Calculate percentage spread and indicated arbitrage trade direction.

    Args:
        pump_spot_price: Pump.fun curve spot price in SOL per token.
        raydium_spot_price: Raydium AMM pool spot price in SOL per token.

    Returns:
        tuple (spread_pct, direction) where direction is "pump_to_raydium" or "raydium_to_pump".
    """
    if pump_spot_price <= 0 or raydium_spot_price <= 0:
        return 0.0, "none"

    if pump_spot_price < raydium_spot_price:
        spread = (raydium_spot_price - pump_spot_price) / pump_spot_price
        return spread, "pump_to_raydium"
    else:
        spread = (pump_spot_price - raydium_spot_price) / raydium_spot_price
        return spread, "raydium_to_pump"


class OptimalArbitrageCalculator:
    """Closed-form mathematical solver for optimal cross-venue swap sizing."""

    def __init__(
        self,
        pump_fee_pct: float = PUMP_FEE_PCT_DEFAULT,
        raydium_fee_pct: float = RAYDIUM_FEE_PCT_DEFAULT,
        gas_estimate_sol: float = DEFAULT_GAS_ESTIMATE_SOL,
        jito_tip_profit_share_pct: float = DEFAULT_TIP_SHARE_PCT,
        min_jito_tip_sol: float = DEFAULT_MIN_JITO_TIP_SOL,
    ) -> None:
        self.pump_fee_pct = pump_fee_pct
        self.raydium_fee_pct = raydium_fee_pct
        self.gas_estimate_sol = gas_estimate_sol
        self.jito_tip_profit_share_pct = jito_tip_profit_share_pct
        self.min_jito_tip_sol = min_jito_tip_sol

    def calculate_optimal_input(
        self,
        pump_virtual_sol: int,
        pump_virtual_token: int,
        raydium_sol_reserve: int,
        raydium_token_reserve: int,
        direction: str,
        min_input_sol: float = 0.005,
        max_input_sol: float = 0.50,
    ) -> tuple[float, float]:
        """Derive the optimal input swap size (x*) in SOL maximizing net profit.

        Returns:
            tuple (optimal_input_sol, expected_net_profit_sol)
        """
        if (
            pump_virtual_sol <= 0
            or pump_virtual_token <= 0
            or raydium_sol_reserve <= 0
            or raydium_token_reserve <= 0
        ):
            return 0.0, 0.0

        gamma1 = 1.0 - self.pump_fee_pct
        gamma2 = 1.0 - self.raydium_fee_pct

        x1 = float(pump_virtual_sol)
        y1 = float(pump_virtual_token)
        r_sol = float(raydium_sol_reserve)
        r_token = float(raydium_token_reserve)

        if direction == "pump_to_raydium":
            # Leg 1: Buy on Pump.fun (SOL -> Token)
            # Leg 2: Sell on Raydium (Token -> SOL)
            a = r_sol * gamma1 * gamma2 * y1
            b = gamma1 * (r_token + gamma2 * y1)
            c = r_token * x1
        elif direction == "raydium_to_pump":
            # Leg 1: Buy on Raydium (SOL -> Token)
            # Leg 2: Sell on Pump.fun (Token -> SOL)
            a = gamma1 * gamma2 * x1 * r_token
            b = gamma2 * (y1 + r_token)
            c = y1 * r_sol
        else:
            return 0.0, 0.0

        if a <= 0 or b <= 0 or c <= 0:
            return 0.0, 0.0

        ac = a * c
        sqrt_ac = math.sqrt(ac)

        if sqrt_ac <= c:
            # Marginal revenue is less than marginal cost at x=0; no profitable arbitrage
            return 0.0, 0.0

        optimal_lamports = (sqrt_ac - c) / b
        optimal_sol = optimal_lamports / LAMPORTS_PER_SOL

        # Clamp between min and max bounds
        clamped_sol = max(min_input_sol, min(optimal_sol, max_input_sol))

        # Simulate exact trade at clamped SOL to obtain exact net profit
        sim_res = self.simulate_arbitrage_trade(
            pump_virtual_sol=pump_virtual_sol,
            pump_virtual_token=pump_virtual_token,
            raydium_sol_reserve=raydium_sol_reserve,
            raydium_token_reserve=raydium_token_reserve,
            direction=direction,
            input_sol=clamped_sol,
        )

        return clamped_sol, sim_res["net_profit_sol"]

    def simulate_arbitrage_trade(
        self,
        pump_virtual_sol: int,
        pump_virtual_token: int,
        raydium_sol_reserve: int,
        raydium_token_reserve: int,
        direction: str,
        input_sol: float,
        slippage_bps: int = 50,  # 0.5% internal slippage buffer on legs
    ) -> dict[str, Any]:
        """Simulate discrete exact multi-leg swap outcome accounting for integer reserves and fees.

        Returns:
            dict containing:
                - input_sol, expected_output_sol, gross_profit_sol, net_profit_sol,
                - leg1_tokens, leg1_min_tokens, leg2_sol, leg2_min_sol,
                - estimated_jito_tip_sol, estimated_fees_sol
        """
        input_lamports = int(round(input_sol * LAMPORTS_PER_SOL))
        if input_lamports <= 0:
            return {
                "input_sol": 0.0,
                "expected_output_sol": 0.0,
                "gross_profit_sol": 0.0,
                "net_profit_sol": 0.0,
                "leg1_tokens": 0,
                "leg1_min_tokens": 0,
                "leg2_sol": 0,
                "leg2_min_sol": 0,
                "estimated_jito_tip_sol": 0.0,
                "estimated_fees_sol": 0.0,
            }

        gamma1_factor = int((1.0 - self.pump_fee_pct) * 10_000)

        if direction == "pump_to_raydium":
            # Leg 1: Buy on Pump.fun
            sol_in_after_fee = (input_lamports * gamma1_factor) // 10_000
            leg1_tokens = (pump_virtual_token * sol_in_after_fee) // (
                pump_virtual_sol + sol_in_after_fee
            )
            leg1_min_tokens = (leg1_tokens * (10_000 - slippage_bps)) // 10_000

            # Leg 2: Sell on Raydium AMM v4
            fee_num = int(self.raydium_fee_pct * 10_000)
            leg2_sol, leg2_min_sol = calculate_raydium_swap_out(
                amount_in=leg1_tokens,
                reserve_in=raydium_token_reserve,
                reserve_out=raydium_sol_reserve,
                slippage_bps=slippage_bps,
                fee_numerator=fee_num,
                fee_denominator=10_000,
            )

        elif direction == "raydium_to_pump":
            # Leg 1: Buy on Raydium AMM v4
            fee_num = int(self.raydium_fee_pct * 10_000)
            leg1_tokens, leg1_min_tokens = calculate_raydium_swap_out(
                amount_in=input_lamports,
                reserve_in=raydium_sol_reserve,
                reserve_out=raydium_token_reserve,
                slippage_bps=slippage_bps,
                fee_numerator=fee_num,
                fee_denominator=10_000,
            )

            # Leg 2: Sell on Pump.fun
            gross_sol_out = (pump_virtual_sol * leg1_tokens) // (
                pump_virtual_token + leg1_tokens
            )
            leg2_sol = (gross_sol_out * gamma1_factor) // 10_000
            leg2_min_sol = (leg2_sol * (10_000 - slippage_bps)) // 10_000

        else:
            return {
                "input_sol": 0.0,
                "expected_output_sol": 0.0,
                "gross_profit_sol": 0.0,
                "net_profit_sol": 0.0,
                "leg1_tokens": 0,
                "leg1_min_tokens": 0,
                "leg2_sol": 0,
                "leg2_min_sol": 0,
                "estimated_jito_tip_sol": 0.0,
                "estimated_fees_sol": 0.0,
            }

        output_sol = leg2_sol / LAMPORTS_PER_SOL
        gross_profit_sol = output_sol - input_sol

        if gross_profit_sol > 0.0:
            estimated_tip = max(
                self.min_jito_tip_sol,
                gross_profit_sol * self.jito_tip_profit_share_pct,
            )
        else:
            estimated_tip = self.min_jito_tip_sol

        net_profit_sol = gross_profit_sol - self.gas_estimate_sol - estimated_tip

        return {
            "input_sol": input_sol,
            "expected_output_sol": output_sol,
            "gross_profit_sol": gross_profit_sol,
            "net_profit_sol": net_profit_sol,
            "leg1_tokens": leg1_tokens,
            "leg1_min_tokens": leg1_min_tokens,
            "leg2_sol": leg2_sol,
            "leg2_min_sol": leg2_min_sol,
            "estimated_jito_tip_sol": estimated_tip,
            "estimated_fees_sol": self.gas_estimate_sol,
        }


class CrossVenueDisparityMonitor:
    """Monitors live spot price disparities across Pump.fun and Raydium pools."""

    def __init__(
        self,
        calculator: Optional[OptimalArbitrageCalculator] = None,
        min_arbitrage_spread_pct: float = 0.015,  # 1.5% minimum spread hurdle
        min_arbitrage_profit_sol: float = 0.003,  # 0.003 SOL net profit minimum
        max_arbitrage_input_sol: float = 0.50,
        min_arbitrage_input_sol: float = 0.01,
        jito_tip_profit_share_pct: float = DEFAULT_TIP_SHARE_PCT,
    ) -> None:
        self.calculator = calculator or OptimalArbitrageCalculator(
            jito_tip_profit_share_pct=jito_tip_profit_share_pct
        )
        self.min_arbitrage_spread_pct = min_arbitrage_spread_pct
        self.min_arbitrage_profit_sol = min_arbitrage_profit_sol
        self.max_arbitrage_input_sol = max_arbitrage_input_sol
        self.min_arbitrage_input_sol = min_arbitrage_input_sol
        self.jito_tip_profit_share_pct = jito_tip_profit_share_pct

    def evaluate_spread(
        self,
        mint: str,
        pump_virtual_sol: int,
        pump_virtual_token: int,
        raydium_sol_reserve: int,
        raydium_token_reserve: int,
        raydium_keys: Optional[RaydiumPoolKeys] = None,
        current_timestamp: Optional[float] = None,
    ) -> Optional[ArbitrageOpportunity]:
        """Evaluate real-time spread and return ArbitrageOpportunity if profitable."""
        if (
            pump_virtual_sol <= 0
            or pump_virtual_token <= 0
            or raydium_sol_reserve <= 0
            or raydium_token_reserve <= 0
        ):
            return None

        # Pump spot price: (virtual_sol_lamports / 1e9) / (virtual_token_raw / 1e6) = (sol / tok) * 1e-3
        pump_spot = (pump_virtual_sol / pump_virtual_token) * 1e-3
        raydium_spot = (raydium_sol_reserve / raydium_token_reserve) * 1e-3

        spread_pct, direction = calculate_cross_venue_spread(pump_spot, raydium_spot)

        if spread_pct < self.min_arbitrage_spread_pct or direction == "none":
            return None

        # Solve optimal sizing
        optimal_input_sol, expected_net_profit = (
            self.calculator.calculate_optimal_input(
                pump_virtual_sol=pump_virtual_sol,
                pump_virtual_token=pump_virtual_token,
                raydium_sol_reserve=raydium_sol_reserve,
                raydium_token_reserve=raydium_token_reserve,
                direction=direction,
                min_input_sol=self.min_arbitrage_input_sol,
                max_input_sol=self.max_arbitrage_input_sol,
            )
        )

        if (
            optimal_input_sol <= 0.0
            or expected_net_profit < self.min_arbitrage_profit_sol
        ):
            return None

        sim_res = self.calculator.simulate_arbitrage_trade(
            pump_virtual_sol=pump_virtual_sol,
            pump_virtual_token=pump_virtual_token,
            raydium_sol_reserve=raydium_sol_reserve,
            raydium_token_reserve=raydium_token_reserve,
            direction=direction,
            input_sol=optimal_input_sol,
        )

        if sim_res["net_profit_sol"] < self.min_arbitrage_profit_sol:
            return None

        ts = current_timestamp if current_timestamp is not None else time.time()

        return ArbitrageOpportunity(
            mint=mint,
            direction=direction,
            pump_spot_price=pump_spot,
            raydium_spot_price=raydium_spot,
            spread_pct=spread_pct,
            optimal_input_sol=optimal_input_sol,
            expected_output_sol=sim_res["expected_output_sol"],
            gross_profit_sol=sim_res["gross_profit_sol"],
            estimated_fees_sol=sim_res["estimated_fees_sol"],
            estimated_jito_tip_sol=sim_res["estimated_jito_tip_sol"],
            net_profit_sol=sim_res["net_profit_sol"],
            timestamp=ts,
            pool_keys=raydium_keys,
            pump_reserves=(pump_virtual_sol, pump_virtual_token),
            raydium_reserves=(raydium_sol_reserve, raydium_token_reserve),
            leg1_min_amount_out=sim_res["leg1_min_tokens"],
            leg2_min_amount_out=sim_res["leg2_min_sol"],
        )


class MempoolBackrunEngine:
    """Detects large whale transactions and triggers atomic back-running rebalancing."""

    def __init__(
        self,
        disparity_monitor: Optional[CrossVenueDisparityMonitor] = None,
        whale_sol_threshold: float = 1.0,  # Trades >= 1.0 SOL considered whale orders
        min_curve_impact_pct: float = 0.02,  # Trades with >= 2.0% curve impact
    ) -> None:
        self.disparity_monitor = disparity_monitor or CrossVenueDisparityMonitor()
        self.whale_sol_threshold = whale_sol_threshold
        self.min_curve_impact_pct = min_curve_impact_pct

    def evaluate_whale_transaction(
        self,
        mint: str,
        is_buy: bool,
        trade_sol: float,
        pump_virtual_sol: int,
        pump_virtual_token: int,
        raydium_sol_reserve: int,
        raydium_token_reserve: int,
        raydium_keys: Optional[RaydiumPoolKeys] = None,
        timestamp: Optional[float] = None,
    ) -> Optional[ArbitrageOpportunity]:
        """Evaluate incoming whale trade on bonding curve and calculate post-whale back-run opportunity."""
        if trade_sol <= 0 or pump_virtual_sol <= 0 or pump_virtual_token <= 0:
            return None

        trade_lamports = int(round(trade_sol * LAMPORTS_PER_SOL))
        impact_pct = trade_lamports / pump_virtual_sol

        if (
            trade_sol < self.whale_sol_threshold
            and impact_pct < self.min_curve_impact_pct
        ):
            return None

        # Simulate post-whale Pump.fun virtual curve reserves
        if is_buy:
            # Whale bought tokens: virtual SOL increased, virtual tokens decreased
            sol_in_after_fee = int(trade_lamports * 0.99)
            tokens_out = (pump_virtual_token * sol_in_after_fee) // (
                pump_virtual_sol + sol_in_after_fee
            )
            post_pump_sol = pump_virtual_sol + sol_in_after_fee
            post_pump_token = max(1, pump_virtual_token - tokens_out)
        else:
            # Whale sold tokens: virtual SOL decreased, virtual tokens increased
            tokens_in = int((pump_virtual_token * trade_lamports) // pump_virtual_sol)
            gross_sol_out = (pump_virtual_sol * tokens_in) // (
                pump_virtual_token + tokens_in
            )
            net_sol_out = int(gross_sol_out * 0.99)
            post_pump_sol = max(1, pump_virtual_sol - net_sol_out)
            post_pump_token = pump_virtual_token + tokens_in

        # Evaluate cross-venue spread on projected post-whale reserves
        return self.disparity_monitor.evaluate_spread(
            mint=mint,
            pump_virtual_sol=post_pump_sol,
            pump_virtual_token=post_pump_token,
            raydium_sol_reserve=raydium_sol_reserve,
            raydium_token_reserve=raydium_token_reserve,
            raydium_keys=raydium_keys,
            current_timestamp=timestamp,
        )


__all__ = [
    "ArbitrageOpportunity",
    "calculate_cross_venue_spread",
    "OptimalArbitrageCalculator",
    "CrossVenueDisparityMonitor",
    "MempoolBackrunEngine",
    "PUMP_FEE_PCT_DEFAULT",
    "RAYDIUM_FEE_PCT_DEFAULT",
    "DEFAULT_GAS_ESTIMATE_SOL",
    "DEFAULT_MIN_JITO_TIP_SOL",
    "DEFAULT_TIP_SHARE_PCT",
]
