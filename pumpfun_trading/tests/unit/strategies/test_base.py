"""Unit tests for ``strategies/base.py``."""

from __future__ import annotations

import json

from pumpfun_trading.strategies import TradingBotConfig


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
