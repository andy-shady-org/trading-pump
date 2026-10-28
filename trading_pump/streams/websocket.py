"""PumpPortal WebSocket transport: connect, read, back off and reconnect.

The module's feed (``trading_pump/feed.py``) owns what a connection *means*
(health state, subscriptions, message routing); this module owns the
transport loop, the subscription wire format and how the PumpPortal API key
is attached to the URL, so stream ingestion stays inside ``streams/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

NEW_TOKEN_SUBSCRIPTION: dict[str, Any] = {"method": "subscribeNewToken"}
# Free like the create feed (not metered): curve-to-PumpSwap migrations.
MIGRATION_SUBSCRIPTION: dict[str, Any] = {"method": "subscribeMigration"}
MIGRATION_TX_TYPES = frozenset({"migrate", "migration"})
MAX_RECONNECT_BACKOFF_SECONDS = 30.0


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


async def send_ws_message(
    ws: Any, message: dict[str, Any], *, prefer_raw_send: bool = False
) -> None:
    """Send a JSON message on an aiohttp socket or a `websockets`-style client.

    `prefer_raw_send` tries a plain `send(str)` first for clients that are not
    aiohttp sockets (the order the per-mint trade subscriptions have always
    used); otherwise `send_json`, then `send_str`, then `send`.
    """
    if (
        prefer_raw_send
        and hasattr(ws, "send")
        and not isinstance(ws, aiohttp.ClientWebSocketResponse)
    ):
        await ws.send(json.dumps(message))
    elif hasattr(ws, "send_json"):
        await ws.send_json(message)
    elif hasattr(ws, "send_str"):
        await ws.send_str(json.dumps(message))
    elif hasattr(ws, "send"):
        await ws.send(json.dumps(message))


class WebSocketStreamHost(Protocol):
    """What the transport loop needs from the runtime.

    Optional attributes (read with ``getattr``): ``stream_heartbeat_seconds``
    (ping interval; aiohttp closes the socket when a pong does not come back
    within half of it; ``None`` = no pings) and ``stream_idle_timeout_seconds``
    (reconnect when no message arrives for that long, ``None`` = wait for
    ever), both BUG-150.
    """

    stream_url: str
    reconnect_delay_seconds: float

    def stream_stop_requested(self) -> bool: ...

    def stream_connect_url(self) -> str: ...

    def stream_log(self, message: str, level: int = logging.INFO) -> None: ...

    async def on_stream_connected(self, ws: Any) -> None: ...

    async def on_stream_message(self, data: Any, ws: Any) -> None: ...

    def on_stream_error(self, message: str) -> None: ...

    def on_stream_exception(self, exc: Exception, backoff: float) -> None: ...

    def on_stream_ended(self) -> None: ...

    def on_stream_closed(self) -> None: ...


async def _next_message(messages: Any, idle_timeout: float | None) -> Any:
    """The socket's next message; ``TimeoutError`` after ``idle_timeout`` seconds."""
    if idle_timeout is None or idle_timeout <= 0:
        return await messages.__anext__()
    return await asyncio.wait_for(messages.__anext__(), timeout=idle_timeout)


async def run_websocket_stream(host: WebSocketStreamHost) -> None:
    """Connect to `host.stream_url` and feed decoded messages until stopped.

    Reconnects with exponential backoff (doubling, capped at 30 s) after an
    error or a remote close; the backoff resets once a connection is up.
    The socket is pinged every ``stream_heartbeat_seconds``, and a socket
    that delivers nothing for ``stream_idle_timeout_seconds`` is dropped and
    reconnected: a half-open connection used to wait for ever (BUG-150).
    """
    backoff = host.reconnect_delay_seconds
    heartbeat = getattr(host, "stream_heartbeat_seconds", None)
    idle_timeout = getattr(host, "stream_idle_timeout_seconds", None)
    connect_kwargs: dict[str, Any] = {"heartbeat": heartbeat} if heartbeat else {}
    while not host.stream_stop_requested():
        try:
            host.stream_log(f"Connecting to WebSocket stream at {host.stream_url}...")
            timeout = aiohttp.ClientTimeout(total=None, sock_read=60.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(
                    host.stream_connect_url(), **connect_kwargs
                ) as ws:
                    await host.on_stream_connected(ws)
                    backoff = host.reconnect_delay_seconds
                    messages = ws.__aiter__()
                    while True:
                        try:
                            msg = await _next_message(messages, idle_timeout)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            host.on_stream_error(
                                f"No WebSocket message for {idle_timeout:g}s: the "
                                "connection is stale; reconnecting"
                            )
                            break
                        if host.stream_stop_requested():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except json.JSONDecodeError:
                                continue
                            await host.on_stream_message(data, ws)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            host.on_stream_error(
                                f"WebSocket connection error: {ws.exception()}"
                            )
                            break
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            host.stream_log(
                                "WebSocket connection closed by remote server.",
                                level=logging.INFO,
                            )
                            break
        except asyncio.CancelledError:
            break
        except ConnectionResetError as exc:
            # "Cannot write to closing transport": the server closed the
            # socket while a subscription was being sent. A disconnect, not a
            # fault; reconnect like a remote close (BUG-150).
            host.stream_log(
                f"WebSocket closed while sending ({exc}); reconnecting.",
                level=logging.INFO,
            )
            if not host.stream_stop_requested():
                host.on_stream_ended()
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2.0, MAX_RECONNECT_BACKOFF_SECONDS)
        except Exception as exc:
            host.on_stream_exception(exc, backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                break
            backoff = min(backoff * 2.0, MAX_RECONNECT_BACKOFF_SECONDS)
        else:
            if not host.stream_stop_requested():
                host.on_stream_ended()
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    break
                backoff = min(backoff * 2.0, MAX_RECONNECT_BACKOFF_SECONDS)
        finally:
            host.on_stream_closed()
