from __future__ import annotations

import json
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"


@pytest.fixture
def base_bot(tmp_path):
    config = TradingBotConfig(
        strategy_preset="balanced",
        buy_amount_sol=0.05,
        take_profit=1.5,
        stop_loss=0.85,
        max_total_exposure_sol=1.0,
        max_position_size_sol=0.2,
        min_market_cap_sol=10.0,
        min_balance_sol=0.1,
        enable_tiered_take_profit=False,
    )
    status_file = tmp_path / "bot_status.json"
    audit_file = tmp_path / "audit.jsonl"
    log_file = tmp_path / "bot.log"

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=True,
        paper_trade=False,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
        log_file=str(log_file),
    )
    return bot


def test_bot_alerting_and_snapshot(base_bot, tmp_path):
    # Alerting configuration with valid & invalid providers
    base_bot.alert_provider = "invalid_provider"
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_provider = "discord"
    base_bot.alert_discord_webhook_url = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_discord_webhook_url = "https://discord.com/webhook"
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is True

    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert discord")
        assert mock_url.called

    base_bot.alert_provider = "slack"
    base_bot.alert_slack_webhook_url = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_slack_webhook_url = "https://slack.com/webhook"
    base_bot._configure_alerting()
    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert slack")
        assert mock_url.called

    base_bot.alert_provider = "telegram"
    base_bot.alert_telegram_bot_token = ""
    base_bot._configure_alerting()
    assert base_bot.alert_enabled is False

    base_bot.alert_telegram_bot_token = "token123"
    base_bot.alert_telegram_chat_id = "chat123"
    base_bot._configure_alerting()
    with patch("urllib.request.urlopen") as mock_url:
        base_bot._send_alert("Test alert telegram")
        assert mock_url.called

    # Snapshot writing
    base_bot._write_status_snapshot()
    assert Path(base_bot.bot_status_path).exists()

    # Audit logging
    base_bot._write_audit_record("test_event", {"info": 123})
    assert Path(base_bot.audit_log_path).exists()


def test_bot_safe_startup_recovery(tmp_path):
    status_file = tmp_path / "recovery_status.json"
    snapshot = {
        "active_positions": {
            "MintRecovered": {
                "name": "TokenRecovered",
                "entry_market_cap": 25.0,
                "current_market_cap": 28.0,
            }
        },
        "buy_attempts": {"MintA": 1},
        "seen_mints": {"MintA": 12345.0},
        "trade_ledger": [{"mint": "MintA", "action": "buy"}],
    }
    status_file.write_text(json.dumps(snapshot), encoding="utf-8")

    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=TradingBotConfig(),
        dry_run=True,
        bot_status_path=str(status_file),
    )
    assert "MintRecovered" in bot.active_positions
    assert bot._buy_attempts.get("MintA") == 1
    assert bot._seen_mints.get("MintA") == 12345.0


@pytest.mark.asyncio
async def test_bot_buy_and_sell_flows(base_bot):
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    # Dry run buy
    success_buy = await base_bot._buy_token(
        mint, market_cap_sol=15.0, token_name="TokenDry"
    )
    assert success_buy is True
    assert mint in base_bot.active_positions

    # Dry run sell
    success_sell = await base_bot._sell_token(mint)
    assert success_sell is True
    assert mint not in base_bot.active_positions

    # Sell token not in positions
    assert await base_bot._sell_token("NonExistentMint") is False


@pytest.mark.asyncio
async def test_bot_live_buy_and_sell_branches(tmp_path):
    config = TradingBotConfig(buy_amount_sol=0.05)
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=config,
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    # Mock execution client
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.get_balance_sol = AsyncMock(return_value=1.0)
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.buy = AsyncMock(return_value="tx_sig_123")
    bot.execution.sell = AsyncMock(return_value="tx_sig_sell_123")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    # Live buy success
    buy_ok = await bot._buy_token(mint, market_cap_sol=20.0, token_name="TokenLive")
    assert buy_ok is True
    assert mint in bot.active_positions

    # Live sell success
    sell_ok = await bot._sell_token(mint)
    assert sell_ok is True
    assert mint not in bot.active_positions

    # Live sell zero balance purge
    bot.active_positions[mint] = {"name": "TokenZero", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=0)
    sell_zero = await bot._sell_token(mint)
    assert sell_zero is True
    assert mint not in bot.active_positions

    # Live buy failure: missing signature
    bot.execution.buy = AsyncMock(return_value=None)
    buy_fail_sig = await bot._buy_token("MintNoSig", market_cap_sol=20.0)
    assert buy_fail_sig is False

    # Live buy failure: confirmation failed
    bot.execution.buy = AsyncMock(return_value="tx_sig_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    buy_fail_conf = await bot._buy_token("MintNoConf", market_cap_sol=20.0)
    assert buy_fail_conf is False

    # Live sell failure: confirmation failed
    bot.active_positions["MintSellConfFail"] = {
        "name": "TokenFail",
        "entry_market_cap": 20.0,
    }
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value="tx_sig_sell_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    sell_fail_conf = await bot._sell_token("MintSellConfFail")
    assert sell_fail_conf is False

    await bot.close()


@pytest.mark.asyncio
async def test_bot_message_handlers_and_events(base_bot):
    mint = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"

    mock_ws = AsyncMock()

    # Handle newTokenCreated
    new_token_msg = {
        "txType": "create",
        "mint": mint,
        "name": "FreshToken",
        "marketCapSol": 25.0,
    }
    await base_bot._handle_message(new_token_msg, mock_ws)
    assert mint in base_bot.active_positions

    # Handle tradeCreated holding update
    trade_msg = {
        "txType": "trade",
        "mint": mint,
        "marketCapSol": 30.0,
    }
    await base_bot._handle_message(trade_msg, mock_ws)
    assert base_bot.active_positions[mint]["current_market_cap"] == 30.0

    # Handle tradeCreated take profit exit
    trade_tp_msg = {
        "txType": "trade",
        "mint": mint,
        "marketCapSol": 50.0,  # 50.0 > 25.0 * 1.5
    }
    await base_bot._handle_message(trade_tp_msg, mock_ws)
    assert mint not in base_bot.active_positions

    # Unrecognized message
    await base_bot._handle_message({"unknown": True}, mock_ws)


@pytest.mark.asyncio
async def test_bot_reconciliation_and_retries(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=TradingBotConfig(),
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
    )

    mint1 = "MintActive1"
    mint2 = "MintZero2"

    bot.active_positions = {
        mint1: {"name": "Token1", "entry_market_cap": 20.0, "token_amount": 100},
        mint2: {"name": "Token2", "entry_market_cap": 20.0, "token_amount": 100},
    }

    async def mock_get_token_balance(mint):
        if mint == mint1:
            return 500
        return 0

    bot.execution.get_token_balance = AsyncMock(side_effect=mock_get_token_balance)
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={"market_cap_sol": 25.0}
    )

    reconciled = await bot.reconcile_onchain_positions()
    assert mint1 in bot.active_positions
    assert mint2 not in bot.active_positions
    assert reconciled[mint2]["status"] == "purged"

    # Test exit retry queue
    bot.active_positions[mint1] = {"name": "Token1"}
    bot._enqueue_exit_retry(mint1, reason="network_blip")
    assert mint1 in bot._exit_retry_queue

    # Set timer to past to trigger process
    bot._exit_retry_queue[mint1]["next_retry_at"] = time.monotonic() - 1.0
    bot._sell_token = AsyncMock(return_value=True)
    await bot._process_exit_retry_queue(websocket=AsyncMock())

    await bot.close()
