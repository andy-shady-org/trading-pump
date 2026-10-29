"""Tests for the record-only observation lists (`strategies/observation.py`)."""

from __future__ import annotations

import pytest

from trading_pump.strategies.observation import (
    DISCOVERY_SOURCE,
    GRADUATION_SOURCE,
    LAUNCH_SAMPLE_SOURCE,
    OBSERVATION_END_EVENT,
    OBSERVATION_START_EVENT,
    POST_EXIT_SOURCE,
    REJECT_SAMPLE_SOURCE,
    SOL_QUOTE_MINT,
    CurveObservationList,
    discovery_candidates,
    in_launch_sample,
    in_reject_sample,
    in_sample,
    is_record_only_row,
)


def _book(**overrides: object) -> CurveObservationList:
    values: dict[str, object] = {
        "source": DISCOVERY_SOURCE,
        "max_mints": 2,
        "ttl_seconds": 100.0,
        "poll_interval_seconds": 10.0,
    }
    values.update(overrides)
    return CurveObservationList(**values)  # type: ignore[arg-type]


def test_record_only_rows_are_observation_events_and_their_polls() -> None:
    assert is_record_only_row({"event": OBSERVATION_START_EVENT})
    assert is_record_only_row({"event": OBSERVATION_END_EVENT})
    assert is_record_only_row({"event": "curve_poll", "source": REJECT_SAMPLE_SOURCE})
    assert is_record_only_row({"event": "curve_poll", "source": DISCOVERY_SOURCE})
    assert is_record_only_row({"event": "curve_poll", "source": GRADUATION_SOURCE})
    assert not is_record_only_row({"event": "curve_poll", "source": "watch"})
    assert not is_record_only_row({"event": "curve_poll"})
    assert not is_record_only_row({"mint": "M", "signal": "buy"})


def test_reject_sample_is_deterministic_and_close_to_its_share() -> None:
    mints = [f"mint{i}pump" for i in range(4000)]
    picked = [m for m in mints if in_reject_sample(m, 0.2)]
    assert 0.17 < len(picked) / len(mints) < 0.23
    # The same mint is always in or out.
    assert picked == [m for m in mints if in_reject_sample(m, 0.2)]
    assert not any(in_reject_sample(m, 0.0) for m in mints[:50])
    assert all(in_reject_sample(m, 1.0) for m in mints[:50])


def test_list_is_bounded_never_evicts_and_counts_why() -> None:
    book = _book()
    first = book.add("A", now=0.0, created_at=-5.0, reasons=["top5"])
    assert first is not None and first.reasons == ("top5",)
    assert book.add("A", now=1.0) is None  # already observed
    assert book.add("B", now=1.0) is not None
    assert book.add("C", now=2.0) is None  # full: nothing evicted
    assert book.mints() == ["A", "B"] and len(book) == 2 and "A" in book
    assert book.stats == {"added": 2, "full": 1}
    assert book.snapshot() == {
        "source": DISCOVERY_SOURCE,
        "observed": 2,
        "max_mints": 2,
        "stats": {"added": 2, "full": 1},
    }


def test_due_update_floor_and_ttl() -> None:
    book = _book(min_real_sol=40.0)
    book.add("A", now=0.0)
    assert book.due(0.0) == ["A"]  # never polled
    assert book.update("A", real_sol=45.0, now=1.0) is None
    assert book.due(5.0) == []
    assert book.due(11.0) == ["A"]
    assert book.update("A", real_sol=50.0, now=11.0) is None
    assert book.update("A", real_sol=39.0, now=21.0) == "below_floor"
    entry = book.get("A")
    assert entry is not None
    assert (entry.first_real_sol, entry.last_real_sol, entry.peak_real_sol) == (
        45.0,
        39.0,
        50.0,
    )
    assert entry.polls == 3
    assert entry.to_dict()["peak_real_sol"] == 50.0
    assert book.update("missing", real_sol=1.0, now=1.0) is None
    assert book.expired(100.0) == []
    assert book.expired(100.5) == ["A"]
    assert book.remove("A", "ttl") is entry
    assert book.remove("A", "ttl") is None
    assert book.stats["ended_ttl"] == 1


def test_reject_sample_has_no_floor() -> None:
    book = _book(source=REJECT_SAMPLE_SOURCE)
    book.add("A", now=0.0)
    assert book.update("A", real_sol=0.0, now=1.0) is None


def _coin(mint: str, real_sol: float, **extra: object) -> dict[str, object]:
    coin: dict[str, object] = {
        "mint": mint,
        "complete": False,
        "program": "pump",
        "quote_mint": SOL_QUOTE_MINT,
        "real_sol_reserves": int(real_sol * 1e9),
        "created_timestamp": 1_792_569_078_000,
    }
    coin.update(extra)
    return coin


def test_discovery_candidates_keep_pump_sol_curves_inside_the_band() -> None:
    page = [
        _coin("keep", 50.0),
        _coin("seconds", 60.0, created_timestamp=1_700_000_000),
        _coin("no_created", 41.0, created_timestamp=None),
        _coin("low", 10.0),
        _coin("done", 84.0, complete=True),
        _coin("graduated_size", 90.0),
        _coin("other_program", 50.0, program="bonk"),
        _coin("usdc_quote", 50.0, quote_mint="EPjFWdd5"),
        _coin("bad_reserve", 50.0, real_sol_reserves="x"),
        {"mint": ""},
        "not a coin",
    ]
    found = discovery_candidates(page, min_real_sol=40.0, max_real_sol=85.0)
    assert found == [
        ("keep", pytest.approx(1_792_569_078.0)),
        ("seconds", 1_700_000_000.0),
        ("no_created", None),
    ]
    # Wrapped pages and junk payloads.
    assert discovery_candidates(
        {"coins": [_coin("w", 45.0)]}, min_real_sol=40.0, max_real_sol=85.0
    ) == [("w", pytest.approx(1_792_569_078.0))]
    assert discovery_candidates("oops", min_real_sol=40.0, max_real_sol=85.0) == []
    assert discovery_candidates({}, min_real_sol=40.0, max_real_sol=85.0) == []


def test_rc5_launch_sample_and_post_exit_polls_are_record_only() -> None:
    assert is_record_only_row({"event": "curve_poll", "source": LAUNCH_SAMPLE_SOURCE})
    assert is_record_only_row({"event": "curve_poll", "source": POST_EXIT_SOURCE})


def test_launch_sample_is_deterministic_and_independent_of_the_reject_sample() -> None:
    mints = [f"mint{i}pump" for i in range(5000)]
    launch = {m for m in mints if in_launch_sample(m, 0.2)}
    reject = {m for m in mints if in_reject_sample(m, 0.2)}
    assert 0.17 < len(launch) / len(mints) < 0.23
    assert launch == {m for m in mints if in_launch_sample(m, 0.2)}
    # Salted: the two samples overlap about as two independent 20% draws (4%).
    assert 0.02 < len(launch & reject) / len(mints) < 0.06
    # The reject sample is the unsalted rc.3 draw, unchanged.
    assert reject == {m for m in mints if in_sample(m, 0.2)}
    assert not in_launch_sample(mints[0], 0.0) and in_launch_sample(mints[0], 1.0)


def test_entry_tags_are_kept_and_exported() -> None:
    book = _book(source=POST_EXIT_SOURCE)
    entry = book.add("M", now=1.0, tags={"exit_reason": "stop_loss_hit"})
    assert entry is not None and entry.tags == {"exit_reason": "stop_loss_hit"}
    assert entry.to_dict()["tags"] == {"exit_reason": "stop_loss_hit"}
    plain = book.add("N", now=1.0)
    assert plain is not None and plain.to_dict()["tags"] == {}


# --- FEAT-73: fast phase and extension ----------------------------------------


def test_a_young_entry_is_polled_fast_then_at_the_normal_interval() -> None:
    book = _book(
        ttl_seconds=1_000.0,
        poll_interval_seconds=10.0,
        fast_seconds=300.0,
        fast_poll_interval_seconds=2.0,
    )
    assert book.shortest_interval() == 2.0
    entry = book.add("young", now=0.0)
    assert entry is not None
    book.update("young", real_sol=85.0, now=0.0)
    assert book.due(1.0) == [] and book.due(2.0) == ["young"]
    assert book.interval_for(entry, 299.0) == 2.0
    assert book.interval_for(entry, 300.0) == 10.0
    book.update("young", real_sol=85.0, now=301.0)
    assert book.due(305.0) == [] and book.due(311.0) == ["young"]
    # No fast phase configured: one interval throughout.
    plain = _book(poll_interval_seconds=10.0)
    assert plain.shortest_interval() == 10.0


def test_an_alive_entry_is_kept_past_its_ttl_until_it_fades_or_ages_out() -> None:
    book = _book(
        max_mints=5,
        ttl_seconds=900.0,
        poll_interval_seconds=5.0,
        extend_ttl_seconds=3_600.0,
        extend_min_real_sol=1.0,
        extend_poll_interval_seconds=15.0,
    )
    assert book.extends and book.shortest_interval() == 5.0
    for mint, real_sol in (("alive", 4.0), ("dead", 0.2), ("unpolled", None)):
        book.add(mint, now=0.0)
        if real_sol is not None:
            book.update(mint, real_sol=real_sol, now=10.0)
    assert sorted(book.expired(901.0)) == ["dead", "unpolled"]
    alive = book.get("alive")
    assert alive is not None and alive.extended and alive.to_dict()["extended"]
    assert book.stats["extended"] == 1
    book.expired(902.0)  # counted once
    assert book.stats["extended"] == 1
    # Polled at the slower interval while extended; fades below the floor.
    assert book.interval_for(alive, 905.0) == 15.0
    assert book.update("alive", real_sol=2.0, now=920.0) is None
    assert book.update("alive", real_sol=0.5, now=935.0) == "faded"
    # ... or ages out at the extension's end.
    book.update("alive", real_sol=3.0, now=950.0)
    assert book.expired(3_601.0) == ["alive", "dead", "unpolled"]
    # A list without an extension never keeps anything past its TTL.
    plain = _book(ttl_seconds=900.0)
    plain.add("alive", now=0.0)
    plain.update("alive", real_sol=50.0, now=1.0)
    assert not plain.extends and plain.expired(901.0) == ["alive"]
