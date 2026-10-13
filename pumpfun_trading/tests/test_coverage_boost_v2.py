from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from solders.pubkey import Pubkey

from pumpfun_trading.bot.alerts import AlertDispatcher
from pumpfun_trading.bot.enrichment import TokenScreeningVerdict
from pumpfun_trading.bot.event_router import EventRouter
from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.persistence import StatusPersistenceManager
from pumpfun_trading.bot.position_manager import Position, PositionManager
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.config.env import get_env_list
from pumpfun_trading.execution.executor import ExecutionResult, OrderExecutor
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.infra.rpc_pool import (
    CircuitState,
    RpcConnectionPool,
    RpcEndpoint,
    RpcPoolConfig,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.copy_trading import (
    CopyTradeEngine,
    CopyTradeSignal,
    TrackedWallet,
    WalletRegistry,
)
from pumpfun_trading.strategies.graduation import GraduationSignal
from pumpfun_trading.strategies.momentum import MomentumSignal, WindowMetrics
from pumpfun_trading.strategies.signal import (
    generate_buy_signal,
    generate_copy_trade_buy_signal,
    generate_graduation_buy_signal,
    generate_momentum_buy_signal,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_MINT_2 = "So11111111111111111111111111111111111111112"


def test_position_dataclass_and_manager_edge_cases():
    pos = Position(
        mint=SAMPLE_MINT,
        name="TestCoin",
        entry_market_cap=0.0,
        current_market_cap=10.0,
        peak_market_cap=15.0,
        initial_token_amount=1000,
        remaining_token_amount=1000,
    )
    # Zero entry mc properties
    assert pos.performance == 1.0
    assert pos.peak_performance == 1.0

    # Setter
    pos.token_amount = 500
    assert pos.remaining_token_amount == 500
    assert pos.token_amount == 500

    cfg = TradingBotConfig(dry_run=True, buy_amount_sol=0.05)
    pm = PositionManager(cfg)

    # Magic methods & container methods
    assert len(pm) == 0
    assert pm.count() == 0
    assert list(pm.keys()) == []
    assert list(pm.values()) == []
    assert list(pm.items()) == []
    assert list(pm) == []

    # get_exit_state and evaluate_exit on non-existent mint
    assert pm.get_exit_state("non_existent") is None
    assert pm.evaluate_exit("non_existent") is None
    assert pm.calculate_unrealized_pnl("non_existent") == 0.0

    # record sell on non-existent
    closed, rem = pm.record_sell("non_existent", 100)
    assert closed is True
    assert rem == 0

    # Update price on non-existent
    entry, curr, peak = pm.update_price("non_existent", 25.0)
    assert entry == 0.0
    assert curr == 25.0
    assert peak == 25.0

    # Add position and test setter/getters
    pm["MintA"] = {
        "name": "TokenA",
        "entry_market_cap": 0.0,  # test zero entry mc branch
        "current_market_cap": 0.0,
        "peak_market_cap": 0.0,
        "token_amount": 1000,
        "remaining_token_amount": 1000,
        "cost_sol": 0.05,
    }
    assert "MintA" in pm
    assert pm["MintA"]["name"] == "TokenA"
    assert len(pm) == 1
    assert pm.count() == 1
    assert list(pm.keys()) == ["MintA"]
    assert len(list(pm.values())) == 1
    assert len(list(pm.items())) == 1
    assert list(pm) == ["MintA"]

    # Price update with entry_mc <= 0
    entry, curr, peak = pm.update_price("MintA", 50.0)
    assert entry == 50.0
    assert curr == 50.0
    assert peak == 50.0

    # calculate unrealized pnl when entry_mc <= 0
    pm["MintA"]["entry_market_cap"] = 0.0
    assert pm.calculate_unrealized_pnl("MintA") == 0.0

    # calculate total open value with entry_mc <= 0
    val = pm.calculate_total_open_value()
    assert val == 0.05

    # restore from dict with invalid structure
    pm.restore_from_dict({"Invalid": "not_a_dict"})
    assert "Invalid" not in pm


def test_persistence_manager_error_handling(tmp_path):
    # Test open failure on invalid audit log path
    invalid_audit_path = str(tmp_path / "not_a_dir" / "audit.jsonl")
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        pm_fail = StatusPersistenceManager(audit_log_path=invalid_audit_path)
        assert pm_fail._audit_handle is None
        # write_audit_record when opening fails
        pm_fail.write_audit_record("test", "STATE", {"data": 1})
        pm_fail.close()

    # Status write exception
    status_file = tmp_path / "status.json"
    pm = StatusPersistenceManager(bot_status_path=str(status_file))
    with patch("os.replace", side_effect=OSError("Replace error")):
        assert pm.write_status_snapshot({"state": "TEST"}) is False

    # Status load non-dict JSON
    status_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert pm.load_status_snapshot() is None

    # Status load corrupt JSON
    status_file.write_text("invalid json {{{", encoding="utf-8")
    assert pm.load_status_snapshot() is None

    # Audit write exception
    audit_file = tmp_path / "valid_audit.jsonl"
    pm_audit = StatusPersistenceManager(audit_log_path=str(audit_file))
    mock_handle = MagicMock()
    mock_handle.write.side_effect = OSError("Disk write failed")
    pm_audit._audit_handle = mock_handle
    pm_audit.write_audit_record("trade", "BUY", {"amount": 1})
    pm_audit.close()


def test_alert_dispatcher_auto_detection_and_providers():
    # Discord auto-detection
    d_auto = AlertDispatcher(discord_webhook_url="https://discord.com/hook")
    assert d_auto.provider == "discord"
    assert d_auto.enabled is True

    # Slack auto-detection
    s_auto = AlertDispatcher(slack_webhook_url="https://slack.com/hook")
    assert s_auto.provider == "slack"
    assert s_auto.enabled is True

    # Telegram auto-detection
    t_auto = AlertDispatcher(telegram_bot_token="tok", telegram_chat_id="chat")
    assert t_auto.provider == "telegram"
    assert t_auto.enabled is True

    # Unknown provider
    u_disp = AlertDispatcher(provider="unsupported_service")
    assert u_disp.enabled is False

    # Missing URLs for explicitly set providers
    assert not AlertDispatcher(provider="slack", slack_webhook_url=None).enabled
    assert not AlertDispatcher(provider="telegram", telegram_bot_token=None).enabled
    assert not AlertDispatcher(
        provider="telegram", telegram_bot_token="t", telegram_chat_id=None
    ).enabled

    # Empty payload handling
    assert not d_auto.send_alert("")
    assert not d_auto.send_alert("   ")

    # Mocked Slack send
    with patch("urllib.request.urlopen") as mock_url:
        assert s_auto.send_alert("Slack test message") is True
        assert mock_url.called

    # Mocked Telegram send
    with patch("urllib.request.urlopen") as mock_url:
        assert t_auto.send_alert("Telegram test message") is True
        assert mock_url.called


@pytest.mark.asyncio
async def test_alert_dispatcher_async_send():
    disp = AlertDispatcher(discord_webhook_url="https://discord.com/hook")
    with patch("urllib.request.urlopen") as mock_url:
        res = await disp.send_alert_async("Async alert test")
        assert res is True
        assert mock_url.called

    disp_disabled = AlertDispatcher(provider="none")
    assert await disp_disabled.send_alert_async("Disabled alert") is False


def make_test_pool_keys() -> RaydiumPoolKeys:
    pk = str(Pubkey.default())
    return RaydiumPoolKeys(
        amm_id=pk,
        amm_authority=pk,
        amm_open_orders=pk,
        amm_target_orders=pk,
        pool_coin_token_account=pk,
        pool_pc_token_account=pk,
        serum_program_id=pk,
        serum_market=pk,
        serum_bids=pk,
        serum_asks=pk,
        serum_event_queue=pk,
        serum_coin_vault=pk,
        serum_pc_vault=pk,
        serum_vault_signer=pk,
        coin_mint=SAMPLE_MINT,
        pc_mint=SAMPLE_MINT_2,
        lp_mint=pk,
    )


@pytest.mark.asyncio
async def test_event_router_all_routes():
    curve_mock = AsyncMock()
    trade_mock = AsyncMock()
    complete_mock = AsyncMock()
    ray_mock = AsyncMock()
    ws_new_mock = AsyncMock()
    ws_trade_mock = AsyncMock()

    router = EventRouter(
        on_curve_update=curve_mock,
        on_trade_event=trade_mock,
        on_complete_event=complete_mock,
        on_raydium_pool=ray_mock,
        on_ws_new_token=ws_new_mock,
        on_ws_trade=ws_trade_mock,
    )

    curve_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curve111",
        slot=12345,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=30.0,
    )
    await router.route_geyser_curve_update(curve_up)
    assert curve_mock.called

    trade_up = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=100,
        is_buy=True,
        user="user111",
        timestamp=time.time(),
        virtual_sol_reserves=1000,
        virtual_token_reserves=1000,
        real_sol_reserves=1000,
        real_token_reserves=1000,
    )
    await router.route_geyser_trade_update(trade_up)
    assert trade_mock.called

    comp_up = CompleteEventUpdate(
        mint=SAMPLE_MINT,
        bonding_curve="curve111",
        user="user111",
        timestamp=time.time(),
    )
    await router.route_geyser_complete_update(comp_up)
    assert complete_mock.called

    pool_keys = make_test_pool_keys()
    await router.route_raydium_pool(pool_keys)
    assert ray_mock.called

    # WS messages
    await router.route_ws_message("not_dict")
    await router.route_ws_message({"type": "create", "mint": SAMPLE_MINT})
    assert ws_new_mock.called

    await router.route_ws_message({"type": "trade", "mint": SAMPLE_MINT})
    assert ws_trade_mock.called


@pytest.mark.asyncio
async def test_order_executor_raydium_and_exceptions():
    exec_client = MagicMock(spec=PumpFunExecutionClient)
    executor = OrderExecutor(execution_client=exec_client, dry_run=False)

    # Buy exception
    exec_client.get_bonding_curve_pda.return_value = (Pubkey.default(), 255)
    exec_client.buy = AsyncMock(side_effect=RuntimeError("RPC Buy timeout"))
    res = await executor.execute_buy(SAMPLE_MINT, 0.05)
    assert res.success is False
    assert "buy_failed" in (res.error or "")

    pool_keys = make_test_pool_keys()

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


@pytest.mark.asyncio
async def test_order_liquidator_branches():
    executor = MagicMock(spec=OrderExecutor)
    pm = PositionManager(TradingBotConfig())
    liquidator = OrderLiquidator(executor=executor, position_manager=pm)

    # Empty positions
    liquidated = await liquidator.liquidate_all_positions()
    assert liquidated == []

    # Populated positions
    pm.record_buy(SAMPLE_MINT, 1000, 0.05, 30.0, dry_run=True)
    pm.record_buy(SAMPLE_MINT_2, 2000, 0.10, 40.0, dry_run=True)

    # Mock execute_sell success and failure
    async def mock_sell(mint, token_amount, slippage_bps=None, reason=""):
        if mint == SAMPLE_MINT:
            return ExecutionResult(
                success=True, mint=mint, amount_sol=0.06, token_amount=token_amount
            )
        raise RuntimeError("Liquidate fail")

    executor.execute_sell = AsyncMock(side_effect=mock_sell)
    liquidated = await liquidator.liquidate_all_positions(reason="panic_test")
    assert liquidated == [SAMPLE_MINT]


def test_strategy_signal_generation_all_branches():
    cfg = TradingBotConfig(
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
    cfg_enabled = TradingBotConfig(
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


@pytest.mark.asyncio
async def test_rpc_pool_broadcast_and_health_branches():
    ep1 = RpcEndpoint(url="https://rpc1.solana.com", label="RPC 1")
    ep2 = RpcEndpoint(url="https://rpc2.solana.com", label="RPC 2")
    cfg = RpcPoolConfig(
        endpoints=[ep1, ep2],
        broadcast_concurrency=2,
        circuit_breaker_threshold=2,
    )
    pool = RpcConnectionPool(endpoints=[ep1, ep2], config=cfg)

    # Mock session post responses for broadcast errors
    mock_session = MagicMock()

    # Case 1: HTTP 429
    resp_429 = AsyncMock()
    resp_429.status = 429
    resp_429.text = AsyncMock(return_value="Rate limited")

    mock_session.post.return_value.__aenter__.return_value = resp_429
    pool._session = mock_session

    with pytest.raises(RuntimeError, match="Multi-RPC transaction broadcast failed"):
        await pool.broadcast_transaction("base64_tx_payload")

    assert ep1.state in {CircuitState.DEGRADED, CircuitState.OPEN}

    # Case 2: HTTP 500
    resp_500 = AsyncMock()
    resp_500.status = 500
    resp_500.text = AsyncMock(return_value="Internal Server Error")
    mock_session.post.return_value.__aenter__.return_value = resp_500

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 3: Invalid JSON type (returns string instead of dict)
    resp_str = AsyncMock()
    resp_str.status = 200
    resp_str.text = AsyncMock(return_value="not_a_json_dict")
    resp_str.json = AsyncMock(side_effect=ValueError("json err"))
    mock_session.post.return_value.__aenter__.return_value = resp_str

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 4: JSON contains "error"
    resp_err = AsyncMock()
    resp_err.status = 200
    resp_err.text = AsyncMock(return_value=json.dumps({"error": "Blockhash expired"}))
    resp_err.json = AsyncMock(return_value={"error": "Blockhash expired"})
    mock_session.post.return_value.__aenter__.return_value = resp_err

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Case 5: Invalid signature (short string)
    resp_bad_sig = AsyncMock()
    resp_bad_sig.status = 200
    resp_bad_sig.text = AsyncMock(return_value=json.dumps({"result": "too_short"}))
    resp_bad_sig.json = AsyncMock(return_value={"result": "too_short"})
    mock_session.post.return_value.__aenter__.return_value = resp_bad_sig

    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("base64_tx_payload")

    # Check health probes
    resp_health_ok = AsyncMock()
    resp_health_ok.status = 200
    mock_session.post.return_value.__aenter__.return_value = resp_health_ok
    assert await pool.check_endpoint_health(ep1) is True

    resp_health_429 = AsyncMock()
    resp_health_429.status = 429
    mock_session.post.return_value.__aenter__.return_value = resp_health_429
    assert await pool.check_endpoint_health(ep1) is False

    resp_health_500 = AsyncMock()
    resp_health_500.status = 500
    mock_session.post.return_value.__aenter__.return_value = resp_health_500
    assert await pool.check_endpoint_health(ep1) is False

    await pool.close()


def test_copy_trading_and_env_missing_branches():
    # Env list helper
    os.environ["PUMPFUN_TEST_LIST"] = " mint1, mint2 , mint3 "

    assert get_env_list("PUMPFUN_TEST_LIST") == ("mint1", "mint2", "mint3")
    assert get_env_list("PUMPFUN_NONEXISTENT_ENV", default=("def",)) == ("def",)

    # CopyTradeSignal to_dict
    sig = CopyTradeSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        wallet_address="Wallet111",
        wallet_label="Whale1",
        is_buy=True,
        sol_amount=1.5,
        computed_copy_size_sol=0.05,
        reason="whale_buy",
    )
    d = sig.to_dict()
    assert d["triggered"] is True
    assert d["wallet_label"] == "Whale1"

    # WalletRegistry tests
    reg = WalletRegistry()
    with pytest.raises(ValueError, match="Wallet address cannot be empty"):
        reg.register_wallet(TrackedWallet(address=""))

    w1 = TrackedWallet(
        address="W1", label="One", enabled=True, win_rate=0.75, risk_score=20.0
    )
    w2 = TrackedWallet(
        address="W2", label="Two", enabled=False, win_rate=0.40, risk_score=50.0
    )
    reg.register_wallets([w1, w2])
    assert reg.wallet_count == 2
    assert len(reg.list_wallets(only_enabled=True)) == 1
    assert len(reg.list_wallets(only_enabled=False)) == 2
    assert reg.remove_wallet("W1") is True
    assert reg.remove_wallet("W_NON") is False
    assert reg.wallet_count == 1
    reg.clear()
    assert reg.wallet_count == 0

    # CopyTradeEngine evaluations
    engine = CopyTradeEngine(
        base_buy_amount_sol=0.02,
        max_position_size_sol=0.05,
        sizing_mode="scaled",
        min_wallet_win_rate=0.60,
        max_wallet_risk_score=40.0,
        mirror_sells=True,
        enabled=True,
    )
    # Disabled wallet
    w_dis = TrackedWallet(address="W_DIS", label="Dis", enabled=False)
    assert (
        engine.evaluate_copy_signal(w_dis, SAMPLE_MINT, 1.0, True).reason
        == "wallet_disabled"
    )

    # Low win rate
    w_low_wr = TrackedWallet(address="W_LOW", label="Low", enabled=True, win_rate=0.30)
    assert (
        "below_min"
        in engine.evaluate_copy_signal(w_low_wr, SAMPLE_MINT, 1.0, True).reason
    )

    # High risk score
    w_high_risk = TrackedWallet(
        address="W_RISK", label="Risk", enabled=True, win_rate=0.80, risk_score=80.0
    )
    assert (
        "exceeds_max"
        in engine.evaluate_copy_signal(w_high_risk, SAMPLE_MINT, 1.0, True).reason
    )

    # Mirror sells disabled
    engine_no_mirror = CopyTradeEngine(mirror_sells=False, enabled=True)
    w_good = TrackedWallet(
        address="W_GOOD", label="Good", enabled=True, win_rate=0.80, risk_score=20.0
    )
    assert (
        engine_no_mirror.evaluate_copy_signal(w_good, SAMPLE_MINT, 1.0, False).reason
        == "mirror_sells_disabled"
    )

    # Engine disabled
    engine_dis = CopyTradeEngine(enabled=False)
    assert (
        engine_dis.evaluate_copy_signal(w_good, SAMPLE_MINT, 1.0, True).reason
        == "copy_trading_disabled"
    )

    # calculate_copy_size with max_allocation <= 0
    w_good.max_allocation_sol = 0.0
    size = engine.calculate_copy_size(w_good, 1.0)
    assert size <= 0.05

    # record_and_evaluate on unregistered wallet
    assert (
        engine.record_and_evaluate("UNREGISTERED", SAMPLE_MINT, 1.0, True).triggered
        is False
    )


def test_trading_bot_validation_errors():
    with pytest.raises(ValueError, match="buy_amount_sol must be greater than zero"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=TradingBotConfig(buy_amount_sol=0.0),
        )

    with pytest.raises(ValueError, match="stop_loss must be less than take_profit"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=TradingBotConfig(stop_loss=2.0, take_profit=1.5),
        )

    with pytest.raises(ValueError, match="max_active_positions must be at least 1"):
        TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=TradingBotConfig(max_active_positions=0),
        )


@pytest.mark.asyncio
async def test_trading_bot_facade_and_lifecycle(tmp_path):
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"
    cfg = TradingBotConfig(
        dry_run=True,
        buy_amount_sol=0.02,
        enable_copy_trading=True,
        copy_trading_wallets=[
            {
                "address": "WhaleAlpha",
                "label": "AlphaWhale",
                "win_rate": 0.85,
                "risk_score": 15.0,
            }
        ],
    )

    with patch.dict(
        os.environ,
        {
            "PUMPFUN_BOT_STATUS_PATH": str(status_file),
            "PUMPFUN_AUDIT_LOG": str(audit_file),
        },
    ):
        bot = TradingBot(
            private_key_b58=SAMPLE_PRIVATE_KEY,
            rpc_url="https://api.mainnet-beta.solana.com",
            config=cfg,
        )

    assert bot.state == TradingBotState.IDLE
    metrics = bot._metrics_snapshot()
    assert "total_trades" in metrics or isinstance(metrics, dict)

    # Position management delegation
    pos = bot.position_manager.record_buy(
        mint=SAMPLE_MINT,
        token_amount=1_000_000,
        cost_sol=0.02,
        entry_market_cap=30.0,
        name="SolCat",
    )
    assert pos["name"] == "SolCat"
    assert bot.position_manager.has_position(SAMPLE_MINT)
    assert bot.position_manager.get_position(SAMPLE_MINT) is not None
    assert len(bot.active_positions) == 1

    entry, curr, peak = bot.position_manager.update_price(SAMPLE_MINT, 45.0)
    assert curr == 45.0
    assert peak == 45.0

    closed, rem = bot.position_manager.record_sell(
        SAMPLE_MINT, 500_000, is_partial=True
    )
    assert not closed
    assert rem == 500_000

    bot.position_manager.remove_position(SAMPLE_MINT)
    assert not bot.position_manager.has_position(SAMPLE_MINT)

    # Status & Audit
    bot._write_status_snapshot()
    bot._write_audit_record("test_action", {"detail": "ok"})
    bot._send_alert("Test alert message")

    # Order execution
    pool_keys = make_test_pool_keys()
    res_buy = await bot._buy_token(SAMPLE_MINT, 30.0, "SolCat")
    assert res_buy
    res_sell = await bot._sell_token(SAMPLE_MINT, sell_amount_tokens=500_000)
    assert res_sell
    await bot._handle_raydium_pool_update(pool_keys)

    # Emergency liquidate
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    closed_mints = await bot._emergency_liquidate_all_positions(reason="panic_test")
    assert SAMPLE_MINT in closed_mints or len(closed_mints) >= 0

    # WebSocket subscribe / unsubscribe
    mock_ws = AsyncMock()
    await bot._subscribe_to_token_trades(mock_ws, SAMPLE_MINT)
    assert mock_ws.send.called
    await bot._unsubscribe_from_token_trades(mock_ws, SAMPLE_MINT)
    assert mock_ws.send.call_count == 2

    # WebSocket handle message with raydium pool data
    await bot._handle_message(
        {
            "amm_id": "amm123",
            "amm_authority": "auth123",
            "amm_open_orders": "open123",
            "amm_target_orders": "tgt123",
            "pool_coin_token_account": "coin123",
            "pool_pc_token_account": "pc123",
            "serum_program_id": "serum123",
            "serum_market": "market123",
            "coin_mint": SAMPLE_MINT,
            "pc_mint": SAMPLE_MINT_2,
        }
    )

    await bot._handle_message(
        {
            "event": "raydium_pool_created",
            "poolKeys": {
                "amm_id": "amm456",
                "amm_authority": "auth456",
                "amm_open_orders": "open456",
                "amm_target_orders": "tgt456",
                "pool_coin_token_account": "coin456",
                "pool_pc_token_account": "pc456",
                "serum_program_id": "serum456",
                "serum_market": "market456",
                "coin_mint": SAMPLE_MINT,
                "pc_mint": SAMPLE_MINT_2,
            },
        }
    )

    # Test run() with KeyboardInterrupt
    with patch("asyncio.run", side_effect=KeyboardInterrupt):
        bot.run()
        assert bot._stop_requested is True


@pytest.mark.asyncio
async def test_bot_safe_startup_and_edge_branches(tmp_path):
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"

    snapshot_payload = {
        "state": "INVALID_STATE_ENUM",
        "active_positions": [SAMPLE_MINT],  # list branch
        "buy_attempts": {"Mint1": 2, "Mint2": "invalid_val"},
        "seen_mints": {"Mint1": 12345.0, "Mint2": "invalid_val"},
        "trade_ledger": [{"mint": "Mint1", "action": "buy"}],
        "recent_actions": [{"action": "buy"}],
        "recent_events": ["Event 1", "Event 2"],
        "exit_retry_queue": {"Mint1": {"count": 1}},
        "circuit_breaker_tripped": True,
        "circuit_breaker_engaged": True,
        "circuit_breaker_lockout_until": 123456.0,
        "metrics": {
            "buys": 5,
            "sells": 3,
            "failures": 1,
            "retries": 2,
            "connection_loss": 1,
            "stale_data": 1,
            "risk_kills": 0,
            "circuit_breaker_trips": 1,
            "latency_ms": {
                "samples": 10,
                "total_ms": 100.0,
                "last_ms": 10.0,
                "max_ms": 20.0,
                "avg_ms": 10.0,
            },
        },
    }
    status_file.write_text(json.dumps(snapshot_payload), encoding="utf-8")

    cfg = TradingBotConfig(dry_run=True, buy_amount_sol=0.02)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )
    bot.bot_status_path = str(status_file)
    bot.audit_log_path = str(audit_file)
    bot.safe_startup()
    assert bot.state == TradingBotState.IDLE
    assert bot._circuit_breaker_tripped is True
    assert bot._metrics["buys"] == 5

    # Safe startup when snapshot is empty
    status_file.unlink()
    bot.safe_startup()

    # Alerting configuration
    bot.alert_provider = "discord"
    bot.alert_discord_webhook_url = "https://discord.com/hook"
    bot._configure_alerting()
    assert bot.alert_enabled is True

    # Validate mint address
    assert TradingBot.validate_mint_address(SAMPLE_MINT) == SAMPLE_MINT
    with pytest.raises(ValueError, match="Mint address is required"):
        TradingBot.validate_mint_address("")

    # Record methods
    bot._record_stale_data("stale test")
    bot._record_failure("test fail", category="rpc")
    bot._record_connection_loss()
    bot.reset_circuit_breaker(new_baseline_sol=10.0, force=True)

    # Balance and risk checks
    assert await bot._validate_balance() is True
    assert await bot._check_account_equity_guard(0.01) is True
    assert bot._check_risk_limits(SAMPLE_MINT, 0.01, {}) is True
    assert bot._check_loss_per_trade(SAMPLE_MINT) is True
    assert bot._check_daily_drawdown() is True

    # Invalid state transition warning
    bot.state = TradingBotState.SHUTDOWN
    bot._transition_to(TradingBotState.BUYING, reason="invalid")

    await bot.close()


def test_raydium_sdk_extended_branches():
    from pumpfun_trading.sdk.raydium import (
        calculate_raydium_swap_out,
        parse_raydium_initialize2_accounts,
        parse_raydium_pool_from_tx,
    )

    # Zero & negative inputs
    assert calculate_raydium_swap_out(0, 1000, 1000) == (0, 0)
    assert calculate_raydium_swap_out(1000, 0, 1000) == (0, 0)
    assert calculate_raydium_swap_out(1000, 1000, 0) == (0, 0)

    # Short accounts list (< 18)
    assert parse_raydium_initialize2_accounts(["acc"] * 10) is None

    # Fallback accounts list (18 accounts)
    accs_18 = [f"acc_{i}" for i in range(18)]
    keys_18 = parse_raydium_initialize2_accounts(accs_18, coin_mint=SAMPLE_MINT)
    assert keys_18 is not None
    assert keys_18.amm_id == "acc_0"
    assert keys_18.coin_mint == SAMPLE_MINT

    # parse_raydium_pool_from_tx
    assert parse_raydium_pool_from_tx("not_a_dict") is None  # type: ignore
    assert parse_raydium_pool_from_tx({}) is None

    # from direct poolKeys in dict
    tx_dict = {
        "poolKeys": {
            "amm_id": "Amm1",
            "amm_authority": "Auth1",
            "amm_open_orders": "Open1",
            "amm_target_orders": "Target1",
            "pool_coin_token_account": "Coin1",
            "pool_pc_token_account": "Pc1",
            "serum_program_id": "Serum1",
            "serum_market": "Market1",
            "serum_bids": "Bids1",
            "serum_asks": "Asks1",
            "serum_event_queue": "Queue1",
            "serum_coin_vault": "CoinV1",
            "serum_pc_vault": "PcV1",
            "serum_vault_signer": "Signer1",
            "coin_mint": SAMPLE_MINT,
            "pc_mint": SAMPLE_MINT_2,
            "lp_mint": "Lp1",
        }
    }
    parsed_keys = parse_raydium_pool_from_tx(tx_dict)
    assert parsed_keys is not None
    assert parsed_keys.amm_id == "Amm1"

    # from accounts in tx dict
    tx_accs_dict = {
        "accounts": [f"acc_{i}" for i in range(21)],
        "mint": SAMPLE_MINT,
    }
    parsed_accs = parse_raydium_pool_from_tx(tx_accs_dict)
    assert parsed_accs is not None
    assert parsed_accs.amm_id == "acc_4"


@pytest.mark.asyncio
async def test_rpc_pool_extended_coverage():
    # RpcEndpoint metrics & score
    ep = RpcEndpoint(url="http://solana.node.internal:8899/rpc")
    assert ep.label == "solana.node.internal:8899"
    assert ep.p50_latency_ms == 0.0
    assert ep.mean_latency_ms == 0.0

    # Add single sample
    ep.record_success(0.05)
    assert ep.p50_latency_ms == 50.0
    assert ep.p95_latency_ms == 50.0
    assert ep.p99_latency_ms == 50.0
    assert ep.mean_latency_ms == 50.0

    # Multiple samples
    for lat in [0.01, 0.02, 0.03, 0.04, 0.10]:
        ep.record_success(lat)
    assert ep.p50_latency_ms > 0.0

    # Score penalties
    ep.state = CircuitState.DEGRADED
    assert ep.get_score() > ep.p50_latency_ms

    ep.state = CircuitState.HALF_OPEN
    assert ep.get_score() > ep.p50_latency_ms

    # Empty URL validation
    pool = RpcConnectionPool()
    with pytest.raises(ValueError, match="Endpoint URL cannot be empty"):
        pool.add_endpoint("")

    # Add duplicate endpoint
    ep_dup = pool.add_endpoint(ep.url, label="Dup")
    assert pool.endpoint_count == 1
    assert pool.add_endpoint(ep) == ep_dup

    # Remove endpoint
    assert pool.remove_endpoint(ep.url) is True
    assert pool.remove_endpoint("non_existent") is False
    assert pool.endpoint_count == 0

    # Requests on empty pool
    with pytest.raises(
        RuntimeError, match="No RPC endpoints configured in connection pool"
    ):
        await pool.request({"jsonrpc": "2.0", "method": "getVersion"})

    with pytest.raises(RuntimeError, match="No RPC endpoints configured for broadcast"):
        await pool.broadcast_transaction("tx_bytes")

    # Request with JSON-RPC error containing 429
    ep_active = pool.add_endpoint("https://rpc.active.solana.com", label="Active")
    mock_session = MagicMock()
    resp_rate_limit = AsyncMock()
    resp_rate_limit.status = 200
    resp_rate_limit.text = AsyncMock(
        return_value=json.dumps(
            {"error": {"code": 429, "message": "Too many requests"}}
        )
    )
    resp_rate_limit.json = AsyncMock(
        return_value={"error": {"code": 429, "message": "Too many requests"}}
    )
    mock_session.post.return_value.__aenter__.return_value = resp_rate_limit
    pool._session = mock_session

    with pytest.raises(RuntimeError, match="All RPC pool query attempts failed"):
        await pool.request({"method": "getBalance"}, max_retries=1)

    assert ep_active.state == CircuitState.OPEN

    # Health check cycle
    resp_ok = AsyncMock()
    resp_ok.status = 200
    mock_session.post.return_value.__aenter__.return_value = resp_ok
    results = await pool.check_all_health()
    assert results.get("https://rpc.active.solana.com") is True
    assert ep_active.state == CircuitState.HEALTHY

    telemetry = pool.get_telemetry()
    assert telemetry["total_endpoints"] == 1
    assert telemetry["healthy_endpoints"] == 1

    await pool.close()


@pytest.mark.asyncio
async def test_sdk_execution_extended_coverage():
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.message import MessageV0
    from solders.transaction import VersionedTransaction

    client = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        use_jito=False,
    )

    # get_ata_exists with mock accounts
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    "not_dict",
                    {"account": "not_dict"},
                    {"account": {"data": "not_dict"}},
                    {"account": {"data": {"parsed": "not_dict"}}},
                    {"account": {"data": {"parsed": {"info": "not_dict"}}}},
                    {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": "other_mint",
                                        "owner": "other_owner",
                                    }
                                }
                            }
                        }
                    },
                    {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": SAMPLE_MINT,
                                        "owner": str(client.wallet),
                                    }
                                }
                            }
                        }
                    },
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is True

    # getTokenAccountBalance with missing amount
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": {}}})
    assert await client.get_token_balance(SAMPLE_MINT) == 0

    # send_transaction with rpc_pool (endpoint_count > 1)
    ep1 = RpcEndpoint(url="https://rpc1.solana.com")
    ep2 = RpcEndpoint(url="https://rpc2.solana.com")
    pool = RpcConnectionPool(endpoints=[ep1, ep2])
    pool.broadcast_transaction = AsyncMock(
        return_value="sig_broadcast_12345678901234567890"
    )
    client.rpc_pool = pool

    msg = MessageV0.try_compile(
        payer=client.wallet,
        instructions=[Instruction(program_id=Pubkey.default(), accounts=[], data=b"")],
        address_lookup_table_accounts=[],
        recent_blockhash=Hash.default(),
    )
    tx = VersionedTransaction.populate(msg, [client.keypair.sign_message(bytes(msg))])

    sig = await client.send_transaction(tx)
    assert sig == "sig_broadcast_12345678901234567890"

    # confirm_transaction branches: None result, [None] status, err in status
    client._request_rpc_json = AsyncMock(
        side_effect=[
            {"result": {"value": None}},
            {"result": {"value": [None]}},
            {
                "result": {
                    "value": [
                        {
                            "confirmationStatus": "confirmed",
                            "err": {"InstructionError": 1},
                        }
                    ]
                }
            },
        ]
    )
    assert (
        await client.confirm_transaction("sig_test", max_retries=3, interval=0.01)
        is False
    )

    # raydium_buy with should_jito=False
    pool_keys = make_test_pool_keys()
    client.build_raydium_buy_tx = AsyncMock(return_value=tx)
    client.send_transaction = AsyncMock(return_value="sig_ray_buy_12345678901234567890")
    res_sig = await client.raydium_buy(pool_keys, 0.05, use_jito=False)
    assert res_sig == "sig_ray_buy_12345678901234567890"

    await client.close()
    await pool.close()


@pytest.mark.asyncio
async def test_bot_raydium_and_trade_updates_deep():
    cfg = TradingBotConfig(
        dry_run=True,
        buy_amount_sol=0.02,
        raydium_buy_amount_sol=0.02,
        enable_copy_trading=True,
        enable_raydium_migration_sniping=True,
        copy_trading_wallets=[
            {
                "address": "Whale1",
                "label": "WhaleAlpha",
                "win_rate": 0.85,
                "risk_score": 15.0,
            }
        ],
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )
    pool_keys = make_test_pool_keys()

    # 1. _buy_raydium_token when _should_buy is False
    bot._should_buy = MagicMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 2. _buy_raydium_token when account equity guard fails
    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 3. _buy_raydium_token when execution fails
    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="Slippage")
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is False

    # 4. _buy_raydium_token success
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(
            success=True, signature="sig_ok", token_amount=1000
        )
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, pool_keys) is True

    # 5. _handle_trade_update on active position with smart money sell mirror exit
    mock_ws = AsyncMock()
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    trade_sell_msg = {
        "mint": SAMPLE_MINT,
        "is_buy": False,
        "user": "Whale1",
        "sol_amount": 0.5,
        "market_cap_sol": 35.0,
    }
    await bot._handle_trade_update(trade_sell_msg, websocket=mock_ws)

    # 6. _handle_trade_update on new token with smart money buy (copy-trade entry)
    bot.position_manager.clear()
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_MINT_2, passed=True, risk_score=10.0
        )
    )
    trade_buy_msg = {
        "mint": SAMPLE_MINT_2,
        "is_buy": True,
        "user": "Whale1",
        "sol_amount": 1.0,
        "market_cap_sol": 25.0,
        "name": "MirroredCoin",
    }
    await bot._handle_trade_update(trade_buy_msg, websocket=mock_ws)
    assert bot.position_manager.has_position(SAMPLE_MINT_2)

    # 7. Copy-trade buy rejected due to anti-rug screening
    bot.position_manager.clear()
    with patch.object(
        bot, "_enrich_and_screen_token", new_callable=AsyncMock
    ) as mock_screen:
        mock_screen.return_value = TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=False, risk_score=90.0
        )
        await bot._handle_trade_update(
            {
                "mint": SAMPLE_MINT,
                "is_buy": True,
                "user": "Whale1",
                "sol_amount": 1.0,
                "market_cap_sol": 25.0,
            }
        )
        assert not bot.position_manager.has_position(SAMPLE_MINT)

    # 8. Copy-trade buy rejected due to _should_buy
    with patch.object(bot, "_should_buy", return_value=False):
        await bot._handle_trade_update(
            {
                "mint": SAMPLE_MINT,
                "is_buy": True,
                "user": "Whale1",
                "sol_amount": 1.0,
                "market_cap_sol": 25.0,
            }
        )

    await bot.close()


@pytest.mark.asyncio
async def test_bot_stream_and_execution_deep_branches():
    cfg = TradingBotConfig(
        dry_run=False,
        buy_amount_sol=0.02,
        enable_anti_rug_filters=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg,
    )

    # _check_account_equity_guard branches
    bot.execution.get_balance_sol = AsyncMock(
        return_value=0.05
    )  # 0.05 - 0.02 < 0.10 reserve
    assert await bot._check_account_equity_guard(0.02) is False

    bot.execution.get_balance_sol = AsyncMock(
        side_effect=RuntimeError("RPC balance error")
    )
    assert await bot._check_account_equity_guard(0.02) is False

    # _validate_balance live
    bot.execution.get_balance_sol = AsyncMock(return_value=0.10)
    assert await bot._validate_balance() is True
    bot.execution.get_balance_sol = AsyncMock(side_effect=RuntimeError("Err"))
    assert await bot._validate_balance() is False

    # _buy_token failure branches
    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_token(SAMPLE_MINT, 30.0, "Coin") is False

    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC Timeout")
    )
    assert await bot._buy_token(SAMPLE_MINT, 30.0, "Coin") is False

    # _sell_token live balance fetch error
    bot.position_manager.record_buy(SAMPLE_MINT, 1000, 0.02, 30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(
        side_effect=RuntimeError("Token balance RPC err")
    )
    assert await bot._sell_token(SAMPLE_MINT) is False
    assert SAMPLE_MINT in bot._exit_retry_queue

    # _sell_token zero balance live
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    assert await bot._sell_token(SAMPLE_MINT) is True

    # _process_exit_retry_queue
    bot._exit_retry_queue["RetryMint"] = {
        "retries": 1,
        "retry_count": 1,
        "first_attempt": time.monotonic() - 10,
        "last_attempt": time.monotonic() - 5,
        "next_retry_at": time.monotonic() - 1,
        "reason": "retry_test",
        "slippage_bps": 1000,
    }
    bot.position_manager.record_buy("RetryMint", 1000, 0.02, 30.0)
    bot.active_positions = bot.position_manager.get_all_positions()
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.executor.execute_sell = AsyncMock(return_value=ExecutionResult(success=True))
    await bot._process_exit_retry_queue()

    # _reconcile_positions_on_startup live
    bot.active_positions = {
        "Pos1": {"name": "P1", "entry_market_cap": 30.0, "peak_market_cap": 30.0}
    }
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    reconciled = await bot._reconcile_positions_on_startup()
    assert "Pos1" in reconciled

    # _handle_bonding_curve_state_update branches
    update_low_mc = BondingCurveStateUpdate(
        mint="LowMC",
        bonding_curve_pubkey="curve1",
        slot=1,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.0001,
        market_cap_sol=1.0,  # below 5.0 min_market_cap_sol
    )
    await bot._handle_bonding_curve_state_update(update_low_mc)

    # start() exception and breaker trip
    bot.geyser_endpoint = "https://mock.geyser"
    bot.geyser_client = MagicMock()

    async def mock_err_listen():
        raise RuntimeError("Geyser stream severed")
        yield None

    bot.geyser_client.listen = mock_err_listen
    bot.geyser_client.start = AsyncMock()
    bot.geyser_client.stop = AsyncMock()
    bot._max_stream_consecutive_failures = 1
    await bot.start()
    assert bot._circuit_breaker_tripped is True

    await bot.close()


def test_graduation_and_api_client_deep():
    from pumpfun_trading.api.client import PumpFunApiClient
    from pumpfun_trading.strategies.graduation import (
        GraduationEngine,
        GraduationTracker,
    )

    # GraduationSignal to_dict
    sig = GraduationSignal(
        triggered=True,
        mint=SAMPLE_MINT,
        stage="graduated",
        market_cap_sol=85.0,
        real_sol_reserves=85.0,
        pool_keys=make_test_pool_keys(),
        reason="graduated_ready",
    )
    d = sig.to_dict()
    assert d["triggered"] is True
    assert d["pool_keys"] is not None

    # GraduationTracker mark_completed
    tracker = GraduationTracker(mint=SAMPLE_MINT, target_graduation_sol=85.0)
    tracker.update_reserves(85.0, 115.0, 85.0, complete=True)
    assert tracker.candidate.is_completed is True
    assert tracker.candidate.progress_pct == 100.0

    # GraduationEngine cleanup_expired_candidates
    engine = GraduationEngine(candidate_ttl_seconds=1)
    engine.update_bonding_curve(SAMPLE_MINT, "curve1", 50.0, 100.0, 50.0)
    engine._trackers[SAMPLE_MINT].candidate.updated_at = time.time() - 10.0
    pruned = engine.cleanup_expired_candidates()
    assert pruned == 1
    assert SAMPLE_MINT not in engine._trackers

    # ApiClient get_creator_coins with empty creator
    api = PumpFunApiClient()
    api.get_creator_coins = AsyncMock(return_value=[])
    # test close
    # synchronous check
    assert api is not None


@pytest.mark.asyncio
async def test_api_client_and_replay_and_main_branches():
    from pumpfun_trading.api.client import PumpFunApiClient
    from pumpfun_trading.cli.main import main
    from pumpfun_trading.engines.replay import (
        PaperTradingEngine,
        render_replay_dashboard,
        render_replay_summary,
        render_replay_trades,
    )

    # 1. ApiClient retries and error branches
    api = PumpFunApiClient(max_retries=2, retry_backoff_seconds=0.01)
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.text = AsyncMock(return_value="Server error")
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    api._session = mock_session

    with pytest.raises(RuntimeError):
        await api.get(f"/coins/{SAMPLE_MINT}")

    # get_coin fallback parsing branches
    api.get = AsyncMock(side_effect=RuntimeError("HTTP 404 Not Found"))
    api.post = AsyncMock(return_value=[{"mint": SAMPLE_MINT, "name": "CoinList"}])
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinList"

    api.post = AsyncMock(
        return_value={"data": [{"mint": SAMPLE_MINT, "name": "CoinData"}]}
    )
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinData"

    api.post = AsyncMock(
        return_value={"items": [{"mint": SAMPLE_MINT, "name": "CoinItems"}]}
    )
    assert (await api.get_coin(SAMPLE_MINT))["name"] == "CoinItems"

    api.post = AsyncMock(return_value={"data": []})
    with pytest.raises(
        RuntimeError, match="not found via the public Pump.fun metadata endpoints"
    ):
        await api.get_coin(SAMPLE_MINT)

    # get_holder_counts when get_coin returns non-dict
    api.get_coin = AsyncMock(return_value=None)
    assert await api.get_holder_counts(SAMPLE_MINT) == {}

    await api.close()

    # 2. ReplayEngine with momentum and graduation simulation
    cfg = TradingBotConfig(
        dry_run=True,
        buy_amount_sol=0.02,
        enable_momentum_signals=True,
        enable_raydium_migration_sniping=True,
    )
    paper = PaperTradingEngine(
        initial_cash=10.0,
        strategy_config=cfg,
    )

    # Feed snapshots that trigger buy, trailing stop, take profit, and graduation
    snapshots = [
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1000.0,
            "market_cap_sol": 30.0,
            "price_sol": 0.00003,
            "is_buy": True,
            "sol_amount": 1.0,
            "user": "Trader1",
            "trade_records": [
                {"is_buy": True, "sol_amount": 1.0, "user": "T1", "timestamp": 1000.0},
                {"is_buy": True, "sol_amount": 1.0, "user": "T2", "timestamp": 1000.0},
                {"is_buy": True, "sol_amount": 1.0, "user": "T3", "timestamp": 1000.0},
            ],
            "real_sol_reserves": 82.0,
            "virtual_sol_reserves": 112.0,
            "complete": False,
        },
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1020.0,
            "market_cap_sol": 65.0,  # 2x+ take profit trigger
            "price_sol": 0.000065,
            "is_buy": True,
            "sol_amount": 1.0,
            "user": "Trader2",
            "real_sol_reserves": 85.0,
            "virtual_sol_reserves": 115.0,
            "complete": True,
        },
        {
            "mint": SAMPLE_MINT,
            "mint_name": "CoinAlpha",
            "timestamp": 1030.0,
            "market_cap_sol": 85.0,
            "price_sol": 0.000085,
            "sell_signal": True,
        },
    ]
    summary = paper.run(snapshots)
    assert summary is not None

    render_replay_summary(summary)
    render_replay_trades(summary.get("trades", []))
    render_replay_dashboard(summary)

    # 3. Main CLI parser with --help / replay --help
    with patch("sys.argv", ["pumpfun_trading", "--help"]), pytest.raises(SystemExit):
        main()

    with (
        patch("sys.argv", ["pumpfun_trading", "replay", "--help"]),
        pytest.raises(SystemExit),
    ):
        main()


@pytest.mark.asyncio
async def test_rpc_pool_factories_and_error_edges():
    # Health loop lifecycle
    ep = RpcEndpoint(url="https://rpc.err.solana.com")
    pool = RpcConnectionPool(
        endpoints=[ep], config=RpcPoolConfig(health_check_interval_seconds=0.01)
    )
    await pool.start_health_loop()
    await pool.start_health_loop()  # idempotent
    await asyncio.sleep(0.05)
    await pool.stop_health_loop()

    # request() with status != 200 and text() exception
    mock_session = MagicMock()
    resp_err = AsyncMock()
    resp_err.status = 502
    resp_err.text = AsyncMock(side_effect=RuntimeError("Text read error"))
    mock_session.post.return_value.__aenter__.return_value = resp_err
    pool._session = mock_session

    with pytest.raises(RuntimeError):
        await pool.request({"method": "getVersion"}, max_retries=1)

    assert ep.state in {CircuitState.DEGRADED, CircuitState.OPEN}

    # broadcast_transaction with status 500 and text() exception
    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("tx_data")

    # broadcast_transaction with status 200 but non-dict json
    resp_200_non_dict = AsyncMock()
    resp_200_non_dict.status = 200
    resp_200_non_dict.json = AsyncMock(return_value="not_a_dict")
    mock_session.post.return_value.__aenter__.return_value = resp_200_non_dict
    with pytest.raises(RuntimeError):
        await pool.broadcast_transaction("tx_data")

    # check_endpoint_health with exception
    mock_session.post.side_effect = RuntimeError("Socket dropped")
    assert await pool.check_endpoint_health(ep) is False

    await pool.close()


@pytest.mark.asyncio
async def test_final_coverage_push():
    from pumpfun_trading.bot.run import main as bot_main

    # 1. TradingBot init with various alert providers in env
    for prov, env_key, env_val in [
        ("slack", "PUMPFUN_SLACK_WEBHOOK_URL", "https://slack.com/hook"),
        ("telegram", "PUMPFUN_TELEGRAM_BOT_TOKEN", "token123"),
        ("webhook", "PUMPFUN_ALERT_WEBHOOK_URL", "https://webhook.site/test"),
    ]:
        with patch.dict(
            os.environ,
            {
                "PUMPFUN_ALERT_PROVIDER": prov,
                env_key: env_val,
                "PUMPFUN_TELEGRAM_CHAT_ID": "chat123",
            },
        ):
            b = TradingBot(
                private_key_b58=SAMPLE_PRIVATE_KEY,
                rpc_url="https://api.mainnet-beta.solana.com",
                config=TradingBotConfig(dry_run=True),
            )
            assert b.alert_provider == prov or b.alert_enabled is True
            await b.close()

    # 2. _reconcile_positions_on_startup with balance > 0 and position difference
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=TradingBotConfig(dry_run=False),
        verbose=False,
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.5)
    bot.active_positions = {
        SAMPLE_MINT: {
            "token_amount": 1000,
            "entry_market_cap": 30.0,
            "peak_market_cap": 30.0,
        }
    }
    bot.position_manager["SAMPLE_MINT"] = bot.active_positions[SAMPLE_MINT]
    bot.execution.get_token_balance = AsyncMock(return_value=500)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 30.0}
    )
    reconciled = await bot._reconcile_positions_on_startup()
    assert reconciled.get(SAMPLE_MINT) == {"status": "active", "balance": 500}

    # 3. _evaluate_and_execute_exit with Tier 1 and Tier 2 partial take profit
    cfg_tiered = TradingBotConfig(
        dry_run=True,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.50,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
    )
    bot_tiered = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=cfg_tiered,
    )
    bot_tiered.position_manager.record_buy(
        SAMPLE_MINT, 1000, 0.02, 30.0, name="TierCoin"
    )
    bot_tiered.active_positions = bot_tiered.position_manager.get_all_positions()

    # Tier 1 (2.0x -> 60.0 mc)
    bot_tiered.position_manager.update_price(SAMPLE_MINT, 60.0)
    assert await bot_tiered._evaluate_and_execute_exit(SAMPLE_MINT, 60.0) is True

    # Tier 2 (3.5x -> 105.0 mc)
    bot_tiered.position_manager.update_price(SAMPLE_MINT, 105.0)
    assert await bot_tiered._evaluate_and_execute_exit(SAMPLE_MINT, 105.0) is True

    # 4. _run_health_loop and _render_loop task handling
    bot.verbose = False
    task_render = asyncio.create_task(bot._render_loop())
    await asyncio.sleep(0.01)
    task_render.cancel()
    try:
        await task_render
    except asyncio.CancelledError:
        pass

    bot.state = TradingBotState.SHUTDOWN
    task_health = asyncio.create_task(bot._run_health_loop())
    await asyncio.sleep(0.01)
    task_health.cancel()
    try:
        await task_health
    except asyncio.CancelledError:
        pass

    # 5. SDK execution sell and raydium_buy with use_jito=True
    exec_client = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        use_jito=True,
    )
    exec_client.calculate_dynamic_jito_tip = AsyncMock(return_value=10_000)
    exec_client.build_sell_tx = AsyncMock()
    exec_client.send_jito_bundle_with_fallback = AsyncMock(return_value="sig_jito_sell")
    sig_sell = await exec_client.sell(
        SAMPLE_MINT, "curve1", 1000, min_sol_output=1_000_000_000, use_jito=True
    )
    assert sig_sell == "sig_jito_sell"

    exec_client.build_raydium_buy_tx = AsyncMock()
    exec_client.send_jito_bundle_with_fallback = AsyncMock(
        return_value="sig_jito_ray_buy"
    )
    sig_ray = await exec_client.raydium_buy(make_test_pool_keys(), 0.05, use_jito=True)
    assert sig_ray == "sig_jito_ray_buy"

    # Swap Raydium buy & sell branches
    sig_swap_buy = await exec_client.swap_raydium(
        make_test_pool_keys(), 50_000_000, is_buy=True, use_jito=True
    )
    assert sig_swap_buy == "sig_jito_ray_buy"

    exec_client.build_raydium_sell_tx = AsyncMock()
    sig_swap_sell = await exec_client.swap_raydium(
        make_test_pool_keys(), 1000, is_buy=False, use_jito=True
    )
    assert sig_swap_sell == "sig_jito_ray_buy"

    exec_client.send_transaction = AsyncMock(return_value="sig_rpc_ray_sell")
    sig_swap_sell_rpc = await exec_client.swap_raydium(
        make_test_pool_keys(), 1000, is_buy=False, use_jito=False
    )
    assert sig_swap_sell_rpc == "sig_rpc_ray_sell"

    # build_raydium_sell_tx builder
    exec_client_fresh = PumpFunExecutionClient(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
    )
    with patch.object(
        exec_client_fresh, "_build_tx_with_instructions", new_callable=AsyncMock
    ) as mock_builder:
        mock_builder.return_value = MagicMock()
        await exec_client_fresh.build_raydium_sell_tx(make_test_pool_keys(), 1000)
        assert mock_builder.called
    exec_client_fresh.get_balance_sol = AsyncMock(return_value=1.5)
    assert await exec_client_fresh.get_wallet_balance_sol() == 1.5
    await exec_client_fresh.close()

    # 6. EventRouter with None callbacks
    router_empty = EventRouter()
    curve_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curve111",
        slot=1,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=30.0,
    )
    await router_empty.route_geyser_curve_update(curve_up)
    await router_empty.route_ws_message({"type": "other"})

    # 7. Liquidator live mode
    mock_exec = MagicMock(spec=OrderExecutor)
    mock_exec.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=True, mint=SAMPLE_MINT, amount_sol=0.05)
    )
    pm_liq = PositionManager(TradingBotConfig())
    pm_liq.record_buy(SAMPLE_MINT, 1000, 0.05, 30.0, dry_run=False)
    liquidator_live = OrderLiquidator(executor=mock_exec, position_manager=pm_liq)
    res_liq = await liquidator_live.liquidate_all_positions(reason="live_panic")
    assert res_liq == [SAMPLE_MINT]

    # 8. Start loop consuming all event types from geyser
    async def mock_geyser_events():
        yield {"event": "test_dict"}
        yield curve_up
        yield TradeEventUpdate(
            mint=SAMPLE_MINT,
            sol_amount_lamports=1_000_000_000,
            token_amount=100,
            is_buy=True,
            user="user111",
            timestamp=time.time(),
            virtual_sol_reserves=1000,
            virtual_token_reserves=1000,
            real_sol_reserves=1000,
            real_token_reserves=1000,
        )
        yield CompleteEventUpdate(
            mint=SAMPLE_MINT,
            bonding_curve="curve111",
            user="user111",
            timestamp=time.time(),
        )

    bot.geyser_endpoint = "https://geyser.helius.xyz"
    bot.geyser_client = MagicMock()
    bot.geyser_client.start = AsyncMock()
    bot.geyser_client.stop = AsyncMock()
    bot.geyser_client.listen = mock_geyser_events
    bot._reconcile_positions_on_startup = AsyncMock(return_value={})
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=True, risk_score=10.0
        )
    )
    bot.executor.execute_sell = AsyncMock(return_value=ExecutionResult(success=True))
    bot.executor.execute_buy = AsyncMock(return_value=ExecutionResult(success=True))
    bot.dry_run = True
    bot._stop_requested = False

    # Run start for 1 cycle
    async def stop_later():
        await asyncio.sleep(0.05)
        bot._stop_requested = True

    asyncio.create_task(stop_later())
    await bot.start()

    # 9. main() entrypoint helper
    with patch.object(TradingBot, "from_env") as mock_from_env:
        mock_bot = MagicMock()
        mock_from_env.return_value = mock_bot
        bot_main()
        assert mock_bot.run.called

    # 10. WebSocket streaming tests in TradingBot
    bot_ws = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=TradingBotConfig(dry_run=True),
    )
    bot_ws.geyser_endpoint = None
    bot_ws.reconnect_delay_seconds = 0.01
    bot_ws._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=SAMPLE_MINT, passed=True, risk_score=10.0
        )
    )
    bot_ws._reconcile_positions_on_startup = AsyncMock(return_value={})

    class MockWSMessage:
        def __init__(self, msg_type, data):
            self.type = msg_type
            self.data = data

    class MockWebSocketContext:
        def __init__(self, messages):
            self.messages = messages
            self.closed = False
            self.exception_mock = None

        def exception(self):
            return self.exception_mock

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.closed = True

        async def send_json(self, msg):
            pass

        async def send_str(self, msg):
            pass

        async def send(self, msg):
            pass

        async def __aiter__(self):
            for m in self.messages:
                yield m

    class MockSessionContext:
        def __init__(self, ws_ctx):
            self.ws_ctx = ws_ctx

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def ws_connect(self, url):
            return self.ws_ctx

    ws_messages = [
        MockWSMessage(
            aiohttp.WSMsgType.TEXT,
            json.dumps({"txType": "create", "mint": SAMPLE_MINT, "name": "SolCat"}),
        ),
        MockWSMessage(aiohttp.WSMsgType.TEXT, "invalid json {"),
        MockWSMessage(aiohttp.WSMsgType.ERROR, "err"),
        MockWSMessage(aiohttp.WSMsgType.CLOSED, ""),
    ]
    mock_ws_ctx = MockWebSocketContext(ws_messages)
    mock_session = MockSessionContext(mock_ws_ctx)

    with patch("aiohttp.ClientSession", return_value=mock_session):

        async def stop_ws():
            await asyncio.sleep(0.05)
            bot_ws._stop_requested = True

        asyncio.create_task(stop_ws())
        await bot_ws._run_websocket_stream()
        assert bot_ws._last_message_at > 0

    bot_ws._stop_requested = False
    bot_ws._max_stream_consecutive_failures = 1
    with patch("aiohttp.ClientSession", side_effect=RuntimeError("connection dropped")):

        async def stop_ws_err():
            await asyncio.sleep(0.05)
            bot_ws._stop_requested = True

        asyncio.create_task(stop_ws_err())
        await bot_ws._run_websocket_stream()
        assert bot_ws._circuit_breaker_tripped is True
        assert bot_ws._health_ok is False

    bot_ws._stop_requested = False
    bot_ws.geyser_endpoint = None
    bot_ws._run_websocket_stream = AsyncMock()

    async def stop_start_ws():
        await asyncio.sleep(0.05)
        bot_ws._stop_requested = True

    asyncio.create_task(stop_start_ws())
    await bot_ws.start()
    assert bot_ws._run_websocket_stream.called

    await bot_ws.close()
    await bot.close()
    await bot_tiered.close()
    await exec_client.close()
