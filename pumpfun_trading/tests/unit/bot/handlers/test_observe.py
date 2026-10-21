"""Tests for the record-only curve observations (`bot/handlers/observe.py`)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.bot.handlers import new_token, observe, watch
from pumpfun_trading.strategies.observation import SOL_QUOTE_MINT, in_reject_sample
from pumpfun_trading.tests.support.constants import SAMPLE_PUMP_MINT
from pumpfun_trading.tests.support.factories import make_bot

OTHER_MINT = "Other1111111111111111111111111111111111pump"


def _bot(tmp_path: Path, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "entry_mode": "confirmed",
        "screen_reject_sample_pct": 1.0,
        "graduation_discovery_scan_seconds": 30.0,
        "observation_poll_interval_seconds": 5.0,
    }
    values.update(overrides)
    bot = make_bot(tmp_path, **values)
    bot.replay_recorder = MagicMock()
    return bot


def _rows(bot: Any, event: str | None = None) -> list[dict[str, Any]]:
    rows = [c.args[0] for c in bot.replay_recorder.record_snapshot.call_args_list]
    return [r for r in rows if event is None or r.get("event") == event]


def _curve(real_sol: float, **extra: Any) -> dict[str, Any]:
    virtual_sol = 30.0 + real_sol
    virtual_tokens = 30.0 * 1_073_000_000.0 / virtual_sol
    state: dict[str, Any] = {
        "virtual_sol_reserves": int(virtual_sol * 1e9),
        "virtual_token_reserves": int(virtual_tokens * 1e6),
        "real_sol_reserves": int(real_sol * 1e9),
        "complete": False,
    }
    state.update(extra)
    return state


def _verdict() -> SimpleNamespace:
    return SimpleNamespace(passed=False, reasons=["top5 31% > 10%"], risk_score=70.0)


def test_lists_are_off_by_default_and_without_a_recorder(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, entry_mode="confirmed")
    bot.replay_recorder = MagicMock()
    assert observe.reject_sample_list(bot) is None
    assert observe.discovery_list(bot) is None
    assert observe.observations_enabled(bot) is False
    assert observe.observation_status(bot) == {}

    no_recorder = make_bot(
        tmp_path, entry_mode="confirmed", screen_reject_sample_pct=0.5
    )
    no_recorder.replay_recorder = None
    assert observe.observations_enabled(no_recorder) is False
    launch = _bot(tmp_path, entry_mode="launch")
    assert observe.observations_enabled(launch) is False


def test_lists_take_their_bounds_from_the_config(tmp_path: Path) -> None:
    bot = _bot(
        tmp_path,
        screen_reject_sample_max_mints=7,
        screen_reject_sample_ttl_seconds=90.0,
        graduation_discovery_max_mints=9,
        graduation_discovery_ttl_seconds=900.0,
        graduation_discovery_min_real_sol=45.0,
    )
    sample = observe.reject_sample_list(bot)
    found = observe.discovery_list(bot)
    assert sample is not None and found is not None
    assert (sample.max_mints, sample.ttl_seconds, sample.min_real_sol) == (7, 90.0, 0)
    assert (found.max_mints, found.ttl_seconds, found.min_real_sol) == (9, 900.0, 45.0)
    assert observe.reject_sample_list(bot) is sample  # built once
    assert observe.observations_enabled(bot) is True
    status = watch.watch_list_status(bot)
    assert status["reject_sample"]["max_mints"] == 7
    assert status["discovery"]["source"] == "discovery"


def test_rejected_launch_in_the_sample_is_observed_with_its_reasons(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path)
    data = {"timestamp": 1_700_000_000_000}
    assert observe.maybe_sample_rejected(bot, SAMPLE_PUMP_MINT, data, _verdict())
    # Only once per mint.
    assert not observe.maybe_sample_rejected(bot, SAMPLE_PUMP_MINT, data, _verdict())
    (start,) = _rows(bot, "observation_start")
    assert start["source"] == "reject_sample"
    assert start["reject_reasons"] == ["top5 31% > 10%"]
    assert start["created_at"] == 1_700_000_000.0
    assert start["risk_score"] == 70.0
    assert bot._watch_stats["reject_sampled"] == 1
    # Never on the watch list: no promotion, no shadow book, no buy.
    assert not bot.order_flow_engine.is_watched(SAMPLE_PUMP_MINT)


def test_reject_sample_skips_mints_outside_the_share(tmp_path: Path) -> None:
    bot = _bot(tmp_path, screen_reject_sample_pct=0.2)
    mint = next(
        f"m{i}pump" for i in range(1000) if not in_reject_sample(f"m{i}pump", 0.2)
    )
    assert not observe.maybe_sample_rejected(bot, mint, {}, _verdict())
    off = _bot(tmp_path, screen_reject_sample_pct=0.0)
    assert not observe.maybe_sample_rejected(off, mint, {}, _verdict())


async def test_new_token_handler_samples_a_screen_reject_without_watching_it(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path)
    bot._enrich_and_screen_token = AsyncMock(  # type: ignore[method-assign]
        return_value=_verdict()
    )
    bot._buy_token = AsyncMock()  # type: ignore[method-assign]
    await new_token.handle_new_token_event(
        bot, {"mint": SAMPLE_PUMP_MINT, "pool": "pump", "marketCapSol": 30.0}
    )
    sample = observe.reject_sample_list(bot)
    assert sample is not None and SAMPLE_PUMP_MINT in sample
    assert not bot.order_flow_engine.is_watched(SAMPLE_PUMP_MINT)
    bot._buy_token.assert_not_awaited()


async def test_poll_records_tagged_rows_and_ends_finished_curves(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path, graduation_discovery_scan_seconds=0.0)
    sample = observe.reject_sample_list(bot)
    assert sample is not None
    now = time.time()
    for mint in ("A", "B", "C", "D", "E", "F"):
        sample.add(mint, now=now, reasons=["creator 12%"])
    old = sample.add("G", now=now - 10_000.0)
    assert old is not None

    async def states(mints: list[str], *, rejected: dict[str, str]) -> dict[str, Any]:
        assert "G" not in mints  # expired before the poll
        rejected.update({"D": "missing", "E": "missing", "X": "missing"})
        # A brand-new account gets a grace period; an older one ends.
        entry = sample.get("E")
        assert entry is not None
        entry.added_at = now - 100.0
        return {
            "A": _curve(12.0),
            "B": _curve(80.0, complete=True),
            "C": _curve(5.0, is_mayhem_mode=True),
            "F": _curve(1.0),
            "X": _curve(1.0),
        }

    bot.execution.get_bonding_curve_states = AsyncMock(side_effect=states)
    await observe.poll_observations(bot)

    poll_a, poll_f = _rows(bot, "curve_poll")
    assert poll_a["mint"] == "A" and poll_a["source"] == "reject_sample"
    assert poll_a["reject_reasons"] == ["creator 12%"]
    assert poll_a["real_sol_reserves"] == pytest.approx(12.0)
    assert poll_f["mint"] == "F"
    ends = {r["mint"]: r["cause"] for r in _rows(bot, "observation_end")}
    assert ends == {"G": "ttl", "B": "complete", "C": "mayhem", "E": "missing"}
    assert sample.mints() == ["A", "D", "F"]
    assert sample.get("A").polls == 1  # type: ignore[union-attr]
    # Record-only: the watch list and the pre-graduation engine never see it.
    assert bot.order_flow_engine.watch_count == 0
    assert bot.graduation_engine.get_candidate("A") is None


async def test_poll_failure_is_counted_and_nothing_due_means_no_rpc(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path, graduation_discovery_scan_seconds=0.0)
    bot.execution.get_bonding_curve_states = AsyncMock(side_effect=RuntimeError("x"))
    await observe.poll_observations(bot)  # empty: no read
    bot.execution.get_bonding_curve_states.assert_not_awaited()

    sample = observe.reject_sample_list(bot)
    assert sample is not None
    sample.add("A", now=time.time())
    bot.event_logger = MagicMock()
    await observe.poll_observations(bot)
    assert bot._watch_stats["observation_poll_errors"] == 1
    assert bot.event_logger.emit.call_args.kwargs["event_name"] == (
        "observation_poll_failed"
    )
    assert sample.mints() == ["A"]


def _coin(mint: str, real_sol: float) -> dict[str, Any]:
    return {
        "mint": mint,
        "complete": False,
        "program": "pump",
        "quote_mint": SOL_QUOTE_MINT,
        "real_sol_reserves": int(real_sol * 1e9),
        "created_timestamp": 1_700_000_000_000,
    }


async def test_discovery_scan_adds_new_curves_past_the_floor_on_its_cadence(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path)
    found = observe.discovery_list(bot)
    sample = observe.reject_sample_list(bot)
    assert found is not None and sample is not None
    bot.order_flow_engine.watch(OTHER_MINT, created_at=0.0)
    bot.active_positions["held"] = {"entry_market_cap": 30.0}
    sample.add("sampled", now=0.0)
    bot.api.scan_active_coins = AsyncMock(
        return_value=[
            _coin("new", 50.0),
            _coin("low", 10.0),
            _coin(OTHER_MINT, 50.0),
            _coin("held", 50.0),
            _coin("sampled", 50.0),
        ]
    )
    assert await observe.scan_discovery(bot, found, 100.0) == 1
    assert found.mints() == ["new"]
    (start,) = _rows(bot, "observation_start")
    assert start == {
        "timestamp": 100.0,
        "mint": "new",
        "event": "observation_start",
        "source": "discovery",
        "created_at": 1_700_000_000.0,
    }
    # Same mint again later: not added twice; too soon: no API call at all.
    assert await observe.scan_discovery(bot, found, 110.0) == 0
    assert bot.api.scan_active_coins.await_count == 1
    assert await observe.scan_discovery(bot, found, 131.0) == 0
    assert bot.api.scan_active_coins.await_count == 2
    assert bot._watch_stats["discovery_scans"] == 2


async def test_discovery_scan_failure_is_counted_not_raised(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    found = observe.discovery_list(bot)
    assert found is not None
    bot.api.scan_active_coins = AsyncMock(side_effect=RuntimeError("HTTP 429"))
    assert await observe.scan_discovery(bot, found, 100.0) == 0
    assert bot._watch_stats["discovery_scan_errors"] == 1


async def test_discovered_curve_below_the_floor_ends(tmp_path: Path) -> None:
    bot = _bot(tmp_path, screen_reject_sample_pct=0.0)
    found = observe.discovery_list(bot)
    assert found is not None
    bot.api.scan_active_coins = AsyncMock(return_value=[_coin("new", 50.0)])
    bot.execution.get_bonding_curve_states = AsyncMock(
        return_value={"new": _curve(30.0)}
    )
    await observe.poll_observations(bot)
    poll = _rows(bot, "curve_poll")[0]
    assert poll["source"] == "discovery" and "reject_reasons" not in poll
    (end,) = _rows(bot, "observation_end")
    assert end["cause"] == "below_floor" and end["peak_real_sol"] == 30.0
    assert len(found) == 0


async def test_observation_loop_polls_until_stopped_and_survives_errors(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path)
    calls = 0

    async def poll(_bot: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        bot._stop_requested = True

    with (
        patch.object(observe, "poll_observations", poll),
        patch.object(observe.asyncio, "sleep", AsyncMock()),
    ):
        await observe.run_observation_loop(bot)
    assert calls == 2


async def test_observation_loop_stops_on_cancel(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    with patch.object(
        observe.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
    ):
        await observe.run_observation_loop(bot)  # returns, no raise


async def test_watch_loop_runs_the_observer_task_and_cancels_it(
    tmp_path: Path,
) -> None:
    bot = _bot(tmp_path, watch_poll_interval_seconds=0.1)
    started = asyncio.Event()
    cancelled = False

    async def observer(_bot: Any) -> None:
        nonlocal cancelled
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def poll() -> None:
        await started.wait()
        bot._stop_requested = True

    bot._poll_watch_list = poll  # type: ignore[method-assign]
    with patch.object(observe, "run_observation_loop", observer):
        await watch.run_watch_poll_loop(bot)
    assert cancelled is True
