"""PumpPortal's WebSocket: its subscriptions and how its API key is attached.

The module's feed (``trading_pump/feed.py``) owns what a connection *means*
(health state, subscriptions, message routing); this module owns
PumpPortal's subscription wire format and how its API key is attached to
the URL (BUG-117, BUG-118). The transport loop (connect, read, back off,
reconnect, pings and the idle reconnect of BUG-150) is trading-core's
``trading_core.ops.stream`` since 0.5.0 (FEAT-110): ``run_websocket_stream``,
``WebSocketStreamHost`` and ``send_ws_message`` moved there unchanged.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

NEW_TOKEN_SUBSCRIPTION: dict[str, Any] = {"method": "subscribeNewToken"}
# Free like the create feed (not metered): curve-to-PumpSwap migrations.
MIGRATION_SUBSCRIPTION: dict[str, Any] = {"method": "subscribeMigration"}
MIGRATION_TX_TYPES = frozenset({"migrate", "migration"})


def _is_api_key_param(name: str) -> bool:
    return name.lower().replace("_", "-") == "api-key"


def _is_pumpportal(parts: Any) -> bool:
    return (parts.hostname or "").endswith("pumpportal.fun")


def stream_url_has_api_key(url: str | None) -> bool | None:
    """Whether a PumpPortal stream URL carries ``api-key``; None for other hosts."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    if not _is_pumpportal(parts):
        return None
    return any(
        _is_api_key_param(key) and bool(value) for key, value in parse_qsl(parts.query)
    )


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


def token_trade_message(method: str, mint: str) -> dict[str, Any]:
    """`subscribeTokenTrade` / `unsubscribeTokenTrade` payload for one mint."""
    return {"method": method, "keys": [mint]}
