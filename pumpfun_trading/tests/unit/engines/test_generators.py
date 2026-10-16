"""Unit tests for ``engines/generators.py``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.engines.generators import (
    RestHistoryExporter,
    SyntheticReplayGenerator,
)
from pumpfun_trading.engines.replay import PaperTradingEngine, run_replay


def test_synthetic_replay_generator(tmp_path: Path):
    """Test SyntheticReplayGenerator across all preset price trajectories."""
    scenarios = [
        "pump_and_dump",
        "stagnant_curve",
        "multi_tier_take_profit",
        "gradual_grind",
        "flash_rug",
    ]

    for sc in scenarios:
        records = SyntheticReplayGenerator.generate(scenario=sc, steps=30, seed=123)
        assert len(records) == 30
        assert records[0]["signal"] == "buy"
        assert all("price" in r and "market_cap_sol" in r for r in records)

    # Test file export and simulation execution
    out_file = tmp_path / "synthetic_run.jsonl"
    count = SyntheticReplayGenerator.generate_to_file(
        path=out_file, scenario="multi_tier_take_profit", steps=50
    )
    assert count == 50
    assert out_file.exists()

    # Verify PaperTradingEngine backtest executes without errors
    engine = PaperTradingEngine(initial_cash=10.0, take_profit=2.0, stop_loss=0.85)
    summary = run_replay(out_file, engine=engine)
    assert summary["initial_cash"] == 10.0
    assert summary["total_trades"] >= 1
    assert "profit_factor" in summary


def test_synthetic_generator_invalid_scenario():
    """Ensure invalid scenario name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown scenario 'invalid_curve'"):
        SyntheticReplayGenerator.generate(scenario="invalid_curve")


async def test_rest_history_exporter(tmp_path: Path):
    """Test RestHistoryExporter fetching and serializing historical trades."""
    mock_client = AsyncMock(spec=PumpFunApiClient)
    mock_client.get_trade_history.return_value = [
        {
            "timestamp": 1700000050.0,
            "price": 0.000000030,
            "is_buy": False,
            "sol_amount": 0.2,
            "token_amount": 6_000_000,
            "user": "Seller1",
        },
        {
            "timestamp": 1700000010.0,
            "price": 0.000000028,
            "is_buy": True,
            "sol_amount": 0.5,
            "token_amount": 17_000_000,
            "user": "Buyer1",
        },
    ]
    mock_client.get_coin.return_value = {
        "mint": "HistoricalMint111111111111111111111111",
        "name": "HistoricalCoin",
        "symbol": "HIST",
    }

    out_file = tmp_path / "rest_export.jsonl"
    count = await RestHistoryExporter.export_token_trades_to_file(
        client=mock_client,
        mint="HistoricalMint111111111111111111111111",
        output_path=out_file,
    )

    assert count == 2
    assert out_file.exists()
    lines = [
        json.loads(line)
        for line in out_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 2
    # Verify chronological sorting (1700000010 before 1700000050)
    assert lines[0]["timestamp"] == 1700000010.0
    assert lines[0]["name"] == "HistoricalCoin"
    assert lines[0]["is_buy"] is True
    assert lines[1]["timestamp"] == 1700000050.0
    assert lines[1]["is_buy"] is False


async def test_rest_history_exporter_branches(tmp_path: Path):
    """Test RestHistoryExporter branch conditions (non-dict payloads, empty lists)."""
    mock_client = AsyncMock(spec=PumpFunApiClient)
    mock_client.get_trade_history.return_value = "not a list"
    mock_client.get_coin.return_value = "not a dict"

    records = await RestHistoryExporter.export_token_trades(mock_client, "Mint1")
    assert records == []

    # Non-dict item inside list
    mock_client.get_trade_history.return_value = [
        "not a dict item",
        {
            "timestamp": 123,
            "price": 0.1,
            "is_buy": True,
            "sol_amount": 0.1,
            "token_amount": 100,
        },
    ]
    records = await RestHistoryExporter.export_token_trades(mock_client, "Mint1")
    assert len(records) == 1
