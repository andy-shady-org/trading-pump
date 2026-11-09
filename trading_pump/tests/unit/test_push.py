"""Unit tests for ``push.py``: the vault push feed beside the poller (FEAT-174)."""

from __future__ import annotations

import base64
import logging
import struct
from typing import Any

import pytest

from trading_pump.config.settings import PushSettings
from trading_pump.push import (
    ACCOUNT_NOTIFICATION,
    VAULT_PUSH_EVENT,
    VaultPushFeed,
    account_amount,
)
from trading_pump.tests.support.constants import SAMPLE_MINT


class FakeSocket:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.error = error

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(message)


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _feed(**settings: Any) -> tuple[VaultPushFeed, list[dict[str, Any]], Clock, list]:
    rows: list[dict[str, Any]] = []
    states: list[tuple[bool, str]] = []
    clock = Clock()
    feed = VaultPushFeed(
        connect_url=lambda: "wss://rpc.example/?api-key=SECRET",
        stream_url="wss://rpc.example",
        settings=PushSettings(enabled=True, **settings),
        record=rows.append,
        clock=clock,
        on_state=lambda connected, detail: states.append((connected, detail)),
    )
    return feed, rows, clock, states


def _token_account(amount: int) -> list[str]:
    raw = bytes(64) + struct.pack("<Q", amount) + bytes(93)
    return [base64.b64encode(raw).decode(), "base64"]


def _push(subscription: int, amount: int, slot: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": ACCOUNT_NOTIFICATION,
        "params": {
            "subscription": subscription,
            "result": {
                "context": {"slot": slot},
                "value": {"data": _token_account(amount), "owner": "Token"},
            },
        },
    }


def test_account_amount_reads_a_token_account() -> None:
    assert account_amount({"data": _token_account(1234)}) == 1234
    assert account_amount({}) is None
    assert account_amount({"data": ["!!", "base64"]}) is None
    assert account_amount({"data": [base64.b64encode(b"short").decode()]}) is None


async def test_a_watched_pool_is_subscribed_and_its_pushes_are_rows() -> None:
    feed, rows, clock, states = _feed()
    assert feed.watch(
        SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation"
    )
    assert not feed.watch(
        SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation"
    )
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    assert states == [(True, "")] and feed.connected
    assert [m["params"] for m in ws.sent] == [
        ["BaseV", {"encoding": "base64", "commitment": "processed"}],
        ["QuoteV", {"encoding": "base64", "commitment": "processed"}],
    ]
    base_id, quote_id = ws.sent[0]["id"], ws.sent[1]["id"]
    await feed.on_stream_message({"jsonrpc": "2.0", "id": base_id, "result": 11}, ws)
    await feed.on_stream_message({"jsonrpc": "2.0", "id": quote_id, "result": 12}, ws)
    clock.now = 1001.5
    await feed.on_stream_message(_push(12, 85_000_000_000, 400), ws)
    assert rows == [
        {
            "timestamp": 1001.5,
            "event": VAULT_PUSH_EVENT,
            "mint": SAMPLE_MINT,
            "source": "graduation",
            "side": "quote",
            "vault": "QuoteV",
            "amount": 85_000_000_000,
            "slot": 400,
        }
    ]
    assert feed.stats["subscribed"] == 2 and feed.stats["pushes"] == 1
    assert feed.status_text() == "connected · 1 pools · 1 pushes"


async def test_the_window_ends_with_an_unsubscribe() -> None:
    feed, rows, clock, _ = _feed(seconds=300.0)
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    await feed.on_stream_message({"id": ws.sent[0]["id"], "result": 11}, ws)
    clock.now = 1290.0
    await feed.flush()
    unsubscribes = [m for m in ws.sent if m["method"] == "accountUnsubscribe"]
    assert [m["params"] for m in unsubscribes] == [[11]]
    assert feed.watches == {} and feed.mints == set()
    assert feed.stats["ended"] == 2
    await feed.on_stream_message(_push(11, 5, 401), ws)
    assert rows == [] and feed.stats["unknown_pushes"] == 1


def test_a_pool_past_its_window_or_beyond_the_list_is_not_followed() -> None:
    feed, _, clock, _ = _feed(seconds=300.0, max_vaults=2)
    assert not feed.watch("Late", ("A", "B"), migrated_at=600.0, source="graduation")
    assert feed.watch("First", ("A", "B"), migrated_at=990.0, source="graduation")
    assert not feed.watch("Second", ("C", "D"), migrated_at=990.0, source="new_pool")
    assert feed.stats == {"too_late": 1, "followed": 1, "list_full": 1}


async def test_nothing_is_sent_while_disconnected_and_a_reconnect_resubscribes() -> (
    None
):
    feed, _, _, states = _feed()
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    await feed.flush(now=1000.0)  # no socket yet: kept for the connect
    first = FakeSocket()
    await feed.on_stream_connected(first)
    await feed.on_stream_message({"id": first.sent[0]["id"], "result": 11}, first)
    feed.on_stream_ended()
    assert feed.ws is None and states[-1] == (False, "connection closed")
    second = FakeSocket()
    await feed.on_stream_connected(second)
    assert [m["params"][0] for m in second.sent] == ["BaseV", "QuoteV"]
    assert all(entry.subscription is None for entry in feed.watches.values())


async def test_replies_that_are_not_ours_or_refused_are_counted() -> None:
    feed, rows, _, _ = _feed()
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    await feed.on_stream_message({"id": 999, "result": 5}, ws)  # not ours
    await feed.on_stream_message({"id": "x", "result": 5}, ws)
    await feed.on_stream_message(
        {"id": ws.sent[0]["id"], "error": {"code": -32602}}, ws
    )
    await feed.on_stream_message({"id": ws.sent[1]["id"], "result": True}, ws)
    await feed.on_stream_message("not a dict", ws)
    await feed.on_stream_message({"method": ACCOUNT_NOTIFICATION}, ws)
    await feed.on_stream_message(
        {"method": ACCOUNT_NOTIFICATION, "params": {"subscription": "x"}}, ws
    )
    await feed.on_stream_message({"method": "slotNotification"}, ws)
    assert feed.stats["subscribe_refused"] == 2
    assert feed.stats["unknown_pushes"] == 2 and rows == []


async def test_a_reply_for_a_vault_that_ended_meanwhile_is_refused() -> None:
    feed, _, clock, _ = _feed(seconds=300.0)
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    clock.now = 1300.0
    await feed.flush()
    await feed.on_stream_message({"id": ws.sent[0]["id"], "result": 11}, ws)
    assert feed.stats["subscribe_refused"] == 1


async def test_a_queued_vault_that_ended_before_its_send_is_skipped() -> None:
    feed, _, clock, _ = _feed(seconds=300.0)
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    feed.ws = FakeSocket()
    feed.watches.pop("QuoteV")
    await feed.flush(now=1000.0)
    assert [m["params"][0] for m in feed.ws.sent] == ["BaseV"]


async def test_maintain_flushes_until_stopped_and_survives_a_failed_send() -> None:
    feed, _, _, _ = _feed(flush_interval_seconds=0.25)
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    feed.ws = FakeSocket(error=ConnectionResetError("closing"))
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    stops = iter([False, False, True])
    await feed.maintain(lambda: next(stops), sleep)
    assert pauses == [0.25, 0.25] and feed.stats["flush_errors"] == 2
    assert feed._queued == ["BaseV", "QuoteV"]  # kept to be sent again


async def test_maintain_uses_asyncio_sleep_by_default(monkeypatch) -> None:
    feed, _, _, _ = _feed()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("trading_pump.push.asyncio.sleep", fake_sleep)
    stops = iter([False, True])
    await feed.maintain(lambda: next(stops))
    assert slept == [0.5]


def test_the_stream_hooks_report_state_and_redact(caplog) -> None:
    feed, _, _, states = _feed()
    assert feed.stream_connect_url().endswith("SECRET")
    with caplog.at_level(logging.INFO, logger="trading_pump.push"):
        feed.on_stream_error("No WebSocket message for 1800s")
        feed.on_stream_exception(
            RuntimeError("wss://rpc.example/?api-key=SECRET refused"), 2.0
        )
        feed.connected = True
        feed.on_stream_closed()
        feed.on_stream_closed()
        feed.stream_log("hello")
    assert "SECRET" not in caplog.text and "SECRET" not in states[1][1]
    assert [connected for connected, _ in states] == [False, False, False]
    assert feed.status_text().startswith("disconnected")
    assert not feed.stream_stop_requested()
    feed.stop()
    assert feed.stream_stop_requested()


def test_a_feed_without_a_state_callback_still_tracks_its_state() -> None:
    feed = VaultPushFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=PushSettings(),
        record=lambda row: None,
    )
    feed.connected = True
    feed.on_stream_ended()
    assert not feed.connected


async def test_the_feed_runs_the_shared_websocket_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed, *_ = _feed()
    ran: list[Any] = []

    async def fake_run(host: Any) -> None:
        ran.append(host)

    monkeypatch.setattr("trading_pump.push.run_websocket_stream", fake_run)
    await feed.run()
    assert ran == [feed]


async def test_a_failed_unsubscribe_is_sent_again() -> None:
    feed, _, clock, _ = _feed(seconds=300.0)
    feed.watch(SAMPLE_MINT, ("BaseV", "QuoteV"), migrated_at=990.0, source="graduation")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    await feed.on_stream_message({"id": ws.sent[0]["id"], "result": 11}, ws)
    clock.now = 1300.0
    ws.error = ConnectionResetError("closing")
    with pytest.raises(ConnectionResetError):
        await feed.flush()
    assert feed._ending == [11]
    ws.error = None
    await feed.flush()
    assert feed._ending == [] and ws.sent[-1]["params"] == [11]
