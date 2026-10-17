"""Trade-feed circuit breaker for PumpPortal's ``subscribeTokenTrade``.

PumpPortal only serves per-token trade data to connections whose API key has a
linked wallet holding at least 0.02 SOL, metered at 0.01 SOL per 10,000
messages. When that wallet runs dry the server answers every subscription with
a mint-less ``message`` refusal and held positions go blind (BUG-112).

The breaker opens on the first refusal, blocks new buys while open, and closes
only on evidence that the feed works again: a "subscribed to keys"
confirmation or trade data for a subscribed mint. While open, the bot sends a
probe subscription every ``probe_interval_seconds`` so a top-up is noticed
without a restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit

PUMPPORTAL_PUBLIC_STREAM_URL = "wss://pumpportal.fun/api/data"

FUNDING_REQUIREMENT = (
    "PumpPortal needs the API key's linked wallet to hold at least 0.02 SOL "
    "(0.01 SOL per 10,000 messages)"
)


def stream_url_has_api_key(url: str | None) -> bool | None:
    """Whether a PumpPortal stream URL carries ``api-key``; None for other hosts."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    if not (parts.hostname or "").endswith("pumpportal.fun"):
        return None
    return any(
        key.lower().replace("_", "-") == "api-key" and bool(value)
        for key, value in parse_qsl(parts.query)
    )


def is_refusal(text: str) -> bool:
    """True for PumpPortal's refusal of a token-trade subscription."""
    lowered = text.lower()
    return "subscribetokentrade" in lowered and (
        "api key" in lowered or "only available" in lowered
    )


def is_confirmation(text: str) -> bool:
    """True for PumpPortal's "Successfully subscribed to keys." reply."""
    lowered = text.lower()
    return "subscribed to keys" in lowered and "unsubscribed" not in lowered


@dataclass
class TradeFeedBreaker:
    """Open while the stream refuses token-trade subscriptions."""

    probe_interval_seconds: float = 300.0
    clock: Callable[[], float] = field(default=time.time, repr=False)
    tripped_at: float | None = None
    trips: int = 0
    refusals: int = 0
    confirmations: int = 0
    trade_messages: int = 0
    send_failures: int = 0
    last_confirmed_at: float | None = None
    last_refusal: str = ""
    next_probe_at: float | None = None
    probe_mint: str | None = None
    confirmed_before_trip: bool = False
    stream_has_api_key: bool | None = None

    @property
    def is_open(self) -> bool:
        return self.tripped_at is not None

    def record_refusal(self, text: str) -> bool:
        """Records a refusal; True when it opens the breaker."""
        self.refusals += 1
        self.last_refusal = text
        now = self.clock()
        self.next_probe_at = now + max(0.0, float(self.probe_interval_seconds))
        if self.is_open:
            return False
        self.tripped_at = now
        self.trips += 1
        self.confirmed_before_trip = self.last_confirmed_at is not None
        return True

    def record_confirmation(self) -> bool:
        """Records a subscription confirmation; True when it closes the breaker."""
        self.confirmations += 1
        return self._close()

    def record_trade_data(self) -> bool:
        """Trade data proves delivery; True when it closes the breaker."""
        self.trade_messages += 1
        return self._close()

    def record_send_failure(self) -> None:
        self.send_failures += 1

    def _close(self) -> bool:
        self.last_confirmed_at = self.clock()
        if not self.is_open:
            return False
        self.tripped_at = None
        self.next_probe_at = None
        return True

    def probe_due(self) -> bool:
        return (
            self.is_open
            and self.next_probe_at is not None
            and self.clock() >= self.next_probe_at
        )

    def start_probe(self, mint: str | None) -> None:
        """Marks a probe as sent; ``mint`` is unsubscribed once it is answered."""
        self.probe_mint = mint
        self.next_probe_at = self.clock() + max(0.0, float(self.probe_interval_seconds))

    def take_probe_mint(self) -> str | None:
        mint, self.probe_mint = self.probe_mint, None
        return mint

    def likely_cause(self) -> str:
        if self.stream_has_api_key is False:
            return (
                "the stream URL the bot connected with carries no api-key: "
                "check that PUMPFUN_STREAM_URL is exported with ?api-key=… "
                "and that the config's stream_url does not override it"
            )
        if self.confirmed_before_trip:
            return (
                "the PumpPortal API key worked earlier in this run, so its "
                "linked wallet has probably run out of funds"
            )
        return (
            "the PumpPortal API key is missing, or its linked wallet is "
            "unfunded or has run out of funds"
        )

    def trip_message(self) -> str:
        return (
            "ALERT trade-feed circuit breaker OPEN: the stream refused a "
            f"token-trade subscription. Most likely {self.likely_cause()}. "
            f"{FUNDING_REQUIREMENT}; top it up (or add a funded API key to "
            "PUMPFUN_STREAM_URL). New buys are blocked and held positions are "
            "priced from the curve only until a probe subscription succeeds. "
            f"Server said: {self.last_refusal}"
        )

    def recovery_message(self) -> str:
        return (
            "trade-feed circuit breaker CLOSED: token-trade subscriptions are "
            "delivering again; new buys resume"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "open": self.is_open,
            "tripped_at": self.tripped_at,
            "trips": self.trips,
            "refusals": self.refusals,
            "confirmations": self.confirmations,
            "trade_messages": self.trade_messages,
            "send_failures": self.send_failures,
            "last_confirmed_at": self.last_confirmed_at,
            "next_probe_at": self.next_probe_at,
            "stream_has_api_key": self.stream_has_api_key,
            "likely_cause": self.likely_cause() if self.is_open else None,
            "last_refusal": self.last_refusal or None,
        }
