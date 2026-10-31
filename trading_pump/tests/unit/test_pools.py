"""Unit tests for ``pools.py``: the new-pool feed and watcher (FEAT-80).

Pool accounts are the mainnet canonical pool in ``tests/support/payloads.py``
(a Pump.fun graduation); the same bytes under another address are a pool
that is not canonical, as a hand-made pool of the same mint would be.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import pytest
from solders.pubkey import Pubkey

from trading_pump.config.settings import GraduationSettings, NewPoolSettings
from trading_pump.graduates import GraduateTracker
from trading_pump.market import NewPoolInfo
from trading_pump.pools import (
    POOL_SUBSCRIPTIONS,
    NewPoolFeed,
    NewPoolWatcher,
    is_canonical,
    pool_notice,
    sol_side,
)
from trading_pump.sdk.pumpswap import (
    POOL_BASE_MINT_OFFSET,
    POOL_QUOTE_MINT_OFFSET,
    decode_pool,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, WSOL_MINT
from trading_pump.tests.support.payloads import (
    GRADUATED_BASE_VAULT_ADDRESS,
    GRADUATED_MINT,
    GRADUATED_POOL,
    GRADUATED_POOL_B64,
    GRADUATED_QUOTE_VAULT_ADDRESS,
)

POOL_BYTES = base64.b64decode(GRADUATED_POOL_B64)
OTHER_POOL = "NewPoo1111111111111111111111111111111111111"


def _with(raw: bytes, offset: int, pubkey: str) -> bytes:
    return raw[:offset] + bytes(Pubkey.from_string(pubkey)) + raw[offset + 32 :]


def _notice(address: str, raw: bytes = POOL_BYTES, slot: int = 7) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "programNotification",
        "params": {
            "result": {
                "context": {"slot": slot},
                "value": {
                    "pubkey": address,
                    "account": {"data": [base64.b64encode(raw).decode(), "base64"]},
                },
            },
            "subscription": 1,
        },
    }


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (_notice(OTHER_POOL), (OTHER_POOL, POOL_BYTES, 7)),
        ({"jsonrpc": "2.0", "result": 123, "id": 1}, None),
        ({"method": "programNotification", "params": {}}, None),
        ({"method": "programNotification", "params": {"result": "x"}}, None),
        ("text", None),
    ],
)
def test_pool_notice(data: Any, expected: Any) -> None:
    assert pool_notice(data) == expected


def test_canonical_pools_are_told_apart() -> None:
    assert is_canonical(decode_pool(GRADUATED_POOL, POOL_BYTES))
    assert not is_canonical(decode_pool(OTHER_POOL, POOL_BYTES))
    broken = decode_pool(OTHER_POOL, POOL_BYTES)
    object.__setattr__(broken, "base_mint", "not-a-key")
    assert not is_canonical(broken)


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_json(self, message: Any) -> None:
        self.sent.append(message)


def _feed(**kwargs: Any) -> tuple[NewPoolFeed, list[tuple[str, int]], list[Any], list]:
    pools: list[tuple[str, int]] = []
    states: list[tuple[bool, str]] = []
    now = [1000.0]
    feed = NewPoolFeed(
        on_pool=lambda address, raw, slot: pools.append((address, slot)),
        connect_url=lambda: "wss://rpc.example/?api-key=SECRET",
        stream_url="wss://rpc.example",
        warmup_seconds=60.0,
        on_state=lambda connected, detail: states.append((connected, detail)),
        clock=lambda: now[0],
        **kwargs,
    )
    return feed, pools, states, now


async def test_the_feed_remembers_warm_up_pools_and_passes_on_later_new_ones() -> None:
    feed, pools, states, now = _feed()
    ws = FakeSocket()
    assert feed.warming_up(now[0])  # not connected yet

    await feed.on_stream_connected(ws)
    await feed.on_stream_message(_notice("Busy"), ws)
    now[0] += 61.0
    await feed.on_stream_message(_notice("Busy", slot=9), ws)  # seen: skipped
    await feed.on_stream_message(_notice(OTHER_POOL, slot=10), ws)
    await feed.on_stream_message({"result": 1, "id": 1}, ws)  # confirmation

    assert ws.sent == list(POOL_SUBSCRIPTIONS)
    assert [m["params"][1]["filters"] for m in ws.sent] == [
        [{"dataSize": 301}],
        [{"dataSize": 287}],
    ]
    assert pools == [(OTHER_POOL, 10)]
    assert feed.connected and states == [(True, "")]
    assert feed.stats == {
        "connects": 1,
        "messages": 3,
        "warmup_pools": 1,
        "first_seen": 1,
    }
    assert feed.stream_connect_url().endswith("api-key=SECRET")

    # A reconnect keeps what was seen and does not warm up again.
    await feed.on_stream_connected(ws)
    assert not feed.warming_up(now[0]) and feed.started_at == 1000.0


def test_feed_errors_disconnect_and_never_log_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed, _, states, _ = _feed()
    feed.connected = True
    with caplog.at_level(logging.INFO, logger="trading_pump.pools"):
        feed.on_stream_error("No WebSocket message for 60s")
        feed.on_stream_exception(
            RuntimeError("wss://rpc.example/?api-key=SECRET refused"), 2.0
        )
        feed.connected = True
        feed.on_stream_ended()
        feed.on_stream_closed()
        feed.connected = True
        feed.on_stream_closed()
        feed.stream_log("hello")
    assert "SECRET" not in caplog.text
    assert [connected for connected, _ in states] == [False, False, False, False]
    assert "SECRET" not in states[1][1]
    assert feed.stats == {"errors": 2, "disconnects": 1}
    assert not feed.stream_stop_requested()
    feed.stop()
    assert feed.stream_stop_requested()


def test_a_feed_without_a_state_callback_still_tracks_its_state() -> None:
    feed = NewPoolFeed(
        on_pool=lambda *_: None, connect_url=lambda: "wss://x", stream_url="wss://x"
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

    monkeypatch.setattr("trading_pump.pools.run_websocket_stream", fake_run)
    await feed.run()
    assert ran == [feed]


class FakeSource:
    """``inspect_new_pool`` and ``register_pool`` from canned answers."""

    def __init__(self, info: NewPoolInfo | None = None) -> None:
        self.info = info
        self.error: Exception | None = None
        self.release = asyncio.Event()
        self.release.set()
        self.lookups: list[tuple[str, str, int]] = []
        self.registered: list[tuple[str, str, str, str, bool]] = []

    async def inspect_new_pool(
        self, address: str, mint: str, *, limit: int
    ) -> NewPoolInfo:
        self.lookups.append((address, mint, limit))
        await self.release.wait()
        if self.error is not None:
            raise self.error
        assert self.info is not None
        return self.info

    def register_pool(
        self,
        mint: str,
        address: str,
        base_vault: str,
        quote_vault: str,
        *,
        sol_is_base: bool = False,
    ) -> None:
        self.registered.append((mint, address, base_vault, quote_vault, sol_is_base))


def _watcher(
    source: FakeSource, **settings: Any
) -> tuple[NewPoolWatcher, GraduateTracker, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    tracker = GraduateTracker(GraduationSettings(), record=rows.append)
    watcher = NewPoolWatcher(
        NewPoolSettings(enabled=True, **settings),
        tracker,
        source,
        rows.append,
        clock=lambda: 1000.0,
    )
    return watcher, tracker, rows


async def _settle(watcher: NewPoolWatcher) -> None:
    await asyncio.gather(*watcher._tasks)


async def test_a_new_sol_pool_is_looked_up_registered_and_followed() -> None:
    source = FakeSource(
        NewPoolInfo(created_at=990.0, exact=True, signatures=3, decimals=9)
    )
    watcher, tracker, rows = _watcher(source, signature_limit=50)

    watcher.on_pool(OTHER_POOL, POOL_BYTES, 42)
    await _settle(watcher)

    assert source.lookups == [(OTHER_POOL, GRADUATED_MINT, 50)]
    assert source.registered == [
        (
            GRADUATED_MINT,
            OTHER_POOL,
            GRADUATED_BASE_VAULT_ADDRESS,
            GRADUATED_QUOTE_VAULT_ADDRESS,
            False,
        )
    ]
    graduate = tracker.get(GRADUATED_MINT)
    assert graduate is not None and graduate.source == "new_pool"
    (start,) = rows
    assert start["event"] == "observation_start" and start["source"] == "new_pool"
    assert start["created_at"] == 990.0 and start["created_exact"] is True
    assert start["decimals"] == 9 and start["slot"] == 42
    assert start["found_by"] == "pool_created"
    assert watcher.stats == {"looked_up": 1, "followed": 1}


@pytest.mark.parametrize(
    "info",
    [
        NewPoolInfo(created_at=100.0, exact=True, signatures=3, decimals=6),
        NewPoolInfo(created_at=None, exact=True, signatures=0, decimals=6),
    ],
)
async def test_an_old_or_undated_pool_is_not_followed(info: NewPoolInfo) -> None:
    source = FakeSource(info)
    watcher, tracker, rows = _watcher(source)
    watcher.on_pool(OTHER_POOL, POOL_BYTES, 1)
    await _settle(watcher)
    assert len(tracker) == 0 and rows == [] and source.registered == []
    assert watcher.stats["old_pools"] == 1


async def test_a_failed_lookup_is_counted_and_shown_without_secrets() -> None:
    source = FakeSource()
    source.error = RuntimeError("https://rpc.example/?api-key=SECRET timed out")
    watcher, tracker, _ = _watcher(source)
    watcher.on_pool(OTHER_POOL, POOL_BYTES, 1)
    await _settle(watcher)
    assert watcher.stats["lookup_errors"] == 1 and len(tracker) == 0
    assert "SECRET" not in watcher.last_error


async def test_a_new_pool_of_a_followed_graduate_stays_the_graduates() -> None:
    source = FakeSource(
        NewPoolInfo(created_at=999.0, exact=True, signatures=1, decimals=6)
    )
    watcher, tracker, _ = _watcher(source)
    tracker.add(GRADUATED_MINT, now=900.0)
    watcher.on_pool(OTHER_POOL, POOL_BYTES, 1)
    await _settle(watcher)
    graduate = tracker.get(GRADUATED_MINT)
    assert graduate is not None and graduate.source == "graduation"
    assert "followed" not in watcher.stats


@pytest.mark.parametrize(
    "raw",
    [
        _with(POOL_BYTES, POOL_QUOTE_MINT_OFFSET, SAMPLE_MINT),  # two coins
        _with(
            _with(POOL_BYTES, POOL_BASE_MINT_OFFSET, WSOL_MINT),
            POOL_QUOTE_MINT_OFFSET,
            WSOL_MINT,
        ),  # SOL on both sides
    ],
)
def test_pools_not_paired_with_sol_are_skipped(raw: bytes) -> None:
    watcher, _, _ = _watcher(FakeSource())
    watcher.on_pool(OTHER_POOL, raw, 1)
    assert watcher.stats == {"not_sol_pair": 1} and not watcher._tasks


def test_undecodable_pools_are_counted() -> None:
    watcher, _, _ = _watcher(FakeSource())
    watcher.on_pool(OTHER_POOL, b"short", 1)
    assert watcher.stats == {"decode_errors": 1}


def test_a_graduates_canonical_pool_is_only_counted() -> None:
    source = FakeSource()
    watcher, tracker, rows = _watcher(source)
    watcher.on_pool(GRADUATED_POOL, POOL_BYTES, 5)
    assert rows == [] and source.lookups == [] and len(tracker) == 0
    assert watcher.stats == {"canonical": 1}


def test_sol_side_names_the_coin_and_which_side_holds_sol() -> None:
    graduation = decode_pool(OTHER_POOL, POOL_BYTES)
    flipped = decode_pool(
        OTHER_POOL,
        _with(
            _with(POOL_BYTES, POOL_BASE_MINT_OFFSET, WSOL_MINT),
            POOL_QUOTE_MINT_OFFSET,
            SAMPLE_MINT,
        ),
    )
    assert sol_side(graduation) == (GRADUATED_MINT, False)
    assert sol_side(flipped) == (SAMPLE_MINT, True)


async def test_a_pool_with_sol_as_its_base_is_followed_with_its_coin_as_the_mint() -> (
    None
):
    source = FakeSource(
        NewPoolInfo(created_at=995.0, exact=True, signatures=2, decimals=9)
    )
    watcher, tracker, rows = _watcher(source)
    raw = _with(
        _with(POOL_BYTES, POOL_BASE_MINT_OFFSET, WSOL_MINT),
        POOL_QUOTE_MINT_OFFSET,
        SAMPLE_MINT,
    )
    watcher.on_pool(OTHER_POOL, raw, 3)
    await _settle(watcher)
    assert source.lookups == [(OTHER_POOL, SAMPLE_MINT, 100)]
    assert source.registered == [
        (
            SAMPLE_MINT,
            OTHER_POOL,
            GRADUATED_BASE_VAULT_ADDRESS,
            GRADUATED_QUOTE_VAULT_ADDRESS,
            True,
        )
    ]
    assert tracker.get(SAMPLE_MINT) is not None
    assert rows[0]["sol_is_base"] is True


async def test_lookups_run_a_few_at_a_time_and_stop_cancels_the_rest() -> None:
    source = FakeSource(
        NewPoolInfo(created_at=999.0, exact=True, signatures=1, decimals=6)
    )
    source.release.clear()
    watcher, tracker, _ = _watcher(source, max_lookups=1)
    second = _with(POOL_BYTES, POOL_BASE_MINT_OFFSET, SAMPLE_MINT)

    watcher.on_pool(OTHER_POOL, POOL_BYTES, 1)
    watcher.on_pool("Other2", second, 2)
    for _ in range(3):
        await asyncio.sleep(0)
    assert len(source.lookups) == 1  # the second waits for a slot

    await watcher.stop()
    assert not watcher._tasks and len(tracker) == 0


def test_status_text_says_what_the_feed_is_doing() -> None:
    watcher, _, _ = _watcher(FakeSource())
    feed, _, _, now = _feed()
    assert watcher.status_text(feed).startswith("disconnected · 0 new followed")
    feed.connected = True
    feed.started_at = now[0]
    watcher.clock = lambda: now[0]
    assert watcher.status_text(feed).startswith("connected (warming up)")
    watcher.stats.update(followed=2, old_pools=5, canonical=3)
    watcher.clock = lambda: now[0] + 3600.0
    assert watcher.status_text(feed) == (
        "connected · 2 new followed · 5 old · 3 graduates' pools skipped"
    )
