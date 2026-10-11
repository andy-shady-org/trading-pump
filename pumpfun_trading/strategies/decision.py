from __future__ import annotations

from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import should_exit_position
from pumpfun_trading.strategies.filters import token_is_eligible
from pumpfun_trading.strategies.risk_validation import validate_risk_limits
from pumpfun_trading.strategies.signal import generate_buy_signal


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
    ) -> bool:
        return generate_buy_signal(
            self.config,
            market_cap_sol=market_cap_sol,
            active_positions=active_positions,
            mint_seen_recently=mint_seen_recently,
            buy_attempts=buy_attempts,
        )

    def should_sell(self, *, performance: float, token_balance: int) -> bool:
        return should_exit_position(
            self.config, performance=performance, token_balance=token_balance
        )

    def is_eligible_for_buy(
        self,
        *,
        market_cap_sol: float,
        mint_seen_recently: bool,
        buy_attempts: int,
    ) -> bool:
        return token_is_eligible(
            self.config,
            market_cap_sol=market_cap_sol,
            mint_seen_recently=mint_seen_recently,
            buy_attempts=buy_attempts,
        )

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

    def summary(self) -> dict[str, float | int | str]:
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
        }
