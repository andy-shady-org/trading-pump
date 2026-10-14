from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import (
    ExitDecision,
    PositionExitState,
    evaluate_exit_strategy,
    should_exit_position,
    update_position_peak,
)
from pumpfun_trading.strategies.filters import (
    DevWalletProfile,
    HolderDistribution,
    ScreeningCache,
    TokenMetadata,
    TokenScreeningVerdict,
    evaluate_token_heuristics,
    token_is_eligible,
)
from pumpfun_trading.strategies.cluster import (
    ClusterAnalysisVerdict,
    FundingClusterAnalyzer,
)
from pumpfun_trading.strategies.copy_trading import CopyTradeEngine, CopyTradeSignal
from pumpfun_trading.strategies.graduation import GraduationEngine, GraduationSignal
from pumpfun_trading.strategies.momentum import MomentumSignal, OrderFlowEngine
from pumpfun_trading.strategies.risk_validation import validate_risk_limits
from pumpfun_trading.strategies.signal import (
    generate_buy_signal,
    generate_copy_trade_buy_signal,
    generate_graduation_buy_signal,
    generate_momentum_buy_signal,
)


class TradingStrategy:
    def __init__(self, config: TradingBotConfig):
        self.config = config

    def should_buy(
        self,
        *,
        market_cap_sol: float,
        active_positions: int,
        mint_seen_recently: bool,
        buy_attempts: int,
        momentum_signal: MomentumSignal | None = None,
    ) -> bool:
        return generate_buy_signal(
            self.config,
            market_cap_sol=market_cap_sol,
            active_positions=active_positions,
            mint_seen_recently=mint_seen_recently,
            buy_attempts=buy_attempts,
            momentum_signal=momentum_signal,
        )

    def should_buy_momentum(
        self,
        *,
        momentum_signal: MomentumSignal,
        active_positions: int,
        buy_attempts: int,
        mint_seen_recently: bool = False,
    ) -> bool:
        return generate_momentum_buy_signal(
            self.config,
            momentum_signal=momentum_signal,
            active_positions=active_positions,
            buy_attempts=buy_attempts,
            mint_seen_recently=mint_seen_recently,
        )

    def evaluate_momentum(
        self,
        engine: OrderFlowEngine,
        mint: str,
        *,
        token_creation_timestamp: float | None = None,
        current_time: float | None = None,
    ) -> MomentumSignal:
        return engine.evaluate_momentum_signal(
            mint,
            window_seconds=self.config.momentum_window_seconds,
            min_buy_ratio=self.config.momentum_min_buy_ratio,
            min_z_score=self.config.momentum_min_z_score,
            min_unique_buyers=self.config.momentum_min_unique_buyers,
            min_net_inflow_sol=self.config.momentum_min_net_inflow_sol,
            baseline_window_seconds=self.config.momentum_baseline_window_seconds,
            token_creation_timestamp=token_creation_timestamp,
            max_token_age_seconds=self.config.momentum_max_token_age_seconds,
            current_time=current_time,
        )

    def should_buy_graduation(
        self,
        *,
        graduation_signal: GraduationSignal,
        active_positions: int,
        buy_attempts: int,
        mint_seen_recently: bool = False,
    ) -> bool:
        return generate_graduation_buy_signal(
            self.config,
            graduation_signal=graduation_signal,
            active_positions=active_positions,
            buy_attempts=buy_attempts,
            mint_seen_recently=mint_seen_recently,
        )

    def evaluate_graduation(
        self,
        engine: GraduationEngine,
        mint: str,
        *,
        require_pool_ready: bool = False,
        current_time: float | None = None,
    ) -> GraduationSignal:
        return engine.evaluate_graduation_signal(
            mint,
            pre_migration_threshold_sol=self.config.raydium_pre_migration_sol_threshold,
            require_pool_ready=require_pool_ready,
            current_time=current_time,
        )

    def should_buy_copy_trade(
        self,
        *,
        copy_trade_signal: CopyTradeSignal,
        active_positions: int,
        buy_attempts: int,
        mint_seen_recently: bool = False,
    ) -> bool:
        return generate_copy_trade_buy_signal(
            self.config,
            copy_trade_signal=copy_trade_signal,
            active_positions=active_positions,
            buy_attempts=buy_attempts,
            mint_seen_recently=mint_seen_recently,
        )

    def evaluate_copy_trade(
        self,
        engine: CopyTradeEngine,
        user: str,
        mint: str,
        sol_amount: float,
        is_buy: bool,
        timestamp: float | None = None,
    ) -> CopyTradeSignal:
        return engine.record_and_evaluate(
            user=user,
            mint=mint,
            sol_amount=sol_amount,
            is_buy=is_buy,
            timestamp=timestamp,
        )

    def should_sell(
        self,
        *,
        performance: float,
        token_balance: int,
        position: dict[str, Any] | PositionExitState | None = None,
        current_market_cap: float | None = None,
    ) -> bool:
        return should_exit_position(
            self.config,
            performance=performance,
            token_balance=token_balance,
            position=position,
            current_market_cap=current_market_cap,
        )

    def evaluate_exit(
        self,
        position: dict[str, Any] | PositionExitState,
        *,
        current_market_cap: float | None = None,
        token_balance: int | None = None,
    ) -> ExitDecision:
        state = (
            position
            if isinstance(position, PositionExitState)
            else PositionExitState.from_dict(position)
        )
        return evaluate_exit_strategy(
            self.config,
            state,
            current_market_cap=current_market_cap,
            token_balance=token_balance,
        )

    def update_peak(
        self,
        position: dict[str, Any] | PositionExitState,
        current_market_cap: float,
    ) -> float:
        return update_position_peak(position, current_market_cap)

    def is_eligible_for_buy(
        self,
        *,
        market_cap_sol: float,
        mint_seen_recently: bool,
        buy_attempts: int,
        screening_verdict: TokenScreeningVerdict | None = None,
    ) -> bool:
        return token_is_eligible(
            self.config,
            market_cap_sol=market_cap_sol,
            mint_seen_recently=mint_seen_recently,
            buy_attempts=buy_attempts,
            screening_verdict=screening_verdict,
        )

    def screen_token(
        self,
        mint: str,
        *,
        metadata: TokenMetadata | dict[str, Any] | None = None,
        dev_profile: DevWalletProfile | None = None,
        holder_distribution: HolderDistribution | None = None,
        bonding_curve_pda: str | None = None,
        cluster_analysis: ClusterAnalysisVerdict | None = None,
        cache: ScreeningCache | None = None,
        use_cache: bool = True,
    ) -> TokenScreeningVerdict:
        return evaluate_token_heuristics(
            self.config,
            mint,
            metadata=metadata,
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            bonding_curve_pda=bonding_curve_pda,
            cluster_analysis=cluster_analysis,
            cache=cache,
            use_cache=use_cache,
        )

    def evaluate_cluster_graph(
        self,
        mint: str,
        *,
        top_holders: list[tuple[str, int]] | None = None,
        creator_wallet: str | None = None,
        creator_balance: int = 0,
        total_supply: int = 1_000_000_000_000_000,
        funding_links: list[tuple[str, str, float]] | None = None,
        trades: list[dict[str, Any]] | None = None,
        analyzer: FundingClusterAnalyzer | None = None,
    ) -> ClusterAnalysisVerdict:
        cluster_analyzer = analyzer or FundingClusterAnalyzer(
            max_cluster_concentration_pct=self.config.max_cluster_concentration_pct,
            max_single_cluster_pct=self.config.max_single_cluster_pct,
            max_sybil_wash_ratio=self.config.max_sybil_wash_ratio,
            cluster_trace_depth=self.config.cluster_trace_depth,
        )
        graph = cluster_analyzer.build_graph(
            top_holders=top_holders,
            creator_wallet=creator_wallet,
            creator_balance=creator_balance,
            total_supply=total_supply,
            funding_links=funding_links,
        )
        return cluster_analyzer.evaluate(mint, graph, trades=trades)

    def validate_risk(
        self,
        *,
        current_positions: dict[str, object] | None,
        proposed_entry_sol: float,
        wallet_balance_sol: float | None = None,
    ) -> bool:
        return validate_risk_limits(
            self.config,
            current_positions=current_positions,
            proposed_entry_sol=proposed_entry_sol,
            wallet_balance_sol=wallet_balance_sol,
        )

    def summary(self) -> dict[str, float | int | str | bool]:
        return {
            "preset": self.config.strategy_preset,
            "buy_amount_sol": self.config.buy_amount_sol,
            "take_profit": self.config.take_profit,
            "stop_loss": self.config.stop_loss,
            "max_active_positions": self.config.max_active_positions,
            "min_market_cap_sol": self.config.min_market_cap_sol,
            "max_buy_attempts_per_mint": self.config.max_buy_attempts_per_mint,
            "min_balance_sol": self.config.min_balance_sol,
            "max_total_exposure_sol": self.config.max_total_exposure_sol,
            "max_position_size_sol": self.config.max_position_size_sol,
            "max_token_concentration_pct": self.config.max_token_concentration_pct,
            "max_loss_per_trade_sol": self.config.max_loss_per_trade_sol,
            "max_daily_drawdown_pct": self.config.max_daily_drawdown_pct,
            "reserve_balance_sol": self.config.reserve_balance_sol,
            "health_check_timeout_seconds": self.config.health_check_timeout_seconds,
            "enable_trailing_stop": self.config.enable_trailing_stop,
            "trailing_stop_activation_pct": self.config.trailing_stop_activation_pct,
            "trailing_stop_drop_pct": self.config.trailing_stop_drop_pct,
            "enable_tiered_take_profit": self.config.enable_tiered_take_profit,
            "tier_1_take_profit": self.config.tier_1_take_profit,
            "tier_1_sell_fraction": self.config.tier_1_sell_fraction,
            "tier_2_take_profit": self.config.tier_2_take_profit,
            "tier_2_sell_fraction": self.config.tier_2_sell_fraction,
            "moonbag_trailing_floor": self.config.moonbag_trailing_floor,
            "enable_anti_rug_filters": self.config.enable_anti_rug_filters,
            "max_dev_24h_launches": self.config.max_dev_24h_launches,
            "max_creator_initial_holding_pct": self.config.max_creator_initial_holding_pct,
            "max_top5_holder_concentration_pct": self.config.max_top5_holder_concentration_pct,
            "max_gini_coefficient": self.config.max_gini_coefficient,
            "require_social_links": self.config.require_social_links,
            "min_social_links_count": self.config.min_social_links_count,
            "max_acceptable_risk_score": self.config.max_acceptable_risk_score,
            "screening_cache_ttl_seconds": self.config.screening_cache_ttl_seconds,
            "enable_momentum_signals": self.config.enable_momentum_signals,
            "momentum_window_seconds": self.config.momentum_window_seconds,
            "momentum_min_buy_ratio": self.config.momentum_min_buy_ratio,
            "momentum_min_z_score": self.config.momentum_min_z_score,
            "momentum_min_unique_buyers": self.config.momentum_min_unique_buyers,
            "momentum_min_net_inflow_sol": self.config.momentum_min_net_inflow_sol,
            "momentum_baseline_window_seconds": self.config.momentum_baseline_window_seconds,
            "momentum_max_token_age_seconds": self.config.momentum_max_token_age_seconds,
            "enable_cluster_analysis": self.config.enable_cluster_analysis,
            "max_cluster_concentration_pct": self.config.max_cluster_concentration_pct,
            "max_single_cluster_pct": self.config.max_single_cluster_pct,
            "max_sybil_wash_ratio": self.config.max_sybil_wash_ratio,
            "cluster_trace_depth": self.config.cluster_trace_depth,
        }


@dataclass(frozen=True)
class PositionEvScore:
    """Expected Value (EV) score and momentum metrics for an active holding."""

    mint: str
    ev_score: float
    z_score: float
    net_inflow_sol: float
    hold_duration_seconds: float
    stagnation_factor: float
    is_displaceable: bool
    metrics: dict[str, Any] = field(default_factory=dict)


class PositionEvEvaluator:
    """Calculates continuous Expected Value (EV) scores for open positions and breakout candidates."""

    def __init__(
        self,
        config: TradingBotConfig | None = None,
        *,
        min_hold_seconds: float = 45.0,
        z_score_weight: float = 0.35,
        inflow_weight: float = 0.30,
        pnl_trajectory_weight: float = 0.25,
        stagnation_penalty_weight: float = 0.20,
    ) -> None:
        self.config = config or TradingBotConfig()
        self.min_hold_seconds = getattr(
            self.config, "min_hold_before_displacement_seconds", min_hold_seconds
        )
        self.z_score_weight = float(z_score_weight)
        self.inflow_weight = float(inflow_weight)
        self.pnl_trajectory_weight = float(pnl_trajectory_weight)
        self.stagnation_penalty_weight = float(stagnation_penalty_weight)

    def evaluate_position(
        self,
        position: dict[str, Any],
        *,
        current_time: float | None = None,
        momentum_signal: MomentumSignal | None = None,
    ) -> PositionEvScore:
        """Compute the Expected Value (EV) conviction score for an active position."""
        now = time.time() if current_time is None else float(current_time)
        mint = str(position.get("mint") or "")
        entry_time = float(
            position.get("entry_time") or position.get("first_seen") or now
        )
        hold_duration = max(0.0, now - entry_time)

        # Displaceability: protected if held less than min_hold_before_displacement_seconds
        is_displaceable = hold_duration >= self.min_hold_seconds

        entry_mc = float(position.get("entry_market_cap") or 30.0)
        curr_mc = float(position.get("current_market_cap") or entry_mc)
        perf = (curr_mc / entry_mc) if entry_mc > 0 else 1.0

        last_price_change_at = float(position.get("last_price_change_at") or entry_time)
        flat_duration = max(0.0, now - last_price_change_at)

        # Stagnation factor: scales from 0.0 to 1.0 as position remains flat over time
        stagnant_timeout = getattr(self.config, "stagnant_timeout_seconds", 120.0)
        stagnation_factor = (
            min(1.0, flat_duration / max(10.0, stagnant_timeout))
            if abs(perf - 1.0) < 0.05
            else 0.0
        )

        z_score = 0.0
        net_inflow = 0.0
        if momentum_signal is not None:
            z_score = float(getattr(momentum_signal, "z_score", 0.0))
            net_inflow = float(
                getattr(momentum_signal, "net_sol_inflow", None)
                or getattr(momentum_signal, "net_inflow_sol", 0.0)
            )
        elif "z_score" in position:
            z_score = float(position.get("z_score", 0.0))
            net_inflow = float(
                position.get("net_sol_inflow", None)
                or position.get("net_inflow_sol", 0.0)
            )

        # Normalized components
        norm_z = max(-2.0, min(5.0, z_score)) / 5.0
        norm_inflow = max(-1.0, min(5.0, net_inflow)) / 5.0
        norm_pnl = max(-1.0, min(3.0, perf - 1.0))

        raw_ev = (
            (self.z_score_weight * norm_z)
            + (self.inflow_weight * norm_inflow)
            + (self.pnl_trajectory_weight * norm_pnl)
            - (self.stagnation_penalty_weight * stagnation_factor)
        )

        return PositionEvScore(
            mint=mint,
            ev_score=float(raw_ev),
            z_score=z_score,
            net_inflow_sol=net_inflow,
            hold_duration_seconds=hold_duration,
            stagnation_factor=stagnation_factor,
            is_displaceable=is_displaceable,
            metrics={
                "performance": perf,
                "flat_duration": flat_duration,
                "norm_z": norm_z,
                "norm_inflow": norm_inflow,
                "norm_pnl": norm_pnl,
            },
        )

    def evaluate_candidate(
        self,
        candidate_mint: str,
        *,
        momentum_signal: MomentumSignal | None = None,
        conviction_percentile: float = 0.95,
    ) -> float:
        """Calculate EV score for an incoming breakout signal."""
        z_score = (
            float(getattr(momentum_signal, "z_score", 3.0)) if momentum_signal else 3.0
        )
        net_inflow = (
            float(
                getattr(momentum_signal, "net_sol_inflow", None)
                or getattr(momentum_signal, "net_inflow_sol", 1.0)
            )
            if momentum_signal
            else 1.0
        )
        buy_ratio = (
            float(
                getattr(momentum_signal, "buy_sell_ratio", None)
                or getattr(momentum_signal, "buy_ratio", 3.0)
            )
            if momentum_signal
            else 3.0
        )

        norm_z = max(0.0, min(5.0, z_score)) / 5.0
        norm_inflow = max(0.0, min(5.0, net_inflow)) / 5.0
        norm_ratio = min(2.0, buy_ratio / 3.0)

        candidate_ev = (
            (self.z_score_weight * norm_z)
            + (self.inflow_weight * norm_inflow)
            + (0.35 * norm_ratio)
            + (0.10 * (conviction_percentile - 0.50))
        )
        return float(candidate_ev)

    def rank_positions_by_ev(
        self,
        positions: dict[str, dict[str, Any]],
        *,
        current_time: float | None = None,
    ) -> list[PositionEvScore]:
        """Rank open positions ascending by EV score (weakest first)."""
        scores: list[PositionEvScore] = []
        for mint, pos in positions.items():
            pos_dict = dict(pos)
            pos_dict["mint"] = mint
            scores.append(self.evaluate_position(pos_dict, current_time=current_time))
        scores.sort(key=lambda s: s.ev_score)
        return scores


__all__ = [
    "PositionEvEvaluator",
    "PositionEvScore",
    "TradingStrategy",
]
