from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from trading_pump.ops.retention import RetentionPolicy, RotatedFileSink

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
        policy: RetentionPolicy | None = None,
    ) -> None:
        self.output_path = Path(output_path)
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self.policy = policy or RetentionPolicy(
            max_bytes=50 * 1024 * 1024,
            max_files=10,
            max_age_days=30,
            compress_archives=True,
        )
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._closed: bool = False
        self._records_written: int = 0
        self._flush_lock = asyncio.Lock()
        self._sink: RotatedFileSink | None = None

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
            if self._sink is None:
                self._sink = RotatedFileSink(self.output_path, policy=self.policy)
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
            lines = [json.dumps(r, default=str) + "\n" for r in batch]
            payload = "".join(lines)
            # The batch has already left the queue, so a cancelled write would
            # lose it (and could leave the thread writing into a closed sink).
            # Shield the write and let it finish before honouring the cancel
            # (BUG-103).
            write = asyncio.ensure_future(asyncio.to_thread(self._sync_append, payload))
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                await asyncio.wait([write])
                self._finish_write(write, len(batch))
                raise
            except Exception:
                pass  # logged by _finish_write
            self._finish_write(write, len(batch))

    def _finish_write(self, write: asyncio.Future[None], count: int) -> None:
        err = write.exception()
        if err is not None:
            logger.error(
                "Failed to write replay batch to %s: %s", self.output_path, err
            )
            return
        self._records_written += count

    def _sync_append(self, text: str) -> None:
        """Append raw text for backward compatibility."""
        if self._sink is None:
            self._sink = RotatedFileSink(self.output_path, policy=self.policy)
        lines = [line for line in text.splitlines() if line]
        self._sink.write_batch(lines)

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
        if self._sink is not None:
            try:
                self._sink.close()
            except Exception:
                pass
            self._sink = None


__all__ = ["ReplayRecorder"]
