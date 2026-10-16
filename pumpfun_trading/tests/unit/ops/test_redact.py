"""Unit tests for ``ops/redact.py`` URL credential masking (BUG-102)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pumpfun_trading.ops.events import DiagnosticEventLogger
from pumpfun_trading.ops.logging import AnsiStrippingFormatter
from pumpfun_trading.ops.redact import MASK, redact_text, redact_url

HELIUS_KEY = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
            "https://mainnet.helius-rpc.com/?api-key=***",
        ),
        (
            "https://rpc.example.com/?cluster=mainnet&token=s3cr3t",
            "https://rpc.example.com/?cluster=mainnet&token=***",
        ),
        (
            "https://rpc.example.com/?API_KEY=abc&x-token=def",
            "https://rpc.example.com/?API_KEY=***&x-token=***",
        ),
        (
            "https://eth.g.alchemy.com/v2/AbCdEf0123456789xyzQWERTY",
            "https://eth.g.alchemy.com/v2/***",
        ),
        (
            "https://example.solana-mainnet.quiknode.pro/a1b2c3d4e5f6a7b8c9d0e1f2/",
            "https://example.solana-mainnet.quiknode.pro/***/",
        ),
        (
            "wss://user:hunter2@stream.example.com/ws",
            "wss://***@stream.example.com/ws",
        ),
        ("grpcs://geyser.example.com:443/", "grpcs://geyser.example.com:443/"),
        ("wss://pumpportal.fun/api/data", "wss://pumpportal.fun/api/data"),
        (
            f"https://frontend-api-v3.pump.fun/coins/{MINT}",
            f"https://frontend-api-v3.pump.fun/coins/{MINT}",
        ),
        ("https://rpc.example.com/?api-key=", "https://rpc.example.com/?api-key="),
        ("not a url", "not a url"),
        ("", ""),
        (None, ""),
    ],
)
def test_redact_url_masks_only_credentials(url: str | None, expected: str) -> None:
    assert redact_url(url) == expected


def test_redact_url_without_host_returned_unchanged() -> None:
    assert redact_url("file:///tmp/x?token=1") == "file:///tmp/x?token=1"


def test_redact_url_unparseable_returned_unchanged() -> None:
    assert redact_url("http://[::1") == "http://[::1"


def test_redact_url_masks_pubkey_length_segment_that_is_not_a_pubkey() -> None:
    # 40 hex chars contain ``0``, which base58 never does: a key, not a mint.
    key = "a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9"
    assert redact_url(f"https://rpc.example.com/{key}") == "https://rpc.example.com/***"


def test_redact_text_masks_every_url_in_a_message() -> None:
    message = (
        "WebSocket stream error: 502, message='Invalid response status', "
        f"url='wss://feed.example.com/data?api-key={HELIUS_KEY}' and "
        f"https://rpc.example.com/?token=abc. Reconnecting"
    )
    redacted = redact_text(message)
    assert HELIUS_KEY not in redacted
    assert "token=abc" not in redacted
    assert "url='wss://feed.example.com/data?api-key=***'" in redacted
    assert "https://rpc.example.com/?token=***." in redacted
    assert redacted.endswith("Reconnecting")


@pytest.mark.parametrize("text", ["plain message", "", None])
def test_redact_text_without_urls_unchanged(text: str | None) -> None:
    assert redact_text(text) == (text or "")


def test_log_formatter_masks_url_credentials() -> None:
    record = logging.LogRecord(
        "pumpfun_trading.bot",
        logging.WARNING,
        __file__,
        1,
        "Connecting to %s",
        (f"https://rpc.example.com/?api-key={HELIUS_KEY}",),
        None,
    )
    formatted = AnsiStrippingFormatter("%(message)s").format(record)
    assert formatted == f"Connecting to https://rpc.example.com/?api-key={MASK}"


async def test_diagnostic_events_written_without_url_credentials(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    events = DiagnosticEventLogger(output_path=path)
    await events.start()
    events.emit(
        event_name="stream_error",
        error_message=f"url='wss://feed.example.com/?api-key={HELIUS_KEY}'",
        data={"endpoint": f"https://rpc.example.com/?token={HELIUS_KEY}"},
    )
    await events.flush_and_close()
    text = path.read_text(encoding="utf-8")
    assert HELIUS_KEY not in text
    record = json.loads(text.splitlines()[-1])
    assert record["data"]["endpoint"] == f"https://rpc.example.com/?token={MASK}"
