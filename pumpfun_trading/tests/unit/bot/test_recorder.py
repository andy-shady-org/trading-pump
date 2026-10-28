"""Unit tests for ``bot/recorder.py`` (``ReplayRecorder``)."""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

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


async def test_replay_recorder_lifecycle(tmp_path: Path):
    """Test ReplayRecorder buffering, background batching, and graceful closing."""
    log_file = tmp_path / "test_nested" / "market.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file,
        batch_size=10,
        flush_interval_seconds=0.2,
    )

    assert not recorder.is_running
    assert recorder.records_written == 0
    assert recorder.queue_size == 0

    await recorder.start()
    assert recorder.is_running
    assert log_file.parent.exists()

    # Enqueue 15 records (should trigger 1 batch immediately + 5 buffered)
    for i in range(15):
        recorder.record_snapshot(
            {
                "timestamp": 1700000000.0 + i,
                "mint": f"Mint{i}",
                "price": 0.000000028 + (i * 0.000000001),
                "market_cap_sol": 28.0 + (i * 0.1),
            }
        )

    # Allow worker to flush
    await asyncio.sleep(0.3)
    assert recorder.records_written >= 10

    # Enqueue 5 more and close gracefully
    for i in range(15, 20):
        recorder.record_snapshot(
            {
                "timestamp": 1700000000.0 + i,
                "mint": f"Mint{i}",
                "price": 0.000000028,
                "market_cap_sol": 28.0,
            }
        )

    await recorder.close()
    assert not recorder.is_running
    assert recorder.records_written == 20

    # Verify file contents
    assert log_file.exists()
    lines = [
        line.strip()
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 20
    first_record = json.loads(lines[0])
    assert first_record["mint"] == "Mint0"
    assert first_record["price"] == pytest.approx(0.000000028)


async def test_replay_recorder_edge_cases(tmp_path: Path):
    """Test ReplayRecorder edge cases like write errors and closed state."""
    log_file = tmp_path / "edge_market.jsonl"
    recorder = ReplayRecorder(output_path=log_file, batch_size=5)

    # Calling record_snapshot when closed
    recorder._closed = True
    recorder.record_snapshot({"mint": "ClosedMint"})
    assert recorder.queue_size == 0

    # Test empty batch write
    await recorder._write_batch([])
    assert recorder.records_written == 0

    # Test write batch exception logging
    recorder._closed = False
    with patch.object(recorder, "_sync_append", side_effect=OSError("Disk full")):
        await recorder._write_batch([{"test": 1}])

    # Test record snapshot exception handling
    with patch.object(
        recorder._queue, "put_nowait", side_effect=Exception("Queue broken")
    ):
        recorder.record_snapshot({"test": 1})

    # Test flush with items
    recorder._queue.put_nowait({"mint": "FlushMint"})
    await recorder.flush()
    assert recorder.records_written == 1

    # Test close when task raises exception
    await recorder.start()
    if recorder._worker_task is not None:
        recorder._worker_task.cancel()
    await recorder.close()


async def test_replay_recorder_drain_and_worker_branches(tmp_path: Path):
    """Test ReplayRecorder queue draining when multiple items are available."""
    log_file = tmp_path / "drain_market.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=5, flush_interval_seconds=0.1
    )

    # Put 4 items into queue before start so worker drains them in one batch
    recorder.record_snapshot({"item": 1})
    recorder.record_snapshot({"item": 2})
    recorder.record_snapshot({"item": 3})
    recorder.record_snapshot({"item": 4})
    assert recorder.queue_size == 4

    await recorder.start()
    # Call start again (branch line 50->exit when already running)
    await recorder.start()

    await asyncio.sleep(0.2)
    assert recorder.records_written == 4
    await recorder.close()


async def test_replay_recorder_worker_inner_drain(tmp_path: Path):
    """Test ReplayRecorder worker inner draining loop."""
    log_file = tmp_path / "inner_drain.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=3, flush_interval_seconds=0.01
    )
    await recorder.start()
    recorder._queue.put_nowait({"item": 1})
    recorder._queue.put_nowait({"item": 2})
    recorder._queue.put_nowait({"item": 3})
    await asyncio.sleep(0.05)
    await recorder.close()
    assert recorder.records_written == 3


async def test_replay_recorder_flush_and_close_branches(tmp_path: Path):
    """Test ReplayRecorder flush QueueEmpty branch and close without start."""
    log_file = tmp_path / "flush_empty.jsonl"
    recorder = ReplayRecorder(output_path=log_file, batch_size=5)

    # Close without start
    await recorder.close()
    assert not recorder.is_running

    # Flush with 1 item triggering QueueEmpty on next iteration
    recorder._queue.put_nowait({"item": 1})
    await recorder.flush()
    assert recorder.records_written == 1


async def test_replay_recorder_worker_error(tmp_path: Path):
    """Test ReplayRecorder worker exception resiliency."""
    log_file = tmp_path / "worker_err.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=2, flush_interval_seconds=0.05
    )
    await recorder.start()

    # Trigger exception in _write_batch inside worker
    with patch.object(
        recorder, "_write_batch", side_effect=[Exception("Batch error"), None]
    ):
        recorder.record_snapshot({"mint": "Mint1"})
        recorder.record_snapshot({"mint": "Mint2"})
        await asyncio.sleep(0.15)

    await recorder.close()
