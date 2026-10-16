"""Unit tests for ``bot/alerts.py``."""

from __future__ import annotations

from unittest.mock import patch

from pumpfun_trading.bot.alerts import AlertDispatcher


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
