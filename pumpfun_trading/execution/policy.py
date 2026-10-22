"""Adaptive execution policy and dynamic volatility-aware slippage engine."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Union

from pumpfun_trading.sdk.curve import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RAW,
    BondingCurveVolatilityEstimator,
    CurveObservation,
    calculate_buy_price_impact,
    calculate_sell_price_impact,
    calculate_spot_price,
)
from pumpfun_trading.strategies.base import TradingBotConfig

Number = Union[int, float]

# Estimators are now fed from every polled curve (BUG-134), so keep the
# most recently used ones only.
MAX_TRACKED_ESTIMATORS = 512


@dataclass(frozen=True)
class DynamicSlippageResult:
    """Encapsulates dynamically resolved slippage, compute budget, and Jito tip parameters."""

    slippage_bps: int
    price_impact_pct: float
    volatility_metric: float
    urgency_tier: str  # "normal" | "high_conviction" | "graduation" | "emergency"
    priority_fee_lamports: int
    jito_tip_lamports: int
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int


class AdaptiveExecutionPolicy:
    """Resolves dynamic price slippage, compute units, and priority fees based on curve volatility and urgency."""

    def __init__(
        self,
        config: TradingBotConfig | None = None,
        *,
        default_slippage_bps: int = 250,
        min_slippage_bps: int = 100,
        max_slippage_bps: int = 500,
        max_exit_slippage_bps: int = 5000,
        alpha_volatility: float = 1.0,
        beta_impact: float = 1.0,
        base_compute_unit_limit: int = 200_000,
        base_compute_unit_price: int = 50_000,
        base_jito_tip_lamports: int = 100_000,
    ) -> None:
        self.config = config or TradingBotConfig()
        self.default_slippage_bps = (
            getattr(self.config, "min_slippage_bps", None) or default_slippage_bps
        )
        self.min_slippage_bps = getattr(
            self.config, "min_slippage_bps", min_slippage_bps
        )
        self.max_slippage_bps = getattr(
            self.config, "max_slippage_bps", max_slippage_bps
        )
        self.max_exit_slippage_bps = getattr(
            self.config, "max_exit_slippage_bps", max_exit_slippage_bps
        )
        self.alpha_volatility = getattr(
            self.config, "volatility_slippage_multiplier", alpha_volatility
        )
        self.beta_impact = getattr(
            self.config, "price_impact_slippage_multiplier", beta_impact
        )
        self.base_compute_unit_limit = base_compute_unit_limit
        self.base_compute_unit_price = base_compute_unit_price
        self.base_jito_tip_lamports = base_jito_tip_lamports
        self._estimators: OrderedDict[str, BondingCurveVolatilityEstimator] = (
            OrderedDict()
        )

    def get_estimator(self, mint: str) -> BondingCurveVolatilityEstimator:
        """Retrieve or create a curve volatility estimator for a given mint."""
        estimator = self._estimators.get(mint)
        if estimator is None:
            estimator = BondingCurveVolatilityEstimator(
                window_seconds=60.0,
                default_slippage_bps=self.default_slippage_bps,
                min_slippage_bps=self.min_slippage_bps,
                max_slippage_bps=self.max_slippage_bps,
                alpha_volatility=self.alpha_volatility,
                beta_impact=self.beta_impact,
            )
            self._estimators[mint] = estimator
            while len(self._estimators) > MAX_TRACKED_ESTIMATORS:
                self._estimators.popitem(last=False)
        else:
            self._estimators.move_to_end(mint)
        return estimator

    def record_curve_update(
        self,
        mint: str,
        virtual_sol_reserves: Number,
        virtual_token_reserves: Number,
        timestamp: float | None = None,
        *,
        sol_amount: float = 0.0,
        is_buy: bool = True,
    ) -> CurveObservation:
        """Record an incoming curve quote or trade update for volatility estimation."""
        estimator = self.get_estimator(mint)
        return estimator.record_observation(
            virtual_sol_reserves=virtual_sol_reserves,
            virtual_token_reserves=virtual_token_reserves,
            timestamp=timestamp,
            sol_amount=sol_amount,
            is_buy=is_buy,
        )

    def resolve_parameters(
        self,
        mint: str,
        trade_amount_sol: float,
        *,
        virtual_sol_reserves: Number | None = None,
        virtual_token_reserves: Number | None = None,
        is_buy: bool = True,
        urgency: str = "normal",
        base_slippage_bps: int | None = None,
        min_slippage_bps: int | None = None,
        max_slippage_bps: int | None = None,
    ) -> DynamicSlippageResult:
        """Calculate dynamic slippage bounds, priority fees, and tip based on urgency tier."""
        urg = urgency.lower().strip()
        if "emergency" in urg or "panic" in urg or "liquidat" in urg:
            urgency_tier = "emergency"
            cu_mult = 4.0
            tip_mult = 4.0
            cu_limit = 400_000
            max_bound = max_slippage_bps or self.max_exit_slippage_bps
        elif "graduat" in urg or "snipe" in urg:
            urgency_tier = "graduation"
            cu_mult = 2.5
            tip_mult = 2.5
            cu_limit = 300_000
            max_bound = max_slippage_bps or self.max_slippage_bps
        elif "high" in urg or "conviction" in urg:
            urgency_tier = "high_conviction"
            cu_mult = 1.5
            tip_mult = 1.5
            cu_limit = 250_000
            max_bound = max_slippage_bps or self.max_slippage_bps
        else:
            urgency_tier = "normal"
            cu_mult = 1.0
            tip_mult = 1.0
            cu_limit = self.base_compute_unit_limit
            max_bound = max_slippage_bps or self.max_slippage_bps

        min_bound = min_slippage_bps or self.min_slippage_bps
        base_bps = base_slippage_bps or self.default_slippage_bps

        # Resolve reserves
        v_sol = (
            float(virtual_sol_reserves)
            if virtual_sol_reserves is not None and virtual_sol_reserves > 0
            else float(INITIAL_VIRTUAL_SOL_LAMPORTS) / 1_000_000_000.0
        )
        v_token = (
            float(virtual_token_reserves)
            if virtual_token_reserves is not None and virtual_token_reserves > 0
            else float(INITIAL_VIRTUAL_TOKEN_RAW)
        )

        estimator = self.get_estimator(mint)
        vol_metric = estimator.calculate_volatility(window_seconds=30.0)

        if is_buy:
            impact = calculate_buy_price_impact(trade_amount_sol, v_sol, v_token)
        else:
            spot = calculate_spot_price(v_sol, v_token)
            token_amt = (trade_amount_sol / spot) if spot > 0 else 0.0
            impact = abs(calculate_sell_price_impact(token_amt, v_sol, v_token))

        resolved_slippage = estimator.estimate_dynamic_slippage(
            trade_amount_sol=trade_amount_sol,
            virtual_sol_reserves=v_sol,
            virtual_token_reserves=v_token,
            is_buy=is_buy,
            urgency_tier=urgency_tier,
            base_slippage_bps=base_bps,
            min_slippage_bps=min_bound,
            max_slippage_bps=max_bound,
        )

        cu_price = int(self.base_compute_unit_price * cu_mult)
        jito_tip = int(self.base_jito_tip_lamports * tip_mult)
        priority_fee = int((cu_price * cu_limit) / 1_000_000)

        return DynamicSlippageResult(
            slippage_bps=resolved_slippage,
            price_impact_pct=float(impact),
            volatility_metric=float(vol_metric),
            urgency_tier=urgency_tier,
            priority_fee_lamports=priority_fee,
            jito_tip_lamports=jito_tip,
            compute_unit_limit=cu_limit,
            compute_unit_price_micro_lamports=cu_price,
        )


__all__ = [
    "AdaptiveExecutionPolicy",
    "DynamicSlippageResult",
]
