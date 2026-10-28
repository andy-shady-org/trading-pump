"""Unit tests for ``strategies/base.py``."""

from __future__ import annotations

import json

from trading_pump.strategies import TradingBotConfig


def test_strategy_config_round_trip_from_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "strategy_preset": "aggressive",
                "buy_amount_sol": 0.02,
                "paper_trade": True,
                "max_active_positions": 2,
            }
        ),
        encoding="utf-8",
    )

    config = TradingBotConfig.from_file(config_path)
    payload = config.to_dict()
    assert config.strategy_preset == "aggressive"
    assert payload["paper_trade"] is True
    assert payload["buy_amount_sol"] == 0.02


def test_simulated_starting_balance_is_shared_by_paper_and_replay() -> None:
    from trading_pump.strategies.base import simulated_starting_balance_sol

    config = TradingBotConfig(buy_amount_sol=0.02, reserve_balance_sol=0.1)
    assert simulated_starting_balance_sol(config) == 0.1 + 0.02 * 10
    funded = TradingBotConfig(buy_amount_sol=0.02, paper_starting_balance_sol=2.5)
    assert simulated_starting_balance_sol(funded) == 2.5
