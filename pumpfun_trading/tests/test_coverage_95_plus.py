from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.hash import Hash

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.cli import bot as cli_bot
import pumpfun_trading.cli.main as cli_main_mod
from pumpfun_trading.sdk.execution import PumpFunExecutionClient

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_MINT_2 = "So11111111111111111111111111111111111111112"


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_execution_sdk_all_branches():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
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

    # get_token_balance when no accounts found
    client._request_rpc_json = AsyncMock(return_value={"result": {"value": None}})
    assert await client.get_token_balance(SAMPLE_MINT) == 0

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

    buy_res = await client.buy(
        SAMPLE_MINT, pda, 0.05, token_amount=1000000, slippage_bps=200
    )
    assert buy_res == "tx_sig_wrapped_123"

    sell_res = await client.sell(SAMPLE_MINT, pda, 1000000, min_sol_output=1000)
    assert sell_res == "tx_sig_wrapped_123"


@pytest.mark.asyncio
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
    }
    await bot._handle_message(msg_new, AsyncMock())
    assert SAMPLE_MINT in bot.active_positions

    # trade message with stop loss exit
    await bot._handle_message(
        {"mint": SAMPLE_MINT, "marketCapSol": 2.0}, AsyncMock()  # 2/25 = 0.08 <= 0.85
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
