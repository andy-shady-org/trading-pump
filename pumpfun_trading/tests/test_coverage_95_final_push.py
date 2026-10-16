from __future__ import annotations

import json
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.audit import (
    export_audit_records,
    load_audit_records,
    summarize_audit_records,
)
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.sdk.execution import (
    PumpFunExecutionClient,
)

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_MINT_2 = "So11111111111111111111111111111111111111112"


def test_audit_module_all_branches(tmp_path):
    # Non-existent file
    assert load_audit_records(tmp_path / "missing.jsonl") == []

    # File with comments, blank lines, and corrupted JSON
    audit_file = tmp_path / "sample_audit.jsonl"
    audit_file.write_text(
        "# comment\n\n{invalid json}\n"
        + json.dumps({"timestamp": 1234, "type": "trade", "payload": {"status": "ok"}})
        + "\n",
        encoding="utf-8",
    )
    records = load_audit_records(audit_file)
    assert len(records) == 1

    # summarize empty and non-empty
    assert summarize_audit_records([])["total_records"] == 0

    # export audit to nested dir
    out_file = tmp_path / "nested" / "export.json"
    assert export_audit_records(records, str(out_file)) == str(out_file)
    assert out_file.exists()


async def test_api_client_snapshot_fallbacks():
    client = PumpFunApiClient()

    client.get_coin = AsyncMock(
        return_value={"name": "NestedCoin", "marketCapSol": 42.0}
    )
    snap = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap["name"] == "NestedCoin"
    assert snap["market_cap_sol"] == 42.0

    client.get_coin = AsyncMock(
        return_value={"displayName": "ItemCoin", "marketCap": 50.0}
    )
    snap2 = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap2["name"] == "ItemCoin"

    client.get_coin = AsyncMock(
        return_value={"tokenName": "ResultCoin", "marketCap": 1000.0}
    )
    snap3 = await client.get_market_data_snapshot(SAMPLE_MINT)
    assert snap3["name"] == "ResultCoin"

    # get_token_age variants
    client.get_coin = AsyncMock(return_value={"age": {"days": 10}})
    assert await client.get_token_age(SAMPLE_MINT) == {"days": 10}

    # get_coin 500 error not caught
    err_client = PumpFunApiClient()
    err_client.get = AsyncMock(side_effect=RuntimeError("HTTP 500 Internal Error"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await err_client.get_coin(SAMPLE_MINT)
    await err_client.close()

    # get_session creation and close
    await client.close()
    session = await client._get_session()
    assert session is not None
    await client.close()


def test_sdk_math_and_keypairs():
    # normalize_slippage_bps
    assert PumpFunExecutionClient.normalize_slippage_bps(None, default=400) == 400
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(True)
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(-10)
    with pytest.raises(ValueError):
        PumpFunExecutionClient.normalize_slippage_bps(20000)

    # evaluate_fill_completion & should_reassess_partial_fill
    assert PumpFunExecutionClient.evaluate_fill_completion(100, 0)["status"] == "failed"
    assert PumpFunExecutionClient.evaluate_fill_completion(100, 100)["status"] == "full"
    assert (
        PumpFunExecutionClient.evaluate_fill_completion(100, 50)["status"] == "partial"
    )
    assert PumpFunExecutionClient.should_reassess_partial_fill(100, 50) is True
    assert PumpFunExecutionClient.should_reassess_partial_fill(100, 0) is False
    assert PumpFunExecutionClient.should_reassess_partial_fill(0, 50) is False

    # calculate_sell_sol_output
    assert PumpFunExecutionClient.calculate_sell_sol_output(0, 100, 100) == 0
    assert PumpFunExecutionClient.calculate_sell_sol_output(10, 0, 100) == 0
    assert (
        PumpFunExecutionClient.calculate_sell_sol_output(
            100, 1000, 1000, slippage_bps=500
        )
        > 0
    )

    # _decode_keypair 32-byte vs 64-byte
    kp = Keypair()
    b58_32 = __import__("base58").b58encode(bytes(kp)[:32]).decode("ascii")
    b58_64 = __import__("base58").b58encode(bytes(kp)).decode("ascii")

    kp1 = PumpFunExecutionClient._decode_keypair(b58_32)
    assert kp1 is not None
    kp2 = PumpFunExecutionClient._decode_keypair(b58_64)
    assert kp2 is not None

    with pytest.raises(ValueError):
        PumpFunExecutionClient._decode_keypair("short")


@pytest.mark.usefixtures("offline_trade_rpc")
async def test_sdk_rpc_retry_recovery_and_tx_assembly():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        priority_fee_lamports=10000,
        compute_unit_limit=300000,
        compute_unit_price_micro_lamports=50000,
        jito_tip_lamports=10000,
    )

    # RPC retry recovery: fails once with 500 then returns valid blockhash
    attempt_count = 0

    class MockResp:
        def __init__(self):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                self.status = 500
                self._body = "Internal Server Error"
            else:
                self.status = 200
                self._body = json.dumps(
                    {"result": {"value": {"blockhash": str(Hash.default())}}}
                )

        async def text(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    with patch("aiohttp.ClientSession.post", side_effect=lambda *a, **k: MockResp()):
        with patch("asyncio.sleep", return_value=None):
            blockhash = await client.get_latest_blockhash()
            assert blockhash is not None

    # build_buy_tx and build_sell_tx with full instructions
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))
    client.get_ata_exists = AsyncMock(return_value=False)

    buy_tx = await client.build_buy_tx(SAMPLE_MINT, pda, 0.05)
    assert buy_tx is not None

    tx = await client.build_sell_tx(
        SAMPLE_MINT,
        pda,
        1000000,
        min_sol_output=0.05,  # float min sol output
        slippage_bps=200,
    )
    assert tx is not None

    # send_jito_bundle with bundle list
    mock_jito_resp = AsyncMock()
    mock_jito_resp.status = 200
    mock_jito_resp.text = AsyncMock(return_value=json.dumps({"result": "bundle_999"}))
    mock_jito_resp.__aenter__.return_value = mock_jito_resp
    mock_jito_resp.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_jito_resp):
        bundle_id = await client.send_jito_bundle([tx])
        assert bundle_id == "bundle_999"

    # get_ata_exists non-dict item cases
    client._request_rpc_json = AsyncMock(
        return_value={
            "result": {
                "value": [
                    "not_dict",
                    {"account": "not_dict"},
                    {"account": {"data": "not_dict"}},
                    {"account": {"data": {"parsed": "not_dict"}}},
                    {"account": {"data": {"parsed": {"info": "not_dict"}}}},
                ]
            }
        }
    )
    assert await client.get_ata_exists(SAMPLE_MINT) is False


async def test_bot_startup_schema_and_edge_branches(tmp_path):
    # Status file in local dir with integer arguments
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=TradingBotConfig(enable_tiered_take_profit=False),
        min_market_cap_sol=20,  # int
        min_balance_sol=1,  # int
        max_active_positions=2,  # int
        dry_run=False,
        paper_trade=False,
        bot_status_path="status.json",
        audit_log_path="audit.jsonl",
    )

    # _send_alert exception handling
    bot.alert_enabled = True
    with patch("urllib.request.urlopen", side_effect=RuntimeError("webhook down")):
        bot._send_alert("Alert failure test")

    # safe_startup with rich schema
    schema = {
        "active_positions": {
            SAMPLE_MINT: {
                "name": "CoinSchema",
                "entry_market_cap": 25.0,
                "current_market_cap": 25.0,
                "token_amount": 1000,
            },
            "InvalidPos": "not_a_dict",
        },
        "buy_attempts": {SAMPLE_MINT: 2},
        "seen_mints": {SAMPLE_MINT: time.monotonic()},
        "recent_actions": [{"timestamp": 1234, "action": "buy"}, "invalid_action"],
        "recent_events": ["event1", 1234],
        "trade_ledger": [{"mint": SAMPLE_MINT, "action": "buy"}, "invalid_trade"],
        "exit_retry_queue": {
            SAMPLE_MINT: {
                "mint": SAMPLE_MINT,
                "retry_count": 6,  # exceeds max retries
                "next_retry_at": time.monotonic() - 1.0,
            }
        },
        "circuit_breaker_tripped": True,
        "ws_consecutive_failures": 3,
    }
    bot_status_file = tmp_path / "full_status.json"
    bot_status_file.write_text(json.dumps(schema), encoding="utf-8")
    bot.bot_status_path = str(bot_status_file)
    bot.safe_startup()

    assert SAMPLE_MINT in bot.active_positions
    assert bot._buy_attempts[SAMPLE_MINT] == 2

    # reconcile_onchain_positions with bonding curve MC update and balance read error
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 35.0}
    )
    reconciled = await bot.reconcile_onchain_positions()
    assert reconciled[SAMPLE_MINT]["status"] == "active"
    assert bot.active_positions[SAMPLE_MINT]["current_market_cap"] == 35.0

    # Exception during balance read in reconciliation
    bot.execution.get_token_balance = AsyncMock(
        side_effect=RuntimeError("balance RPC err")
    )
    await bot.reconcile_onchain_positions()

    # _enqueue_exit_retry max retries alert
    bot._enqueue_exit_retry(SAMPLE_MINT, reason="test_max_retry")

    # _validate_balance failure
    bot.execution.get_balance_sol = AsyncMock(return_value=0.0)
    assert await bot._validate_balance() is False
    assert await bot._buy_token(SAMPLE_MINT_2, market_cap_sol=20.0) is False

    # Trade update with on-chain curve reading in non-dry-run mode
    bot.active_positions[SAMPLE_MINT]["entry_market_cap"] = 25.0
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 60.0}  # TP hit (60 > 25*1.5)
    )
    bot.execution.get_token_balance = AsyncMock(return_value=1000)
    bot.execution.sell = AsyncMock(return_value="tx_tp_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    await bot._handle_trade_update(
        {"mint": SAMPLE_MINT, "marketCapSol": 28.0}, AsyncMock()
    )
    assert SAMPLE_MINT not in bot.active_positions

    # Message handlers edge conditions
    mock_ws = AsyncMock()
    bot._stop_requested = True
    await bot._handle_new_token_event({"mint": SAMPLE_MINT}, mock_ws)
    await bot._handle_trade_update({"mint": SAMPLE_MINT}, mock_ws)
    bot._stop_requested = False

    await bot._handle_new_token_event({}, mock_ws)  # empty mint
    bot._seen_mints[SAMPLE_MINT] = time.monotonic()
    await bot._handle_new_token_event({"mint": SAMPLE_MINT}, mock_ws)  # seen mint
    bot._seen_mints.clear()

    await bot._handle_trade_update({}, mock_ws)  # empty mint
    await bot._handle_trade_update(
        {"mint": SAMPLE_MINT_2, "marketCapSol": 10.0}, mock_ws
    )  # not active
    bot.active_positions[SAMPLE_MINT] = {"entry_market_cap": 20.0}
    await bot._handle_trade_update(
        {"mint": SAMPLE_MINT, "marketCapSol": 0.0}, mock_ws
    )  # non-positive mc

    await bot._handle_message("not_dict", mock_ws)

    # Cleanup test files created in current dir
    await bot.close()
    for fname in ("status.json", "audit.jsonl"):
        p = Path(fname)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


async def test_bot_start_and_message_loop_heartbeat(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="http://127.0.0.1:10000",
        config=TradingBotConfig(),
        dry_run=True,
    )
    bot._circuit_breaker_tripped = True
    bot._last_message_at = time.monotonic() - 70.0  # triggers heartbeat timeout check

    events = [
        "not_valid_dict",
        {"txType": "create", "mint": SAMPLE_MINT, "marketCapSol": 30.0},
    ]

    async def mock_listen():
        for e in events:
            yield e
        bot.request_shutdown()

    bot.geyser_client.listen = mock_listen
    bot.reconcile_onchain_positions = AsyncMock(side_effect=RuntimeError("recon err"))

    await bot.start()

    assert bot._circuit_breaker_tripped is False
    await bot.close()
