"""Shared fixtures for ``unit/execution/``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.strategies.base import TradingBotConfig


@pytest.fixture
def mock_exec_client() -> MagicMock:
    client = MagicMock(spec=PumpFunExecutionClient)
    client.default_slippage_bps = 250
    client.get_bonding_curve_pda.return_value = ("BondingCurvePubkey111", 255)
    client.buy = AsyncMock(return_value="BuySignature111")
    client.sell = AsyncMock(return_value="SellSignature111")
    client.swap_raydium = AsyncMock(return_value="RaydiumSignature111")
    client.confirm_transaction = AsyncMock(return_value=True)
    client.get_token_balance = AsyncMock(return_value=1_000_000)
    client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    client.calculate_sell_sol_output = MagicMock(return_value=500_000_000)
    return client


@pytest.fixture
def base_config() -> TradingBotConfig:
    return TradingBotConfig(
        buy_amount_sol=0.1,
        take_profit=1.5,
        stop_loss=0.8,
        dry_run=False,
    )
