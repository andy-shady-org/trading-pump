"""Structured diagnostic event telemetry engine for pumpfun-trading (FEAT-30)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)


class EventCategory(str, Enum):
    """Subsystem domain category for diagnostic events."""

    STREAM = "stream"
    SCREENING = "screening"
    STRATEGY = "strategy"
    EXECUTION = "execution"
    ARBITRAGE = "arbitrage"
    RISK = "risk"
    LIFECYCLE = "lifecycle"


class EventSeverity(str, Enum):
    """Severity classification for diagnostic telemetry."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DiagnosticEvent:
    """Structured telemetry event record with microsecond precision."""

    timestamp_ns: int = field(default_factory=time.time_ns)
    iso_timestamp: str = ""
    category: EventCategory = EventCategory.LIFECYCLE
    severity: EventSeverity = EventSeverity.INFO
    event_name: str = ""
    mint: str | None = None
    mint_name: str | None = None
    latency_ms: float | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.iso_timestamp:
            dt = datetime.datetime.fromtimestamp(
                self.timestamp_ns / 1_000_000_000, tz=datetime.timezone.utc
            )
            self.iso_timestamp = dt.isoformat()
        if isinstance(self.category, str) and not isinstance(
            self.category, EventCategory
        ):
            try:
                self.category = EventCategory(self.category.lower())
            except ValueError:
                self.category = EventCategory.LIFECYCLE
        if isinstance(self.severity, str) and not isinstance(
            self.severity, EventSeverity
        ):
            try:
                self.severity = EventSeverity(self.severity.lower())
            except ValueError:
                self.severity = EventSeverity.INFO

    def to_dict(self) -> dict[str, Any]:
        """Serializes event to dictionary for JSONL disk persistence."""
        return {
            "timestamp_ns": self.timestamp_ns,
            "iso_timestamp": self.iso_timestamp,
            "category": (
                self.category.value
                if isinstance(self.category, EventCategory)
                else str(self.category)
            ),
            "severity": (
                self.severity.value
                if isinstance(self.severity, EventSeverity)
                else str(self.severity)
            ),
            "event_name": self.event_name,
            "mint": self.mint,
            "mint_name": self.mint_name,
            "latency_ms": self.latency_ms,
            "data": dict(self.data),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiagnosticEvent":
        """Deserializes event from dictionary."""
        raw_cat = payload.get("category", "lifecycle")
        raw_sev = payload.get("severity", "info")
        try:
            cat = EventCategory(str(raw_cat).lower())
        except ValueError:
            cat = EventCategory.LIFECYCLE
        try:
            sev = EventSeverity(str(raw_sev).lower())
        except ValueError:
            sev = EventSeverity.INFO

        return cls(
            timestamp_ns=int(payload.get("timestamp_ns", 0) or time.time_ns()),
            iso_timestamp=str(payload.get("iso_timestamp", "") or ""),
            category=cat,
            severity=sev,
            event_name=str(payload.get("event_name", "") or ""),
            mint=payload.get("mint"),
            mint_name=payload.get("mint_name"),
            latency_ms=(
                float(payload["latency_ms"])
                if payload.get("latency_ms") is not None
                else None
            ),
            data=dict(payload.get("data") or {}),
            error_message=payload.get("error_message"),
        )


def _coerce_category(category: EventCategory | str) -> EventCategory:
    if isinstance(category, EventCategory):
        return category
    try:
        return EventCategory(str(category).lower())
    except ValueError:
        return EventCategory.LIFECYCLE


def _coerce_severity(severity: EventSeverity | str) -> EventSeverity:
    if isinstance(severity, EventSeverity):
        return severity
    try:
        return EventSeverity(str(severity).lower())
    except ValueError:
        return EventSeverity.INFO


class DiagnosticEventLogger:
    """
    High-throughput, asynchronous, non-blocking diagnostic event writer.
    Uses an in-memory bounded queue and background worker task to flush
    batches of JSONL telemetry events to disk with zero latency impact
    on critical trading execution paths.
    """

    def __init__(
        self,
        output_path: str | Path = "events.jsonl",
        enabled_categories: Iterable[EventCategory | str] | None = None,
        max_queue_size: int = 10_000,
        batch_size: int = 100,
        flush_interval_seconds: float = 0.25,
        enabled: bool = True,
    ) -> None:
        self.output_path = Path(output_path)
        self.enabled = enabled
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self.enabled_categories: set[str] = {
            (c.value if isinstance(c, EventCategory) else str(c)).lower()
            for c in (
                enabled_categories
                if enabled_categories is not None
                else tuple(EventCategory)
            )
        }
        self._queue: asyncio.Queue[DiagnosticEvent] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._consumer_task: asyncio.Task[None] | None = None
        self._running = False
        self._dropped_events_count = 0
        self._total_emitted_count = 0
        self._total_written_count = 0
        self._file_handle: TextIO | None = None

    def is_category_enabled(self, category: EventCategory | str) -> bool:
        """Checks if a given category is enabled for logging."""
        cat_str = (
            category.value if isinstance(category, EventCategory) else str(category)
        ).lower()
        return cat_str in self.enabled_categories

    def emit(
        self,
        event: DiagnosticEvent | None = None,
        *,
        category: EventCategory | str = EventCategory.LIFECYCLE,
        severity: EventSeverity | str = EventSeverity.INFO,
        event_name: str = "",
        mint: str | None = None,
        mint_name: str | None = None,
        latency_ms: float | None = None,
        data: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> bool:
        """
        Emits a diagnostic event asynchronously into the in-memory queue.
        Guarantees non-blocking execution (<0.05ms) with backpressure resilience.
        """
        if not self.enabled:
            return False

        if event is None:
            # Normalise first so an unknown category or severity falls back to
            # LIFECYCLE / INFO (as ``DiagnosticEvent`` does) instead of raising
            # on the hot path (BUG-98).
            resolved_category = _coerce_category(category)
            if not self.is_category_enabled(resolved_category):
                return False
            event = DiagnosticEvent(
                category=resolved_category,
                severity=_coerce_severity(severity),
                event_name=event_name,
                mint=mint,
                mint_name=mint_name,
                latency_ms=latency_ms,
                data=data or {},
                error_message=error_message,
            )
        else:
            if not self.is_category_enabled(event.category):
                return False

        self._total_emitted_count += 1

        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._dropped_events_count += 1
            # If queue is full and incoming is critical/error, attempt to make room
            if event.severity in {EventSeverity.ERROR, EventSeverity.CRITICAL}:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    self._queue.put_nowait(event)
                    return True
                except Exception:
                    pass
            return False

    async def start(self) -> None:
        """Starts the background worker task and opens the file sink."""
        if not self.enabled or self._running:
            return

        self._running = True
        try:
            if self.output_path.parent and not self.output_path.parent.exists():
                os.makedirs(self.output_path.parent, exist_ok=True)
            self._file_handle = open(self.output_path, "a", encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Unable to open diagnostic event file at %s: %s",
                self.output_path,
                exc,
            )

        self._consumer_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        """Continuous background loop consuming events and flushing to disk."""
        batch: list[DiagnosticEvent] = []
        last_flush_time = time.monotonic()

        while self._running:
            try:
                # Wait for next event or timeout
                timeout = max(
                    0.05,
                    self.flush_interval_seconds - (time.monotonic() - last_flush_time),
                )
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                    batch.append(event)
                    self._queue.task_done()
                except asyncio.TimeoutError:
                    pass

                # Flush condition
                time_elapsed = (
                    time.monotonic() - last_flush_time
                ) >= self.flush_interval_seconds
                if len(batch) >= self.batch_size or (batch and time_elapsed):
                    self._write_batch(batch)
                    batch.clear()
                    last_flush_time = time.monotonic()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Error in diagnostic event worker loop: %s", exc)

        # Drain any remaining events in batch or queue
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                batch.append(event)
                self._queue.task_done()
            except Exception:
                break

        if batch:
            self._write_batch(batch)
            batch.clear()

    def _write_batch(self, batch: list[DiagnosticEvent]) -> None:
        """Writes a batch of serialized events to the open file sink."""
        if not batch or self._file_handle is None:
            return

        try:
            lines = [json.dumps(evt.to_dict(), sort_keys=True) + "\n" for evt in batch]
            self._file_handle.writelines(lines)
            self._file_handle.flush()
            self._total_written_count += len(batch)
        except Exception as exc:
            logger.warning("Failed to write diagnostic event batch: %s", exc)

    async def flush_and_close(self) -> None:
        """Flushes all queued events and shuts down the background worker."""
        if not self._running:
            return

        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

        # Process any remaining events in queue
        remaining: list[DiagnosticEvent] = []
        while not self._queue.empty():
            try:
                evt = self._queue.get_nowait()
                remaining.append(evt)
                self._queue.task_done()
            except Exception:
                break

        if remaining:
            self._write_batch(remaining)

        if self._file_handle is not None:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None

    def get_stats(self) -> dict[str, Any]:
        """Returns runtime performance statistics of the event logger."""
        return {
            "enabled": self.enabled,
            "output_path": str(self.output_path),
            "total_emitted": self._total_emitted_count,
            "total_written": self._total_written_count,
            "dropped_events": self._dropped_events_count,
            "pending_queue_size": self._queue.qsize(),
            "enabled_categories": sorted(self.enabled_categories),
        }


__all__ = [
    "DiagnosticEvent",
    "DiagnosticEventLogger",
    "EventCategory",
    "EventSeverity",
]
