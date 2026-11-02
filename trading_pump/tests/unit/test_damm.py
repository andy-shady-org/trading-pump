"""Unit tests for ``damm.py``: the Meteora DAMM v2 capture (FEAT-107).

The pool accounts are two mainnet reads from 2026-11-02 in
``tests/support/payloads.py``: a coin / SOL pool activated by timestamp and
a SOL / coin pool activated by slot. Other cases are those bytes edited.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import pytest
from solders.pubkey import Pubkey

from trading_pump import damm
from trading_pump.config.settings import DammSettings
from trading_pump.damm import (
    SUBSCRIPTION,
    DammFeed,
    DammWatcher,
    activation_age,
    decode_damm_pool,
    mint_decimals,
    sol_per_coin,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, WSOL_MINT
from trading_pump.tests.support.payloads import (
    DAMM_COIN_MINT,
    DAMM_POOL,
    DAMM_POOL_B64,
    DAMM_SOL_A_POOL,
    DAMM_SOL_A_POOL_B64,
)

RAW = base64.b64decode(DAMM_POOL_B64)
SOL_A_RAW = base64.b64decode(DAMM_SOL_A_POOL_B64)
ACTIVATED = 1793633790  # the coin / SOL pool's activation time
SLOT = 464548170


def _set(raw: bytes, offset: int, value: bytes) -> bytes:
    start = 8 + offset
    return raw[:start] + value + raw[start + len(value) :]


def _u(value: int, size: int) -> bytes:
    return value.to_bytes(size, "little")


def _key(pubkey: str) -> bytes:
    return bytes(Pubkey.from_string(pubkey))


def _price(raw: bytes, sqrt_price: int) -> bytes:
    return _set(raw, 448, _u(sqrt_price, 16))


def _mint_value(decimals: int) -> dict[str, Any]:
    raw = bytes(44) + bytes([decimals]) + bytes(37)
    return {"data": [base64.b64encode(raw).decode(), "base64"]}


def _pool_value(raw: bytes) -> dict[str, Any]:
    return {"data": [base64.b64encode(raw).decode(), "base64"]}


class Clock:
    def __init__(self, now: float = ACTIVATED + 50.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Reader:
    """``read_accounts``: answers by address, records the calls."""

    def __init__(self, answers: dict[str, Any] | None = None, fail: bool = False):
        self.answers = answers or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    async def __call__(self, addresses: list[str]) -> list[Any]:
        self.calls.append(list(addresses))
        if self.fail:
            raise RuntimeError("rpc down https://rpc.example/?api-key=SECRET")
        return [self.answers.get(address) for address in addresses]


def _watcher(
    reader: Reader | None = None, clock: Clock | None = None, **settings: Any
) -> tuple[DammWatcher, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    watcher = DammWatcher(
        DammSettings(enabled=True, **settings),
        rows.append,
        read_accounts=reader,
        clock=clock or Clock(),
    )
    return watcher, rows


# -- the pool account -----------------------------------------------------------


def test_a_mainnet_pool_decodes() -> None:
    pool = decode_damm_pool(DAMM_POOL, RAW)
    assert (pool.token_a_mint, pool.token_b_mint) == (DAMM_COIN_MINT, WSOL_MINT)
    assert (pool.activation_type, pool.activation_point) == (1, ACTIVATED)
    assert (pool.status, pool.layout_version) == (0, 1)
    assert (pool.token_a_amount, pool.token_b_amount) == (318472025837, 45003818)
    assert len(pool.pool_fees) == 160 and pool.liquidity > 0
    assert pool.sol_side() == (DAMM_COIN_MINT, False)
    assert pool.sol_amount(sol_is_a=False) == 45003818
    # 50 s after activation DexScreener showed 1.652e-7 SOL; the read 1.413e-7.
    assert sol_per_coin(pool, False, 6) == pytest.approx(1.4131168e-7)
    assert pool.state() == (
        pool.sqrt_price,
        pool.liquidity,
        pool.token_a_amount,
        pool.token_b_amount,
        0,
    )


def test_a_pool_with_sol_as_token_a_and_a_slot_activation() -> None:
    pool = decode_damm_pool(DAMM_SOL_A_POOL, SOL_A_RAW)
    assert pool.token_a_mint == WSOL_MINT and pool.activation_type == 0
    assert pool.sqrt_price == 2908389897151445673669
    coin, sol_is_a = pool.sol_side() or ("", False)
    assert sol_is_a and coin == pool.token_b_mint
    assert sol_per_coin(pool, True, 6) == pytest.approx(4.0228533e-8)
    slot = pool.activation_point + 25
    assert activation_age(pool, now=0.0, slot=slot) == pytest.approx(10.0)


@pytest.mark.parametrize(
    ("raw", "message"),
    [(RAW[:-1], "not a DAMM v2 pool"), (b"x" * 8 + RAW[8:], "not a DAMM v2 pool")],
)
def test_other_accounts_are_refused(raw: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        decode_damm_pool("x", raw)


def test_sides_amounts_and_zero_prices() -> None:
    both_sol = decode_damm_pool("p", _set(RAW, 160, _key(WSOL_MINT)))
    assert both_sol.sol_side() is None
    no_sol = decode_damm_pool("p", _set(RAW, 192, _key(SAMPLE_MINT)))
    assert no_sol.sol_side() is None
    old_layout = decode_damm_pool("p", _set(RAW, 688, b"\x00"))
    assert old_layout.sol_amount(sol_is_a=False) is None
    flat = decode_damm_pool("p", _price(RAW, 0))
    assert flat.price == 0 and sol_per_coin(flat, False, 6) is None


def test_mint_decimals() -> None:
    assert mint_decimals(_mint_value(6)) == 6
    assert mint_decimals({"data": [base64.b64encode(b"short").decode()]}) is None
    assert mint_decimals({"data": ["not base64!"]}) is None
    assert mint_decimals({}) is None


# -- the watcher -----------------------------------------------------------------


async def test_a_new_pool_is_followed_and_its_decimals_read() -> None:
    reader = Reader({DAMM_COIN_MINT: _mint_value(6)})
    watcher, rows = _watcher(reader)
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    await asyncio.gather(*watcher._tasks)
    first, state, decimals = rows
    assert first["event"] == "damm_pool" and first["coin_mint"] == DAMM_COIN_MINT
    assert first["sol_is_a"] is False and first["age_seconds"] == pytest.approx(50.0)
    assert len(first["pool_fees_hex"]) == 320
    assert state["event"] == "damm_state" and state["price_sol"] is None
    assert state["via"] == "stream" and state["slot"] == SLOT
    assert decimals == {
        "event": "damm_decimals",
        "timestamp": pytest.approx(ACTIVATED + 50.0),
        "pool": DAMM_POOL,
        "coin_mint": DAMM_COIN_MINT,
        "decimals": 6,
    }
    # The next change carries the price now that the decimals are known.
    watcher.on_account(DAMM_POOL, _price(RAW, 2 * 10**18), SLOT + 1)
    assert rows[-1]["price_sol"] is not None
    assert watcher.stats["followed"] == 1 and watcher.stats["state_rows"] == 2


async def test_an_unchanged_write_is_not_a_row() -> None:
    watcher, rows = _watcher()
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    watcher.on_account(DAMM_POOL, RAW, SLOT + 1)
    assert len(rows) == 2 and watcher.stats["unchanged"] == 1
    watcher.on_account(DAMM_POOL, b"broken", SLOT + 2)
    assert watcher.stats["decode_errors"] == 1


@pytest.mark.parametrize(
    ("raw", "clock", "reason"),
    [
        (_set(RAW, 192, _key(SAMPLE_MINT)), ACTIVATED, "not_sol_pair"),
        (RAW, ACTIVATED + 301.0, "old_pools"),
        (RAW, ACTIVATED - 3601.0, "far_future"),
        (b"short", ACTIVATED, "decode_errors"),
    ],
)
def test_pools_that_are_not_followed(raw: bytes, clock: float, reason: str) -> None:
    watcher, rows = _watcher(clock=Clock(clock))
    watcher.on_account(DAMM_POOL, raw, SLOT)
    watcher.on_account(DAMM_POOL, raw, SLOT)  # remembered: not decoded again
    assert rows == [] and watcher.stats == {reason: 1}


def test_a_full_list_skips_without_forgetting() -> None:
    watcher, rows = _watcher(max_followed=1)
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    watcher.on_account("Other", RAW, SLOT)
    watcher.on_account("Other", RAW, SLOT)
    assert watcher.stats["list_full"] == 2 and "Other" not in watcher.skipped
    assert len(watcher.followed) == 1


async def test_decimals_that_cannot_be_read(caplog: pytest.LogCaptureFixture) -> None:
    for reader, stat in (
        (Reader(fail=True), "read_errors"),
        (Reader({DAMM_COIN_MINT: {"data": ["???"]}}), "decimals_unread"),
        (Reader(), "decimals_unread"),
    ):
        watcher, rows = _watcher(reader)
        watcher.on_account(DAMM_POOL, RAW, SLOT)
        await asyncio.gather(*watcher._tasks)
        assert watcher.stats[stat] == 1 and len(rows) == 2
    assert "SECRET" not in watcher.last_error


async def test_heartbeats_read_end_and_close() -> None:
    clock = Clock()
    reader = Reader({DAMM_POOL: _pool_value(_price(RAW, 3 * 10**18))})
    watcher, rows = _watcher(reader, clock, follow_seconds=100.0)
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    watcher.on_account(DAMM_SOL_A_POOL, _set(SOL_A_RAW, 464, _u(SLOT, 8)), SLOT)
    await asyncio.gather(*watcher._tasks)
    await watcher.heartbeat()
    beat = [row for row in rows if row.get("via") == "heartbeat"]
    assert [row["pool"] for row in beat] == [DAMM_POOL] and beat[0]["slot"] is None
    assert rows[-1] == {
        "event": "damm_end",
        "timestamp": clock.now,
        "pool": DAMM_SOL_A_POOL,
        "cause": "closed",
        "followed_seconds": 0.0,
        "rows": 1,
    }
    clock.now += 100.0
    await watcher.heartbeat()
    assert rows[-1]["cause"] == "follow_time" and watcher.followed == {}
    assert watcher.stats["heartbeats"] == 1
    watcher.on_account(DAMM_POOL, RAW, SLOT)  # ended pools are not taken back
    assert rows[-1]["event"] == "damm_end"
    watcher.end("never-followed", "closed")


async def test_heartbeat_reads_that_fail_or_cannot_be_decoded() -> None:
    reader = Reader(fail=True)
    watcher, _ = _watcher(reader)
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    await asyncio.gather(*watcher._tasks)
    await watcher.heartbeat()
    assert watcher.stats["read_errors"] == 2
    reader.fail = False
    reader.answers = {DAMM_POOL: {"data": ["???"]}}
    await watcher.heartbeat()
    assert watcher.stats["decode_errors"] == 1
    reader.answers = {DAMM_POOL: {"data": [123]}}
    await watcher.heartbeat()
    assert watcher.stats["decode_errors"] == 2
    watcher._heartbeat_one("gone", None)


async def test_heartbeats_need_a_reader_and_pools() -> None:
    watcher, rows = _watcher()
    await watcher.heartbeat()
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    await watcher.heartbeat()
    assert len(rows) == 2
    reader = Reader()
    with_reader, _ = _watcher(reader)
    await with_reader.heartbeat()
    assert reader.calls == []


async def test_heartbeats_run_until_stopped() -> None:
    watcher, _ = _watcher(heartbeat_seconds=5.0)
    beats: list[float] = []
    stops = iter([False, False, False, True, True])

    async def sleep(seconds: float) -> None:
        beats.append(seconds)

    async def heartbeat() -> None:
        beats.append(-1.0)

    watcher.heartbeat = heartbeat
    await watcher.run_heartbeats(lambda: next(stops), sleep)
    assert beats == [5.0, -1.0, 5.0]


async def test_stop_cancels_pending_reads() -> None:
    gate = asyncio.Event()

    async def slow(addresses: list[str]) -> list[Any]:
        await gate.wait()
        return []

    watcher, _ = _watcher(slow)  # type: ignore[arg-type]
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    await watcher.stop()
    assert watcher._tasks == set()


def test_status_text() -> None:
    watcher, _ = _watcher()
    feed = DammFeed(
        on_account=watcher.on_account, connect_url=str, stream_url="wss://x"
    )
    assert watcher.status_text(feed) == "disconnected · 0 followed · 0 found · 0 writes"
    feed.connected = True
    watcher.on_account(DAMM_POOL, RAW, SLOT)
    feed.stats["messages"] = 3
    assert watcher.status_text(feed) == "connected · 1 followed · 1 found · 3 writes"


# -- the feed ----------------------------------------------------------------------


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_json(self, message: Any) -> None:
        self.sent.append(message)


def _notice(address: str, raw: bytes, slot: int) -> dict[str, Any]:
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
            }
        },
    }


async def test_the_feed_subscribes_and_passes_every_write_on() -> None:
    seen: list[tuple[str, bytes, int]] = []
    states: list[tuple[bool, str]] = []
    messages: list[int] = []
    feed = DammFeed(
        on_account=lambda *args: seen.append(args),
        connect_url=lambda: "wss://rpc.example/?api-key=SECRET",
        stream_url="wss://rpc.example",
        on_state=lambda connected, detail: states.append((connected, detail)),
        on_message=lambda: messages.append(1),
    )
    socket = FakeSocket()
    await feed.on_stream_connected(socket)
    assert socket.sent == [SUBSCRIPTION] and feed.connected
    assert SUBSCRIPTION["params"][1]["filters"] == [{"dataSize": 1112}]
    await feed.on_stream_message({"result": 1, "id": 1}, socket)
    await feed.on_stream_message(_notice(DAMM_POOL, RAW, SLOT), socket)
    await feed.on_stream_message(_notice(DAMM_POOL, RAW, SLOT + 1), socket)
    assert seen == [(DAMM_POOL, RAW, SLOT), (DAMM_POOL, RAW, SLOT + 1)]
    assert len(messages) == 2 and feed.stats["messages"] == 2
    assert feed.stream_connect_url().endswith("SECRET")
    assert not feed.stream_stop_requested()
    feed.stop()
    assert feed.stream_stop_requested()
    assert states == [(True, "")]


def test_the_feed_reports_its_state(caplog: pytest.LogCaptureFixture) -> None:
    states: list[tuple[bool, str]] = []
    feed = DammFeed(
        on_account=lambda *args: None,
        connect_url=str,
        stream_url="wss://x",
        on_state=lambda connected, detail: states.append((connected, detail)),
    )
    with caplog.at_level(logging.WARNING, logger="trading_pump.damm"):
        feed.on_stream_error("refused wss://rpc.example/?api-key=SECRET")
        feed.on_stream_exception(
            RuntimeError("down wss://rpc.example/?api-key=SECRET"), 2.0
        )
    feed.on_stream_ended()
    feed.connected = True
    feed.on_stream_closed()
    feed.on_stream_closed()  # already down: nothing more
    assert [connected for connected, _ in states] == [False, False, False, False]
    assert "SECRET" not in caplog.text and "SECRET" not in states[1][1]
    assert feed.stats == {"errors": 2, "disconnects": 1}
    plain = DammFeed(on_account=lambda *args: None, connect_url=str, stream_url="x")
    plain.on_stream_ended()
    assert plain.stats == {"disconnects": 1}


async def test_a_feed_without_a_message_callback() -> None:
    seen: list[str] = []
    feed = DammFeed(
        on_account=lambda address, raw, slot: seen.append(address),
        connect_url=str,
        stream_url="x",
    )
    await feed.on_stream_message(_notice(DAMM_POOL, RAW, SLOT), FakeSocket())
    assert seen == [DAMM_POOL]


async def test_the_feed_runs_the_shared_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[Any] = []

    async def fake(host: Any) -> None:
        ran.append(host)

    monkeypatch.setattr(damm, "run_websocket_stream", fake)
    feed = DammFeed(on_account=lambda *args: None, connect_url=str, stream_url="x")
    await feed.run()
    assert ran == [feed]
