"""Unit tests for ``bot/alerts.py``."""

from __future__ import annotations

from unittest.mock import patch

from trading_pump.bot.alerts import AlertDispatcher


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


async def test_alert_dispatcher_async_send():
    disp = AlertDispatcher(discord_webhook_url="https://discord.com/hook")
    with patch("urllib.request.urlopen") as mock_url:
        res = await disp.send_alert_async("Async alert test")
        assert res is True
        assert mock_url.called

    disp_disabled = AlertDispatcher(provider="none")
    assert await disp_disabled.send_alert_async("Disabled alert") is False


def test_alert_dispatcher_all_providers():
    from trading_pump.bot.alerts import AlertDispatcher

    # 1. None provider
    disp_none = AlertDispatcher(provider="none")
    assert disp_none.enabled is False
    assert disp_none.send_alert("hello") is False

    # 2. Unsupported provider
    disp_unsupported = AlertDispatcher(provider="unsupported_provider")
    assert disp_unsupported.enabled is False

    # 3. Discord missing URL vs with URL
    disp_disc_missing = AlertDispatcher(provider="discord", discord_webhook_url=None)
    assert disp_disc_missing.enabled is False

    disp_disc = AlertDispatcher(
        provider="discord", discord_webhook_url="https://discord.com/mock"
    )
    assert disp_disc.enabled is True
    assert disp_disc.send_alert("   ") is False  # empty message
    with patch("urllib.request.urlopen"):
        assert disp_disc.send_alert("Discord message") is True

    # 4. Slack missing URL vs with URL
    disp_slack_missing = AlertDispatcher(provider="slack", slack_webhook_url=None)
    assert disp_slack_missing.enabled is False

    disp_slack = AlertDispatcher(
        provider="slack", slack_webhook_url="https://slack.com/mock"
    )
    assert disp_slack.enabled is True
    with patch("urllib.request.urlopen"):
        assert disp_slack.send_alert("Slack message") is True

    # 5. Telegram missing tokens vs with tokens
    disp_tg_missing = AlertDispatcher(
        provider="telegram", telegram_bot_token=None, telegram_chat_id=None
    )
    assert disp_tg_missing.enabled is False

    disp_tg = AlertDispatcher(
        provider="telegram", telegram_bot_token="token123", telegram_chat_id="chat456"
    )
    assert disp_tg.enabled is True
    with patch("urllib.request.urlopen"):
        assert disp_tg.send_alert("Telegram message") is True

    # 6. Exception handling
    with patch("urllib.request.urlopen", side_effect=OSError("Network error")):
        assert disp_tg.send_alert("Fail message") is False
