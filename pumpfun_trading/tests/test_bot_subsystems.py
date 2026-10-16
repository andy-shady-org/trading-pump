from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.alerts import AlertDispatcher
from pumpfun_trading.bot.enrichment import TokenEnricher
from pumpfun_trading.bot.persistence import StatusPersistenceManager
from pumpfun_trading.bot.strategy import ScreeningCache, TokenScreeningVerdict
from pumpfun_trading.strategies.base import TradingBotConfig


async def test_token_enricher_disabled():
    config = TradingBotConfig(enable_anti_rug_filters=False)
    enricher = TokenEnricher(config=config)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert verdict.passed
    assert verdict.risk_score == 0.0


async def test_token_enricher_cache_hit():
    cache = ScreeningCache(default_ttl=60)
    cached = TokenScreeningVerdict(mint="Mint111", passed=True, risk_score=10.0)
    cache.set("Mint111", cached)

    config = TradingBotConfig(enable_anti_rug_filters=True)
    enricher = TokenEnricher(config=config, screening_cache=cache)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert verdict is cached


async def test_token_enricher_with_mock_api():
    mock_api = MagicMock(spec=PumpFunApiClient)
    mock_api.get_coin = AsyncMock(
        return_value={
            "mint": "Mint111",
            "name": "TestToken",
            "creator": "Creator111",
            "creatorHoldingPct": 0.05,
            "holders": [
                {"address": "Holder1", "amount": 100_000},
                {"address": "Holder2", "amount": 50_000},
            ],
            "totalSupply": 1_000_000_000,
        }
    )
    mock_api.get_creator_coins = AsyncMock(
        return_value=[
            {"mint": "Past1", "created_timestamp": 1_000_000_000_000},
        ]
    )

    config = TradingBotConfig(
        enable_anti_rug_filters=True, max_acceptable_risk_score=50.0
    )
    enricher = TokenEnricher(api_client=mock_api, config=config)
    verdict = await enricher.enrich_and_screen("Mint111")
    assert isinstance(verdict, TokenScreeningVerdict)
    assert verdict.passed


def test_status_persistence_manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_path = os.path.join(tmpdir, "bot_status.json")
        audit_path = os.path.join(tmpdir, "audit.jsonl")

        pm = StatusPersistenceManager(
            bot_status_path=status_path,
            audit_log_path=audit_path,
        )

        snapshot_data = {
            "state": "RUNNING",
            "active_positions": {"Mint1": {"name": "SolCat", "entry_market_cap": 30.0}},
        }

        success = pm.write_status_snapshot(snapshot_data)
        assert success
        assert os.path.exists(status_path)

        loaded = pm.load_status_snapshot()
        assert loaded is not None
        assert loaded["state"] == "RUNNING"
        assert "Mint1" in loaded["active_positions"]

        pm.write_audit_record("test_event", "RUNNING", {"msg": "hello"})
        pm.close()

        with open(audit_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
            assert len(lines) == 1
            assert lines[0]["type"] == "test_event"
            assert lines[0]["payload"]["msg"] == "hello"


def test_status_persistence_manager_missing_files():
    pm = StatusPersistenceManager(bot_status_path=None, audit_log_path=None)
    assert not pm.write_status_snapshot({"test": 1})
    assert pm.load_status_snapshot() is None
    pm.write_audit_record("test", "IDLE", {})
    pm.close()


def test_alert_dispatcher_configuration():
    # None provider
    disp_none = AlertDispatcher(provider="none")
    assert not disp_none.enabled
    assert not disp_none.send_alert("test")

    # Discord missing URL
    disp_discord_missing = AlertDispatcher(provider="discord", discord_webhook_url=None)
    assert not disp_discord_missing.enabled

    # Discord configured
    disp_discord = AlertDispatcher(
        provider="discord", discord_webhook_url="https://discord.com/webhook"
    )
    assert disp_discord.enabled

    # Slack configured
    disp_slack = AlertDispatcher(
        provider="slack", slack_webhook_url="https://slack.com/webhook"
    )
    assert disp_slack.enabled

    # Telegram configured
    disp_tg = AlertDispatcher(
        provider="telegram", telegram_bot_token="tok123", telegram_chat_id="chat123"
    )
    assert disp_tg.enabled


def test_alert_dispatcher_send_mocked():
    disp = AlertDispatcher(
        provider="discord", discord_webhook_url="https://discord.com/api/webhooks/test"
    )
    with patch("urllib.request.urlopen") as mock_urlopen:
        sent = disp.send_alert("Trade executed: SolCat buy @ 0.1 SOL")
        assert sent
        assert mock_urlopen.called

    # Test error isolation (should return False, not raise)
    with patch("urllib.request.urlopen", side_effect=OSError("Network down")):
        sent = disp.send_alert("Trade executed: SolCat sell")
        assert not sent
