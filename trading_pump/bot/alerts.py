from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Dispatches webhook notifications across Discord, Slack, and Telegram with non-blocking error isolation."""

    def __init__(
        self,
        provider: Optional[str] = None,
        discord_webhook_url: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ) -> None:
        raw_provider = (
            provider
            if provider is not None
            else os.getenv("PUMPFUN_ALERT_PROVIDER", "none")
        )
        self.provider = (raw_provider or "none").lower().strip()
        self.discord_webhook_url = discord_webhook_url or os.getenv(
            "PUMPFUN_ALERT_DISCORD_WEBHOOK_URL"
        )
        self.slack_webhook_url = slack_webhook_url or os.getenv(
            "PUMPFUN_ALERT_SLACK_WEBHOOK_URL"
        )
        self.telegram_bot_token = telegram_bot_token or os.getenv(
            "PUMPFUN_ALERT_TELEGRAM_BOT_TOKEN"
        )
        self.telegram_chat_id = telegram_chat_id or os.getenv(
            "PUMPFUN_ALERT_TELEGRAM_CHAT_ID"
        )
        self.enabled = False

        self._configure()

    def _configure(self) -> None:
        if not self.provider or self.provider == "none":
            if self.discord_webhook_url:
                self.provider = "discord"
            elif self.slack_webhook_url:
                self.provider = "slack"
            elif self.telegram_bot_token and self.telegram_chat_id:
                self.provider = "telegram"
            else:
                self.enabled = False
                return

        if self.provider not in {"discord", "slack", "telegram"}:
            self.enabled = False
            logger.warning(
                "Unsupported alert provider '%s'. Supported providers: discord, slack, telegram, none.",
                self.provider,
            )
            return

        if self.provider == "discord" and not self.discord_webhook_url:
            self.enabled = False
            logger.warning(
                "PUMPFUN_ALERT_PROVIDER is set to 'discord' but webhook URL is missing."
            )
            return

        if self.provider == "slack" and not self.slack_webhook_url:
            self.enabled = False
            logger.warning(
                "PUMPFUN_ALERT_PROVIDER is set to 'slack' but webhook URL is missing."
            )
            return

        if self.provider == "telegram" and (
            not self.telegram_bot_token or not self.telegram_chat_id
        ):
            self.enabled = False
            logger.warning(
                "PUMPFUN_ALERT_PROVIDER is set to 'telegram' but token or chat ID is missing."
            )
            return

        self.enabled = True

    def send_alert(self, message: str) -> bool:
        """Sends an alert synchronously with defensive error isolation."""
        if not self.enabled:
            return False

        payload = message.strip()
        if not payload:
            return False

        try:
            if self.provider == "discord" and self.discord_webhook_url:
                request = urllib.request.Request(
                    self.discord_webhook_url,
                    data=json.dumps({"content": payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
                return True
            elif self.provider == "slack" and self.slack_webhook_url:
                request = urllib.request.Request(
                    self.slack_webhook_url,
                    data=json.dumps({"text": payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
                return True
            elif (
                self.provider == "telegram"
                and self.telegram_bot_token
                and self.telegram_chat_id
            ):
                request = urllib.request.Request(
                    f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                    data=json.dumps(
                        {"chat_id": self.telegram_chat_id, "text": payload}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10):
                    pass
                return True
        except Exception as exc:
            logger.warning("Failed to send alert via %s: %s", self.provider, exc)
            return False

        return False

    async def send_alert_async(self, message: str) -> bool:
        """Sends an alert asynchronously without blocking the event loop."""
        if not self.enabled:
            return False
        return await asyncio.to_thread(self.send_alert, message)
