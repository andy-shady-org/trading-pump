"""Unit tests for ``strategies/signal.py``."""

from __future__ import annotations

from pumpfun_trading.strategies.filters import token_is_eligible
from pumpfun_trading.strategies.signal import generate_buy_signal
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
