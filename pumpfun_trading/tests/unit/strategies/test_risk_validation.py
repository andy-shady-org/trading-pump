"""Unit tests for ``strategies/risk_validation.py``."""

from __future__ import annotations

from pumpfun_trading.strategies.exits import should_exit_position
from pumpfun_trading.strategies.risk_validation import validate_risk_limits
from pumpfun_trading.tests.support.factories import make_config


def test_validate_risk_limits_and_exit_logic():
    config = make_config(dry_run=False, max_active_positions=2, reserve_balance_sol=0.1)
    assert validate_risk_limits(
        config,
        current_positions={"a": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert not validate_risk_limits(
        config,
        current_positions={"a": {}, "b": {}},
        proposed_entry_sol=0.05,
        wallet_balance_sol=0.25,
    )
    assert not validate_risk_limits(
        config,
        current_positions={"a": {}},
        proposed_entry_sol=0.15,
        wallet_balance_sol=0.15,
    )
    assert should_exit_position(config, performance=1.8, token_balance=2)
    assert not should_exit_position(config, performance=1.0, token_balance=0)


def test_strategy_risk_validation():
    # Capital caps are wide enough here; BUG-78 caps are covered elsewhere.
    config = make_config(
        dry_run=False,
        max_active_positions=2,
        reserve_balance_sol=0.1,
        max_position_size_sol=1.0,
        max_total_exposure_sol=2.0,
        max_token_concentration_pct=1.0,
    )

    # Valid
    assert validate_risk_limits(
        config,
        current_positions={"Mint1": {}},
        proposed_entry_sol=0.2,
        wallet_balance_sol=0.5,
    )

    # max_active_positions < 1
    config_zero = make_config(
        dry_run=False,
        max_active_positions=0,
        reserve_balance_sol=0.1,
    )
    assert not validate_risk_limits(
        config_zero,
        current_positions={},
        proposed_entry_sol=0.1,
    )

    # Active positions full
    assert not validate_risk_limits(
        config,
        current_positions={"Mint1": {}, "Mint2": {}},
        proposed_entry_sol=0.1,
    )

    # Insufficient wallet balance after reserve
    assert not validate_risk_limits(
        config,
        current_positions={"Mint1": {}},
        proposed_entry_sol=0.3,
        wallet_balance_sol=0.35,  # 0.35 - 0.1 = 0.25 < 0.3
    )
