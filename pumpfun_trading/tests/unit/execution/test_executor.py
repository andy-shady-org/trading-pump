"""Unit tests for ``execution/executor.py``: token-account close (BUG-96) and
transaction cost capture (FEAT-49)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.execution.policy import AdaptiveExecutionPolicy
from pumpfun_trading.sdk.costs import (
    COST_SOURCE_MODELLED,
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
    model_transaction_costs,
)
from pumpfun_trading.sdk.execution import (
    NonStandardCurveError,
    NotPumpFunCurveError,
    PumpFunExecutionClient,
    TokenBalanceUnavailableError,
)
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.tests.support.constants import SAMPLE_MINT
from pumpfun_trading.tests.support.factories import make_config, make_pool_keys

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
    executor = OrderExecutor(client, config=make_config(dry_run=False), dry_run=True)

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

    bare = OrderExecutor(object(), config=make_config(dry_run=False), dry_run=False)  # type: ignore[arg-type]
    assert await bare._capture_costs("Sig", MINT, is_buy=True) is None
    assert bare._model_costs() is None

    broken = _client(model_trade_costs=MagicMock(side_effect=ValueError("bad")))
    assert _executor(broken)._model_costs() is None


async def test_order_executor_dry_run():
    exec_client = MagicMock()
    executor = OrderExecutor(exec_client, dry_run=True)

    buy_res = await executor.execute_buy("Mint111", 0.1, reason="dry_buy")
    assert buy_res.success
    assert buy_res.dry_run
    assert buy_res.mint == "Mint111"
    assert buy_res.is_buy

    sell_res = await executor.execute_sell("Mint111", 500_000, reason="dry_sell")
    assert sell_res.success
    assert sell_res.dry_run
    assert not sell_res.is_buy
    assert sell_res.token_amount == 500_000
    assert sell_res.amount_sol == 0.0

    # With min_sol_output_lamports
    sell_res_lamports = await executor.execute_sell(
        "Mint111",
        500_000,
        min_sol_output_lamports=50_000_000,
        reason="dry_sell_lamports",
    )
    assert sell_res_lamports.amount_sol == pytest.approx(0.05)


@pytest.mark.regression("BUG-49")
async def test_order_executor_live_buy(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    # Pre-trade dust of 100 must not count toward the fill (BUG-49).
    mock_exec_client.get_token_balance = AsyncMock(side_effect=[100, 12_345_778])
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.signature == "BuySignature111"
    assert res.token_amount == 12_345_678
    assert res.metadata["fill_source"] == "balance_delta"
    mock_exec_client.buy.assert_awaited_once_with(
        "Mint111", "BondingCurvePubkey111", 0.1, slippage_bps=300
    )
    mock_exec_client.confirm_transaction.assert_awaited_once_with("BuySignature111")


async def test_order_executor_live_buy_curve_fallback(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    mock_exec_client.get_token_balance = AsyncMock(return_value=0)
    mock_exec_client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_073_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.signature == "BuySignature111"
    assert res.token_amount > 0


async def test_order_executor_buy_confirmation_failed(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    mock_exec_client.confirm_transaction = AsyncMock(return_value=False)
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1)
    assert not res.success
    assert res.error == "buy_confirmation_failed"


@pytest.mark.regression("BUG-48")
async def test_order_executor_live_sell(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_sell("Mint111", 500_000, slippage_bps=500)
    assert res.success
    assert res.signature == "SellSignature111"
    # No SOL balance available: proceeds are the fee-adjusted pre-trade quote,
    # not the slippage floor (BUG-48).
    expected = (30_000_000_000 * 500_000) // (1_000_000_000 + 500_000)
    expected = expected * (10_000 - 125) // 10_000
    assert res.amount_sol == pytest.approx(expected / 1e9)
    assert res.metadata["proceeds_source"] == "pre_trade_quote"
    mock_exec_client.sell.assert_awaited_once_with(
        "Mint111",
        "BondingCurvePubkey111",
        500_000,
        min_sol_output=500_000_000,
        slippage_bps=500,
    )


async def test_order_executor_raydium(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)
    pool_keys = RaydiumPoolKeys(
        amm_id="Amm111",
        amm_authority="Auth111",
        amm_open_orders="Open111",
        amm_target_orders="Target111",
        pool_coin_token_account="CoinVault111",
        pool_pc_token_account="PcVault111",
        serum_program_id="Serum111",
        serum_market="Market111",
        serum_bids="Bids111",
        serum_asks="Asks111",
        serum_event_queue="Events111",
        serum_coin_vault="SerumCoin111",
        serum_pc_vault="SerumPc111",
        serum_vault_signer="Signer111",
        coin_mint="Mint111",
        pc_mint="So11111111111111111111111111111111111111112",
        lp_mint="LpMint111",
    )

    buy_res = await executor.execute_raydium_buy("Mint111", pool_keys, 0.25)
    assert buy_res.success
    assert buy_res.signature == "RaydiumSignature111"

    sell_res = await executor.execute_raydium_sell("Mint111", pool_keys, 1_000_000)
    assert sell_res.success
    assert sell_res.signature == "RaydiumSignature111"


@pytest.mark.regression("BUG-73")
async def test_buy_confirmation_timeout_with_tokens_received_is_success(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-73: a confirm timeout is re-checked against balances before failing."""
    mock_exec_client.confirm_transaction = AsyncMock(return_value=False)
    mock_exec_client.get_token_balance = AsyncMock(side_effect=[0, 0, 7_000_000])
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    assert res.token_amount == 7_000_000
    assert res.metadata == {
        "fill_source": "balance_delta",
        "confirmed": False,
        "requested_sol": 0.1,
    }


@pytest.mark.regression("BUG-49", "BUG-73")
async def test_buy_unreadable_pre_balance_falls_back_to_pre_trade_quote(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-49/73: an unreadable balance never counts the whole ATA as the fill."""

    mock_exec_client.get_token_balance = AsyncMock(
        side_effect=TokenBalanceUnavailableError("rpc down")
    )
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_buy("Mint111", 0.1, slippage_bps=300)
    assert res.success
    lamports = 100_000_000 * 10_000 // 10_125
    expected = (1_000_000_000 * lamports) // (30_000_000_000 + lamports)
    assert res.token_amount == expected
    assert res.metadata["fill_source"] == "pre_trade_quote"


@pytest.mark.regression("BUG-48")
async def test_sell_proceeds_come_from_sol_balance_delta(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-48: proceeds are the SOL actually received, not min_sol_output."""
    mock_exec_client.get_balance_sol = AsyncMock(side_effect=[1.0, 1.0, 1.0123])
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_sell("Mint111", 500_000, slippage_bps=500)
    assert res.success
    assert res.amount_sol == pytest.approx(0.0123)
    assert res.metadata["proceeds_source"] == "sol_balance_delta"


@pytest.mark.regression("BUG-73")
async def test_sell_confirmation_timeout_rechecks_token_balance(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-73: a sell that landed after the confirm timeout is reported as filled."""
    mock_exec_client.confirm_transaction = AsyncMock(return_value=False)
    mock_exec_client.get_token_balance = AsyncMock(side_effect=[500_000, 0])
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)

    res = await executor.execute_sell("Mint111", 500_000, slippage_bps=500)
    assert res.success
    assert res.metadata["confirmed"] is False

    mock_exec_client.get_token_balance = AsyncMock(return_value=500_000)
    res_failed = await executor.execute_sell("Mint111", 500_000, slippage_bps=500)
    assert not res_failed.success
    assert res_failed.error == "sell_confirmation_failed"


@pytest.mark.regression("BUG-50")
async def test_raydium_buy_records_token_balance_delta(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-50: live Raydium buys record the tokens received, not 0."""
    mock_exec_client.get_token_balance = AsyncMock(side_effect=[50, 4_000_050])
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)
    pool_keys = MagicMock(spec=RaydiumPoolKeys)

    res = await executor.execute_raydium_buy("Mint111", pool_keys, 0.1)
    assert res.success
    assert res.token_amount == 4_000_000

    mock_exec_client.get_balance_sol = AsyncMock(side_effect=[2.0, 2.05])
    sell = await executor.execute_raydium_sell("Mint111", pool_keys, 4_000_000)
    assert sell.success
    assert sell.amount_sol == pytest.approx(0.05)


@pytest.mark.regression("BUG-52")
async def test_dynamic_slippage_uses_live_reserves_and_real_notional(
    mock_exec_client: MagicMock, base_config: TradingBotConfig
):
    """BUG-52: policy gets live curve reserves, the real SOL size and curve updates."""
    executor = OrderExecutor(mock_exec_client, config=base_config, dry_run=False)
    policy = executor.execution_policy
    resolve_spy = MagicMock(wraps=policy.resolve_parameters)

    with patch.object(policy, "resolve_parameters", resolve_spy):
        await executor.execute_buy("Mint111", 0.1)
        buy_kwargs = resolve_spy.call_args
        assert buy_kwargs.args[1] == pytest.approx(0.1)
        assert buy_kwargs.kwargs["virtual_sol_reserves"] == pytest.approx(30.0)
        assert buy_kwargs.kwargs["virtual_token_reserves"] == 1_000_000_000

        await executor.execute_sell("Mint111", 500_000)
        sell_kwargs = resolve_spy.call_args
    assert sell_kwargs.kwargs["is_buy"] is False
    assert sell_kwargs.args[1] == pytest.approx(0.0148, rel=0.01)
    assert len(policy.get_estimator("Mint111").get_observations()) == 2


async def test_order_executor_raydium_and_exceptions():
    exec_client = MagicMock(spec=PumpFunExecutionClient)
    executor = OrderExecutor(execution_client=exec_client, dry_run=False)

    # Buy exception
    exec_client.get_bonding_curve_pda.return_value = (Pubkey.default(), 255)
    exec_client.buy = AsyncMock(side_effect=RuntimeError("RPC Buy timeout"))
    res = await executor.execute_buy(SAMPLE_MINT, 0.05)
    assert res.success is False
    assert "buy_failed" in (res.error or "")

    pool_keys = make_pool_keys(unique=False)

    # Raydium buy dry run
    executor_dry = OrderExecutor(execution_client=exec_client, dry_run=True)
    res_dry = await executor_dry.execute_raydium_buy(SAMPLE_MINT, pool_keys, 0.05)
    assert res_dry.success is True
    assert res_dry.dry_run is True

    # Raydium buy swap exception
    exec_client.swap_raydium = AsyncMock(
        side_effect=RuntimeError("Raydium pool locked")
    )
    res_ray_err = await executor.execute_raydium_buy(SAMPLE_MINT, pool_keys, 0.05)
    assert res_ray_err.success is False
    assert "raydium_buy_failed" in (res_ray_err.error or "")

    # Raydium buy empty signature
    exec_client.swap_raydium = AsyncMock(return_value="")
    res_no_sig = await executor.execute_raydium_buy(SAMPLE_MINT, pool_keys, 0.05)
    assert res_no_sig.success is False
    assert res_no_sig.error == "raydium_buy_signature_missing"

    # Raydium buy confirmation failure
    exec_client.swap_raydium = AsyncMock(return_value="sig_ray_123")
    exec_client.confirm_transaction = AsyncMock(return_value=False)
    res_no_conf = await executor.execute_raydium_buy(SAMPLE_MINT, pool_keys, 0.05)
    assert res_no_conf.success is False
    assert res_no_conf.error == "raydium_buy_confirmation_failed"

    # Raydium sell dry run
    res_sell_dry = await executor_dry.execute_raydium_sell(SAMPLE_MINT, pool_keys, 1000)
    assert res_sell_dry.success is True
    assert res_sell_dry.dry_run is True

    # Raydium sell swap exception
    exec_client.swap_raydium = AsyncMock(side_effect=RuntimeError("Slippage exceeded"))
    res_sell_err = await executor.execute_raydium_sell(SAMPLE_MINT, pool_keys, 1000)
    assert res_sell_err.success is False
    assert "raydium_sell_failed" in (res_sell_err.error or "")

    # Raydium sell signature missing
    exec_client.swap_raydium = AsyncMock(return_value="")
    res_sell_no_sig = await executor.execute_raydium_sell(SAMPLE_MINT, pool_keys, 1000)
    assert res_sell_no_sig.success is False
    assert res_sell_no_sig.error == "raydium_sell_signature_missing"


async def test_order_executor_retry_and_liquidator():
    mock_client = MagicMock(spec=PumpFunExecutionClient)
    mock_client.wallet = Keypair().pubkey()
    mock_client.get_token_balance = AsyncMock(return_value=1_000_000)
    mock_client.get_bonding_curve_pda.return_value = (
        "11111111111111111111111111111111",
        255,
    )
    mock_client.default_slippage_bps = 250
    mock_client.calculate_sell_sol_output = MagicMock(return_value=10_000_000)
    mock_client.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
        }
    )
    mock_client.sell = AsyncMock(return_value="sig_sell")
    mock_client.confirm_transaction = AsyncMock(return_value=True)

    policy = AdaptiveExecutionPolicy()
    executor = OrderExecutor(
        execution_client=mock_client,
        execution_policy=policy,
        dry_run=False,
    )

    # Live buy and sell
    res_buy = await executor.execute_buy("mint_buy", 0.01, dry_run=True)
    assert res_buy.success is True

    res_sell = await executor.execute_sell("mint_sell", 1_000_000, dry_run=False)
    assert res_sell.success is True

    # Liquidator

    pos_mgr = PositionManager(config=make_config(dry_run=False))
    pos_mgr.record_buy(
        "mint_liq", token_amount=1_000_000, cost_sol=0.01, entry_market_cap=30.0
    )
    liquidator = OrderLiquidator(executor=executor, position_manager=pos_mgr)
    res_liq = await liquidator.liquidate_position("mint_liq", reason="emergency_stop")
    assert res_liq is True

    # Liquidate all
    pos_mgr.record_buy(
        "mint_liq_2", token_amount=1_000_000, cost_sol=0.01, entry_market_cap=30.0
    )
    all_liq = await liquidator.liquidate_all_positions(reason="panic")
    assert len(all_liq) >= 1


# --- BUG-104: paper pricing from the curve, non-standard curves refused -----------


@pytest.mark.regression("BUG-104")
@pytest.mark.parametrize("dry_run", [True, False])
async def test_execute_buy_non_standard_curve_is_refused(dry_run: bool) -> None:
    client = _client(
        get_bonding_curve_state=AsyncMock(
            side_effect=NonStandardCurveError("virtual SOL offset 105860 SOL")
        )
    )
    executor = _executor(client)

    result = await executor.execute_buy(MINT, 0.01, dry_run=dry_run)

    assert not result.success
    assert result.error is not None
    assert result.error.startswith("non_standard_curve")
    client.buy.assert_not_awaited()


@pytest.mark.regression("BUG-104")
async def test_execute_buy_dry_run_reports_curve_entry_market_cap() -> None:
    client = _client()
    executor = _executor(client)

    result = await executor.execute_buy(MINT, 0.01, dry_run=True)

    assert result.success
    assert result.metadata["entry_market_cap_sol"] == pytest.approx(30.0)


async def test_execute_buy_dry_run_without_curve_has_no_entry_market_cap() -> None:
    client = _client(get_bonding_curve_state=AsyncMock(side_effect=RuntimeError("x")))
    executor = _executor(client)

    result = await executor.execute_buy(MINT, 0.01, dry_run=True)

    assert result.success
    assert "entry_market_cap_sol" not in result.metadata


async def test_execute_sell_non_standard_curve_still_sells_without_quote() -> None:
    client = _client(
        get_bonding_curve_state=AsyncMock(side_effect=NonStandardCurveError("bad"))
    )
    executor = _executor(client)

    result = await executor.execute_sell(MINT, TOKENS, reason="stop_loss", dry_run=True)

    assert result.success
    assert result.amount_sol == 0.0


# --- BUG-108: only Pump.fun curves are bought -------------------------------------


@pytest.mark.regression("BUG-108")
@pytest.mark.parametrize("dry_run", [True, False])
async def test_execute_buy_without_pump_fun_curve_is_refused(dry_run: bool) -> None:
    client = _client(
        get_bonding_curve_state=AsyncMock(
            side_effect=NotPumpFunCurveError("Bonding curve account not found")
        )
    )
    executor = _executor(client)

    result = await executor.execute_buy(MINT, 0.01, dry_run=dry_run)

    assert not result.success
    assert result.error is not None
    assert result.error.startswith("not_pump_fun")
    client.buy.assert_not_awaited()


# --- Paper entries pay for latency ------------------------------------------------


async def test_execute_buy_dry_run_entry_slippage_worsens_the_fill() -> None:
    plain = await _executor(_client()).execute_buy(MINT, 0.01, dry_run=True)
    worse = await _executor(_client(), paper_entry_slippage_bps=300).execute_buy(
        MINT, 0.01, dry_run=True
    )

    assert worse.token_amount == plain.token_amount * 9_700 // 10_000
    assert worse.metadata["entry_market_cap_sol"] == pytest.approx(30.0 / 0.97)
    assert worse.metadata["paper_entry_slippage_bps"] == 300
    assert "paper_entry_slippage_bps" not in plain.metadata


async def test_execute_buy_dry_run_delay_prices_from_the_later_curve() -> None:
    client = _client(
        get_bonding_curve_state=AsyncMock(
            side_effect=[
                {
                    "virtual_token_reserves": 1_000_000_000_000_000,
                    "virtual_sol_reserves": 30_000_000_000,
                },
                {
                    "virtual_token_reserves": 500_000_000_000_000,
                    "virtual_sol_reserves": 60_000_000_000,
                },
            ]
        )
    )
    executor = _executor(client, paper_entry_delay_seconds=1.5)

    with patch(
        "pumpfun_trading.execution.executor.asyncio.sleep", AsyncMock()
    ) as sleep:
        result = await executor.execute_buy(MINT, 0.01, dry_run=True)

    sleep.assert_awaited_once_with(1.5)
    assert result.success
    # The curve doubled in price while the "buy" was landing.
    assert result.metadata["entry_market_cap_sol"] == pytest.approx(120.0)
    assert result.metadata["paper_entry_delay_seconds"] == 1.5


async def test_execute_buy_dry_run_curve_turning_non_standard_after_delay_refuses() -> (
    None
):
    client = _client(
        get_bonding_curve_state=AsyncMock(
            side_effect=[
                {
                    "virtual_token_reserves": 1_000_000_000_000_000,
                    "virtual_sol_reserves": 30_000_000_000,
                },
                NonStandardCurveError("virtual SOL offset 764 SOL"),
            ]
        )
    )
    executor = _executor(client, paper_entry_delay_seconds=1.0)

    with patch("pumpfun_trading.execution.executor.asyncio.sleep", AsyncMock()):
        result = await executor.execute_buy(MINT, 0.01, dry_run=True)

    assert not result.success
    assert result.error is not None
    assert result.error.startswith("non_standard_curve")


async def test_execute_buy_dry_run_without_curve_skips_the_delay() -> None:
    client = _client(get_bonding_curve_state=AsyncMock(side_effect=RuntimeError("x")))
    executor = _executor(client, paper_entry_delay_seconds=2.0)

    with patch(
        "pumpfun_trading.execution.executor.asyncio.sleep", AsyncMock()
    ) as sleep:
        result = await executor.execute_buy(MINT, 0.01, dry_run=True)

    assert result.success
    sleep.assert_not_awaited()


@pytest.mark.parametrize("configured, applied", [(-5, 0), (9_999, 5_000), (250, 250)])
def test_paper_entry_slippage_bps_is_clamped(configured: int, applied: int) -> None:
    executor = _executor(_client())
    executor.config = MagicMock(paper_entry_slippage_bps=configured)

    assert executor._paper_entry_slippage_bps() == applied


# --- Mayhem-mode curves are not bought --------------------------------------------


@pytest.mark.parametrize("dry_run", [True, False])
async def test_execute_buy_on_mayhem_curve_is_refused(dry_run: bool) -> None:
    client = _client()
    state = dict(client.get_bonding_curve_state.return_value)
    client.get_bonding_curve_state = AsyncMock(
        return_value={**state, "is_mayhem_mode": True}
    )

    result = await _executor(client).execute_buy(MINT, 0.01, dry_run=dry_run)
    assert not result.success
    assert result.error is not None and result.error.startswith("mayhem_mode")
    client.buy.assert_not_awaited()

    allowed = await _executor(client, skip_mayhem_mode=False).execute_buy(
        MINT, 0.01, dry_run=True
    )
    assert allowed.success
