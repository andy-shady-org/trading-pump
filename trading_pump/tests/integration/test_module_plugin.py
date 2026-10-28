"""trading-core runs the module it finds through the entry point, end to end.

A paper engine with :class:`PumpModule` (installed as ``pumpfun``) against a
fake pool source: a migration, pool readings, the FEAT-76 signal, the paper
buy, the take-profit sell, the audit trail, the status file and the
dashboard, all through trading-core's own code paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console
from trading_core.config.settings import EngineSettings
from trading_core.engine.engine import TradingEngine
from trading_core.module.registry import available_modules, resolve_module
from trading_core.ops.alerts import AlertDispatcher
from trading_core.ui.dashboard import build_dashboard

from trading_pump.config.env import Credentials
from trading_pump.module import PumpModule
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_reading
from trading_pump.tests.support.fakes import FakeClock, FakePoolSource

MINT = SAMPLE_MINT


def test_the_entry_point_names_the_module() -> None:
    assert "pumpfun" in available_modules()
    assert resolve_module("pumpfun") is PumpModule


def _settings(tmp_path: Path) -> EngineSettings:
    config = json.loads(
        (Path(__file__).parents[3] / "configs" / "paper.example.json").read_text()
    )
    config.update(
        status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        event_log_path=None,
        log_file=None,
    )
    config["module_settings"]["capture"]["path"] = str(tmp_path / "capture.jsonl")
    return EngineSettings.from_mapping(config)


def _set(source: FakePoolSource, scale: float) -> None:
    reading = make_reading(MINT, scale=scale)
    source.set(MINT, reading.base_reserve, reading.quote_reserve)


async def test_a_paper_run_buys_the_signal_and_takes_profit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    clock = FakeClock(start=1_793_000_000.0)
    source = FakePoolSource(fee_bps=125)
    module = resolve_module(settings.module)(
        source=source,
        credentials=Credentials(),
        clock=clock.time,
        sleep=clock.async_sleep,
        live_feeds=False,
        **settings.module_settings,
    )
    engine = TradingEngine(
        module,
        settings,
        alerts=AlertDispatcher(provider="none"),
        clock=clock.time,
        monotonic=clock.time,
    )
    await engine.start()
    assert isinstance(module, PumpModule)

    module.on_migration(MINT)
    _set(source, 1.0)
    for second in range(0, 70, 2):
        if second == 60:
            _set(source, 1.3)
        await module.poller.poll_once()
        await engine.run_cycle()
        clock.advance(2.0)
    assert engine.book.get(MINT) is not None

    _set(source, 1.6)
    clock.advance(1.0)
    await module.poller.poll_once()
    await engine.run_cycle()
    assert engine.book.get(MINT) is None

    view = engine.view()
    console = Console(record=True, width=160)
    console.print(build_dashboard(view, module))
    screen = console.export_text()
    assert "PumpPortal" in screen and "pumpswap_momentum" in screen
    await engine.shutdown()

    records = [
        json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()
    ]
    trades = [r["payload"] for r in records if r.get("type") == "trade"]
    assert [t["action"] for t in trades] == ["buy", "sell"]
    assert trades[1]["reason"] == "take_profit" and trades[1]["net_pnl"] > 0
    assert trades[0]["strategy"] == "pumpswap_momentum"
    provenance = next(r for r in records if r.get("type") == "run_started")
    assert "lane" in json.dumps(provenance)
    capture = (tmp_path / "capture.jsonl").read_text()
    assert '"event": "observation_start"' in capture
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["module"] == "pumpfun"


@pytest.mark.regression("BUG-149")
async def test_no_rpc_means_no_entries_and_the_condition_is_shown(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    clock = FakeClock(start=1_793_000_000.0)
    source = FakePoolSource()
    module = PumpModule(
        source=source,
        credentials=Credentials(),
        clock=clock.time,
        live_feeds=False,
        **settings.module_settings,
    )
    engine = TradingEngine(
        module,
        settings,
        alerts=AlertDispatcher(provider="none"),
        clock=clock.time,
        monotonic=clock.time,
    )
    await engine.start()
    module.on_migration(MINT)
    _set(source, 1.0)
    await module.poller.poll_once()
    await engine.run_cycle()
    assert engine.entry_blockers() == []
    source.fail = RuntimeError("no healthy endpoint")
    for second in range(2, 160, 2):
        if second == 60:
            _set(source, 1.3)  # the signal, unseen: the RPC is down
        await module.poller.poll_once()
        await engine.run_cycle()
        clock.advance(2.0)

    assert len(engine.book) == 0
    assert engine.degraded["solana rpc"] == "no healthy endpoint"
    assert "market data stale" in engine.entry_blockers()
    await engine.shutdown()
