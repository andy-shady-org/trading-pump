"""Unit tests for ``bot/operator.py``: the operator pause state (Sprint 24D)."""

from __future__ import annotations

import pytest

from pumpfun_trading.bot import operator as operator_module
from pumpfun_trading.bot.operator import OperatorPause


def test_operator_pause_pause_then_resume_tracks_reason_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operator_module.time, "time", lambda: 1_000.0)
    pause = OperatorPause()

    assert pause.pause(reason="drill", source="SIGUSR1") is True
    assert (pause.paused, pause.reason, pause.source, pause.since) == (
        True,
        "drill",
        "SIGUSR1",
        1_000.0,
    )
    assert pause.pause(reason="again") is False
    assert pause.reason == "drill"

    assert pause.resume(source="api") is True
    assert (pause.paused, pause.reason, pause.since) == (False, "", None)
    assert pause.resume() is False


def test_operator_pause_toggle_flips_state() -> None:
    pause = OperatorPause()

    assert pause.toggle() is True
    assert pause.reason == "operator signal"
    assert pause.source == "signal"
    assert pause.toggle(source="SIGUSR1") is False
    assert pause.source == "SIGUSR1"


@pytest.mark.parametrize(
    ("since", "now", "expected"),
    [(None, 500.0, "PAUSED (operator, 0m)"), (100.0, 400.0, "PAUSED (operator, 5m)")],
)
def test_operator_pause_describe_paused_shows_minutes(
    since: float | None, now: float, expected: str
) -> None:
    pause = OperatorPause(paused=True, since=since)

    assert pause.describe(now) == expected


def test_operator_pause_describe_active_and_duration_zero() -> None:
    pause = OperatorPause()

    assert pause.describe() == "active"
    assert pause.paused_for_seconds(10.0) == 0.0


def test_operator_pause_round_trip_through_dict() -> None:
    pause = OperatorPause(paused=True, reason="drill", source="api", since=12.5)

    assert OperatorPause.from_dict(pause.to_dict()) == pause


@pytest.mark.parametrize(
    "data",
    [None, "paused", {"paused": 1, "since": "yesterday", "reason": None}],
)
def test_operator_pause_from_dict_malformed_falls_back(data: object) -> None:
    pause = OperatorPause.from_dict(data)

    assert pause.since is None
    assert pause.reason == ""
    assert pause.paused is (isinstance(data, dict))
