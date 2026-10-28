"""Tests for the scripted risk drills (`ops/drills.py`, FEAT-69)."""

from __future__ import annotations

import datetime as _dt
import os
import shutil
from pathlib import Path

import pytest

from trading_pump.ops import drills
from trading_pump.ops.drills import (
    DRILL_NAMES,
    DrillClock,
    DrillReport,
    DrillResult,
    isolated_environment,
    run_drills,
)


@pytest.mark.regression("BUG-128", "BUG-130", "BUG-140")
async def test_every_drill_passes_on_the_current_risk_code(tmp_path: Path) -> None:
    report = await run_drills(workdir=tmp_path)

    failed = {
        r.name: r.error or [c.description for c in r.checks if not c.passed]
        for r in report.results
        if not r.passed
    }
    assert failed == {}
    assert [r.name for r in report.results] == list(DRILL_NAMES)
    assert report.passed
    # Each drill writes its own files under the work folder.
    assert (tmp_path / "cumulative_cap" / "bot_status.json").exists()
    assert (tmp_path / "midnight_lock" / "audit_trail.jsonl").exists()
    data = report.to_dict()
    assert data["passed"] is True
    assert len(data["drills"]) == 4
    assert all(d["checks"] for d in data["drills"])


async def test_only_selected_drills_run_in_a_temp_dir() -> None:
    report = await run_drills(["slow_tier_sell"])
    assert [r.name for r in report.results] == ["slow_tier_sell"]
    assert Path(report.workdir).name.startswith("pumpfun-drill-")
    shutil.rmtree(report.workdir)
    with pytest.raises(ValueError, match="Unknown drill"):
        await run_drills(["nope"])


async def test_a_drill_that_raises_is_a_failed_drill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(folder: Path) -> DrillResult:
        raise RuntimeError("boom")

    monkeypatch.setitem(drills.DRILLS, "midnight_lock", broken)
    report = await run_drills(["midnight_lock"], workdir=tmp_path)
    (result,) = report.results
    assert result.passed is False
    assert result.error == "RuntimeError: boom"
    assert report.passed is False


def test_result_and_report_pass_only_with_checks_all_passing() -> None:
    empty = DrillResult("x", "x")
    assert empty.passed is False  # a drill that checked nothing proves nothing
    assert empty.check("ok", True) is True
    assert empty.passed is True
    assert empty.check("bad", False, 3) is False
    assert empty.passed is False
    assert empty.to_dict()["checks"][1] == {
        "check": "bad",
        "passed": False,
        "detail": "3",
    }
    assert DrillReport([], "w", "t").passed is False


def test_clock_and_environment_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = _dt.datetime(2026, 1, 5, 23, 55, tzinfo=_dt.timezone.utc)
    clock = DrillClock(start)
    assert clock() == start.timestamp()
    clock.advance(600)
    assert clock() == start.timestamp() + 600
    clock.set(start)
    assert clock() == start.timestamp()

    monkeypatch.setenv("PUMPFUN_PRIVATE_KEY", "operator-key")
    monkeypatch.setenv("PUMPFUN_ALERT_PROVIDER", "discord")
    with isolated_environment(tmp_path):
        assert "PUMPFUN_PRIVATE_KEY" not in os.environ
        assert os.environ["PUMPFUN_ALERT_PROVIDER"] == "none"
        assert os.environ["PUMPFUN_EVENT_LOG_PATH"] == str(tmp_path / "events.jsonl")
        os.environ["PUMPFUN_LEFTOVER"] = "x"
    assert os.environ["PUMPFUN_PRIVATE_KEY"] == "operator-key"
    assert os.environ["PUMPFUN_ALERT_PROVIDER"] == "discord"
    assert "PUMPFUN_LEFTOVER" not in os.environ


def test_audit_types_skips_missing_files_and_bad_lines(tmp_path: Path) -> None:
    assert drills._audit_types(tmp_path) == []
    (tmp_path / "audit_trail.jsonl").write_text(
        '{"type": "operator_pause"}\nnot json\n{"type": "trade"}\n', encoding="utf-8"
    )
    assert drills._audit_types(tmp_path) == ["operator_pause", "trade"]
