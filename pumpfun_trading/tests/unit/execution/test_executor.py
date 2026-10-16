"""Unit tests for ``execution/executor.py``: token-account close (BUG-96) and
transaction cost capture (FEAT-49)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.sdk.costs import (
    COST_SOURCE_MODELLED,
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
    model_transaction_costs,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.strategies.base import TradingBotConfig

MINT = "Mint111"
TOKENS = 500_000


def _client(**overrides: Any) -> MagicMock:
    client = MagicMock(spec=PumpFunExecutionClient)
    client.default_slippage_bps = 250
    client.pump_fee_bps = 125
    client.get_bonding_curve_pda.return_value = ("Curve111", 255)
    client.buy = AsyncMock(return_value="BuySig111")
    client.sell = AsyncMock(return_value="SellSig111")
    client.confirm_transaction = AsyncMock(return_value=True)
    client.get_token_balance = AsyncMock(return_value=TOKENS)
    client.get_balance_sol = AsyncMock(return_value=1.0)
    client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    client.calculate_sell_sol_output = MagicMock(return_value=10_000_000)
    client.get_transaction_costs = AsyncMock(side_effect=RuntimeError("no rpc"))
    client.model_trade_costs = MagicMock(
        side_effect=lambda rent_lamports=0, signature=None: model_transaction_costs(
            priority_fee_lamports=1_000,
            tip_lamports=2_000,
            rent_lamports=rent_lamports,
            signature=signature,
        )
    )
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


def _executor(client: MagicMock, **config: Any) -> OrderExecutor:
    return OrderExecutor(client, config=TradingBotConfig(**config), dry_run=False)


def _meta_costs(swap: int, rent: int = 0) -> TransactionCosts:
    return TransactionCosts(
        signature="Sig",
        network_fee_lamports=15_000,
        priority_fee_lamports=10_000,
        tip_lamports=100_000,
        rent_lamports=rent,
        swap_lamports=swap,
        source=COST_SOURCE_TRANSACTION_META,
    )


async def test_full_exit_closes_token_account_when_balance_matches() -> None:
    client = _client(
        get_transaction_costs=AsyncMock(
            return_value=_meta_costs(9_800_000, rent=-TOKEN_ACCOUNT_RENT_LAMPORTS)
        )
    )
    client.get_token_balance = AsyncMock(side_effect=[TOKENS, 0])
    executor = _executor(client)

    res = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=True
    )

    assert res.success
    assert client.sell.await_args.kwargs["close_token_account"] is True
    assert res.metadata["closed_token_account"] is True
    # Proceeds are the exact swap output from the transaction meta.
    assert res.metadata["proceeds_source"] == "transaction_meta"
    assert res.amount_sol == pytest.approx(0.0098)
    assert res.costs is not None and res.costs.rent_lamports < 0


@pytest.mark.parametrize(
    "balance, close_requested, config",
    [
        (TOKENS + 7, True, {}),  # dust left: closing would fail the whole sell
        (TOKENS, False, {}),  # partial exits never close
        (TOKENS, True, {"close_token_account_on_full_exit": False}),
    ],
)
async def test_sell_skips_close_when_unsafe_or_disabled(
    balance: int, close_requested: bool, config: dict[str, Any]
) -> None:
    client = _client()
    client.get_token_balance = AsyncMock(return_value=balance)
    executor = _executor(client, **config)

    res = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=close_requested
    )

    assert res.success
    assert "close_token_account" not in client.sell.await_args.kwargs
    assert res.metadata["closed_token_account"] is False


async def test_failed_closing_sell_disables_close_for_the_retry() -> None:
    client = _client(sell=AsyncMock(side_effect=RuntimeError("custom program error")))
    executor = _executor(client)

    first = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=True
    )
    assert not first.success
    assert MINT in executor._close_disabled_mints

    client.sell = AsyncMock(return_value="SellSig111")
    retry = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=True
    )
    assert retry.success
    assert "close_token_account" not in client.sell.await_args.kwargs
    assert MINT not in executor._close_disabled_mints


async def test_unconfirmed_closing_sell_disables_close() -> None:
    client = _client(confirm_transaction=AsyncMock(return_value=False))
    executor = _executor(client)

    res = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=True
    )

    assert res.error == "sell_confirmation_failed"
    assert MINT in executor._close_disabled_mints


async def test_sell_without_cost_data_uses_net_wallet_delta() -> None:
    """A wallet delta already nets out fee and tip, so no costs are attached."""
    client = _client(get_balance_sol=AsyncMock(side_effect=[1.0, 1.0095]))
    # Reserves that quote ~0.015 SOL, so the 0.0095 SOL delta is plausible.
    client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    executor = _executor(client)

    res = await executor.execute_sell(MINT, TOKENS, slippage_bps=500)

    assert res.metadata["proceeds_source"] == "sol_balance_delta"
    assert res.amount_sol == pytest.approx(0.0095)
    assert res.costs is None


async def test_sell_quote_fallback_attaches_modelled_costs() -> None:
    client = _client(get_balance_sol=AsyncMock(side_effect=RuntimeError("rpc")))
    client.get_token_balance = AsyncMock(side_effect=[TOKENS, 0])
    executor = _executor(client)

    res = await executor.execute_sell(
        MINT, TOKENS, slippage_bps=500, close_token_account=True
    )

    assert res.metadata["proceeds_source"] == "pre_trade_quote"
    assert res.costs is not None
    assert res.costs.source == COST_SOURCE_MODELLED
    assert res.costs.rent_lamports == -TOKEN_ACCOUNT_RENT_LAMPORTS


async def test_live_buy_uses_actual_swap_spend_and_costs() -> None:
    client = _client(
        get_transaction_costs=AsyncMock(
            return_value=_meta_costs(9_900_000, rent=TOKEN_ACCOUNT_RENT_LAMPORTS)
        )
    )
    client.get_token_balance = AsyncMock(side_effect=[0, 350_000])
    executor = _executor(client)

    res = await executor.execute_buy(MINT, 0.01, slippage_bps=300)

    assert res.amount_sol == pytest.approx(0.0099)
    assert res.metadata["requested_sol"] == 0.01
    assert res.costs is not None and res.costs.rent_lamports > 0


async def test_live_buy_without_meta_models_rent_for_a_new_account() -> None:
    client = _client()
    client.get_token_balance = AsyncMock(side_effect=[0, 350_000])
    executor = _executor(client)

    res = await executor.execute_buy(MINT, 0.01, slippage_bps=300)

    assert res.amount_sol == 0.01
    assert res.costs is not None
    assert res.costs.source == COST_SOURCE_MODELLED
    assert res.costs.rent_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS


async def test_dry_run_trades_carry_modelled_costs() -> None:
    client = _client()
    executor = OrderExecutor(client, config=TradingBotConfig(), dry_run=True)

    buy = await executor.execute_buy(MINT, 0.01)
    partial = await executor.execute_sell(MINT, TOKENS)
    full = await executor.execute_sell(MINT, TOKENS, close_token_account=True)

    assert buy.costs is not None and buy.costs.rent_lamports > 0
    assert partial.costs is not None and partial.costs.rent_lamports == 0
    assert full.costs is not None and full.costs.rent_lamports < 0
    assert full.metadata["closed_token_account"] is True


async def test_cost_capture_is_bounded_and_ignores_foreign_types() -> None:
    async def slow(*_args: Any, **_kwargs: Any) -> TransactionCosts:
        await asyncio.sleep(5)
        return _meta_costs(1)

    executor = _executor(_client(get_transaction_costs=AsyncMock(side_effect=slow)))
    executor.cost_capture_timeout_seconds = 0.01
    assert await executor._capture_costs("Sig", MINT, is_buy=True) is None

    executor = _executor(_client(get_transaction_costs=AsyncMock(return_value="x")))
    assert await executor._capture_costs("Sig", MINT, is_buy=True) is None

    bare = OrderExecutor(object(), config=TradingBotConfig(), dry_run=False)  # type: ignore[arg-type]
    assert await bare._capture_costs("Sig", MINT, is_buy=True) is None
    assert bare._model_costs() is None

    broken = _client(model_trade_costs=MagicMock(side_effect=ValueError("bad")))
    assert _executor(broken)._model_costs() is None
