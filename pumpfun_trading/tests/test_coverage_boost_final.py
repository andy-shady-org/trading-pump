from __future__ import annotations

import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.hash import Hash
from solders.pubkey import Pubkey

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.cli import bot as cli_bot
from pumpfun_trading.sdk.execution import (
    PumpFunExecutionClient,
)

cli_main_mod = sys.modules["pumpfun_trading.cli.main"]

SAMPLE_PRIVATE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
SAMPLE_MINT_2 = "So11111111111111111111111111111111111111112"


def test_cli_all_modes_and_flags(tmp_path):
    cfg_file = tmp_path / "bot_conf.json"
    cfg_file.write_text(json.dumps({"buy_amount_sol": 0.05}), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.get_latest_coins = AsyncMock(return_value=[{"name": "Coin1"}])
    mock_client.get_coin = AsyncMock(
        return_value={"name": "Coin1", "mint": SAMPLE_MINT}
    )
    mock_client.close = AsyncMock()

    # 1. main mode == latest-coins with --raw
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch("sys.argv", ["pumpfun", "--mode", "latest-coins", "--raw"]):
            cli_main_mod.main()

    # 2. main mode == market-info with --raw
    with patch("pumpfun_trading.cli.main.PumpFunApiClient", return_value=mock_client):
        with patch(
            "sys.argv",
            ["pumpfun", "--mode", "market-info", "--mint", SAMPLE_MINT, "--raw"],
        ):
            cli_main_mod.main()

    # 3. main mode == bot with --config and --raw
    mock_bot = MagicMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    with patch("pumpfun_trading.cli.main.TradingBot.from_env", return_value=mock_bot):
        with patch(
            "sys.argv",
            ["pumpfun", "--mode", "bot", "--config", str(cfg_file), "--dry-run"],
        ):
            cli_main_mod.main()

    # 4. cli_bot main with --config
    with patch("pumpfun_trading.cli.bot.TradingBot.from_env", return_value=mock_bot):
        with patch("sys.argv", ["pumpfun-bot", "--config", str(cfg_file), "--dry-run"]):
            cli_bot.main()


@pytest.mark.asyncio
async def test_api_client_all_methods_and_options():
    client = PumpFunApiClient(base_url="https://api.pump.fun")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"data": []})
    mock_resp.text = AsyncMock(return_value='{"data": []}')
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.__aexit__.return_value = None

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.request = MagicMock(return_value=mock_resp)
    client._get_session = AsyncMock(return_value=mock_session)

    # Call with options
    await client.get("/test", params={"q": "sol"}, headers={"X-Custom": "val"})
    await client.get_latest_coins(limit=50, offset=10)
    await client.get_advanced_coins_list(
        limit=20, offset=5, sort="market_cap", order="desc", include_nsfw=True
    )
    await client.get_coins_for_you(limit=15, offset=5)
    await client.get_coins_featured(limit=5)
    await client.get_coins_search("pepe", limit=10, offset=0)
    await client.get_trades_for_mint(SAMPLE_MINT, limit=25, offset=0)
    await client.get_trade_count(SAMPLE_MINT)
    await client.get_candlesticks(SAMPLE_MINT, interval="5m", limit=50)
    await client.get_sol_price()
    await client.get_market_overview()

    # Error handling on non-200 text vs json
    mock_err_resp = AsyncMock()
    mock_err_resp.status = 400
    mock_err_resp.text = AsyncMock(return_value="Bad Request Message")
    mock_err_resp.__aenter__.return_value = mock_err_resp
    mock_err_resp.__aexit__.return_value = None
    mock_session.request = MagicMock(return_value=mock_err_resp)

    with patch("asyncio.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="Bad Request Message"):
            await client.get("/error")

    await client.close()


def test_sdk_instructions_and_decoding():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY, "https://api.mainnet-beta.solana.com"
    )

    # SetComputeUnitLimit and SetComputeUnitPrice
    limit_ix = client.build_set_compute_unit_limit_instruction(300_000)
    assert limit_ix is not None

    price_ix = client.build_set_compute_unit_price_instruction(100_000)
    assert price_ix is not None

    # Jito tip instruction
    tip_ix = client.build_jito_tip_instruction(
        tip_lamports=50_000,
        tip_account=SAMPLE_MINT_2,
    )
    assert tip_ix is not None

    # decode_bonding_curve_data invalid length
    with pytest.raises(ValueError):
        client.decode_bonding_curve_data(b"short_bytes")

    # classify_execution_error
    assert (
        client.classify_execution_error(Exception("signature failed"))
        == "transaction_failed"
    )
    assert (
        client.classify_execution_error(Exception("custom error string")) == "unknown"
    )

    # _to_pubkey when already Pubkey
    pk_obj = Pubkey.from_string(SAMPLE_MINT)
    assert client._to_pubkey(pk_obj) == pk_obj


@pytest.mark.asyncio
async def test_sdk_tx_build_and_confirm_variations():
    client = PumpFunExecutionClient(
        SAMPLE_PRIVATE_KEY,
        "https://api.mainnet-beta.solana.com",
        compute_unit_limit=150_000,
        compute_unit_price_micro_lamports=25_000,
        jito_tip_lamports=5_000,
    )
    pda, _ = client.get_bonding_curve_pda(SAMPLE_MINT)
    client.get_latest_blockhash = AsyncMock(return_value=str(Hash.default()))

    # Build buy with ATA existing vs not existing
    client.get_ata_exists = AsyncMock(return_value=True)
    buy_tx_ata = await client.build_buy_tx(SAMPLE_MINT, pda, 0.05, token_amount=500000)
    assert buy_tx_ata is not None

    # Build sell with slippage and ATA not existing
    client.get_ata_exists = AsyncMock(return_value=False)
    sell_tx = await client.build_sell_tx(
        SAMPLE_MINT, pda, 500000, min_sol_output=10000, slippage_bps=300
    )
    assert sell_tx is not None

    # Jito bundle send error
    mock_jito_err = AsyncMock()
    mock_jito_err.status = 500
    mock_jito_err.text = AsyncMock(return_value="Jito Node Down")
    mock_jito_err.__aenter__.return_value = mock_jito_err
    mock_jito_err.__aexit__.return_value = None

    with patch("aiohttp.ClientSession.post", return_value=mock_jito_err):
        with pytest.raises(RuntimeError, match="Jito bundle submission failed"):
            await client.send_jito_bundle([])


@pytest.mark.asyncio
async def test_bot_full_websocket_and_lifecycle(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"PUMPFUN_PRIVATE_KEY={SAMPLE_PRIVATE_KEY}\nPUMPFUN_RPC_URL=https://api.mainnet-beta.solana.com\n",
        encoding="utf-8",
    )

    bot = TradingBot.from_env(
        env_file=str(env_file),
        config=TradingBotConfig(
            buy_amount_sol=0.05,
            min_market_cap_sol=10.0,
            enable_tiered_take_profit=False,
        ),
        dry_run=True,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Prune seen mints when expired
    bot._seen_mints[SAMPLE_MINT] = time.monotonic() - (
        bot.recent_token_ttl_seconds + 10.0
    )
    bot._prune_seen_mints()
    assert SAMPLE_MINT not in bot._seen_mints

    # Start loop with events and graceful shutdown
    events = [
        {
            "txType": "create",
            "mint": SAMPLE_MINT,
            "name": "LiveToken",
            "marketCapSol": 25.0,
        },
        {
            "txType": "trade",
            "mint": SAMPLE_MINT,
            "marketCapSol": 50.0,  # TP exit
        },
    ]

    async def mock_listen():
        for msg in events:
            yield msg
        bot.request_shutdown()

    bot.geyser_client.listen = mock_listen
    await bot.start()

    assert SAMPLE_MINT not in bot.active_positions
    await bot.close()


@pytest.mark.asyncio
async def test_bot_live_error_branches(tmp_path):
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        stream_url="wss://pumpportal.fun/api/data",
        config=TradingBotConfig(buy_amount_sol=0.05),
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Live buy missing signature and confirmation failure
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(str(Pubkey.from_string(SAMPLE_MINT_2)), "bump")
    )
    bot.execution.buy = AsyncMock(return_value=None)
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    bot.execution.buy = AsyncMock(return_value="tx_sig_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    # Live sell missing signature and confirmation failure
    bot.active_positions[SAMPLE_MINT] = {"name": "TokenFail", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value=None)
    assert await bot._sell_token(SAMPLE_MINT) is False

    bot.execution.sell = AsyncMock(return_value="tx_sell_fail")
    bot.execution.confirm_transaction = AsyncMock(return_value=False)
    assert await bot._sell_token(SAMPLE_MINT) is False

    # Live buy PDA exception
    bot.execution.get_bonding_curve_pda = MagicMock(
        side_effect=RuntimeError("PDA error")
    )
    assert await bot._buy_token(SAMPLE_MINT, market_cap_sol=20.0) is False

    # Live sell PDA exception
    bot.active_positions[SAMPLE_MINT] = {"name": "TokenPDA", "entry_market_cap": 20.0}
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    assert await bot._sell_token(SAMPLE_MINT) is False
    assert SAMPLE_MINT in bot._exit_retry_queue

    # Live sell bonding curve fetch exception (continues with min_sol_lamports=0)
    bot.execution.get_bonding_curve_pda = MagicMock(
        return_value=(str(Pubkey.from_string(SAMPLE_MINT_2)), "bump")
    )
    bot.execution.get_bonding_curve_state = AsyncMock(
        side_effect=RuntimeError("curve fetch error")
    )
    bot.execution.sell = AsyncMock(return_value="tx_sell_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    sell_ok = await bot._sell_token(SAMPLE_MINT)
    assert sell_ok is True
    assert SAMPLE_MINT not in bot.active_positions

    await bot.close()
