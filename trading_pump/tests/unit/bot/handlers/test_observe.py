"""Tests for the record-only curve observations (`bot/handlers/observe.py`)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_pump.bot.handlers import new_token, observe, watch
from trading_pump.strategies.observation import (
    SOL_QUOTE_MINT,
    in_launch_sample,
    in_reject_sample,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_bot

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


# -- rc.5 (FEAT-72): launch sample and post-exit observations -----------------


def _rc5_bot(tmp_path: Path, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "entry_mode": "launch",
        "launch_sample_pct": 1.0,
        "post_exit_observation_seconds": 900.0,
    }
    values.update(overrides)
    bot = make_bot(tmp_path, **values)
    bot.replay_recorder = MagicMock()
    return bot


def test_rc5_lists_run_in_both_modes_with_their_own_bounds(tmp_path: Path) -> None:
    bot = _rc5_bot(
        tmp_path,
        launch_sample_max_mints=40,
        launch_sample_ttl_seconds=600.0,
        launch_sample_poll_interval_seconds=4.0,
        post_exit_max_mints=12,
        post_exit_poll_interval_seconds=2.0,
        screen_reject_sample_pct=1.0,
        graduation_discovery_scan_seconds=30.0,
    )
    launch, post = observe.launch_sample_list(bot), observe.post_exit_list(bot)
    assert launch is not None and post is not None
    assert (launch.max_mints, launch.ttl_seconds, launch.poll_interval_seconds) == (
        40,
        600.0,
        4.0,
    )
    assert (post.max_mints, post.ttl_seconds, post.poll_interval_seconds) == (
        12,
        900.0,
        2.0,
    )
    # Launch mode: only the rc.5 lists (the rc.3 ones need the watch list).
    assert [b.source for b in observe.active_lists(bot)] == [
        "launch_sample",
        "post_exit",
    ]
    assert observe.observations_enabled(bot) is True
    assert observe.observation_interval(bot) == 2.0
    status = observe.observation_status(bot)
    assert set(status) == {"launch_sample", "post_exit"}

    confirmed = _rc5_bot(
        tmp_path,
        entry_mode="confirmed",
        screen_reject_sample_pct=1.0,
        graduation_discovery_scan_seconds=30.0,
    )
    assert [b.source for b in observe.active_lists(confirmed)] == [
        "reject_sample",
        "discovery",
        "launch_sample",
        "post_exit",
    ]
    off = make_bot(tmp_path, entry_mode="launch")
    off.replay_recorder = MagicMock()
    assert observe.launch_sample_list(off) is None
    assert observe.post_exit_list(off) is None
    assert observe.observations_enabled(off) is False
    assert observe.observation_interval(off) == 5.0


def test_launch_sample_records_the_create_event(tmp_path: Path) -> None:
    bot = _rc5_bot(tmp_path)
    data = {
        "timestamp": 1_700_000_000_000,
        "traderPublicKey": "Creator111",
        "solAmount": 1.5,
        "initialBuy": 52_000_000,
        "symbol": "DOG",
        "name": "Dog",
        "uri": "https://ignored.example",
    }
    assert observe.maybe_sample_launch(bot, SAMPLE_PUMP_MINT, data, 31.2)
    assert not observe.maybe_sample_launch(bot, SAMPLE_PUMP_MINT, data, 31.2)
    (start,) = _rows(bot, "observation_start")
    assert start == {
        "timestamp": start["timestamp"],
        "mint": SAMPLE_PUMP_MINT,
        "event": "observation_start",
        "source": "launch_sample",
        "created_at": 1_700_000_000.0,
        "market_cap_sol": 31.2,
        "entry_mode": "launch",
        "creator": "Creator111",
        "creator_buy_sol": 1.5,
        "creator_buy_tokens": 52_000_000,
        "symbol": "DOG",
        "name": "Dog",
    }
    assert bot._watch_stats["launch_sampled"] == 1

    part = _rc5_bot(tmp_path, launch_sample_pct=0.2)
    outside = next(
        f"m{i}pump" for i in range(1000) if not in_launch_sample(f"m{i}pump", 0.2)
    )
    assert not observe.maybe_sample_launch(part, outside, {}, 30.0)
    no_recorder = _rc5_bot(tmp_path)
    no_recorder.replay_recorder = None
    assert not observe.maybe_sample_launch(no_recorder, SAMPLE_PUMP_MINT, {}, 30.0)
    off = _rc5_bot(tmp_path, launch_sample_pct=0.0)
    assert not observe.maybe_sample_launch(off, SAMPLE_PUMP_MINT, {}, 30.0)


@pytest.mark.parametrize("entry_mode", ["launch", "confirmed"])
async def test_new_token_handler_samples_launches_before_any_gate(
    tmp_path: Path, entry_mode: str
) -> None:
    bot = _rc5_bot(tmp_path, entry_mode=entry_mode)
    # Every entry gate says no: the launch is still sampled.
    bot._should_buy = MagicMock(return_value=False)  # type: ignore[method-assign]
    bot._may_watch = MagicMock(return_value=False)  # type: ignore[method-assign]
    bot._enrich_and_screen_token = AsyncMock()  # type: ignore[method-assign]
    await new_token.handle_new_token_event(
        bot, {"mint": SAMPLE_PUMP_MINT, "pool": "pump", "marketCapSol": 30.0}
    )
    sample = observe.launch_sample_list(bot)
    assert sample is not None and SAMPLE_PUMP_MINT in sample
    bot._enrich_and_screen_token.assert_not_awaited()

    # Mayhem-mode and non-Pump.fun launches are never sampled.
    await new_token.handle_new_token_event(
        bot,
        {
            "mint": OTHER_MINT,
            "pool": "pump",
            "marketCapSol": 30.0,
            "is_mayhem_mode": True,
        },
    )
    await new_token.handle_new_token_event(
        bot, {"mint": "NotPump111", "pool": "bonk", "marketCapSol": 30.0}
    )
    assert sample.mints() == [SAMPLE_PUMP_MINT]


def _position(**extra: Any) -> dict[str, Any]:
    pos = {
        "entry_market_cap": 30.0,
        "current_market_cap": 24.0,
        "entry_time": time.time() - 42.0,
        "strategy": "momentum",
    }
    pos.update(extra)
    return pos


async def test_post_exit_starts_at_the_exit_and_tags_every_poll(
    tmp_path: Path,
) -> None:
    bot = _rc5_bot(tmp_path, launch_sample_pct=0.0)
    reason = "stop_loss_hit (79.00% <= 80.00%) " + "x" * 200
    assert observe.start_post_exit(bot, SAMPLE_PUMP_MINT, _position(), reason=reason)
    assert not observe.start_post_exit(
        bot, SAMPLE_PUMP_MINT, _position(), reason="again"
    )
    (start,) = _rows(bot, "observation_start")
    assert start["source"] == "post_exit" and start["strategy"] == "momentum"
    assert len(start["exit_reason"]) == observe.EXIT_REASON_CHARS
    assert (start["entry_market_cap_sol"], start["exit_market_cap_sol"]) == (30.0, 24.0)
    assert 41.0 <= start["held_seconds"] <= 60.0
    assert bot._watch_stats["post_exit_observed"] == 1

    bot.execution.get_bonding_curve_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _curve(8.0)}
    )
    await observe.poll_observations(bot)
    (poll,) = _rows(bot, "curve_poll")
    assert poll["source"] == "post_exit"
    assert poll["exit_market_cap_sol"] == 24.0
    assert poll["exit_reason"].startswith("stop_loss_hit")
    assert "reject_reasons" not in poll

    # Ends at its TTL like any observation.
    book = observe.post_exit_list(bot)
    assert book is not None
    book.get(SAMPLE_PUMP_MINT).added_at -= 1_000.0  # type: ignore[union-attr]
    await observe.poll_observations(bot)
    assert _rows(bot, "observation_end")[0]["cause"] == "ttl"

    # No recorder or switched off: nothing starts; no entry time: no held time.
    unrecorded = _rc5_bot(tmp_path)
    unrecorded.replay_recorder = None
    assert not observe.start_post_exit(unrecorded, "M", _position(), reason="x")
    off = _rc5_bot(tmp_path, post_exit_observation_seconds=0.0)
    assert not observe.start_post_exit(off, "M", _position(), reason="x")
    fresh = _rc5_bot(tmp_path)
    assert observe.start_post_exit(fresh, "M", _position(entry_time=0.0), reason="x")
    assert _rows(fresh, "observation_start")[0]["held_seconds"] is None


async def test_a_mint_in_two_lists_is_read_once_and_recorded_per_list(
    tmp_path: Path,
) -> None:
    bot = _rc5_bot(tmp_path)
    assert observe.maybe_sample_launch(bot, SAMPLE_PUMP_MINT, {}, 30.0)
    assert observe.start_post_exit(bot, SAMPLE_PUMP_MINT, _position(), reason="tp")

    async def states(mints: list[str], *, rejected: dict[str, str]) -> dict[str, Any]:
        assert mints == [SAMPLE_PUMP_MINT]  # one read for both lists
        return {SAMPLE_PUMP_MINT: _curve(12.0)}

    bot.execution.get_bonding_curve_states = AsyncMock(side_effect=states)
    await observe.poll_observations(bot)
    assert sorted(r["source"] for r in _rows(bot, "curve_poll")) == [
        "launch_sample",
        "post_exit",
    ]

    # A missing account ends it in every list once the grace period is over.
    for book in observe.active_lists(bot):
        book.get(SAMPLE_PUMP_MINT).added_at -= 60.0  # type: ignore[union-attr]
        book.get(SAMPLE_PUMP_MINT).last_polled_at = 0.0  # type: ignore[union-attr]

    async def missing(mints: list[str], *, rejected: dict[str, str]) -> dict[str, Any]:
        rejected.update(dict.fromkeys(mints, "missing"))
        return {}

    bot.execution.get_bonding_curve_states = AsyncMock(side_effect=missing)
    await observe.poll_observations(bot)
    ends = sorted((r["source"], r["cause"]) for r in _rows(bot, "observation_end"))
    assert ends == [("launch_sample", "missing"), ("post_exit", "missing")]


async def test_launch_mode_discovery_never_scans(tmp_path: Path) -> None:
    bot = _rc5_bot(tmp_path, graduation_discovery_scan_seconds=30.0)
    bot.api.scan_active_coins = AsyncMock(return_value=[])
    bot.execution.get_bonding_curve_states = AsyncMock(return_value={})
    await observe.poll_observations(bot)
    bot.api.scan_active_coins.assert_not_awaited()


async def test_launch_mode_watch_loop_runs_only_the_observer(tmp_path: Path) -> None:
    bot = _rc5_bot(tmp_path)
    observer = AsyncMock()
    bot._poll_watch_list = AsyncMock()  # type: ignore[method-assign]
    with patch.object(observe, "run_observation_loop", observer):
        await watch.run_watch_poll_loop(bot)
    observer.assert_awaited_once_with(bot)
    bot._poll_watch_list.assert_not_awaited()

    quiet = make_bot(tmp_path, entry_mode="launch")
    quiet.replay_recorder = MagicMock()
    observer.reset_mock()
    with patch.object(observe, "run_observation_loop", observer):
        await watch.run_watch_poll_loop(quiet)
    observer.assert_not_awaited()


async def test_record_only_hooks_never_raise_into_trading(tmp_path: Path) -> None:
    bot = _rc5_bot(tmp_path)
    # A malformed create event (non-numeric timestamp) is counted, not raised.
    assert not observe.maybe_sample_launch(
        bot, SAMPLE_PUMP_MINT, {"timestamp": "soon"}, 30.0
    )
    assert not observe.start_post_exit(
        bot, OTHER_MINT, {"entry_market_cap": "n/a"}, reason="stop"
    )
    assert bot._watch_stats["observation_hook_errors"] == 2
    # ... and the new-token handler still reaches its buy decision.
    bot._should_buy = MagicMock(return_value=False)  # type: ignore[method-assign]
    await new_token.handle_new_token_event(
        bot,
        {
            "mint": SAMPLE_PUMP_MINT,
            "pool": "pump",
            "marketCapSol": 30.0,
            "timestamp": "soon",
        },
    )
    bot._should_buy.assert_called_once()


@pytest.mark.regression("BUG-151")
async def test_record_only_polls_wait_while_the_rpc_is_rate_limited(
    tmp_path: Path,
) -> None:
    # Record-only reads competed with the reads that price and sell positions.
    bot = _bot(tmp_path, graduation_discovery_scan_seconds=0.0)
    sample = observe.reject_sample_list(bot)
    assert sample is not None
    sample.add("A", now=time.time())
    bot.execution.get_bonding_curve_states = AsyncMock(return_value={"A": _curve(1.0)})
    endpoint = bot.rpc_pool.endpoints[0]
    endpoint.last_rate_limited_time = time.time()

    await observe.poll_observations(bot)

    bot.execution.get_bonding_curve_states.assert_not_awaited()
    assert bot._watch_stats["observation_polls_deferred"] == 1

    endpoint.last_rate_limited_time = time.time() - 31.0
    await observe.poll_observations(bot)
    bot.execution.get_bonding_curve_states.assert_awaited_once()


# --- FEAT-73: graduated coins' PumpSwap pools ----------------------------------


def _grad_bot(tmp_path: Path, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "entry_mode": "launch",
        "graduation_observation_seconds": 14_400.0,
    }
    values.update(overrides)
    bot = make_bot(tmp_path, **values)
    bot.replay_recorder = MagicMock()
    return bot


def _pool(quote_sol: float, tokens: float = 200_000_000.0) -> dict[str, Any]:
    from trading_pump.sdk.pumpswap import pumpswap_market_cap_sol

    base, quote = int(tokens * 1e6), int(quote_sol * 1e9)
    return {
        "pool": "Pool1",
        "base_reserve": base,
        "quote_reserve": quote,
        "market_cap_sol": pumpswap_market_cap_sol(base, quote),
    }


def test_graduation_list_is_off_by_default_and_runs_in_both_modes(
    tmp_path: Path,
) -> None:
    off = make_bot(tmp_path, entry_mode="launch")
    off.replay_recorder = MagicMock()
    assert observe.graduation_list(off) is None
    assert not observe.start_graduation(off, SAMPLE_PUMP_MINT)

    bot = _grad_bot(
        tmp_path,
        graduation_observation_max_mints=7,
        graduation_observation_poll_interval_seconds=3.0,
        graduation_observation_fast_seconds=0.0,
    )
    book = observe.graduation_list(bot)
    assert book is not None
    assert (book.max_mints, book.ttl_seconds, book.poll_interval_seconds) == (
        7,
        14_400.0,
        3.0,
    )
    assert [b.source for b in observe.active_lists(bot)] == ["graduation"]
    assert observe.observations_enabled(bot) is True
    assert observe.observation_interval(bot) == 3.0
    # By default the first 5 minutes after a migration are polled every 2 s.
    fast = observe.graduation_list(_grad_bot(tmp_path))
    assert fast is not None
    assert (fast.fast_seconds, fast.fast_poll_interval_seconds) == (300.0, 2.0)
    assert observe.observation_interval(_grad_bot(tmp_path)) == 2.0
    assert set(observe.observation_status(bot)) == {"graduation"}
    confirmed = _grad_bot(tmp_path, entry_mode="confirmed")
    assert "graduation" in [b.source for b in observe.active_lists(confirmed)]


def test_graduation_starts_at_the_migration_with_its_pool(tmp_path: Path) -> None:
    from trading_pump.sdk.pumpswap import canonical_pool_address

    bot = _grad_bot(tmp_path)
    assert observe.start_graduation(bot, SAMPLE_PUMP_MINT, now=1_000.0)
    assert not observe.start_graduation(bot, SAMPLE_PUMP_MINT)  # once per mint
    (start,) = _rows(bot, "observation_start")
    assert start == {
        "timestamp": 1_000.0,
        "mint": SAMPLE_PUMP_MINT,
        "event": "observation_start",
        "source": "graduation",
        "migrated_at": 1_000.0,
        "pool": str(canonical_pool_address(SAMPLE_PUMP_MINT)),
        "held": False,
    }
    assert bot._watch_stats["graduation_observed"] == 1

    # Not a valid mint: counted, never raised; no recorder: nothing starts.
    assert not observe.start_graduation(bot, "not a mint")
    assert bot._watch_stats["observation_hook_errors"] == 1
    unrecorded = _grad_bot(tmp_path)
    unrecorded.replay_recorder = None
    assert not observe.start_graduation(unrecorded, SAMPLE_PUMP_MINT)


async def test_graduation_polls_the_pool_and_records_rugs_too(
    tmp_path: Path,
) -> None:
    bot = _grad_bot(tmp_path)
    assert observe.start_graduation(bot, SAMPLE_PUMP_MINT)
    bot.execution.get_bonding_curve_states = AsyncMock(return_value={})
    bot.execution.get_pumpswap_pool_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _pool(85.0)}
    )
    await observe.poll_observations(bot)
    bot.execution.get_bonding_curve_states.assert_not_awaited()  # pools only
    bot.execution.get_pumpswap_pool_states.assert_awaited_once()
    (poll,) = _rows(bot, "curve_poll")
    assert poll["source"] == "graduation"
    assert (poll["pool_sol"], poll["pool_tokens"]) == (85.0, 200_000_000.0)
    assert poll["market_cap_sol"] == pytest.approx(425.0)
    assert poll["price"] == pytest.approx(425.0 / 1e9)

    # A drained pool is a result: it is written with a market cap of 0.
    book = observe.graduation_list(bot)
    assert book is not None
    book.get(SAMPLE_PUMP_MINT).last_polled_at = 0.0  # type: ignore[union-attr]
    bot.execution.get_pumpswap_pool_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: {**_pool(0.0), "market_cap_sol": 0.0}}
    )
    await observe.poll_observations(bot)
    assert _rows(bot, "curve_poll")[-1]["market_cap_sol"] == 0.0

    # Ends at its TTL with the pool's first / last / peak SOL.
    book.get(SAMPLE_PUMP_MINT).added_at -= 20_000.0  # type: ignore[union-attr]
    await observe.poll_observations(bot)
    (end,) = _rows(bot, "observation_end")
    assert end["cause"] == "ttl"
    assert (end["first_real_sol"], end["last_real_sol"], end["peak_real_sol"]) == (
        85.0,
        0.0,
        85.0,
    )

    # Without curve-poll capture the observation still runs its course.
    quiet = _grad_bot(tmp_path, capture_curve_polls=False)
    assert observe.start_graduation(quiet, SAMPLE_PUMP_MINT)
    quiet.execution.get_pumpswap_pool_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _pool(85.0)}
    )
    await observe.poll_observations(quiet)
    assert _rows(quiet, "curve_poll") == []
    assert observe.graduation_list(quiet).get(SAMPLE_PUMP_MINT).polls == 1  # type: ignore[union-attr]


async def test_a_missing_pool_gets_a_grace_period_other_reasons_end_it(
    tmp_path: Path,
) -> None:
    bot = _grad_bot(tmp_path)
    assert observe.start_graduation(bot, SAMPLE_PUMP_MINT)
    assert observe.start_graduation(bot, SAMPLE_MINT)

    async def states(mints: list[str], *, rejected: dict[str, str]) -> dict[str, Any]:
        rejected.update(dict.fromkeys(mints, "missing"))
        if SAMPLE_MINT in mints:
            rejected[SAMPLE_MINT] = "not_sol_pair"
        return {}

    bot.execution.get_pumpswap_pool_states = AsyncMock(side_effect=states)
    await observe.poll_observations(bot)
    ends = [(r["mint"], r["cause"]) for r in _rows(bot, "observation_end")]
    assert ends == [(SAMPLE_MINT, "not_sol_pair")]

    book = observe.graduation_list(bot)
    assert book is not None
    entry = book.get(SAMPLE_PUMP_MINT)
    assert entry is not None
    entry.added_at -= observe.POOL_MISSING_GRACE_SECONDS + 1
    entry.last_polled_at = 0.0
    await observe.poll_observations(bot)
    assert _rows(bot, "observation_end")[-1]["cause"] == "missing"


async def test_pool_poll_failure_is_counted_and_curves_still_read(
    tmp_path: Path,
) -> None:
    bot = _grad_bot(tmp_path, launch_sample_pct=1.0)
    assert observe.maybe_sample_launch(bot, SAMPLE_PUMP_MINT, {}, 30.0)
    assert observe.start_graduation(bot, SAMPLE_MINT)
    bot.execution.get_bonding_curve_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _curve(1.0)}
    )
    bot.execution.get_pumpswap_pool_states = AsyncMock(side_effect=RuntimeError("down"))
    await observe.poll_observations(bot)
    assert [r["source"] for r in _rows(bot, "curve_poll")] == ["launch_sample"]
    assert bot._watch_stats["observation_poll_errors"] == 1


async def test_a_sampled_launch_alive_at_its_ttl_is_followed_to_graduation(
    tmp_path: Path,
) -> None:
    # FEAT-73: the curve before graduation, for coins that graduate later.
    bot = _rc5_bot(
        tmp_path,
        post_exit_observation_seconds=0.0,
        launch_sample_extend_seconds=14_400.0,
        launch_sample_extend_min_real_sol=1.0,
        launch_sample_extend_poll_interval_seconds=15.0,
    )
    book = observe.launch_sample_list(bot)
    assert book is not None
    assert (
        book.extend_ttl_seconds,
        book.extend_min_real_sol,
        book.extend_poll_interval_seconds,
    ) == (14_400.0, 1.0, 15.0)
    assert observe.maybe_sample_launch(bot, SAMPLE_PUMP_MINT, {}, 30.0)
    assert observe.maybe_sample_launch(bot, SAMPLE_MINT, {}, 30.0)
    bot.execution.get_bonding_curve_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _curve(6.0), SAMPLE_MINT: _curve(0.1)}
    )
    await observe.poll_observations(bot)
    for mint in (SAMPLE_PUMP_MINT, SAMPLE_MINT):
        entry = book.get(mint)
        assert entry is not None
        entry.added_at -= 1_000.0  # past the 900 s TTL
        entry.last_polled_at = 0.0
    await observe.poll_observations(bot)
    # The dead one ends at its TTL; the live one is kept and still polled.
    (end,) = _rows(bot, "observation_end")
    assert (end["mint"], end["cause"]) == (SAMPLE_MINT, "ttl")
    assert "extended" not in end
    assert book.get(SAMPLE_PUMP_MINT).extended  # type: ignore[union-attr]
    assert bot._launch_sample_list.stats["extended"] == 1

    # It graduates: the observation ends as complete, marked as extended.
    book.get(SAMPLE_PUMP_MINT).last_polled_at = 0.0  # type: ignore[union-attr]
    bot.execution.get_bonding_curve_states = AsyncMock(
        return_value={SAMPLE_PUMP_MINT: _curve(85.0, complete=True)}
    )
    await observe.poll_observations(bot)
    last = _rows(bot, "observation_end")[-1]
    assert (last["mint"], last["cause"], last["extended"]) == (
        SAMPLE_PUMP_MINT,
        "complete",
        True,
    )
