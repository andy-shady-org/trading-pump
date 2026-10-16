from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.hash import Hash
from solders.pubkey import Pubkey

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.cli import bot as cli_bot
import pumpfun_trading.cli.main as cli_main_mod
from pumpfun_trading.sdk.execution import TOKEN_PROGRAM_ID_STR
from pumpfun_trading.sdk.execution import TokenBalanceUnavailableError
from pumpfun_trading.sdk.execution import PumpFunExecutionClient

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_MINT_2 = "So11111111111111111111111111111111111111112"


async def test_api_client_missing_branches():
    client = PumpFunApiClient(base_url="https://api.pump.fun")

    # get_coins_by_mints
    client.post = AsyncMock(return_value=[{"mint": SAMPLE_MINT}])
    coins_by_mints = await client.get_coins_by_mints([SAMPLE_MINT])
    assert coins_by_mints is not None

    # get_coin with fallback payload having 'data' or 'items'
    fallback_client = PumpFunApiClient()
    fallback_client.get = AsyncMock(side_effect=RuntimeError("HTTP 404"))
    fallback_client.post = AsyncMock(
        return_value={"data": [{"mint": SAMPLE_MINT, "name": "CoinData"}]}
    )
    coin_data = await fallback_client.get_coin(SAMPLE_MINT)
    assert coin_data["name"] == "CoinData"

    fallback_client.post = AsyncMock(
        return_value={"items": [{"mint": SAMPLE_MINT, "name": "CoinItems"}]}
    )
    coin_items = await fallback_client.get_coin(SAMPLE_MINT)
    assert coin_items["name"] == "CoinItems"

    # get_coin not found after post
    fallback_client.post = AsyncMock(return_value={"other": []})
    with pytest.raises(
        RuntimeError, match="not found via the public Pump.fun metadata"
    ):
        await fallback_client.get_coin(SAMPLE_MINT)

    # get_coin_info invalid type
    client.get_coin = AsyncMock(return_value="string_not_dict")
    with pytest.raises(ValueError):
        await client.get_coin_info(SAMPLE_MINT)

    await client.close()
    await fallback_client.close()


async def test_execution_sdk_all_branches():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
    )
    # The token-balance ATA fallback resolves the token program over the RPC
    # pool; stub it so the test never reaches mainnet.
    client.get_token_program_for_mint = AsyncMock(
        return_value=Pubkey.from_string(TOKEN_PROGRAM_ID_STR)
    )

    # _to_pubkey invalid
    with pytest.raises(ValueError):
        client._to_pubkey("invalid-pubkey")

    # get_balance_sol int and non-dict
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": 5000000000}})
    assert await client.get_balance_sol() == 5.0

    client._request_rpc_json = AsyncMock(return_value={"result": None})
    assert await client.get_balance_sol() == 0.0

    # get_token_balance
    client._request_rpc_json = AsyncMock(
        return_value={"result": {"value": {"amount": "50000000"}}}
    )
    assert await client.get_token_balance(SAMPLE_MINT) == 50000000

    # get_token_balance when no accounts found: unreadable balance raises instead of reading as 0 (BUG-35)
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    with pytest.raises(TokenBalanceUnavailableError):
        await client.get_token_balance(SAMPLE_MINT)

    # get_ata_exists
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
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
                    }
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is True

    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    assert await client.get_ata_exists(SAMPLE_MINT) is False

    # send_transaction
    tx_mock = MagicMock()
    tx_mock.__bytes__ = MagicMock(return_value=b"tx_bytes_12345678901234567890")
    client._request_rpc_json = AsyncMock(
        return_value={"result": "valid_signature_hash_1234567890"}
    )
    sig = await client.send_transaction(tx_mock)
    assert sig == "valid_signature_hash_1234567890"

    # send_transaction invalid result
    client._request_rpc_json = AsyncMock(return_value={"result": "short"})
    with pytest.raises(RuntimeError):
        await client.send_transaction(tx_mock)

    # confirm_transaction with status error and HTTP non-200
    mock_resp_err = AsyncMock()
    mock_resp_err.status = 500
    mock_resp_err.__aenter__.return_value = mock_resp_err
    mock_resp_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp_err):
        assert (
            await client.confirm_transaction("sig_test", max_retries=1, interval=0.01)
            is False
        )

    # confirm_transaction on-chain transaction failed error
    mock_resp_tx_err = AsyncMock()
    mock_resp_tx_err.status = 200
    mock_resp_tx_err.json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    {
                        "confirmationStatus": "confirmed",
                        "err": {"InstructionError": [0, "Custom"]},
                    }
                ]
            }
        }
    )
    mock_resp_tx_err.__aenter__.return_value = mock_resp_tx_err
    mock_resp_tx_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_resp_tx_err):
        assert (
            await client.confirm_transaction("sig_test", max_retries=1, interval=0.01)
            is False
        )

    # buy and sell wrappers
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))
    client.get_ata_exists = AsyncMock(return_value=True)
    client.send_transaction = AsyncMock(return_value="tx_sig_wrapped_123")
    client._fetch_trade_curve_state = AsyncMock(
        return_value={"creator": str(Pubkey.new_unique()), "is_mayhem_mode": False}
    )

    buy_res = await client.buy(
        SAMPLE_MINT, pda, 0.05, token_amount=1000000, slippage_bps=200
    )
    assert buy_res == "tx_sig_wrapped_123"

    sell_res = await client.sell(SAMPLE_MINT, pda, 1000000, min_sol_output=1000)
    assert sell_res == "tx_sig_wrapped_123"


async def test_bot_run_all_missing_branches(tmp_path):
    config = TradingBotConfig(
        buy_amount_sol=0.05,
        min_market_cap_sol=10.0,
        max_active_positions=2,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=True,
        bot_status_path=str(tmp_path / "status.json"),
    )

    # validate_mint_address errors
    with pytest.raises(ValueError, match="Mint address is required"):
        TradingBot.validate_mint_address("")
    with pytest.raises(ValueError, match="32 bytes"):
        TradingBot.validate_mint_address("short")

    # from_env missing variables
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="Missing PUMPFUN_PRIVATE_KEY"):
            TradingBot.from_env()

        with patch.dict("os.environ", {"PUMPFUN_PRIVATE_KEY": SAMPLE_PRIVATE_KEY}):
            with pytest.raises(ValueError, match="Missing PUMPFUN_RPC_URL"):
                TradingBot.from_env()

    # safe_startup corrupt files and edge schemas
    bad_status = tmp_path / "bad_status.json"
    bad_status.write_text("corrupt json", encoding="utf-8")
    bot.bot_status_path = str(bad_status)
    bot.safe_startup()

    bad_schema = tmp_path / "bad_schema.json"
    bad_schema.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    bot.bot_status_path = str(bad_schema)
    bot.safe_startup()

    partial_schema = tmp_path / "partial.json"
    partial_schema.write_text(
        json.dumps(
            {
                "active_positions": [SAMPLE_MINT],  # list instead of dict
                "buy_attempts": {"a": "not_int"},
                "seen_mints": {"a": "not_float"},
                "recent_actions": ["not_dict"],
                "recent_events": [123],
                "trade_ledger": ["not_dict"],
            }
        ),
        encoding="utf-8",
    )
    bot.bot_status_path = str(partial_schema)
    bot.safe_startup()

    # _record_trade with > 50 entries
    for i in range(55):
        bot._record_trade(mint=SAMPLE_MINT, action="buy", entry=0.01)
    assert len(bot._trade_ledger) <= 50

    # _record_event with alerting enabled
    bot.alert_enabled = True
    bot._send_alert = MagicMock()
    bot._record_event("Alert event")
    assert bot._send_alert.called

    # _record_stale_data and _record_failure
    bot._record_stale_data("delayed ping")
    bot._record_failure(category="network")
    bot._record_connection_loss()

    # _next_position_id, _check_daily_drawdown, _check_loss_per_trade
    assert bot._next_position_id().startswith("trade-")
    assert bot._check_daily_drawdown() is True
    assert bot._check_loss_per_trade(mint=SAMPLE_MINT) is True

    # _validate_balance and _check_account_equity_guard in non-dry-run mode
    bot.dry_run = False
    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)  # below min balance
    assert await bot._validate_balance() is False
    assert await bot._check_account_equity_guard(required_sol=1.0) is False

    # _buy_token when equity guard blocks or balance blocks
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot.dry_run = True

    # _should_buy branches
    bot._buy_attempts[SAMPLE_MINT] = 5
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot._buy_attempts[SAMPLE_MINT] = 0
    assert (
        bot._should_buy(SAMPLE_MINT, market_cap_sol=5.0) is False
    )  # below min_market_cap

    bot._seen_mints[SAMPLE_MINT] = time.monotonic()
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot._seen_mints.clear()

    bot.active_positions[SAMPLE_MINT] = {"name": "Active"}
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot.active_positions.clear()

    bot.active_positions = {"P1": {}, "P2": {}}
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot.active_positions.clear()

    bot._health_ok = False
    assert bot._should_buy(SAMPLE_MINT, market_cap_sol=20.0) is False
    bot._health_ok = True

    # new token message creates position
    bot.state = TradingBotState.MONITORING
    bot.wallet_balance_sol = 10.0
    bot.daily_equity_tracker.reset_circuit_breaker()
    msg_new = {
        "txType": "create",
        "mint": SAMPLE_MINT,
        "name": "FreshCoin",
        "marketCapSol": 25.0,
        "traderPublicKey": "DevWa11et1111111111111111111111111111111111",
    }
    await bot._handle_message(msg_new, AsyncMock())
    assert SAMPLE_MINT in bot.active_positions

    # trade message with stop loss exit
    await bot._handle_message(
        {"mint": SAMPLE_MINT, "marketCapSol": 2.0},
        AsyncMock(),  # 2/25 = 0.08 <= 0.85
    )
    assert SAMPLE_MINT not in bot.active_positions

    # trade message with update only
    bot.active_positions[SAMPLE_MINT_2] = {
        "name": "TokenUp",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
    }
    await bot._handle_message(
        {"mint": SAMPLE_MINT_2, "marketCapSol": 32.0}, AsyncMock()
    )
    assert bot.active_positions[SAMPLE_MINT_2]["current_market_cap"] == 32.0

    # Unsubscribe
    mock_ws = AsyncMock()
    await bot._unsubscribe_from_token_trades(mock_ws, SAMPLE_MINT)

    # Metrics snapshots and latencies
    bot._record_latency_ms(time.perf_counter() - 0.1)
    metrics = bot._metrics_snapshot()
    assert "latency_ms" in metrics

    # _register_signal_handlers and request_shutdown
    bot._register_signal_handlers()
    bot.request_shutdown()
    assert bot._stop_requested is True

    await bot.close()


async def test_bot_start_circuit_breaker_and_loop():
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=TradingBotConfig(),
        dry_run=True,
    )
    bot._max_stream_consecutive_failures = 1

    call_count = 0

    async def failing_listen():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated stream failure")
        bot.request_shutdown()
        if False:
            yield {}

    bot.geyser_client.listen = failing_listen

    with patch("asyncio.sleep", return_value=None):
        try:
            await bot.start()
        except (asyncio.CancelledError, Exception):
            pass

    assert bot._circuit_breaker_tripped is True
    await bot.close()


def test_cli_runners_execution():
    mock_client = MagicMock()
    mock_client.get_latest_coins = AsyncMock(return_value=[{"name": "Coin1"}])
    mock_client.get_coin = AsyncMock(
        return_value={"name": "Coin1", "mint": SAMPLE_MINT}
    )
    mock_client.close = AsyncMock()

    # 1. main mode == latest-coins
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("sys.argv", ["pumpfun", "--mode", "latest-coins"]):
            cli_main_mod.main()

    # 2. main mode == market-info
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch(
            "sys.argv", ["pumpfun", "--mode", "market-info", "--mint", SAMPLE_MINT]
        ):
            cli_main_mod.main()

    # 3. cli_bot main
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    with patch("pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot):
        with patch("sys.argv", ["pumpfun-bot", "--dry-run"]):
            cli_bot.main()


async def test_bot_ws_and_sub_unsub_and_idle_coverage(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=TradingBotConfig(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # 1. Idle branch in start()
    async def stop_soon():
        await asyncio.sleep(0.02)
        bot.request_shutdown()

    asyncio.create_task(stop_soon())
    await bot.start()
    assert bot.state == TradingBotState.SHUTDOWN

    # 2. _subscribe_to_token_trades & _unsubscribe_from_token_trades variants
    class SendJsonWS:
        def __init__(self):
            self.json_calls = []

        async def send_json(self, msg):
            self.json_calls.append(msg)

    class SendStrWS:
        def __init__(self):
            self.str_calls = []

        async def send_str(self, msg):
            self.str_calls.append(msg)

    class SendWS:
        def __init__(self):
            self.send_calls = []

        async def send(self, msg):
            self.send_calls.append(msg)

    class FailingWS:
        async def send_json(self, msg):
            raise RuntimeError("ws error")

    ws_json = SendJsonWS()
    await bot._subscribe_to_token_trades(ws_json, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_json, SAMPLE_MINT)
    assert len(ws_json.json_calls) == 2

    ws_str = SendStrWS()
    await bot._subscribe_to_token_trades(ws_str, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_str, SAMPLE_MINT)
    assert len(ws_str.str_calls) == 2

    ws_send = SendWS()
    await bot._subscribe_to_token_trades(ws_send, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_send, SAMPLE_MINT)
    assert len(ws_send.send_calls) == 2

    ws_fail = FailingWS()
    await bot._subscribe_to_token_trades(ws_fail, SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(ws_fail, SAMPLE_MINT)

    # 3. Active WS fallback
    bot._active_ws = ws_json
    await bot._subscribe_to_token_trades(mint=SAMPLE_MINT)
    await bot._unsubscribe_from_token_trades(mint=SAMPLE_MINT)
    bot._active_ws = None

    # Empty mint / None ws
    await bot._subscribe_to_token_trades(None, "")
    await bot._unsubscribe_from_token_trades(None, "")

    # 4. Raydium message parsing in _handle_message
    raydium_msg_direct = {
        "amm_id": "AMM111",
        "coin_mint": SAMPLE_MINT,
        "pc_mint": SAMPLE_MINT_2,
        "lp_mint": "LP111",
        "open_orders": "OO111",
        "target_orders": "TO111",
        "base_vault": "BV111",
        "quote_vault": "QV111",
        "market_id": "MKT111",
    }
    await bot._handle_message(raydium_msg_direct)

    raydium_msg_event = {
        "event": "raydium_pool_created",
        "poolKeys": raydium_msg_direct,
    }
    await bot._handle_message(raydium_msg_event)

    # Malformed raydium dict
    await bot._handle_message({"amm_id": 123, "coin_mint": None})
    await bot._handle_message({"event": "raydium_pool_created", "pool_keys": "invalid"})

    await bot.close()


async def test_bot_run_additional_coverage_boost(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=TradingBotConfig(dry_run=True),
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # 1. _record_latency_ms branch where latency_ms is not yet dict
    bot._metrics.pop("latency_ms", None)
    bot._record_metric("latency_ms", 12.5)
    assert bot._metrics["latency_ms"]["samples"] == 1
    bot._record_metric("last_latency_ms", 15.0)
    assert bot._metrics["latency_ms"]["samples"] == 2

    # 2. _record_stale_data, _record_failure, _record_connection_loss
    bot._record_stale_data("stale stream test")
    bot._record_failure(reason="failed order", category="network")
    bot._record_connection_loss()
    assert bot._metrics["stale_data"] >= 1
    assert bot._metrics["failures"] >= 1
    assert bot._metrics["connection_loss"] >= 1

    # 3. reset_circuit_breaker
    bot.reset_circuit_breaker(new_baseline_sol=1.5, force=True)
    assert bot._risk_killed is False

    # 4. _check_risk_limits & _check_loss_per_trade
    assert bot._check_risk_limits(SAMPLE_MINT, 0.01, {}) is True
    assert bot._check_loss_per_trade(SAMPLE_MINT) is True
    assert bot._check_daily_drawdown() is True
    assert bot._health_ok_for_trading() is True
    await bot._update_health_state()
    bot._mark_health_check()
    assert bot._next_position_id() is not None

    # 5. _handle_new_token_event with virtual reserves
    token_with_reserves = {
        "mint": "MintReserveNew",
        "name": "ReserveCoin",
        "vSolInBondingCurve": 30_000_000_000,
        "vTokensInBondingCurve": 1_073_000_000_000_000,
    }
    await bot._handle_new_token_event(token_with_reserves)

    # 6. _refresh_active_positions_market_caps with virtual reserves fallback
    bot.active_positions["MintReserveNew"] = {
        "name": "ReserveCoin",
        "entry_market_cap": 27.96,
        "current_market_cap": 27.96,
    }
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 40_000_000_000,
        }
    )
    await bot._refresh_active_positions_market_caps()
    assert bot.active_positions["MintReserveNew"]["current_market_cap"] == 40.0

    # 7. _refresh_active_positions_market_caps with exception handling
    bot.execution.get_bonding_curve_state = AsyncMock(
        side_effect=RuntimeError("RPC down")
    )
    await bot._refresh_active_positions_market_caps()

    # 8. _prune_seen_mints
    bot._seen_mints = {
        "OldMint1": time.monotonic() - 10000,
        "FreshMint1": time.monotonic(),
    }
    bot.recent_token_ttl_seconds = 100
    bot._prune_seen_mints()
    assert "OldMint1" not in bot._seen_mints
    assert "FreshMint1" in bot._seen_mints

    # 9. _handle_complete_event_update
    from pumpfun_trading.streams.geyser import CompleteEventUpdate

    comp_update = CompleteEventUpdate(
        mint="MintCompleteTest",
        bonding_curve="curveComp",
        user="creator1",
        timestamp=int(time.time()),
        slot=100,
    )
    await bot._handle_complete_event_update(comp_update)

    # 10. _enqueue_exit_retry existing entry update
    bot._enqueue_exit_retry("MintRetry2", reason="timeout")
    bot._enqueue_exit_retry("MintRetry2", reason="slippage")
    assert bot._exit_retry_queue["MintRetry2"]["retries"] == 2

    # 11. _process_exit_retry_queue with failed sell
    bot._sell_token = AsyncMock(return_value=False)
    bot._exit_retry_queue["MintRetry2"]["next_retry_at"] = time.monotonic() - 1.0
    await bot._process_exit_retry_queue()

    # 12. _enqueue_exit_retry with max retries exceeded
    bot.max_exit_retries = 3
    bot._exit_retry_queue["MintRetry2"]["retry_count"] = 3
    bot._enqueue_exit_retry("MintRetry2", reason="final_retry")
    assert "MintRetry2" not in bot._exit_retry_queue

    # 13. _resolve_token_name
    assert await bot._resolve_token_name(SAMPLE_MINT, "ExplicitName") == "ExplicitName"
    bot.active_positions[SAMPLE_MINT] = {"name": "CachedName"}
    assert await bot._resolve_token_name(SAMPLE_MINT) == "CachedName"
    bot.active_positions.pop(SAMPLE_MINT, None)
    bot.api.get_coin = AsyncMock(return_value={"name": "ApiCoinName"})
    assert await bot._resolve_token_name(SAMPLE_MINT) == "ApiCoinName"

    # 14. _check_account_equity_guard branches
    bot.dry_run = False
    bot.paper_trade = False
    bot.execution.get_balance_sol = AsyncMock(return_value=1.5)
    assert await bot._check_account_equity_guard(0.01) is True

    bot.execution.get_balance_sol = AsyncMock(return_value=0.01)  # below reserve
    assert await bot._check_account_equity_guard(0.01) is False

    # 15. _handle_trade_event_update
    from pumpfun_trading.streams.geyser import TradeEventUpdate

    trade_ev = TradeEventUpdate(
        mint="MintTradeEv1",
        sol_amount_lamports=500_000_000,
        token_amount=1000,
        is_buy=True,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=35_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=10_000_000_000,
        real_token_reserves=500_000_000_000_000,
        slot=123,
    )
    await bot._handle_trade_event_update(trade_ev)

    # 16. TradingBot.from_env
    with patch.dict(
        os.environ,
        {
            "PUMPFUN_PRIVATE_KEY": SAMPLE_PRIVATE_KEY,
            "PUMPFUN_RPC_URL": "https://api.mainnet-beta.solana.com",
        },
    ):
        bot_env = TradingBot.from_env(dry_run=True, paper_trade=True)
        assert bot_env.dry_run is True
        assert bot_env.paper_trade is True
        await bot_env.close()

    # 17. _buy_raydium_token branches
    from pumpfun_trading.strategies.graduation import RaydiumPoolKeys
    from pumpfun_trading.execution.executor import ExecutionResult

    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "AMM111",
            "coin_mint": SAMPLE_MINT,
            "pc_mint": SAMPLE_MINT_2,
            "lp_mint": "LP1",
        }
    )
    bot._should_buy = MagicMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot._should_buy = MagicMock(return_value=True)
    bot._check_account_equity_guard = AsyncMock(return_value=False)
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC Timeout")
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is False

    bot.executor.execute_raydium_buy = AsyncMock(
        return_value=ExecutionResult(
            success=True, token_amount=1_000_000, signature="sig_ray"
        )
    )
    assert await bot._buy_raydium_token(SAMPLE_MINT, keys) is True
    assert SAMPLE_MINT in bot.active_positions

    # 18. _handle_bonding_curve_state_update held token evaluation
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    bc_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curveHeld",
        slot=200,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=70_000_000_000,
        real_token_reserves=500_000_000_000_000,
        real_sol_reserves=40_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00007,
        market_cap_sol=70.0,
    )
    await bot._handle_bonding_curve_state_update(bc_up)

    await bot.close()


async def test_bot_deep_coverage_additional(tmp_path):
    # 1. validate_mint_address invalid checks
    with pytest.raises(ValueError):
        TradingBot.validate_mint_address("invalid_base58_###")

    with pytest.raises(ValueError):
        # valid base58 but not 32 bytes
        TradingBot.validate_mint_address("1111")

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        verbose=True,
        config=TradingBotConfig(
            dry_run=True,
            paper_trade=True,
            enable_copy_trading=True,
            copy_trading_wallets=["WhaleTrd1"],
            enable_momentum_signals=True,
            enable_raydium_migration_sniping=True,
        ),
        bot_status_path=str(tmp_path / "status.json"),
    )

    # 2. _log when verbose
    bot._log("Verbose log test", level=10)

    # 3. _handle_trade_event_update triggering copy-trade and momentum
    from pumpfun_trading.streams.geyser import TradeEventUpdate

    trade_buy = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=500_000,
        is_buy=True,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    bot._buy_token = AsyncMock(return_value=True)
    await bot._handle_trade_event_update(trade_buy)

    trade_sell = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=500_000_000,
        token_amount=250_000,
        is_buy=False,
        user="WhaleTrd1",
        timestamp=int(time.time()),
        virtual_sol_reserves=30_000_000_000,
        virtual_token_reserves=1_000_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    bot.active_positions[SAMPLE_MINT] = {"name": "TestToken", "entry_sol": 0.01}
    bot._sell_token = AsyncMock(return_value=True)
    await bot._handle_trade_event_update(trade_sell)

    # 4. _handle_bonding_curve_state_update triggering graduation snipe
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    bc_grad = BondingCurveStateUpdate(
        mint=SAMPLE_MINT_2,
        bonding_curve_pubkey="curveGrad",
        slot=300,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=85_000_000_000,
        real_token_reserves=200_000_000_000_000,
        real_sol_reserves=85_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=True,
        price_sol=0.000085,
        market_cap_sol=85.0,
    )
    await bot._handle_bonding_curve_state_update(bc_grad)

    # 5. _handle_raydium_pool_update
    from pumpfun_trading.strategies.graduation import RaydiumPoolKeys

    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "AMM222",
            "coin_mint": SAMPLE_MINT_2,
            "pc_mint": SAMPLE_MINT,
            "lp_mint": "LP2",
        }
    )
    bot._buy_raydium_token = AsyncMock(return_value=True)
    await bot._handle_raydium_pool_update(keys)

    # 6. WebSocket message parsing branches
    await bot._handle_message(
        {"txType": "create", "mint": SAMPLE_MINT_2, "name": "CreatedToken"}
    )
    await bot._handle_message(
        {"txType": "trade", "mint": SAMPLE_MINT, "marketCapSol": 30.0}
    )
    await bot._handle_message(
        {"type": "complete", "mint": SAMPLE_MINT_2, "bondingCurve": "curveGrad"}
    )

    await bot.close()


async def test_liquidator_and_api_edge_branches():
    from pumpfun_trading.execution.liquidator import OrderLiquidator
    from pumpfun_trading.execution.executor import ExecutionResult, OrderExecutor
    from pumpfun_trading.bot.position_manager import PositionManager

    exec_mock = MagicMock(spec=OrderExecutor)
    pm = PositionManager(TradingBotConfig())
    pm.record_buy(SAMPLE_MINT, token_amount=1000, cost_sol=0.01, entry_market_cap=27.96)
    liquidator = OrderLiquidator(
        executor=exec_mock, position_manager=pm, config=TradingBotConfig()
    )

    exec_mock.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=False, error="RPC fail", dry_run=False)
    )
    results = await liquidator.liquidate_all_positions(reason="panic")
    assert results == []

    exec_mock.execute_sell = AsyncMock(
        return_value=ExecutionResult(success=True, signature="sold_all", dry_run=False)
    )
    results2 = await liquidator.liquidate_all_positions(reason="panic")
    assert SAMPLE_MINT in results2
    assert len(pm.get_all_positions()) == 0


def test_cli_entrypoints_coverage():
    from pumpfun_trading.cli.main import main as cli_main_func
    from pumpfun_trading.cli.bot import main as bot_main_func

    # Test main CLI with mode=bot catching KeyboardInterrupt
    with (
        patch(
            "sys.argv",
            ["pumpfun-cli", "--mode", "bot", "--dry-run", "--preset", "balanced"],
        ),
        patch("pumpfun_trading.bot.run.TradingBot.from_env") as mock_bot_factory,
    ):
        mock_bot_instance = MagicMock()
        mock_bot_instance.start = AsyncMock(side_effect=KeyboardInterrupt)
        mock_bot_instance.close = AsyncMock()
        mock_bot_factory.return_value = mock_bot_instance

        cli_main_func()
        mock_bot_instance.close.assert_called_once()

    # Test bot CLI main catching KeyboardInterrupt
    with patch("pumpfun_trading.cli.bot.build_parser") as mock_parser_builder:
        parser = MagicMock()
        parser.parse_args.return_value = MagicMock(
            config=None,
            preset="balanced",
            dry_run=True,
            paper_trade=True,
            headless=False,
            buy_amount_sol=None,
            take_profit=None,
            stop_loss=None,
            min_market_cap_sol=None,
            min_balance_sol=None,
        )
        mock_parser_builder.return_value = parser
        with patch("pumpfun_trading.bot.run.TradingBot.from_env") as mock_bot_factory:
            mock_bot_instance = MagicMock()
            mock_bot_instance.start = AsyncMock(side_effect=KeyboardInterrupt)
            mock_bot_instance.close = AsyncMock()
            mock_bot_factory.return_value = mock_bot_instance

            bot_main_func()
            mock_bot_instance.close.assert_called_once()


async def test_api_client_context_manager_and_text_response():
    from pumpfun_trading.api.client import PumpFunApiClient

    async with PumpFunApiClient() as client:
        # Mock _get_session request returning non-json string
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="plain non-json response text")

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.request = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp), __aexit__=AsyncMock()
            )
        )
        client._session = mock_session

        res = await client.request("GET", "/health")
        assert res == "plain non-json response text"
