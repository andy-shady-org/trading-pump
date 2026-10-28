import io
import logging
import logging.handlers
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from pumpfun_trading.ops.logging import (
    AnsiStrippingFormatter,
    get_configured_console,
    gzip_namer,
    gzip_rotator,
    is_color_enabled,
    log_runtime_event,
    setup_structured_logging,
    strip_ansi,
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


@pytest.mark.regression("BUG-10")
def test_bug10_ansi_stripping_and_no_color():
    """Test BUG-10: ANSI stripping formatter and NO_COLOR compliance."""
    raw_text = "\x1b[31;1mError Message\x1b[0m"
    cleaned = strip_ansi(raw_text)
    assert cleaned == "Error Message"
    assert "\x1b" not in cleaned

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="\x1b[32mSuccess\x1b[0m",
        args=(),
        exc_info=None,
    )
    formatter = AnsiStrippingFormatter("%(message)s")
    assert formatter.format(record) == "Success"

    # Test is_color_enabled with NO_COLOR
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        assert not is_color_enabled()

    with patch.dict(os.environ, {"NO_COLOR": ""}):
        mock_tty = MagicMock()
        mock_tty.isatty.return_value = True
        assert is_color_enabled(mock_tty)

        mock_non_tty = MagicMock()
        mock_non_tty.isatty.return_value = False
        assert not is_color_enabled(mock_non_tty)

    console = get_configured_console(file=io.StringIO())
    assert isinstance(console, Console)


def test_setup_structured_logging_can_write_to_console_and_file(tmp_path):
    log_path = tmp_path / "runtime.log"
    logger = setup_structured_logging(
        logger_name="pumpfun_trading.coverage_boost",
        log_file=str(log_path),
        console=True,
    )
    assert logger.name == "pumpfun_trading.coverage_boost"
    log_runtime_event(logger, "check", component="tests", ok=True)
    assert log_path.exists()
    assert "check" in log_path.read_text(encoding="utf-8")

    log_runtime_event(logger, "caplog_check", component="tests", ok=False)
    assert "caplog_check" in log_path.read_text(encoding="utf-8")


def test_logging_rotator_and_color(tmp_path: Path):
    from pumpfun_trading.ops.logging import (
        gzip_namer,
        gzip_rotator,
        is_color_enabled,
        strip_ansi,
    )

    assert gzip_namer("file.log") == "file.log.gz"
    assert gzip_namer("file.log.gz") == "file.log.gz"
    assert strip_ansi("123") == "123"

    # Rotator with file
    src = tmp_path / "app.log"
    dst = tmp_path / "app.log.gz"
    src.write_text("Hello log content\n", encoding="utf-8")
    gzip_rotator(str(src), str(dst))
    assert dst.exists()
    assert not src.exists()

    # Rotator when source removal fails
    src2 = tmp_path / "app2.log"
    dst2 = tmp_path / "app2.log.gz"
    src2.write_text("Hello 2\n", encoding="utf-8")
    with patch("os.remove", side_effect=OSError("Permission denied")):
        gzip_rotator(str(src2), str(dst2))
        assert dst2.exists()

    # is_color_enabled with NO_COLOR env
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        assert is_color_enabled() is False
