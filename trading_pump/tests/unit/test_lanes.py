"""Unit tests for ``lanes.py``: captures as the strategy library's records.

The capture rows come from the module's own writer (``GraduateTracker``
for graduates and new pools), so the tests read exactly what a run writes.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from trading_core.lanes.market import Listing, Reading, parse_row
from trading_core.lanes.sweep import load_capture

from trading_pump.config.settings import GraduationSettings
from trading_pump.graduates import GraduateTracker
from trading_pump.lanes import (
    NO_CREATOR,
    SKIP_BEFORE_LISTING,
    SKIP_MALFORMED,
    SKIP_NO_DECIMALS,
    SKIP_NO_LISTING,
    SKIP_NO_PRICE,
    LaneRows,
    lane_records,
    write_lane_rows,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading

NEW_POOL = "NewPoo1111111111111111111111111111111111111"
CREATOR = "Creator111111111111111111111111111111111111"


def _graduate_rows(mint: str = SAMPLE_PUMP_MINT) -> list[dict[str, Any]]:
    """A migration at 100 s and three pool readings, as a run writes them."""
    rows: list[dict[str, Any]] = []
    tracker = GraduateTracker(GraduationSettings(), record=rows.append)
    tracker.add(mint, now=100.0)
    for at, scale in ((102.0, 1.0), (104.0, 1.5), (106.0, 1.2)):
        tracker.update(make_reading(mint, at=at, scale=scale))
    tracker.end(mint, "ttl", 110.0)
    return rows


def _new_pool_rows(**details: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tracker = GraduateTracker(GraduationSettings(), record=rows.append)
    found = {"created_at": 90.0, "decimals": 9, "coin_creator": CREATOR, **details}
    tracker.add_new_pool(SAMPLE_MINT, NEW_POOL, now=100.0, details=found)
    tracker.update(make_reading(SAMPLE_MINT, at=102.0))
    return rows


def _convert(rows: list[dict[str, Any]], **kwargs: Any) -> tuple[list[Any], LaneRows]:
    lanes = LaneRows(**kwargs)
    for row in rows:
        lanes.learn(row)
    records = [record for row in rows for record in lanes.records(row)]
    return records, lanes


def _write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


# -- graduates ---------------------------------------------------------------------


def test_a_graduate_is_a_listing_and_readings_at_the_module_price() -> None:
    records, lanes = _convert(_graduate_rows())

    listing, *readings = records
    assert listing == Listing(SAMPLE_PUMP_MINT, 100.0, kind="graduation")
    expected = [
        make_reading(SAMPLE_PUMP_MINT, at=a, scale=s)
        for a, s in ((102, 1.0), (104, 1.5), (106, 1.2))
    ]
    assert [(r.at, r.liquidity, r.progress) for r in readings] == [
        (e.at, e.pool_sol, None) for e in expected
    ]
    for reading, reading_of_pool in zip(readings, expected, strict=True):
        assert reading.price == pytest.approx(reading_of_pool.price, rel=1e-9)
    assert lanes.stats.written == {"listing": 1, "reading": 3}
    assert lanes.stats.ignored == {"migration": 1, "observation_end/graduation": 1}
    assert not lanes.stats.skipped


def test_readings_without_their_listing_or_before_it_are_skipped() -> None:
    rows = _graduate_rows()
    start = next(r for r in rows if r["event"] == "observation_start")
    early = dict(rows[2], timestamp=99.0)
    orphan = dict(rows[2], mint=SAMPLE_MINT)
    records, lanes = _convert([start, early, orphan])

    assert records == [Listing(SAMPLE_PUMP_MINT, 100.0, kind="graduation")]
    assert lanes.stats.skipped == {SKIP_BEFORE_LISTING: 1, SKIP_NO_LISTING: 1}


def test_a_graduate_followed_twice_keeps_its_first_listing() -> None:
    rows = _graduate_rows()
    start = next(r for r in rows if r["event"] == "observation_start")
    again = dict(start, timestamp=500.0, migrated_at=500.0)
    records, lanes = _convert([again, start, again, rows[2]])

    assert records[0] == Listing(SAMPLE_PUMP_MINT, 100.0, kind="graduation")
    assert len(records) == 2
    assert lanes.stats.ignored == {"observation_start/graduation (listed already)": 2}


def test_malformed_rows_and_drained_pools_are_skipped() -> None:
    rows = _graduate_rows()
    start, poll = rows[1], rows[2]
    no_mint = {k: v for k, v in start.items() if k != "mint"}
    no_time = {k: v for k, v in start.items() if k not in ("timestamp", "migrated_at")}
    bad = [
        no_mint,
        no_time,
        dict(poll, timestamp="soon"),
        dict(poll, pool_sol="lots"),
        dict(poll, pool_sol=0.0),
    ]
    records, lanes = _convert([start, *bad])

    assert records == [Listing(SAMPLE_PUMP_MINT, 100.0, kind="graduation")]
    assert lanes.stats.skipped == {SKIP_MALFORMED: 3, SKIP_NO_PRICE: 1}
    assert lanes.stats.ignored == {"observation_start/graduation (listed already)": 1}


def test_rows_of_other_sources_and_events_are_counted_not_translated() -> None:
    rows: list[dict[str, Any]] = [
        {"event": "curve_poll", "source": "post_exit", "mint": SAMPLE_MINT},
        {"event": "observation_start", "source": "launch_sample", "mint": SAMPLE_MINT},
        {"timestamp": 1.0, "mint": SAMPLE_MINT, "signal": "buy"},
        {"event": "screening", "mint": SAMPLE_MINT},
        # A Meteora DAMM v2 row of a v0.4.0 capture: trading-meteora's now.
        {"event": "damm_state", "timestamp": 1.0, "pool": SAMPLE_MINT},
    ]
    records, lanes = _convert(rows)

    assert records == []
    assert lanes.stats.ignored == {
        "curve_poll/post_exit": 1,
        "observation_start/launch_sample": 1,
        "no event": 1,
        "screening": 1,
        "damm_state": 1,
    }


def test_unknown_sources_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown sources: launch_sample"):
        LaneRows(sources=("graduation", "launch_sample"))


# -- new PumpSwap pools (FEAT-80) ----------------------------------------------------


def test_a_new_pool_is_listed_at_its_creation_and_priced_by_its_decimals() -> None:
    records, lanes = _convert(_new_pool_rows())

    listing, reading = records
    assert listing == Listing(SAMPLE_MINT, 90.0, kind="listing", creator=CREATOR)
    pool = make_reading(SAMPLE_MINT, at=102.0)
    # 9 decimals: a thousand times the 6-decimal price PoolReading assumes.
    assert reading.price == pytest.approx(pool.price * 1_000, rel=1e-9)
    assert reading.liquidity == pytest.approx(pool.pool_sol)
    assert lanes.stats.written == {"listing": 1, "reading": 1}


def test_a_new_pool_without_decimals_or_creator() -> None:
    records, lanes = _convert(
        _new_pool_rows(decimals=None, coin_creator=NO_CREATOR, created_at=None)
    )
    assert records == []
    assert lanes.stats.skipped == {SKIP_NO_DECIMALS: 2}
    assert lanes.listed[SAMPLE_MINT].listing == Listing(SAMPLE_MINT, 100.0)


def test_sources_choose_what_is_written() -> None:
    rows = _graduate_rows() + _new_pool_rows()
    records, lanes = _convert(rows, sources=("new_pool",))

    assert {r.instrument_id for r in records} == {SAMPLE_MINT}
    assert lanes.stats.ignored["curve_poll/graduation"] == 3


# -- forgetting ----------------------------------------------------------------------


def test_forget_keeps_only_what_is_asked() -> None:
    _, lanes = _convert(_graduate_rows() + _new_pool_rows())
    lanes.forget([SAMPLE_MINT])
    assert set(lanes.listed) == {SAMPLE_MINT}


# -- files ---------------------------------------------------------------------------


def test_parts_in_any_order_are_read_twice(tmp_path: Path) -> None:
    rows = _graduate_rows()
    late = _write(tmp_path / "capture.jsonl", rows[2:])
    with gzip.open(tmp_path / "capture.jsonl.1.gz", "wt", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rows[:2]))
    lanes = LaneRows()

    records = list(lane_records([late, tmp_path / "capture.jsonl.1.gz"], lanes))

    assert [type(r) for r in records] == [Reading, Reading, Reading, Listing]
    assert not lanes.stats.skipped


@pytest.mark.parametrize("name", ["rows.jsonl", "rows.jsonl.gz"])
def test_rows_are_written_for_the_sweep(tmp_path: Path, name: str) -> None:
    capture = _write(tmp_path / "capture.jsonl", _graduate_rows() + _new_pool_rows())
    out = tmp_path / name

    stats = write_lane_rows([capture], out)

    assert stats.written == {"listing": 2, "reading": 4, "trade": 0, "holders": 0}
    opener: Any = gzip.open if name.endswith(".gz") else open
    with opener(out, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert {row["row"] for row in rows} == {"listing", "reading"}
    assert all(parse_row(row) is not None for row in rows)
    assert not any("pool_sol" in row or "source" in row for row in rows)
    loaded = load_capture([out])
    assert [r.at for r in loaded] == sorted(r.at for r in loaded)
    assert not (tmp_path / f"{name}.partial").exists()


def test_the_output_must_be_a_new_jsonl_file(tmp_path: Path) -> None:
    capture = _write(tmp_path / "capture.jsonl", _graduate_rows())
    with pytest.raises(ValueError, match="must end in .jsonl or .jsonl.gz"):
        write_lane_rows([capture], tmp_path / "rows.csv")
    with pytest.raises(ValueError, match="exists already"):
        write_lane_rows([capture], capture)


def test_a_failed_conversion_leaves_no_file(tmp_path: Path) -> None:
    out = tmp_path / "rows.jsonl"
    with pytest.raises(OSError):
        write_lane_rows([tmp_path / "missing.jsonl"], out)
    assert list(tmp_path.iterdir()) == []
