"""Unit tests for ``feed.py``: the migration feed and the pool poller."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from trading_pump.config.settings import GraduationSettings
from trading_pump.feed import MigrationFeed, PoolPoller, migration_mint
from trading_pump.graduates import GraduateTracker
from trading_pump.streams.websocket import MIGRATION_SUBSCRIPTION
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import (
    GRADUATION_BASE_RESERVE,
    GRADUATION_QUOTE_RESERVE,
)
from trading_pump.tests.support.fakes import FakePoolSource


@pytest.mark.parametrize(
    ("data", "mint"),
    [
        ({"mint": "M", "txType": "migrate"}, "M"),
        ({"mint": "M", "txType": "Migration"}, "M"),
        ({"mint": "M", "txType": "buy"}, None),
        ({"txType": "migrate"}, None),
        ({"message": "Successfully subscribed"}, None),
        ("text", None),
    ],
)
def test_migration_mint(data: Any, mint: str | None) -> None:
    assert migration_mint(data) == mint


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_json(self, message: Any) -> None:
        self.sent.append(message)


def _feed(**kwargs: Any) -> tuple[MigrationFeed, list[str], list[tuple[bool, str]]]:
    migrations: list[str] = []
    states: list[tuple[bool, str]] = []
    feed = MigrationFeed(
        on_migration=migrations.append,
        connect_url=lambda: "wss://pumpportal.fun/api/data?api-key=SECRET",
        stream_url="wss://pumpportal.fun/api/data",
        on_state=lambda connected, detail: states.append((connected, detail)),
        clock=lambda: 42.0,
        **kwargs,
    )
    return feed, migrations, states


async def test_the_feed_subscribes_to_migrations_only_and_reports_them() -> None:
    feed, migrations, states = _feed()
    ws = FakeSocket()

    await feed.on_stream_connected(ws)
    await feed.on_stream_message({"mint": SAMPLE_MINT, "txType": "migrate"}, ws)
    await feed.on_stream_message({"message": "hello"}, ws)

    assert ws.sent == [MIGRATION_SUBSCRIPTION]
    assert migrations == [SAMPLE_MINT]
    assert feed.connected and states == [(True, "")]
    assert feed.stats == {"connects": 1, "messages": 2, "migrations": 1}
    assert feed.last_message_at == 42.0
    assert feed.stream_connect_url().endswith("api-key=SECRET")


def test_disconnects_are_reported_and_logged_without_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed, _, states = _feed()
    feed.connected = True
    with caplog.at_level(logging.INFO, logger="trading_pump.feed"):
        feed.on_stream_error("boom at wss://x.example/?api-key=SECRET")
        feed.on_stream_exception(RuntimeError("down"), 4.0)
        feed.on_stream_ended()
        feed.stream_log("hello")
    feed.connected = True
    feed.on_stream_closed()
    feed.on_stream_closed()  # already down: no second report

    assert [s[0] for s in states] == [False, False, False, False]
    assert feed.stats["errors"] == 2 and feed.stats["disconnects"] == 1
    assert "SECRET" not in caplog.text and "retry in 4s" in caplog.text


def test_stop_ends_the_stream_loop_and_works_without_a_state_hook() -> None:
    feed = MigrationFeed(
        on_migration=lambda mint: None,
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
    )
    assert not feed.stream_stop_requested()
    feed.stop()
    assert feed.stream_stop_requested()
    feed.on_stream_ended()
    assert not feed.connected


async def test_run_returns_at_once_when_stopped() -> None:
    feed, _, _ = _feed()
    feed.stop()
    await feed.run()


def _poller(
    source: FakePoolSource, held: list[str] | None = None
) -> tuple[PoolPoller, GraduateTracker, dict[str, Any]]:
    seen: dict[str, Any] = {"readings": [], "ok": 0, "failed": []}
    tracker = GraduateTracker(
        GraduationSettings(observation_seconds=100.0, pool_missing_grace_seconds=0.0),
        signal_after_seconds=60.0,
    )
    poller = PoolPoller(
        source,
        tracker,
        held=lambda: list(held or []),
        on_reading=seen["readings"].append,
        on_success=lambda: seen.__setitem__("ok", seen["ok"] + 1),
        on_failure=seen["failed"].append,
        clock=lambda: 10.0,
    )
    return poller, tracker, seen


async def test_a_poll_reads_due_graduates_and_held_mints_together() -> None:
    source = FakePoolSource()
    source.set(SAMPLE_MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)
    source.set(SAMPLE_PUMP_MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)
    poller, tracker, seen = _poller(source, held=[SAMPLE_PUMP_MINT])
    tracker.add(SAMPLE_MINT, now=0.0)

    assert await poller.poll_once() == 2

    assert source.reads == [([SAMPLE_PUMP_MINT, SAMPLE_MINT], 10.0)]
    assert len(seen["readings"]) == 2 and seen["ok"] == 1
    assert tracker.get(SAMPLE_MINT).last is not None  # type: ignore[union-attr]
    assert poller.stats == {"polls": 1, "readings": 2}


async def test_nothing_due_means_no_read() -> None:
    source = FakePoolSource()
    poller, _, _ = _poller(source)
    assert await poller.poll_once(5.0) == 0
    assert source.reads == []


async def test_a_failed_read_is_reported_redacted_and_rejections_end_pools() -> None:
    source = FakePoolSource()
    poller, tracker, seen = _poller(source)
    tracker.add(SAMPLE_MINT, now=0.0)
    source.fail = RuntimeError("down: https://rpc.example/?api-key=SECRET")

    assert await poller.poll_once() == 0
    assert seen["failed"] and "SECRET" not in seen["failed"][0]
    assert poller.stats["poll_errors"] == 1 and "SECRET" not in poller.last_error

    source.fail = None
    source.reject(SAMPLE_MINT, "not_pumpswap")
    assert await poller.poll_once() == 0
    assert SAMPLE_MINT not in tracker
    assert poller.stats["rejected_not_pumpswap"] == 1


async def test_expired_graduates_end_before_the_read() -> None:
    source = FakePoolSource()
    poller, tracker, _ = _poller(source)
    tracker.add(SAMPLE_MINT, now=0.0)
    assert await poller.poll_once(200.0) == 0
    assert SAMPLE_MINT not in tracker and source.reads == []


async def test_the_loop_polls_until_stopped_and_survives_a_bug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = FakePoolSource()
    poller, tracker, _ = _poller(source)
    calls: list[float] = []

    async def broken(now: float | None = None) -> int:
        calls.append(0.0)
        if len(calls) == 1:
            raise ValueError("bug")
        return 0

    poller.poll_once = broken
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with caplog.at_level(logging.WARNING, logger="trading_pump.feed"):
        await poller.run(2.0, lambda: len(calls) >= 3, sleep)

    assert len(calls) == 3 and sleeps == [2.0, 2.0, 2.0]
    assert poller.stats["loop_errors"] == 1 and "bug" in caplog.text
