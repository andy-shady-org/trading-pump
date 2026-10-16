import logging
import logging.handlers
import tempfile
import time
from pathlib import Path

from pumpfun_trading.ops.logging import (
    gzip_namer,
    gzip_rotator,
    setup_structured_logging,
)


def test_gzip_namer_and_rotator():
    assert gzip_namer("bot.log.1") == "bot.log.1.gz"
    assert gzip_namer("bot.log.1.gz") == "bot.log.1.gz"

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "test.log"
        dst = Path(tmpdir) / "test.log.gz"
        src.write_text("hello world " * 100, encoding="utf-8")

        gzip_rotator(str(src), str(dst))
        assert dst.exists()
        assert not src.exists()


def test_setup_structured_logging_size_rotation():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "bot.log"
        logger = setup_structured_logging(
            logger_name="test_size_rot",
            log_file=str(log_file),
            max_bytes=200,
            backup_count=3,
            rotation_type="size",
            compress=True,
        )

        for i in range(25):
            logger.info("Message %03d: %s", i, "X" * 50)

        # Check that files were created and rotated
        files = list(Path(tmpdir).glob("bot.log*"))
        assert len(files) >= 2


def test_setup_structured_logging_time_rotation():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "bot_time.log"
        logger = setup_structured_logging(
            logger_name="test_time_rot",
            log_file=str(log_file),
            rotation_type="time",
            when="S",
            interval=1,
            backup_count=2,
            compress=False,
        )

        logger.info("Log line 1")
        # Make the next record due for rollover instead of waiting a second.
        (handler,) = [
            h
            for h in logger.handlers
            if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        handler.rolloverAt = int(time.time())
        logger.info("Log line 2")

        files = list(Path(tmpdir).glob("bot_time.log*"))
        assert len(files) == 2
        assert log_file.read_text(encoding="utf-8").count("Log line 2") == 1


def test_setup_structured_logging_none_rotation():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "bot_none.log"
        logger = setup_structured_logging(
            logger_name="test_none_rot",
            log_file=str(log_file),
            rotation_type="none",
        )

        logger.info("Single line without rotation")
        assert log_file.exists()
