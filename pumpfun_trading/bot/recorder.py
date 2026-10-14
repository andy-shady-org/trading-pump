from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ReplayRecorder:
    """
    Asynchronous non-blocking market stream recorder.

    Buffers token snapshots and trade events into an unbounded asyncio.Queue
    and batch-flushes to disk periodically or when the batch size threshold is reached,
    eliminating disk I/O latency contention from critical trading execution paths.
    """

    def __init__(
        self,
        output_path: str | Path,
        batch_size: int = 50,
        flush_interval_seconds: float = 5.0,
    ) -> None:
        self.output_path = Path(output_path)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._closed: bool = False
        self._records_written: int = 0
        self._flush_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    @property
    def records_written(self) -> int:
        return self._records_written

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Start the background batch flushing task."""
        if self._worker_task is None or self._worker_task.done():
            self._closed = False
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._worker_task = asyncio.create_task(
                self._flush_worker(), name="replay_recorder_flusher"
            )

    def record_snapshot(self, record: dict[str, Any]) -> None:
        """
        Enqueue a market quote or trade snapshot for recording.
        This operation is strictly non-blocking and executes in < 0.05ms.
        """
        if self._closed:
            return
        try:
            self._queue.put_nowait(dict(record))
        except Exception as err:
            logger.debug("Failed to enqueue replay snapshot: %s", err)

    async def _flush_worker(self) -> None:
        """Background coroutine that aggregates records and writes batches to disk."""
        while not self._closed:
            try:
                batch: list[dict[str, Any]] = []
                # Wait for at least one item or timeout
                try:
                    first_item = await asyncio.wait_for(
                        self._queue.get(), timeout=self.flush_interval_seconds
                    )
                    batch.append(first_item)
                    self._queue.task_done()
                except asyncio.TimeoutError:
                    continue

                # Drain additional available items up to batch_size
                while len(batch) < self.batch_size and not self._queue.empty():
                    try:
                        item = self._queue.get_nowait()
                        batch.append(item)
                        self._queue.task_done()
                    except asyncio.QueueEmpty:
                        break

                if batch:
                    await self._write_batch(batch)
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error("Error in ReplayRecorder flush worker: %s", err)
                await asyncio.sleep(0.5)

    async def _write_batch(self, batch: list[dict[str, Any]]) -> None:
        """Append a batch of serialized JSON lines to the destination file."""
        if not batch:
            return
        async with self._flush_lock:
            try:
                lines = [json.dumps(r, default=str) + "\n" for r in batch]
                payload = "".join(lines)
                await asyncio.to_thread(self._sync_append, payload)
                self._records_written += len(batch)
            except Exception as err:
                logger.error(
                    "Failed to write replay batch to %s: %s", self.output_path, err
                )

    def _sync_append(self, text: str) -> None:
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()

    async def flush(self) -> None:
        """Force flush all currently enqueued records to disk immediately."""
        batch: list[dict[str, Any]] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                batch.append(item)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._write_batch(batch)

    async def close(self) -> None:
        """Stop worker and perform graceful final flush."""
        self._closed = True
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
            self._worker_task = None
        await self.flush()


__all__ = ["ReplayRecorder"]
