"""Unit tests for ``bot/recorder.py`` (``ReplayRecorder``)."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pumpfun_trading.bot.recorder import ReplayRecorder


async def _yield(times: int = 20) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


def _mints(path: Path) -> list[str]:
    return [json.loads(line)["mint"] for line in path.read_text().splitlines() if line]


@pytest.mark.regression("BUG-103")
async def test_close_with_batch_queued_in_executor_writes_the_batch(
    tmp_path: Path,
) -> None:
    # One busy executor thread keeps the worker's write job queued (not started)
    # when close() cancels the worker, the shutdown race CI hit on 3.11.
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(executor)
    release = threading.Event()
    blocker = loop.run_in_executor(None, release.wait, 5.0)
    path = tmp_path / "replay.jsonl"
    recorder = ReplayRecorder(path, batch_size=1, flush_interval_seconds=0.1)
    await recorder.start()

    recorder.record_snapshot({"mint": "Queued1"})
    await _yield()
    closing = asyncio.create_task(recorder.close())
    await _yield()
    release.set()
    await closing
    await blocker

    assert _mints(path) == ["Queued1"]
    assert recorder.records_written == 1


@pytest.mark.regression("BUG-103")
async def test_close_with_write_running_counts_it_before_closing_sink(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replay.jsonl"
    recorder = ReplayRecorder(path, batch_size=1, flush_interval_seconds=0.1)
    await recorder.start()
    started = threading.Event()
    release = threading.Event()
    real_append = recorder._sync_append

    def slow_append(text: str) -> None:
        started.set()
        release.wait(5.0)
        real_append(text)

    recorder._sync_append = slow_append  # type: ignore[method-assign]
    recorder.record_snapshot({"mint": "Running1"})
    while not started.is_set():
        await asyncio.sleep(0.001)
    closing = asyncio.create_task(recorder.close())
    await _yield()
    release.set()
    await closing

    assert _mints(path) == ["Running1"]
    assert recorder.records_written == 1


async def test_close_drains_records_still_in_queue(tmp_path: Path) -> None:
    path = tmp_path / "replay.jsonl"
    recorder = ReplayRecorder(path, batch_size=50, flush_interval_seconds=5.0)
    await recorder.start()

    for mint in ("A", "B", "C"):
        recorder.record_snapshot({"mint": mint})
    await recorder.close()
    recorder.record_snapshot({"mint": "AfterClose"})

    assert _mints(path) == ["A", "B", "C"]
    assert recorder.records_written == 3
