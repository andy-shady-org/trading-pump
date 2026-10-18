"""Unit tests for ``strategies/signal.py``."""

from __future__ import annotations

import pytest

from pumpfun_trading.strategies.copy_trading import CopyTradeSignal
from pumpfun_trading.strategies.filters import token_is_eligible
from pumpfun_trading.strategies.graduation import GraduationSignal
from pumpfun_trading.strategies.momentum import MomentumSignal, WindowMetrics
from pumpfun_trading.strategies.signal import (
    generate_buy_signal,
    generate_copy_trade_buy_signal,
    generate_graduation_buy_signal,
    generate_momentum_buy_signal,
)
from pumpfun_trading.tests.support.constants import SAMPLE_MINT
from pumpfun_trading.tests.support.factories import make_config


def test_generate_buy_signal_and_filters():
    config = make_config(
        dry_run=False,
        max_active_positions=2,
        min_market_cap_sol=5.0,
        max_buy_attempts_per_mint=3,
    )
    assert generate_buy_signal(
        config,
        market_cap_sol=10.0,
        active_positions=1,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert token_is_eligible(
        config,
        market_cap_sol=10.0,
        mint_seen_recently=False,
        buy_attempts=1,
    )
    assert not token_is_eligible(
        config,
        market_cap_sol=2.0,
        mint_seen_recently=False,
        buy_attempts=1,
    )


def test_strategy_signal_generation_all_branches():
    cfg = make_config(
        dry_run=False,
        max_active_positions=2,
        min_market_cap_sol=5.0,
        max_buy_attempts_per_mint=3,
        enable_momentum_signals=False,
        enable_raydium_migration_sniping=False,
        enable_copy_trading=False,
    )

    metrics = WindowMetrics(
        window_seconds=30,
        trade_count=5,
        buy_count=4,
        sell_count=1,
        buy_volume_sol=2.0,
        sell_volume_sol=0.2,
        buy_sell_ratio=10.0,
        net_sol_inflow=1.8,
        unique_buyers=4,
        unique_sellers=1,
        trade_velocity=0.5,
    )
    mom_sig = MomentumSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        z_score=3.0,
        buy_sell_ratio=10.0,
        net_sol_inflow=1.8,
        unique_buyers=4,
        trade_velocity=0.5,
        metrics=metrics,
    )

    grad_sig = GraduationSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        stage="graduated",
        market_cap_sol=85.0,
        real_sol_reserves=85.0,
    )

    copy_sig = CopyTradeSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        wallet_address="Wallet111",
        wallet_label="Wallet111",
        is_buy=True,
        sol_amount=1.0,
        computed_copy_size_sol=0.05,
    )

    # Disabled flags -> signals return False
    assert (
        generate_momentum_buy_signal(
            cfg, momentum_signal=mom_sig, active_positions=0, buy_attempts=0
        )
        is False
    )
    assert (
        generate_graduation_buy_signal(
            cfg, graduation_signal=grad_sig, active_positions=0, buy_attempts=0
        )
        is False
    )
    assert (
        generate_copy_trade_buy_signal(
            cfg, copy_trade_signal=copy_sig, active_positions=0, buy_attempts=0
        )
        is False
    )

    # Enabled flags
    cfg_enabled = make_config(
        dry_run=False,
        max_active_positions=2,
        min_market_cap_sol=5.0,
        max_buy_attempts_per_mint=3,
        enable_momentum_signals=True,
        enable_raydium_migration_sniping=True,
        enable_copy_trading=True,
    )

    assert (
        generate_buy_signal(
            cfg_enabled,
            market_cap_sol=10.0,
            active_positions=0,
            mint_seen_recently=False,
            buy_attempts=0,
            momentum_signal=mom_sig,
        )
        is True
    )
    assert (
        generate_momentum_buy_signal(
            cfg_enabled, momentum_signal=mom_sig, active_positions=0, buy_attempts=0
        )
        is True
    )
    assert (
        generate_graduation_buy_signal(
            cfg_enabled, graduation_signal=grad_sig, active_positions=0, buy_attempts=0
        )
        is True
    )
    assert (
        generate_copy_trade_buy_signal(
            cfg_enabled, copy_trade_signal=copy_sig, active_positions=0, buy_attempts=0
        )
        is True
    )


def _triggered_momentum() -> MomentumSignal:
    metrics = WindowMetrics(
        window_seconds=30,
        trade_count=10,
        buy_count=9,
        sell_count=1,
        buy_volume_sol=3.0,
        sell_volume_sol=0.3,
        buy_sell_ratio=10.0,
        net_sol_inflow=2.7,
        unique_buyers=9,
        unique_sellers=1,
        trade_velocity=0.33,
    )
    return MomentumSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        z_score=4.0,
        buy_sell_ratio=10.0,
        net_sol_inflow=2.7,
        unique_buyers=9,
        trade_velocity=0.33,
        metrics=metrics,
    )


@pytest.mark.parametrize(
    ("age", "market_cap", "expected"),
    [
        (None, None, True),  # legacy callers: no window or band
        (120.0, 50.0, True),
        (30.0, 50.0, False),  # too young: no follow-on demand shown yet
        (700.0, 50.0, False),  # past momentum_max_token_age_seconds
        (120.0, 20.0, False),  # below the band
        (120.0, 90.0, False),  # above the band, late buyers are exit liquidity
        (60.0, 35.0, True),  # inclusive edges
        (600.0, 75.0, True),
    ],
)
def test_momentum_signal_applies_age_window_and_market_cap_band(
    age: float | None, market_cap: float | None, expected: bool
) -> None:
    config = make_config(
        enable_momentum_signals=True,
        max_active_positions=2,
        min_market_cap_sol=35.0,
        momentum_max_market_cap_sol=75.0,
        momentum_min_token_age_seconds=60.0,
        momentum_max_token_age_seconds=600,
    )

    assert (
        generate_momentum_buy_signal(
            config,
            momentum_signal=_triggered_momentum(),
            active_positions=0,
            buy_attempts=0,
            token_age_seconds=age,
            market_cap_sol=market_cap,
        )
        is expected
    )
