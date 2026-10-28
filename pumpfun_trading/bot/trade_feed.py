"""Trade-feed circuit breaker for PumpPortal's ``subscribeTokenTrade``.

PumpPortal only serves per-token trade data to connections whose API key has a
linked wallet holding at least 0.02 SOL, metered at 0.01 SOL per 10,000
messages. When that wallet runs dry the server answers every subscription with
a mint-less ``message`` refusal and held positions go blind (BUG-112).

The breaker opens on the first refusal, blocks new buys while open, and closes
only on evidence that the feed works again: a "subscribed to keys"
confirmation or trade data for a subscribed mint. While open, the bot sends a
probe subscription every ``probe_interval_seconds`` so a top-up is noticed
without a restart. A connection that has already refused is not asked again:
a 0.02 SOL top-up at 15:49:16 UTC on 2026-10-26 was not accepted on the open
connection 65 s later (BUG-156), so the next probe reconnects instead and the
fresh connection subscribes again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PUMPPORTAL_PUBLIC_STREAM_URL = "wss://pumpportal.fun/api/data"

FUNDING_REQUIREMENT = (
    "PumpPortal needs the API key's linked wallet to hold at least 0.02 SOL at "
    "all times; only the balance above that pays for messages (0.01 SOL per "
    "10,000)"
)
# ``_last_status`` while the breaker is open (dashboard "Last status").
TRADE_FEED_REFUSED_STATUS = "degraded: token-trade subscription refused"


def stream_url_has_api_key(url: str | None) -> bool | None:
    """Whether a PumpPortal stream URL carries ``api-key``; None for other hosts."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    if not (parts.hostname or "").endswith("pumpportal.fun"):
        return None
    return any(
        _is_api_key_param(key) and bool(value) for key, value in parse_qsl(parts.query)
    )


def _is_api_key_param(name: str) -> bool:
    return name.lower().replace("_", "-") == "api-key"


def _is_pumpportal(parts: Any) -> bool:
    return (parts.hostname or "").endswith("pumpportal.fun")


def split_stream_api_key(url: str | None) -> tuple[str, str | None]:
    """Splits ``api-key`` out of a PumpPortal stream URL (BUG-118).

    Returns the URL without the key, which is safe to display, and the key (or
    None). Other hosts and unparseable URLs come back unchanged.
    """
    text = str(url or "")
    try:
        parts = urlsplit(text)
    except ValueError:
        return text, None
    if not _is_pumpportal(parts) or not parts.query:
        return text, None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = [value for name, value in pairs if _is_api_key_param(name)]
    if not keys:
        return text, None
    kept = [(name, value) for name, value in pairs if not _is_api_key_param(name)]
    clean = urlunsplit(parts._replace(query=urlencode(kept)))
    return clean, next((key for key in keys if key), None)


def stream_connect_url(url: str | None, api_key: str | None) -> str:
    """The URL to connect with: ``url`` plus ``api-key`` for PumpPortal hosts.

    The key is only ever added for ``pumpportal.fun``, so it never leaks to a
    different stream provider. Never log or display the result.
    """
    clean, embedded = split_stream_api_key(url)
    key = (api_key or "").strip() or embedded
    if not key:
        return clean
    parts = urlsplit(clean)
    if not _is_pumpportal(parts):
        return clean
    pairs = parse_qsl(parts.query, keep_blank_values=True) + [("api-key", key)]
    return urlunsplit(parts._replace(query=urlencode(pairs)))


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
    # A refusal arrived on the current connection, so the next probe
    # reconnects rather than asking it again (BUG-156).
    refused_on_connection: bool = False
    reconnects: int = 0

    @property
    def is_open(self) -> bool:
        return self.tripped_at is not None

    def record_refusal(self, text: str) -> bool:
        """Records a refusal; True when it opens the breaker."""
        self.refusals += 1
        self.last_refusal = text
        self.refused_on_connection = True
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

    def connection_opened(self) -> None:
        """A new stream connection: it has not refused anything yet."""
        self.refused_on_connection = False

    def wants_reconnect(self) -> bool:
        """Open, and the current connection has already refused (BUG-156)."""
        return self.is_open and self.refused_on_connection

    def start_reconnect(self) -> None:
        """Marks a reconnect as requested; the fresh connection probes at once."""
        self.reconnects += 1
        self.next_probe_at = self.clock() + max(0.0, float(self.probe_interval_seconds))

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
                "the bot connected to PumpPortal without an api-key: check "
                "that PUMPFUN_STREAM_API_KEY is exported"
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
            f"{FUNDING_REQUIREMENT}; top it up (or export a funded key as "
            "PUMPFUN_STREAM_API_KEY). New buys are blocked and held positions are "
            "priced from the curve only until a probe subscription succeeds; the "
            "bot reconnects every "
            f"{max(0.0, float(self.probe_interval_seconds)):g} s to pick up a "
            f"top-up, no restart needed. Server said: {self.last_refusal}"
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
            "reconnects": self.reconnects,
            "last_confirmed_at": self.last_confirmed_at,
            "next_probe_at": self.next_probe_at,
            "stream_has_api_key": self.stream_has_api_key,
            "likely_cause": self.likely_cause() if self.is_open else None,
            "last_refusal": self.last_refusal or None,
        }
