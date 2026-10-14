import os
import tempfile
import time
from pathlib import Path

import pytest

from pumpfun_trading.ops.retention import (
    LogRetentionManager,
    RetentionPolicy,
    RotatedFileSink,
    compress_file_to_gzip,
)


def test_compress_file_to_gzip():
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "data.jsonl"
        src.write_text('{"event": "test"}\n', encoding="utf-8")

        gz_path = compress_file_to_gzip(src)
        assert gz_path.exists()
        assert gz_path.name.endswith(".gz")
        assert not src.exists()


def test_rotated_file_sink_size_rotation_and_compression():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_file = Path(tmpdir) / "audit_trail.jsonl"
        policy = RetentionPolicy(
            max_bytes=100,
            max_files=3,
            max_age_days=30,
            compress_archives=True,
        )
        sink = RotatedFileSink(base_file, policy=policy)

        # Write lines to exceed 100 bytes multiple times
        for i in range(20):
            sink.write_line(f'{{"record": {i}, "payload": "{"X" * 30}"}}')

        sink.flush()
        sink.close()

        # Let background compression threads finish
        time.sleep(0.3)

        files = list(Path(tmpdir).glob("audit_trail.jsonl*"))
        assert len(files) >= 2


@pytest.mark.asyncio
async def test_rotated_file_sink_async_write_batch():
    with tempfile.TemporaryDirectory() as tmpdir:
        base_file = Path(tmpdir) / "replay.jsonl"
        policy = RetentionPolicy(
            max_bytes=200,
            max_files=2,
            compress_archives=False,
        )
        sink = RotatedFileSink(base_file, policy=policy)

        lines = [f'{{"step": {i}, "msg": "{"Y" * 40}"}}' for i in range(15)]
        await sink.write_batch_async(lines)
        sink.close()

        files = list(Path(tmpdir).glob("replay.jsonl*"))
        assert len(files) >= 2


def test_log_retention_manager_pruning_and_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        policy = RetentionPolicy(
            max_bytes=1024,
            max_files=5,
            max_age_days=10,
            total_max_bytes=1000,
            compress_archives=True,
        )
        manager = LogRetentionManager(td, policy=policy)

        # Create files of varying ages
        now = time.time()
        file1 = td / "old_audit.jsonl.1.gz"
        file1.write_text("old data", encoding="utf-8")
        os.utime(file1, (now - 15 * 86400, now - 15 * 86400))

        file2 = td / "recent_audit.jsonl"
        file2.write_text("recent data", encoding="utf-8")
        os.utime(file2, (now - 86400, now - 86400))

        # Test stats
        stats = manager.get_storage_stats()
        assert stats["exists"] is True
        assert stats["file_count"] == 2
        assert stats["compressed_count"] == 1

        # Test age pruning
        pruned = manager.prune_expired(now=now)
        assert len(pruned) == 1
        assert file1 not in list(td.glob("*"))
        assert file2.exists()


def test_log_retention_manager_compress_uncompressed():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        manager = LogRetentionManager(td)

        f1 = td / "bot.log.1"
        f1.write_text("uncompressed log chunk", encoding="utf-8")

        compressed = manager.compress_uncompressed_archives()
        assert len(compressed) == 1
        assert (td / "bot.log.1.gz").exists()
        assert not f1.exists()


@pytest.mark.asyncio
async def test_log_retention_manager_async_pruning():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        policy = RetentionPolicy(max_age_days=5)
        manager = LogRetentionManager(td, policy=policy)

        now = time.time()
        f1 = td / "expired.log.1.gz"
        f1.write_text("old", encoding="utf-8")
        os.utime(f1, (now - 10 * 86400, now - 10 * 86400))

        pruned = await manager.prune_expired_async(now=now)
        assert len(pruned) == 1
        assert not f1.exists()
