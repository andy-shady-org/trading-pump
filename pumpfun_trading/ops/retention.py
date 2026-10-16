"""Automated file retention, async-safe multi-sink rollover, and archive compression engine (FEAT-22)."""

from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionPolicy:
    """Configurable retention and rotation policy across file sinks."""

    max_bytes: int = 10 * 1024 * 1024  # 10 MB per chunk
    max_files: int = 10  # Maximum number of retained backup archives per sink
    max_age_days: int = 30  # Max age in days before pruning
    compress_archives: bool = True  # Automatically gzip old archives (.gz)
    total_max_bytes: int | None = None  # Optional cap on total directory/archive bytes


def compress_file_to_gzip(source: Path | str, dest: Path | str | None = None) -> Path:
    """Compress a single file to a .gz archive using an atomic temporary swap."""
    src_path = Path(source)
    if not src_path.exists() or src_path.stat().st_size == 0:
        return src_path

    dst_path = Path(dest) if dest else Path(f"{src_path}.gz")
    tmp_path = Path(f"{dst_path}.tmp")

    if dst_path.parent:
        dst_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        open(src_path, "rb") as f_in,
        gzip.open(tmp_path, "wb", compresslevel=6) as f_out,
    ):
        shutil.copyfileobj(f_in, f_out)

    tmp_path.replace(dst_path)
    try:
        src_path.unlink()
    except OSError:
        pass
    return dst_path


class RotatedFileSink:
    """Thread-safe, high-throughput rotating file sink with background gzip compression."""

    def __init__(
        self,
        base_path: Path | str,
        policy: RetentionPolicy | None = None,
        encoding: str = "utf-8",
    ) -> None:
        self.base_path = Path(base_path)
        self.policy = policy or RetentionPolicy()
        self.encoding = encoding
        self._lock = threading.Lock()
        self._file: Any | None = None
        self._current_size = 0

        self._ensure_dir()
        self._open_file()

    def _ensure_dir(self) -> None:
        if self.base_path.parent:
            self.base_path.parent.mkdir(parents=True, exist_ok=True)

    def _open_file(self) -> None:
        if self.base_path.exists():
            self._current_size = self.base_path.stat().st_size
        else:
            self._current_size = 0
        self._file = open(self.base_path, "a", encoding=self.encoding, buffering=1)

    def write_line(self, line: str) -> None:
        """Write a single text line to disk, triggering rotation if size threshold is reached."""
        with self._lock:
            self.rotate_if_needed()
            if not line.endswith("\n"):
                line = line + "\n"
            encoded = line.encode(self.encoding)
            if self._file is not None:
                self._file.write(line)
                self._current_size += len(encoded)
            self.rotate_if_needed()

    def write_batch(self, lines: list[str]) -> None:
        """Write multiple text lines atomically to disk."""
        if not lines:
            return
        with self._lock:
            self.rotate_if_needed()
            payload_lines: list[str] = []
            byte_count = 0
            for line in lines:
                if not line.endswith("\n"):
                    line = line + "\n"
                payload_lines.append(line)
                byte_count += len(line.encode(self.encoding))

            if self._file is not None:
                self._file.writelines(payload_lines)
                self._file.flush()
                self._current_size += byte_count
            self.rotate_if_needed()

    async def write_batch_async(self, lines: list[str]) -> None:
        """Asynchronously write a batch of lines off the main asyncio loop."""
        await asyncio.to_thread(self.write_batch, lines)

    def rotate_if_needed(self) -> bool:
        """Check current file size and rotate if policy max_bytes is exceeded."""
        if self.policy.max_bytes <= 0:
            return False
        if self._current_size < self.policy.max_bytes:
            return False

        return self.rotate_now()

    def rotate_now(self) -> bool:
        """Force an immediate file rotation and dispatch background compression."""
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            self._file = None

        if not self.base_path.exists():
            self._open_file()
            return False

        max_files = max(1, self.policy.max_files)

        # Shift existing backup files
        for i in range(max_files - 1, 0, -1):
            sfn = self._get_rotated_filename(i)
            dfn = self._get_rotated_filename(i + 1)
            if sfn.exists():
                if dfn.exists():
                    try:
                        dfn.unlink()
                    except OSError:
                        pass
                try:
                    sfn.rename(dfn)
                except OSError:
                    pass

        # Target file 1
        target_dest = self._get_rotated_filename(1, compressed=False)
        target_gz = self._get_rotated_filename(1, compressed=True)

        if target_dest.exists():
            try:
                target_dest.unlink()
            except OSError:
                pass
        if target_gz.exists():
            try:
                target_gz.unlink()
            except OSError:
                pass

        try:
            self.base_path.replace(target_dest)
        except OSError as exc:
            logger.warning(
                "Failed to rotate file %s to %s: %s",
                self.base_path,
                target_dest,
                exc,
            )

        # Prune any files beyond max_files
        oldest_candidate = self._get_rotated_filename(max_files + 1)
        if oldest_candidate.exists():
            try:
                oldest_candidate.unlink()
            except OSError:
                pass
        oldest_uncompressed = self._get_rotated_filename(
            max_files + 1, compressed=False
        )
        if oldest_uncompressed.exists():
            try:
                oldest_uncompressed.unlink()
            except OSError:
                pass

        # Reopen main file
        self._open_file()

        # Compress target_dest in background thread if configured
        if self.policy.compress_archives and target_dest.exists():
            threading.Thread(
                target=compress_file_to_gzip,
                args=(target_dest, target_gz),
                daemon=True,
            ).start()

        return True

    def _get_rotated_filename(self, index: int, compressed: bool | None = None) -> Path:
        is_comp = self.policy.compress_archives if compressed is None else compressed
        base_str = str(self.base_path)
        if is_comp:
            # Check if index.gz exists or return default
            gz_path = Path(f"{base_str}.{index}.gz")
            uncomp_path = Path(f"{base_str}.{index}")
            if gz_path.exists():
                return gz_path
            if uncomp_path.exists() and compressed is None:
                return uncomp_path
            return gz_path
        return Path(f"{base_str}.{index}")

    def flush(self) -> None:
        """Flush internal file buffer to disk."""
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                except Exception:
                    pass

    def close(self) -> None:
        """Close active file handle cleanly."""
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                self._file = None


class LogRetentionManager:
    """Manages disk retention policies, expired archive pruning, and batch compression."""

    def __init__(
        self,
        target_directory: Path | str,
        policy: RetentionPolicy | None = None,
        file_patterns: tuple[str, ...] = ("*.log*", "*.jsonl*"),
    ) -> None:
        self.target_directory = Path(target_directory)
        self.policy = policy or RetentionPolicy()
        self.file_patterns = file_patterns

    def prune_expired(self, now: float | None = None) -> list[Path]:
        """Prune archives older than max_age_days or exceeding quota constraints."""
        if not self.target_directory.exists():
            return []

        current_time = now if now is not None else time.time()
        max_age_seconds = self.policy.max_age_days * 86400.0
        pruned_files: list[Path] = []

        # Only rotated archives matching the log patterns are ever candidates; live
        # sinks (`events.jsonl`, `bot.log`) and unrelated files are never touched (BUG-64).
        unique_files = self._archive_candidates()

        for file_path in unique_files:
            try:
                stat = file_path.stat()
                age = current_time - stat.st_mtime
                if self.policy.max_age_days > 0 and age > max_age_seconds:
                    file_path.unlink(missing_ok=True)
                    pruned_files.append(file_path)
            except OSError as exc:
                logger.warning("Error pruning file %s: %s", file_path, exc)

        # Count-based pruning: keep the newest `max_files` archives per sink.
        if self.policy.max_files > 0:
            by_sink: dict[str, list[Path]] = {}
            for file_path in unique_files:
                if file_path not in pruned_files:
                    by_sink.setdefault(self._sink_name(file_path), []).append(file_path)
            for archives in by_sink.values():
                excess = len(archives) - self.policy.max_files
                for file_path in archives[: max(0, excess)]:
                    try:
                        file_path.unlink(missing_ok=True)
                        pruned_files.append(file_path)
                    except OSError as exc:
                        logger.warning("Error pruning file %s: %s", file_path, exc)

        # Quota-based pruning if total_max_bytes is specified
        if self.policy.total_max_bytes is not None and self.policy.total_max_bytes > 0:
            remaining_files = [f for f in unique_files if f not in pruned_files]
            total_size = sum(f.stat().st_size for f in remaining_files)
            while total_size > self.policy.total_max_bytes and remaining_files:
                oldest = remaining_files.pop(0)
                try:
                    f_size = oldest.stat().st_size
                    oldest.unlink(missing_ok=True)
                    pruned_files.append(oldest)
                    total_size -= f_size
                except OSError:
                    pass

        return pruned_files

    @staticmethod
    def _is_rotated_archive(path: Path) -> bool:
        """True for rotated/compressed archives such as `bot.log.1` or `x.jsonl.2.gz`."""
        if path.name.endswith(".gz"):
            return True
        parts = path.name.split(".")
        return len(parts) >= 3 and parts[-1].isdigit()

    @staticmethod
    def _sink_name(path: Path) -> str:
        parts = path.name.split(".")
        if parts and parts[-1] == "gz":
            parts = parts[:-1]
        if len(parts) >= 3 and parts[-1].isdigit():
            parts = parts[:-1]
        return ".".join(parts)

    def _archive_candidates(self) -> list[Path]:
        """Rotated archives matching `file_patterns`, oldest first."""
        found: set[Path] = set()
        for pattern in self.file_patterns:
            found.update(
                f
                for f in self.target_directory.glob(pattern)
                if f.is_file() and self._is_rotated_archive(f)
            )
        return sorted(found, key=lambda p: p.stat().st_mtime)

    async def prune_expired_async(self, now: float | None = None) -> list[Path]:
        """Asynchronous wrapper for prune_expired offloading to worker thread."""
        return await asyncio.to_thread(self.prune_expired, now)

    def compress_uncompressed_archives(self) -> list[Path]:
        """Compress any uncompressed rotated files (*.1, *.2, etc.) to .gz."""
        if not self.target_directory.exists():
            return []

        compressed: list[Path] = []
        for pattern in self.file_patterns:
            for file_path in self.target_directory.glob(pattern):
                if file_path.is_file() and not file_path.name.endswith(".gz"):
                    # Check if it has a numeric suffix like .log.1, .jsonl.2
                    parts = file_path.name.split(".")
                    if len(parts) >= 3 and parts[-1].isdigit():
                        gz_path = compress_file_to_gzip(file_path)
                        compressed.append(gz_path)
        return compressed

    def get_storage_stats(self) -> dict[str, Any]:
        """Calculate disk consumption metrics and file counts."""
        if not self.target_directory.exists():
            return {
                "directory": str(self.target_directory),
                "exists": False,
                "file_count": 0,
                "total_bytes": 0,
                "total_human": "0 B",
                "compressed_count": 0,
            }

        files: list[Path] = []
        for pattern in self.file_patterns:
            files.extend(self.target_directory.glob(pattern))

        unique_files = list({f for f in files if f.is_file()})
        total_bytes = sum(f.stat().st_size for f in unique_files)
        compressed_count = sum(1 for f in unique_files if f.name.endswith(".gz"))
        oldest_mtime = min((f.stat().st_mtime for f in unique_files), default=None)

        def _format_bytes(size: int) -> str:
            units = ["B", "KB", "MB", "GB", "TB"]
            idx = 0
            val = float(size)
            while val >= 1024.0 and idx < len(units) - 1:
                val /= 1024.0
                idx += 1
            return f"{val:.2f} {units[idx]}"

        return {
            "directory": str(self.target_directory),
            "exists": True,
            "file_count": len(unique_files),
            "total_bytes": total_bytes,
            "total_human": _format_bytes(total_bytes),
            "compressed_count": compressed_count,
            "oldest_timestamp": oldest_mtime,
        }


__all__ = [
    "LogRetentionManager",
    "RetentionPolicy",
    "RotatedFileSink",
    "compress_file_to_gzip",
]
