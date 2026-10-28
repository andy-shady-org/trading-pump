"""Tests for the PumpPortal WebSocket transport (`streams/websocket.py`)."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from trading_pump.streams import websocket as ws_module
from trading_pump.streams.websocket import (
    MIGRATION_SUBSCRIPTION,
    MIGRATION_TX_TYPES,
    NEW_TOKEN_SUBSCRIPTION,
    run_websocket_stream,
    send_ws_message,
    split_stream_api_key,
    stream_connect_url,
    stream_url_has_api_key,
    token_trade_message,
)


class RecordingHost:
    """A `WebSocketStreamHost` that records every hook call."""

    def __init__(self, *, stop_after_connections: int = 1) -> None:
        self.stream_url = "wss://example.invalid/api/data"
        self.reconnect_delay_seconds = 1.0
        self.calls: list[tuple[str, Any]] = []
        self.messages: list[Any] = []
        self.connections = 0
        self.closed = 0
        self._stop_after = stop_after_connections

    def stream_stop_requested(self) -> bool:
        return self.closed >= self._stop_after

    def stream_connect_url(self) -> str:
        return self.stream_url + "?api-key=secret"

    def stream_log(self, message: str, level: int = logging.INFO) -> None:
        self.calls.append(("log", message))

    async def on_stream_connected(self, ws: Any) -> None:
        self.connections += 1
        self.calls.append(("connected", ws))

    async def on_stream_message(self, data: Any, ws: Any) -> None:
        self.messages.append(data)

    def on_stream_error(self, message: str) -> None:
        self.calls.append(("error", message))

    def on_stream_exception(self, exc: Exception, backoff: float) -> None:
        self.calls.append(("exception", backoff))

    def on_stream_ended(self) -> None:
        self.calls.append(("ended", None))

    def on_stream_closed(self) -> None:
        self.closed += 1


class FakeSocket:
    def __init__(self, messages: list[Any]) -> None:
        self._messages = list(messages)

    def __aiter__(self) -> FakeSocket:
        return self

    async def __anext__(self) -> Any:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    def exception(self) -> str:
        return "boom"

    async def __aenter__(self) -> FakeSocket:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _session_for(*sockets: FakeSocket) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.ws_connect = MagicMock(side_effect=list(sockets))
    return session


def _text(payload: Any) -> SimpleNamespace:
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(payload))


def test_token_trade_message_shape() -> None:
    assert token_trade_message("subscribeTokenTrade", "MINT") == {
        "method": "subscribeTokenTrade",
        "keys": ["MINT"],
    }
    assert NEW_TOKEN_SUBSCRIPTION == {"method": "subscribeNewToken"}
    # Free (not metered) like the create feed; carries graduations (BUG-123).
    assert MIGRATION_SUBSCRIPTION == {"method": "subscribeMigration"}
    assert "migrate" in MIGRATION_TX_TYPES


async def test_send_prefers_send_json_unless_raw_send_requested() -> None:
    ws = SimpleNamespace(send=AsyncMock(), send_json=AsyncMock())
    await send_ws_message(ws, {"a": 1})
    ws.send_json.assert_awaited_once_with({"a": 1})
    ws.send.assert_not_awaited()

    await send_ws_message(ws, {"a": 2}, prefer_raw_send=True)
    ws.send.assert_awaited_once_with(json.dumps({"a": 2}))


async def test_send_falls_back_to_send_str_then_send() -> None:
    str_ws = SimpleNamespace(send_str=AsyncMock())
    await send_ws_message(str_ws, {"b": 1})
    str_ws.send_str.assert_awaited_once_with(json.dumps({"b": 1}))

    raw_ws = SimpleNamespace(send=AsyncMock())
    await send_ws_message(raw_ws, {"c": 1})
    raw_ws.send.assert_awaited_once_with(json.dumps({"c": 1}))

    await send_ws_message(SimpleNamespace(), {"d": 1})  # nothing to send on


async def test_send_never_uses_raw_send_on_aiohttp_socket() -> None:
    ws = MagicMock(spec=aiohttp.ClientWebSocketResponse)
    ws.send_json = AsyncMock()
    await send_ws_message(ws, {"e": 1}, prefer_raw_send=True)
    ws.send_json.assert_awaited_once_with({"e": 1})


async def test_stream_decodes_text_and_skips_bad_json() -> None:
    host = RecordingHost()
    socket = FakeSocket(
        [
            _text({"mint": "A"}),
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data="{not json"),
            SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=b"x"),
            _text({"mint": "B"}),
            SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=None),
            _text({"mint": "never"}),
        ]
    )
    session = _session_for(socket)
    with patch.object(ws_module.aiohttp, "ClientSession", return_value=session):
        await run_websocket_stream(host)

    assert host.messages == [{"mint": "A"}, {"mint": "B"}]
    session.ws_connect.assert_called_once_with(host.stream_connect_url())
    # The key-bearing URL is only used to connect, never logged.
    assert all("secret" not in str(arg) for _, arg in host.calls)
    assert ("log", "WebSocket connection closed by remote server.") in host.calls


async def test_stream_error_message_reports_and_reconnects_with_backoff() -> None:
    host = RecordingHost(stop_after_connections=2)
    first = FakeSocket([SimpleNamespace(type=aiohttp.WSMsgType.ERROR, data=None)])
    second = FakeSocket([])
    session = _session_for(first, second)
    sleep = AsyncMock()
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(ws_module.asyncio, "sleep", sleep),
    ):
        await run_websocket_stream(host)

    assert ("error", "WebSocket connection error: boom") in host.calls
    assert host.calls.count(("ended", None)) == 2
    assert host.connections == 2
    # A successful connect resets the backoff, so both waits are the base delay.
    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 1.0]


async def test_stream_exception_doubles_backoff_up_to_cap() -> None:
    host = RecordingHost(stop_after_connections=7)
    host.reconnect_delay_seconds = 8.0
    session = MagicMock()
    session.__aenter__ = AsyncMock(side_effect=OSError("refused"))
    session.__aexit__ = AsyncMock(return_value=None)
    sleep = AsyncMock()
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(ws_module.asyncio, "sleep", sleep),
    ):
        await run_websocket_stream(host)

    backoffs = [arg for name, arg in host.calls if name == "exception"]
    assert backoffs == [8.0, 16.0, 30.0, 30.0, 30.0, 30.0, 30.0]
    assert host.connections == 0


async def test_stream_stops_on_cancel_during_backoff() -> None:
    host = RecordingHost(stop_after_connections=99)
    session = MagicMock()
    session.__aenter__ = AsyncMock(side_effect=OSError("refused"))
    session.__aexit__ = AsyncMock(return_value=None)
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(
            ws_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
        ),
    ):
        await run_websocket_stream(host)
    assert host.closed == 1


async def test_stream_stops_on_cancel_while_connected_and_after_remote_close() -> None:
    host = RecordingHost(stop_after_connections=99)
    session = MagicMock()
    session.__aenter__ = AsyncMock(side_effect=asyncio.CancelledError)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch.object(ws_module.aiohttp, "ClientSession", return_value=session):
        await run_websocket_stream(host)
    assert host.closed == 1

    host = RecordingHost(stop_after_connections=99)
    session = _session_for(FakeSocket([]))
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(
            ws_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
        ),
    ):
        await run_websocket_stream(host)
    assert host.calls.count(("ended", None)) == 1
    assert host.closed == 1


async def test_stop_request_between_messages_ends_without_reconnect() -> None:
    host = RecordingHost()

    async def stop_on_first(data: Any, ws: Any) -> None:
        host.messages.append(data)
        host._stop_after = 0

    host.on_stream_message = stop_on_first
    session = _session_for(FakeSocket([_text({"n": 1}), _text({"n": 2})]))
    with patch.object(ws_module.aiohttp, "ClientSession", return_value=session):
        await run_websocket_stream(host)
    assert host.messages == [{"n": 1}]
    assert ("ended", None) not in host.calls


class SilentSocket(FakeSocket):
    """Delivers its messages, then nothing: a half-open connection."""

    async def __anext__(self) -> Any:
        if self._messages:
            return self._messages.pop(0)
        await asyncio.Event().wait()  # never set
        raise AssertionError("unreachable")


@pytest.mark.regression("BUG-150")
async def test_silent_stream_is_dropped_and_reconnected() -> None:
    # The archived rc.5 run sat on a half-open PumpPortal socket for ~3 h:
    # `async for msg in ws` waited for ever and only a restart helped.
    host = RecordingHost(stop_after_connections=2)
    host.stream_heartbeat_seconds = 20.0  # type: ignore[attr-defined]
    host.stream_idle_timeout_seconds = 0.05  # type: ignore[attr-defined]
    session = _session_for(SilentSocket([_text({"mint": "A"})]), FakeSocket([]))
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(ws_module.asyncio, "sleep", AsyncMock()),
    ):
        await asyncio.wait_for(run_websocket_stream(host), timeout=5.0)

    assert host.messages == [{"mint": "A"}]
    assert host.connections == 2
    errors = [arg for name, arg in host.calls if name == "error"]
    assert errors == [
        "No WebSocket message for 0.05s: the connection is stale; reconnecting"
    ]
    # The socket is pinged, so a dead peer is also noticed between messages.
    for call in session.ws_connect.call_args_list:
        assert call.kwargs == {"heartbeat": 20.0}


@pytest.mark.regression("BUG-150")
async def test_write_to_a_closing_socket_reconnects_quietly() -> None:
    host = RecordingHost(stop_after_connections=2)
    calls = 0

    async def send_fails(data: Any, ws: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError("Cannot write to closing transport")

    host.on_stream_message = send_fails
    session = _session_for(FakeSocket([_text({"n": 1})]), FakeSocket([]))
    sleep = AsyncMock()
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(ws_module.asyncio, "sleep", sleep),
    ):
        await run_websocket_stream(host)

    assert host.connections == 2
    assert ("exception", 1.0) not in host.calls  # not reported as a fault
    assert (
        "log",
        "WebSocket closed while sending (Cannot write to closing transport); "
        "reconnecting.",
    ) in host.calls
    assert host.calls.count(("ended", None)) == 2
    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 1.0]


@pytest.mark.regression("BUG-150")
async def test_closing_socket_after_a_stop_request_does_not_reconnect() -> None:
    host = RecordingHost(stop_after_connections=99)

    async def stop_and_fail(data: Any, ws: Any) -> None:
        host._stop_after = 0
        raise ConnectionResetError("Cannot write to closing transport")

    host.on_stream_message = stop_and_fail
    session = _session_for(FakeSocket([_text({"n": 1})]))
    with patch.object(ws_module.aiohttp, "ClientSession", return_value=session):
        await run_websocket_stream(host)
    assert ("ended", None) not in host.calls

    # Cancelled during the reconnect wait after a reset: stops cleanly.
    host = RecordingHost(stop_after_connections=99)

    async def fail(data: Any, ws: Any) -> None:
        raise ConnectionResetError("closing")

    host.on_stream_message = fail
    session = _session_for(FakeSocket([_text({"n": 1})]))
    with (
        patch.object(ws_module.aiohttp, "ClientSession", return_value=session),
        patch.object(
            ws_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
        ),
    ):
        await run_websocket_stream(host)
    assert host.closed == 1


# --- the PumpPortal API key in the URL (moved from bot/trade_feed.py) ---------


@pytest.mark.regression("BUG-117")
@pytest.mark.parametrize(
    "url, expected",
    [
        ("wss://pumpportal.fun/api/data?api-key=abc", True),
        ("wss://pumpportal.fun/api/data?api_key=abc", True),
        ("wss://pumpportal.fun/api/data?api-key=", False),
        ("wss://pumpportal.fun/api/data", False),
        ("wss://other.test/feed?api-key=abc", None),
        (None, None),
        ("http://[::1", None),
    ],
)
def test_stream_url_has_api_key(url: str | None, expected: bool | None) -> None:
    assert stream_url_has_api_key(url) is expected


@pytest.mark.regression("BUG-118")
@pytest.mark.parametrize(
    "url, clean, key",
    [
        (
            "wss://pumpportal.fun/api/data?api-key=abc",
            "wss://pumpportal.fun/api/data",
            "abc",
        ),
        (
            "wss://pumpportal.fun/api/data?x=1&api_key=abc",
            "wss://pumpportal.fun/api/data?x=1",
            "abc",
        ),
        (
            "wss://pumpportal.fun/api/data?api-key=",
            "wss://pumpportal.fun/api/data",
            None,
        ),
        ("wss://pumpportal.fun/api/data", "wss://pumpportal.fun/api/data", None),
        (
            "wss://other.test/feed?api-key=abc",
            "wss://other.test/feed?api-key=abc",
            None,
        ),
        (None, "", None),
        ("http://[::1", "http://[::1", None),
    ],
)
def test_split_stream_api_key(url: str | None, clean: str, key: str | None) -> None:
    assert split_stream_api_key(url) == (clean, key)


@pytest.mark.regression("BUG-118")
@pytest.mark.parametrize(
    "url, api_key, expected",
    [
        (
            "wss://pumpportal.fun/api/data",
            "k1",
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        # The separate key wins over one left in the URL.
        (
            "wss://pumpportal.fun/api/data?api-key=old",
            "k1",
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        (
            "wss://pumpportal.fun/api/data?api-key=old",
            None,
            "wss://pumpportal.fun/api/data?api-key=old",
        ),
        ("wss://pumpportal.fun/api/data", " ", "wss://pumpportal.fun/api/data"),
        # The PumpPortal key is never sent to another provider.
        ("wss://other.test/feed", "k1", "wss://other.test/feed"),
    ],
)
def test_stream_connect_url(url: str, api_key: str | None, expected: str) -> None:
    assert stream_connect_url(url, api_key) == expected


def test_a_pumpportal_url_with_other_parameters_only_keeps_them() -> None:
    url = "wss://pumpportal.fun/api/data?x=1"
    assert split_stream_api_key(url) == (url, None)
