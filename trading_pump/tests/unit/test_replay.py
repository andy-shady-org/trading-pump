"""Unit tests for ``replay.py``: capture playback through the engine."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from trading_core.config.settings import EngineSettings

from trading_pump.market import PoolReading
from trading_pump.replay import (
    CaptureMarket,
    CapturePoolSource,
    ReplayClock,
    is_graduation_row,
    read_rows,
    replay_capture,
    replay_settings,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading

MINT = SAMPLE_MINT


def graduation_rows(
    mint: str, path: list[tuple[float, float]], *, migrated_at: float = 0.0
) -> list[dict[str, Any]]:
    """Capture rows of one graduate: (seconds after migration, price scale)."""
    rows: list[dict[str, Any]] = [
        {"timestamp": migrated_at, "mint": mint, "event": "migration"},
        {
            "timestamp": migrated_at,
            "mint": mint,
            "event": "observation_start",
            "source": "graduation",
            "migrated_at": migrated_at,
            "pool": "P",
            "held": False,
        },
    ]
    for offset, scale in path:
        reading = make_reading(mint, at=migrated_at + offset, scale=scale)
        rows.append(reading.capture_row(source="graduation"))
    return rows


def settings(**overrides: Any) -> EngineSettings:
    values: dict[str, Any] = {
        "module": "pumpfun",
        "order_size": 0.1,
        "paper_starting_balance": 2.0,
        "cycle_seconds": 1.0,
        "risk": {
            "max_total_exposure": 1.0,
            "max_position_size": 0.1,
            "max_active_positions": 5,
        },
        "exits": {
            "take_profit_pct": 0.2,
            "stop_loss_pct": 0.15,
            "max_hold_seconds": 1800,
        },
        "module_settings": {
            "graduation": {"observation_seconds": 600},
            "execution": {"paper_entry_delay_seconds": 2.0},
            "capture": {"path": "should-be-ignored.jsonl"},
        },
    }
    values.update(overrides)
    return EngineSettings.from_mapping(values)


def test_rows_are_read_from_plain_and_gzip_parts(tmp_path: Path) -> None:
    rows = graduation_rows(MINT, [(2.0, 1.0)])
    plain = tmp_path / "a.jsonl"
    plain.write_text(json.dumps(rows[0]) + "\nnot json\n[1]\n")
    packed = tmp_path / "b.jsonl.gz"
    with gzip.open(packed, "wt") as handle:
        handle.write("\n".join(json.dumps(r) for r in rows[1:]))

    assert list(read_rows([plain, packed])) == rows


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"event": "migration"}, True),
        ({"event": "curve_poll", "source": "graduation"}, True),
        ({"event": "observation_end", "source": "graduation"}, True),
        ({"event": "curve_poll", "source": "launch_sample"}, False),
        ({"event": "trade", "source": "graduation"}, False),
    ],
)
def test_is_graduation_row(row: dict[str, Any], expected: bool) -> None:
    assert is_graduation_row(row) is expected


def test_the_market_indexes_migrations_and_readings_without_look_ahead() -> None:
    rows = [
        *graduation_rows(MINT, [(2.0, 1.0), (4.0, 1.5)], migrated_at=100.0),
        *graduation_rows(SAMPLE_PUMP_MINT, [(2.0, 1.0)], migrated_at=50.0),
        {"event": "observation_start", "source": "graduation", "mint": MINT},
        {"event": "curve_poll", "source": "graduation", "mint": "", "timestamp": 1},
        {"event": "curve_poll", "source": "graduation", "mint": MINT, "timestamp": "x"},
        {
            "event": "curve_poll",
            "source": "graduation",
            "mint": MINT,
            "timestamp": 1,
            "pool_sol": "bad",
        },
        {"event": "curve_poll", "source": "launch_sample", "mint": MINT},
    ]
    market = CaptureMarket.from_rows(rows)

    assert market.migrations == [(50.0, SAMPLE_PUMP_MINT), (100.0, MINT)]
    assert market.start == 50.0 and market.end == 104.0
    assert market.reading_at(MINT, 101.0) is None
    first = market.reading_at(MINT, 103.0)
    assert first is not None and first.at == 102.0
    assert first.market_cap_sol == pytest.approx(410.8, abs=0.1)
    assert market.reading_at(MINT, 1e9) is not None
    assert market.reading_at("unknown", 1.0) is None


def test_an_empty_capture_has_no_span() -> None:
    market = CaptureMarket.from_rows([])
    assert market.start is None and market.end is None


async def test_the_capture_source_answers_like_rpc_with_a_fixed_fee() -> None:
    market = CaptureMarket.from_rows(graduation_rows(MINT, [(2.0, 1.0)]))
    source = CapturePoolSource(market, fee_bps=90)
    found, rejected = await source.read_pools([MINT, SAMPLE_PUMP_MINT], now=3.0)
    assert set(found) == {MINT} and rejected == {SAMPLE_PUMP_MINT: "missing"}
    fee = await source.swap_fee(found[MINT])
    assert (fee.bps, fee.source) == (90, "replay")


async def test_the_replay_clock_moves_only_when_told() -> None:
    clock = ReplayClock(10.0)
    await clock.sleep(2.5)
    await clock.sleep(-1)
    assert clock() == 12.5


def test_replay_settings_force_paper_and_new_files(tmp_path: Path) -> None:
    run = replay_settings(settings(mode="paper"), tmp_path / "out")
    assert run.mode == "paper"
    assert run.status_path == str(tmp_path / "out" / "status.json")
    assert run.event_log_path is None and run.log_file is None
    assert run.module_settings["capture"]["path"] is None
    (tmp_path / "out" / "audit.jsonl").write_text("")
    with pytest.raises(ValueError, match="already holds a replay"):
        replay_settings(settings(), tmp_path / "out")


async def test_a_riser_is_bought_after_the_delay_and_sold_at_take_profit(
    tmp_path: Path,
) -> None:
    path = [(2.0 * i, 1.0 + 0.005 * i) for i in range(1, 30)]  # to 1.145x at 58 s
    path += [(60.0, 1.3), (62.0, 1.32), (64.0, 1.34), (66.0, 1.5), (68.0, 1.6)]
    path += [(70.0 + 10.0 * i, 1.6) for i in range(1, 5)]
    flat = [(2.0 * i, 1.0) for i in range(1, 60)]
    rows = [
        *graduation_rows(MINT, path, migrated_at=0.0),
        *graduation_rows(SAMPLE_PUMP_MINT, flat, migrated_at=1.0),
    ]
    market = CaptureMarket.from_rows(rows)

    result = await replay_capture(market, settings(), tmp_path / "run", fee_bps=100)

    trades = [
        json.loads(line)
        for line in (tmp_path / "run" / "audit.jsonl").read_text().splitlines()
        if '"trade"' in line
    ]
    actions = [(t["payload"]["action"], t["payload"]["instrument_id"]) for t in trades]
    assert actions == [("buy", MINT), ("sell", MINT)]
    buy, sell = (t["payload"] for t in trades)
    # Signal on the 60 s reading (1.3x the 2 s one at 1.005x), filled 2 s
    # later at the 62 s reading.
    assert buy["entry_metrics"]["ratio"] == pytest.approx(1.3 / 1.005, rel=1e-5)
    assert buy["timestamp"] == 62.0
    assert (
        buy["fill_metadata"]["market_cap_sol"]
        > buy["entry_metrics"]["signal_market_cap_sol"]
    )
    assert buy["strategy"] == "pumpswap_momentum"
    assert buy["cost_breakdown"]["swap_fee"] > 0
    assert sell["reason"] == "take_profit"
    assert sell["cost_breakdown"]["rent"] == -buy["cost_breakdown"]["rent"]
    assert result.totals["positions_closed"] == 1
    assert result.totals["net_pnl"] > 0
    assert result.migrations == 2 and result.cycles > 60
    assert result.tracker["stats"]["followed"] == 2
    assert not (tmp_path / "should-be-ignored.jsonl").exists()


async def test_replaying_nothing_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no graduation rows"):
        await replay_capture(CaptureMarket(), settings(), tmp_path / "x")


def test_reading_dataclass_round_trip() -> None:
    reading = PoolReading(MINT, 1.0, 2, 3)
    assert reading.pool is None
