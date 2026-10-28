"""Unit tests for ``bot/trade_feed.py`` (trade-feed circuit breaker)."""

from __future__ import annotations

import pytest

from trading_pump.bot.trade_feed import (
    TradeFeedBreaker,
    is_confirmation,
    is_refusal,
    split_stream_api_key,
    stream_connect_url,
    stream_url_has_api_key,
)

REFUSAL = (
    "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only available "
    "when connecting with an API key funded with at least 0.02 SOL."
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    "text, refusal, confirmation",
    [
        (REFUSAL, True, False),
        ("Successfully subscribed to keys.", False, True),
        ("Successfully unsubscribed from keys.", False, False),
        ("Successfully subscribed to token creation events.", False, False),
        ("rate limited", False, False),
    ],
)
def test_message_classification(text: str, refusal: bool, confirmation: bool) -> None:
    assert is_refusal(text) is refusal
    assert is_confirmation(text) is confirmation


@pytest.mark.regression("BUG-116")
def test_breaker_opens_once_and_closes_only_on_proof_of_delivery() -> None:
    clock = _Clock()
    breaker = TradeFeedBreaker(probe_interval_seconds=60.0, clock=clock)

    assert breaker.record_refusal(REFUSAL) is True
    assert breaker.record_refusal(REFUSAL) is False
    assert breaker.is_open and breaker.trips == 1 and breaker.refusals == 2
    assert breaker.tripped_at == 1_000.0

    clock.now = 1_030.0
    assert breaker.record_trade_data() is True
    assert not breaker.is_open
    assert breaker.next_probe_at is None
    assert breaker.record_confirmation() is False
    assert breaker.trade_messages == 1 and breaker.confirmations == 1


def test_likely_cause_says_funds_ran_out_when_the_key_worked_before() -> None:
    fresh = TradeFeedBreaker()
    fresh.record_refusal(REFUSAL)
    assert "missing" in fresh.likely_cause()

    worked = TradeFeedBreaker()
    worked.record_confirmation()
    worked.record_refusal(REFUSAL)
    assert "run out of funds" in worked.likely_cause()
    message = worked.trip_message()
    assert "circuit breaker OPEN" in message
    assert "0.02 SOL" in message and "API key" in message
    assert REFUSAL in message
    assert "CLOSED" in worked.recovery_message()


def test_probe_schedule_follows_the_interval() -> None:
    clock = _Clock()
    breaker = TradeFeedBreaker(probe_interval_seconds=60.0, clock=clock)
    assert breaker.probe_due() is False

    breaker.record_refusal(REFUSAL)
    assert breaker.probe_due() is False
    clock.now += 60.0
    assert breaker.probe_due() is True

    breaker.start_probe("ProbeMint")
    assert breaker.probe_due() is False
    assert breaker.take_probe_mint() == "ProbeMint"
    assert breaker.take_probe_mint() is None
    clock.now += 60.0
    assert breaker.probe_due() is True


def test_to_dict_reports_state() -> None:
    breaker = TradeFeedBreaker()
    assert breaker.to_dict()["open"] is False
    assert breaker.to_dict()["likely_cause"] is None

    breaker.record_send_failure()
    breaker.record_refusal(REFUSAL)
    data = breaker.to_dict()
    assert data["open"] is True
    assert data["trips"] == 1 and data["send_failures"] == 1
    assert data["last_refusal"] == REFUSAL
    assert "API key" in data["likely_cause"]


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


@pytest.mark.regression("BUG-156")
def test_a_connection_that_refused_is_reconnected_not_asked_again() -> None:
    now = [1_000.0]
    breaker = TradeFeedBreaker(probe_interval_seconds=300.0, clock=lambda: now[0])
    assert not breaker.wants_reconnect()  # closed
    breaker.record_refusal("refused")
    assert breaker.refused_on_connection and breaker.wants_reconnect()
    breaker.start_reconnect()
    assert breaker.reconnects == 1 and breaker.next_probe_at == 1_300.0
    breaker.connection_opened()  # the fresh connection has refused nothing yet
    assert not breaker.wants_reconnect() and breaker.is_open
    assert breaker.to_dict()["reconnects"] == 1
    message = breaker.trip_message()
    assert "at all times" in message and "reconnects every 300 s" in message
    assert "no restart needed" in message
