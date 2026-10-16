"""Unit tests for ``ops/retention.py`` (rotating sinks, gzip archives and pruning)."""

from __future__ import annotations

import gzip
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pumpfun_trading.ops import retention
from pumpfun_trading.ops.retention import (
    LogRetentionManager,
    RetentionPolicy,
    RotatedFileSink,
    compress_file_to_gzip,
)

DAY = 86400.0
NOW = 1_800_000_000.0


class _SyncThread:
    """``threading.Thread`` stand-in that runs the target inline on ``start``."""

    def __init__(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        daemon: bool | None = None,
    ) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)

    def is_alive(self) -> bool:
        return False


class _ExplodingFile:
    """File double whose flush/close/write raise."""

    def write(self, data: str) -> None:
        raise OSError("boom")

    def flush(self) -> None:
        raise OSError("boom")

    def close(self) -> None:
        raise OSError("boom")


def _no_compress(max_bytes: int = 0, max_files: int = 3) -> RetentionPolicy:
    return RetentionPolicy(
        max_bytes=max_bytes, max_files=max_files, compress_archives=False
    )


def _write(path: Path, content: str, mtime: float | None = None) -> Path:
    path.write_text(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _fail_unlink_for(
    monkeypatch: pytest.MonkeyPatch, names: set[str] | None = None
) -> list[str]:
    """Make ``Path.unlink`` raise for ``names`` (or for every path when None)."""
    attempts: list[str] = []
    real_unlink = Path.unlink

    def fake_unlink(self: Path, missing_ok: bool = False) -> None:
        if names is None or self.name in names:
            attempts.append(self.name)
            raise PermissionError(f"locked: {self.name}")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    return attempts


# --- compress_file_to_gzip -------------------------------------------------------


@pytest.mark.parametrize("content", [None, ""])
def test_compress_file_to_gzip_missing_or_empty_returns_source(
    tmp_path: Path, content: str | None
) -> None:
    src = tmp_path / "bot.log.1"
    if content is not None:
        src.write_text(content)

    assert compress_file_to_gzip(src) == src
    assert not Path(f"{src}.gz").exists()


def test_compress_file_to_gzip_default_dest_replaces_source(tmp_path: Path) -> None:
    src = _write(tmp_path / "bot.log.1", "hello\nworld\n")

    result = compress_file_to_gzip(src)

    assert result == tmp_path / "bot.log.1.gz"
    assert not src.exists()
    assert not Path(f"{result}.tmp").exists()
    assert gzip.decompress(result.read_bytes()) == b"hello\nworld\n"


def test_compress_file_to_gzip_custom_dest_creates_parent(tmp_path: Path) -> None:
    src = _write(tmp_path / "x.jsonl.2", "{}\n")
    dest = tmp_path / "archive" / "deep" / "x.gz"

    assert compress_file_to_gzip(src, dest) == dest
    assert gzip.decompress(dest.read_bytes()) == b"{}\n"


# --- RotatedFileSink --------------------------------------------------------------


def test_sink_write_line_appends_newline_and_tracks_size(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "e.jsonl"
    sink = RotatedFileSink(path, _no_compress())

    sink.write_line("one")
    sink.write_line("two\n")
    sink.close()

    assert path.read_text() == "one\ntwo\n"
    assert sink._current_size == 8


def test_sink_reopen_existing_file_resumes_size(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", "12345\n")

    sink = RotatedFileSink(path, _no_compress())

    assert sink._current_size == 6
    sink.close()


def test_sink_write_line_over_threshold_rotates_to_numbered_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bot.log"
    sink = RotatedFileSink(path, _no_compress(max_bytes=10))

    sink.write_line("0123456789")
    sink.write_line("next")
    sink.close()

    assert (tmp_path / "bot.log.1").read_text() == "0123456789\n"
    assert path.read_text() == "next\n"


def test_sink_write_batch_joins_lines_and_rotates(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    sink = RotatedFileSink(path, _no_compress(max_bytes=4))

    sink.write_batch([])
    assert path.read_text() == ""
    sink.write_batch(["a", "b\n", "c"])
    sink.close()

    assert (tmp_path / "e.jsonl.1").read_text() == "a\nb\nc\n"
    assert path.read_text() == ""


async def test_sink_write_batch_async_writes_lines(tmp_path: Path) -> None:
    path = tmp_path / "e.jsonl"
    sink = RotatedFileSink(path, _no_compress())

    await sink.write_batch_async(["x", "y"])
    sink.close()

    assert path.read_text() == "x\ny\n"


@pytest.mark.parametrize("method", ["write_line", "write_batch"])
def test_sink_write_without_open_handle_is_dropped(tmp_path: Path, method: str) -> None:
    path = tmp_path / "e.jsonl"
    sink = RotatedFileSink(path, _no_compress())
    sink.close()

    if method == "write_line":
        sink.write_line("lost")
    else:
        sink.write_batch(["lost"])

    assert sink._current_size == 0
    assert path.read_text() == ""


def test_sink_flush_and_close_without_handle_are_noops(tmp_path: Path) -> None:
    sink = RotatedFileSink(tmp_path / "e.jsonl", _no_compress())
    sink.close()

    sink.flush()
    sink.close()

    assert sink._file is None


def test_sink_flush_and_close_swallow_handle_errors(tmp_path: Path) -> None:
    sink = RotatedFileSink(tmp_path / "e.jsonl", _no_compress())
    sink.close()
    sink._file = _ExplodingFile()

    sink.flush()
    sink.close()

    assert sink._file is None


def test_sink_rotate_now_base_missing_reopens_without_rotation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "e.jsonl"
    sink = RotatedFileSink(path, _no_compress())
    sink.close()
    path.unlink()

    assert sink.rotate_now() is False

    assert path.exists()
    assert sink._file is not None
    assert not (tmp_path / "e.jsonl.1").exists()
    sink.close()


def test_sink_rotate_now_close_error_still_rotates(tmp_path: Path) -> None:
    path = _write(tmp_path / "e.jsonl", "data\n")
    sink = RotatedFileSink(path, _no_compress())
    sink.close()
    sink._file = _ExplodingFile()

    assert sink.rotate_now() is True
    sink.close()

    assert (tmp_path / "e.jsonl.1").read_text() == "data\n"
    assert path.read_text() == ""


def test_sink_rotate_now_single_slot_overwrites_previous_backup(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "bot.log", "new\n")
    _write(tmp_path / "bot.log.1", "old\n")
    sink = RotatedFileSink(path, _no_compress(max_files=1))

    assert sink.rotate_now() is True
    sink.close()

    assert (tmp_path / "bot.log.1").read_text() == "new\n"
    assert not (tmp_path / "bot.log.2").exists()


def test_sink_rotate_now_shifts_backups_and_prunes_overflow(tmp_path: Path) -> None:
    path = _write(tmp_path / "bot.log", "current\n")
    _write(tmp_path / "bot.log.1", "one\n")
    _write(tmp_path / "bot.log.3", "stale\n")
    sink = RotatedFileSink(path, _no_compress(max_files=2))

    assert sink.rotate_now() is True
    sink.close()

    assert (tmp_path / "bot.log.1").read_text() == "current\n"
    assert (tmp_path / "bot.log.2").read_text() == "one\n"
    assert not (tmp_path / "bot.log.3").exists()


def test_sink_rotate_now_compressed_prunes_both_overflow_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention.threading, "Thread", _SyncThread)
    path = _write(tmp_path / "e.jsonl", "live\n")
    gz_old = tmp_path / "e.jsonl.3.gz"
    gz_old.write_bytes(gzip.compress(b"stale-gz\n"))
    _write(tmp_path / "e.jsonl.3", "stale-raw\n")
    sink = RotatedFileSink(path, RetentionPolicy(max_bytes=0, max_files=2))

    assert sink.rotate_now() is True
    sink.close()

    assert not gz_old.exists()
    assert not (tmp_path / "e.jsonl.3").exists()
    assert not (tmp_path / "e.jsonl.1").exists()
    archived = tmp_path / "e.jsonl.1.gz"
    assert gzip.decompress(archived.read_bytes()) == b"live\n"


def test_sink_rotate_now_compressed_shifts_existing_gz_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention.threading, "Thread", _SyncThread)
    path = _write(tmp_path / "e.jsonl", "second\n")
    (tmp_path / "e.jsonl.1.gz").write_bytes(gzip.compress(b"first\n"))
    sink = RotatedFileSink(path, RetentionPolicy(max_bytes=0, max_files=3))

    assert sink.rotate_now() is True
    sink.close()

    assert gzip.decompress((tmp_path / "e.jsonl.2.gz").read_bytes()) == b"first\n"
    assert gzip.decompress((tmp_path / "e.jsonl.1.gz").read_bytes()) == b"second\n"


class _PendingThread:
    """``threading.Thread`` stand-in that never runs: compression is still pending."""

    started: list["_PendingThread"] = []

    def __init__(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        daemon: bool | None = None,
    ) -> None:
        self._target = target
        self._args = args
        self.joined = False

    def start(self) -> None:
        _PendingThread.started.append(self)

    def is_alive(self) -> bool:
        return not self.joined

    def join(self, timeout: float | None = None) -> None:
        self.joined = True


def test_sink_rotate_now_uncompressed_backup_keeps_plain_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-97: a not-yet-gzipped ``.1`` is shifted to ``.2``, never ``.2.gz``."""
    monkeypatch.setattr(retention.threading, "Thread", _PendingThread)
    path = _write(tmp_path / "b.log", "current\n")
    _write(tmp_path / "b.log.1", "pending-raw\n")
    (tmp_path / "b.log.2.gz").write_bytes(gzip.compress(b"older\n"))
    sink = RotatedFileSink(path, RetentionPolicy(max_bytes=0, max_files=3))

    assert sink.rotate_now() is True
    sink.close()

    assert (tmp_path / "b.log.2").read_text() == "pending-raw\n"
    assert not (tmp_path / "b.log.2.gz").exists()
    assert gzip.decompress((tmp_path / "b.log.3.gz").read_bytes()) == b"older\n"
    assert (tmp_path / "b.log.1").read_text() == "current\n"


def test_sink_rotate_now_waits_for_previous_compression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-97: the next rotation joins the running gzip before shifting ``.1``."""
    _PendingThread.started.clear()
    monkeypatch.setattr(retention.threading, "Thread", _PendingThread)
    path = _write(tmp_path / "b.log", "first\n")
    sink = RotatedFileSink(path, RetentionPolicy(max_bytes=0, max_files=3))

    assert sink.rotate_now() is True
    first = _PendingThread.started[-1]
    assert first.joined is False
    sink.write_line("second")
    assert sink.rotate_now() is True
    sink.close()

    assert first.joined is True
    assert sink._compress_thread is _PendingThread.started[-1]
    assert (tmp_path / "b.log.2").read_text() == "first\n"


def test_sink_rotate_now_compression_still_running_after_timeout_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _StuckThread(_PendingThread):
        def join(self, timeout: float | None = None) -> None:
            assert timeout == retention.COMPRESSION_JOIN_TIMEOUT_SECONDS

    monkeypatch.setattr(retention.threading, "Thread", _StuckThread)
    path = _write(tmp_path / "b.log", "first\n")
    sink = RotatedFileSink(path, RetentionPolicy(max_bytes=0, max_files=3))
    sink.rotate_now()
    stuck = sink._compress_thread
    sink.write_line("second")

    with caplog.at_level(logging.WARNING, logger=retention.logger.name):
        assert sink.rotate_now() is True
    sink.close()

    assert "still running" in caplog.text
    assert sink._compress_thread is not stuck


def test_compress_quietly_logs_and_keeps_source_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    src = _write(tmp_path / "b.log.1", "raw\n")

    def boom(source: Path, dest: Path | None = None) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(retention, "compress_file_to_gzip", boom)
    with caplog.at_level(logging.WARNING, logger=retention.logger.name):
        retention._compress_quietly(src, tmp_path / "b.log.1.gz")

    assert "Failed to compress" in caplog.text
    assert src.read_text() == "raw\n"


def test_sink_rotate_now_filesystem_errors_are_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path / "bot.log", "current\n")
    _write(tmp_path / "bot.log.1", "one\n")
    _write(tmp_path / "bot.log.2", "two\n")
    _write(tmp_path / "bot.log.3", "stale\n")
    (tmp_path / "bot.log.1.gz").write_bytes(b"gz")
    sink = RotatedFileSink(path, _no_compress(max_files=2))
    attempts = _fail_unlink_for(monkeypatch)

    def fail_rename(self: Path, target: Any) -> Path:
        raise PermissionError("rename blocked")

    monkeypatch.setattr(Path, "rename", fail_rename)

    assert sink.rotate_now() is True
    sink.close()

    assert attempts == [
        "bot.log.2",
        "bot.log.1",
        "bot.log.1.gz",
        "bot.log.3",
    ]
    assert (tmp_path / "bot.log.1").read_text() == "current\n"
    assert (tmp_path / "bot.log.2").read_text() == "two\n"
    assert (tmp_path / "bot.log.3").read_text() == "stale\n"
    assert path.read_text() == ""


def test_sink_rotate_now_replace_failure_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path / "bot.log", "current\n")
    sink = RotatedFileSink(path, _no_compress())

    def fail_replace(self: Path, target: Any) -> Path:
        raise PermissionError("replace blocked")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with caplog.at_level(logging.WARNING, logger="pumpfun_trading.ops.retention"):
        assert sink.rotate_now() is True
    sink.close()

    assert "Failed to rotate file" in caplog.text
    assert path.read_text() == "current\n"
    assert not (tmp_path / "bot.log.1").exists()


def test_sink_rotated_filename_prefers_existing_variant(tmp_path: Path) -> None:
    sink = RotatedFileSink(tmp_path / "e.jsonl", RetentionPolicy(max_bytes=0))
    sink.close()
    raw = _write(tmp_path / "e.jsonl.1", "x")

    assert sink._get_rotated_filename(1) == raw
    assert sink._get_rotated_filename(1, compressed=True) == tmp_path / "e.jsonl.1.gz"
    assert sink._get_rotated_filename(2) == tmp_path / "e.jsonl.2.gz"


# --- LogRetentionManager ----------------------------------------------------------


def test_manager_prune_missing_directory_returns_empty(tmp_path: Path) -> None:
    manager = LogRetentionManager(tmp_path / "absent")

    assert manager.prune_expired(now=NOW) == []
    assert manager.compress_uncompressed_archives() == []


def test_manager_prune_expired_removes_only_old_archives(tmp_path: Path) -> None:
    old = _write(tmp_path / "bot.log.2", "old", NOW - 40 * DAY)
    fresh = _write(tmp_path / "bot.log.1", "fresh", NOW - 1 * DAY)
    live = _write(tmp_path / "bot.log", "live", NOW - 90 * DAY)
    other = _write(tmp_path / "notes.txt.1", "x", NOW - 90 * DAY)
    manager = LogRetentionManager(tmp_path, RetentionPolicy(max_files=0))

    assert manager.prune_expired(now=NOW) == [old]

    assert fresh.exists() and live.exists() and other.exists()


async def test_manager_prune_expired_async_matches_sync(tmp_path: Path) -> None:
    old = _write(tmp_path / "x.jsonl.1.gz", "old", NOW - 31 * DAY)
    manager = LogRetentionManager(tmp_path)

    assert await manager.prune_expired_async(now=NOW) == [old]
    assert not old.exists()


def test_manager_prune_count_keeps_newest_per_sink(tmp_path: Path) -> None:
    b3 = _write(tmp_path / "bot.log.3.gz", "3", NOW - 3 * DAY)
    b2 = _write(tmp_path / "bot.log.2.gz", "2", NOW - 2 * DAY)
    b1 = _write(tmp_path / "bot.log.1", "1", NOW - 1 * DAY)
    e1 = _write(tmp_path / "e.jsonl.1.gz", "e", NOW - 5 * DAY)
    manager = LogRetentionManager(tmp_path, RetentionPolicy(max_files=2))

    assert manager.prune_expired(now=NOW) == [b3]

    assert b2.exists() and b1.exists() and e1.exists()


def test_manager_prune_stat_error_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ghost = tmp_path / "bot.log.1"
    manager = LogRetentionManager(tmp_path, RetentionPolicy(max_files=0))
    monkeypatch.setattr(manager, "_archive_candidates", lambda: [ghost])

    with caplog.at_level(logging.WARNING, logger="pumpfun_trading.ops.retention"):
        assert manager.prune_expired(now=NOW) == []

    assert "Error pruning file" in caplog.text


def test_manager_prune_count_unlink_error_keeps_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    oldest = _write(tmp_path / "bot.log.2", "2", NOW - 2 * DAY)
    _write(tmp_path / "bot.log.1", "1", NOW - 1 * DAY)
    manager = LogRetentionManager(tmp_path, RetentionPolicy(max_files=1))
    _fail_unlink_for(monkeypatch, {"bot.log.2"})

    with caplog.at_level(logging.WARNING, logger="pumpfun_trading.ops.retention"):
        assert manager.prune_expired(now=NOW) == []

    assert oldest.exists()
    assert "Error pruning file" in caplog.text


def test_manager_prune_quota_removes_oldest_until_under_cap(tmp_path: Path) -> None:
    a = _write(tmp_path / "bot.log.3", "a" * 10, NOW - 3 * DAY)
    b = _write(tmp_path / "bot.log.2", "b" * 10, NOW - 2 * DAY)
    c = _write(tmp_path / "bot.log.1", "c" * 10, NOW - 1 * DAY)
    manager = LogRetentionManager(
        tmp_path, RetentionPolicy(max_files=0, total_max_bytes=15)
    )

    assert manager.prune_expired(now=NOW) == [a, b]

    assert c.exists()


def test_manager_prune_quota_unlink_error_skips_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _write(tmp_path / "bot.log.2", "a" * 10, NOW - 2 * DAY)
    b = _write(tmp_path / "bot.log.1", "b" * 10, NOW - 1 * DAY)
    manager = LogRetentionManager(
        tmp_path, RetentionPolicy(max_files=0, total_max_bytes=15)
    )
    _fail_unlink_for(monkeypatch, {"bot.log.2"})

    assert manager.prune_expired(now=NOW) == [b]

    assert a.exists()
    assert not b.exists()


@pytest.mark.parametrize(
    ("name", "sink"),
    [
        ("bot.log.1", "bot.log"),
        ("bot.log.2.gz", "bot.log"),
        ("events.jsonl.gz", "events.jsonl"),
        ("bot.log", "bot.log"),
    ],
)
def test_manager_sink_name_strips_rotation_suffixes(name: str, sink: str) -> None:
    assert LogRetentionManager._sink_name(Path(name)) == sink


def test_manager_compress_uncompressed_archives_only_numbered_files(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "bot.log.1", "one\n")
    _write(tmp_path / "bot.log", "live\n")
    _write(tmp_path / "e.jsonl.2.gz", "gz")
    (tmp_path / "dir.log.3").mkdir()
    manager = LogRetentionManager(tmp_path)

    assert manager.compress_uncompressed_archives() == [tmp_path / "bot.log.1.gz"]

    assert gzip.decompress((tmp_path / "bot.log.1.gz").read_bytes()) == b"one\n"
    assert (tmp_path / "bot.log").read_text() == "live\n"
    assert (tmp_path / "e.jsonl.2.gz").read_text() == "gz"


def test_manager_storage_stats_missing_directory(tmp_path: Path) -> None:
    stats = LogRetentionManager(tmp_path / "absent").get_storage_stats()

    assert stats["exists"] is False
    assert stats["file_count"] == 0
    assert stats["total_human"] == "0 B"


def test_manager_storage_stats_counts_and_formats(tmp_path: Path) -> None:
    _write(tmp_path / "bot.log", "x" * 2048, NOW - 5)
    gz = tmp_path / "bot.log.1.gz"
    gz.write_bytes(b"y" * 1024)
    os.utime(gz, (NOW, NOW))
    _write(tmp_path / "readme.md", "ignored")
    (tmp_path / "sub.log").mkdir()

    stats = LogRetentionManager(tmp_path).get_storage_stats()

    assert stats["exists"] is True
    assert stats["file_count"] == 2
    assert stats["total_bytes"] == 3072
    assert stats["total_human"] == "3.00 KB"
    assert stats["compressed_count"] == 1
    assert stats["oldest_timestamp"] == pytest.approx(NOW - 5)
