"""Tests for PumpPortal's subscriptions and API key (`streams/websocket.py`).

The transport loop is trading-core's (``trading_core.ops.stream``) since
0.5.0 and tested there (BUG-150).
"""

from __future__ import annotations

import pytest

from trading_pump.streams.websocket import (
    MIGRATION_SUBSCRIPTION,
    MIGRATION_TX_TYPES,
    NEW_TOKEN_SUBSCRIPTION,
    split_stream_api_key,
    stream_connect_url,
    stream_url_has_api_key,
    token_trade_message,
)


def test_token_trade_message_shape() -> None:
    assert token_trade_message("subscribeTokenTrade", "MINT") == {
        "method": "subscribeTokenTrade",
        "keys": ["MINT"],
    }
    assert NEW_TOKEN_SUBSCRIPTION == {"method": "subscribeNewToken"}
    # Free (not metered) like the create feed; carries graduations (BUG-123).
    assert MIGRATION_SUBSCRIPTION == {"method": "subscribeMigration"}
    assert "migrate" in MIGRATION_TX_TYPES


# --- the PumpPortal API key in the URL (moved from bot/trade_feed.py) ---------


@pytest.mark.regression("BUG-117")
@pytest.mark.parametrize(
    "url, expected",
    [
        ("wss://pumpportal.fun/api/data?api-key=abc", True),
        ("wss://pumpportal.fun/api/data?api_key=abc", True),
        ("wss://pumpportal.fun/api/data?api-key=", False),
        ("wss://pumpportal.fun/api/data", False),
        ("wss://other.test/feed?api-key=abc", None),
        (None, None),
        ("http://[::1", None),
    ],
)
def test_stream_url_has_api_key(url: str | None, expected: bool | None) -> None:
    assert stream_url_has_api_key(url) is expected


@pytest.mark.regression("BUG-118")
@pytest.mark.parametrize(
    "url, clean, key",
    [
        (
            "wss://pumpportal.fun/api/data?api-key=abc",
            "wss://pumpportal.fun/api/data",
            "abc",
        ),
        (
            "wss://pumpportal.fun/api/data?x=1&api_key=abc",
            "wss://pumpportal.fun/api/data?x=1",
            "abc",
        ),
        (
            "wss://pumpportal.fun/api/data?api-key=",
            "wss://pumpportal.fun/api/data",
            None,
        ),
        ("wss://pumpportal.fun/api/data", "wss://pumpportal.fun/api/data", None),
        (
            "wss://other.test/feed?api-key=abc",
            "wss://other.test/feed?api-key=abc",
            None,
        ),
        (None, "", None),
        ("http://[::1", "http://[::1", None),
    ],
)
def test_split_stream_api_key(url: str | None, clean: str, key: str | None) -> None:
    assert split_stream_api_key(url) == (clean, key)


@pytest.mark.regression("BUG-118")
@pytest.mark.parametrize(
    "url, api_key, expected",
    [
        (
            "wss://pumpportal.fun/api/data",
            "k1",
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        # The separate key wins over one left in the URL.
        (
            "wss://pumpportal.fun/api/data?api-key=old",
            "k1",
            "wss://pumpportal.fun/api/data?api-key=k1",
        ),
        (
            "wss://pumpportal.fun/api/data?api-key=old",
            None,
            "wss://pumpportal.fun/api/data?api-key=old",
        ),
        ("wss://pumpportal.fun/api/data", " ", "wss://pumpportal.fun/api/data"),
        # The PumpPortal key is never sent to another provider.
        ("wss://other.test/feed", "k1", "wss://other.test/feed"),
    ],
)
def test_stream_connect_url(url: str, api_key: str | None, expected: str) -> None:
    assert stream_connect_url(url, api_key) == expected


def test_a_pumpportal_url_with_other_parameters_only_keeps_them() -> None:
    url = "wss://pumpportal.fun/api/data?x=1"
    assert split_stream_api_key(url) == (url, None)
