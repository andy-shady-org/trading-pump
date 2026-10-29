"""Unit tests for ``module.py``: PumpModule against trading-core's contract."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from trading_core.module.base import (
    ExecutionRefused,
    MarketQuote,
    OrderRequest,
    Side,
)
from trading_core.positions import Position

from trading_pump.config.env import Credentials, load_credentials
from trading_pump.feed import CONDITION_FEED, CONDITION_RPC
from trading_pump.module import PUMP_QUOTE, PumpModule, QuoteUnavailable
from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import (
    GRADUATION_BASE_RESERVE,
    GRADUATION_QUOTE_RESERVE,
)
from trading_pump.tests.support.fakes import FakeClock, FakeHost, FakePoolSource

MINT = SAMPLE_MINT


def _module(
    tmp_path: Path | None = None, **settings: Any
) -> tuple[PumpModule, FakePoolSource, FakeClock, FakeHost]:
    source = FakePoolSource(fee_bps=100)
    clock = FakeClock(start=1_000.0)
    host = FakeHost()
    capture = (
        {"path": str(tmp_path / "capture.jsonl"), "flush_interval_seconds": 0.01}
        if tmp_path
        else {"path": None}
    )
    module = PumpModule(
        source=source,
        credentials=Credentials(),
        clock=clock.time,
        sleep=clock.async_sleep,
        live_feeds=False,
        capture=capture,
        **settings,
    )
    module.bind(host)
    return module, source, clock, host


def test_identity_and_quote_asset() -> None:
    module, *_ = _module()
    assert (module.name, module.quote) == ("pumpfun", PUMP_QUOTE)
    assert module.quote.format(0.0000205, signed=True) == "+20.5000 µSOL"
    assert module.format_price(4.1e-7) == "0.4100 µSOL"
    assert module.format_price(None) == "-" and module.format_price(0) == "-"
    assert module.is_public_identifier(SAMPLE_PUMP_MINT)
    assert not module.is_public_identifier("deadbeef" * 5)


def test_unknown_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="Unknown module_settings keys: lanes"):
        PumpModule(source=FakePoolSource(), credentials=Credentials(), lanes={})


def test_without_a_source_the_sdk_client_is_built_from_the_environment() -> None:
    module = PumpModule(
        credentials=load_credentials(
            {
                "PUMPFUN_RPC_URL": "https://a.example",
                "PUMPFUN_RPC_URLS": "https://b.example",
            }
        ),
        capture={"path": None},
        execution={"priority_fee_lamports": 7_000, "use_jito": False},
    )
    client = module.client
    assert isinstance(client, PumpFunExecutionClient)
    assert [e.url for e in client.rpc_pool.endpoints] == [
        "https://a.example",
        "https://b.example",
    ]
    assert client.priority_fee_lamports == 7_000
    rows = dict(module.status_rows())
    assert rows["RPC endpoints"] == "2/2 healthy"


async def test_quotes_come_from_the_latest_reading_and_refresh_when_old() -> None:
    module, source, clock, _ = _module()
    source.set(MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)

    quote = await module.get_quote(MINT)
    price = (GRADUATION_QUOTE_RESERVE / 1e9) / (GRADUATION_BASE_RESERVE / 1e6)
    assert quote.last == pytest.approx(price) and not quote.stale
    assert quote.bid == pytest.approx(price * 0.99)
    assert quote.ask == pytest.approx(price * 1.01)
    assert quote.mark == pytest.approx(price)
    assert len(source.reads) == 1

    clock.advance(10.0)
    await module.get_quote(MINT)
    assert len(source.reads) == 1  # fresh enough
    clock.advance(10.0)
    await module.get_quote(MINT)
    assert len(source.reads) == 2


async def test_no_pool_means_no_quote_and_a_drained_one_is_stale() -> None:
    module, source, _, _ = _module()
    source.reject(MINT, "not_pumpswap")
    with pytest.raises(QuoteUnavailable, match="not_pumpswap"):
        await module.get_quote(MINT)
    source.set(MINT, 0, 10)
    quote = await module.get_quote(MINT)
    assert quote.stale and quote.mark is None


@pytest.mark.regression("BUG-136")
async def test_exit_value_is_what_selling_into_the_pool_returns_after_the_fee() -> None:
    module, source, _, _ = _module()
    source.set(MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)
    fill = await module.execute(OrderRequest(MINT, Side.BUY, notional=1.0), paper=True)
    position = Position(MINT, size=fill.size, entry_price=fill.price, cost_basis=1.0)
    quote = await module.get_quote(MINT)

    value = module.exit_value(position, quote)

    spot = position.size * (quote.last or 0.0)
    # Below spot: the sale moves the price and pays the 1% fee.
    assert 0.97 * spot < value < 0.99 * spot


@pytest.mark.regression("BUG-147")
def test_exit_value_without_a_pool_reading_falls_back_to_the_quote() -> None:
    module, *_ = _module()
    position = Position(MINT, size=10.0, entry_price=1.0, cost_basis=10.0)
    quote = MarketQuote(MINT, bid=0.5, ask=0.6)
    assert module.exit_value(position, quote) == pytest.approx(5.0)


async def test_paper_and_live_execution() -> None:
    module, source, _, _ = _module()
    source.set(MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)
    fill = await module.execute(OrderRequest(MINT, Side.BUY, notional=0.1), paper=True)
    assert fill.simulated and fill.size > 0
    with pytest.raises(ExecutionRefused, match="not built yet"):
        await module.execute(OrderRequest(MINT, Side.BUY, notional=0.1), paper=False)


async def test_balance_needs_the_wallet_key() -> None:
    module, *_ = _module()
    with pytest.raises(RuntimeError, match="PUMPFUN_PRIVATE_KEY is not set"):
        await module.get_balance()

    class Wallet:
        async def get_wallet_balance_sol(self) -> float:
            return 1.25

    keyed = PumpModule(
        client=Wallet(),
        source=FakePoolSource(),
        credentials=Credentials(private_key="k"),
        capture={"path": None},
    )
    assert await keyed.get_balance() == 1.25


async def test_migrations_start_tracking_and_reads_reach_the_host(
    tmp_path: Path,
) -> None:
    module, source, clock, host = _module(tmp_path)
    await module.start()
    source.set(MINT, GRADUATION_BASE_RESERVE, GRADUATION_QUOTE_RESERVE)

    module.on_migration(MINT)
    module.on_migration(MINT)  # repeated event
    assert await module.poller.poll_once() == 1
    source.fail = RuntimeError("rpc down")
    clock.advance(5.0)
    await module.poller.poll_once()
    module._feed_state(False, "closed")

    assert host.market_data == 1
    assert host.degraded == {CONDITION_RPC: "rpc down", CONDITION_FEED: "closed"}
    assert MINT in module.readings and len(module.tracker) == 1
    assert dict(module.status_rows())["Capture"].endswith("rows")
    await module.stop()
    rows = [
        json.loads(line)
        for line in (tmp_path / "capture.jsonl").read_text().splitlines()
    ]
    assert [r["event"] for r in rows] == [
        "migration",
        "observation_start",
        "curve_poll",
    ]


async def test_start_warns_about_unread_variables_and_a_key_in_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUMPFUN_STOP_LOSS", "0.9")
    module = PumpModule(
        source=FakePoolSource(),
        credentials=load_credentials(
            {"PUMPFUN_STREAM_URL": "wss://pumpportal.fun/api/data?api-key=SECRET"}
        ),
        capture={"path": None},
        live_feeds=False,
    )
    host = FakeHost()
    module.bind(host)
    await module.start()
    await module.start()  # idempotent
    messages = [m for m, _ in host.events]
    assert any("PUMPFUN_STOP_LOSS is set but not read" in m for m in messages)
    assert any("BUG-118" in m for m in messages)
    assert not any("SECRET" in m for m in messages)
    await module.stop()
    await module.stop()


async def test_live_feeds_run_as_tasks_and_stop_cleanly() -> None:
    module = PumpModule(
        source=FakePoolSource(), credentials=Credentials(), capture={"path": None}
    )
    started: list[str] = []

    async def feed_run() -> None:
        started.append("feed")
        await asyncio.sleep(3600)

    module.feed.run = feed_run
    await module.start()
    await asyncio.sleep(0)
    assert started == ["feed"] and len(module._tasks) == 2
    await module.stop()
    assert module._tasks == [] and module.feed.stream_stop_requested()


async def test_stop_closes_the_client_and_ignores_its_errors() -> None:
    class Client:
        closed = 0

        async def close(self) -> None:
            Client.closed += 1
            raise RuntimeError("already closed")

    module = PumpModule(
        client=Client(),
        source=FakePoolSource(),
        credentials=Credentials(),
        capture={"path": None},
        live_feeds=False,
    )
    await module.start()
    await module.stop()
    assert Client.closed == 1


def test_the_poll_tick_follows_the_shortest_schedule() -> None:
    module, *_ = _module(graduation={"fast_poll_interval_seconds": 0.1})
    assert module.poll_tick == 0.5
    slow, *_ = _module(
        graduation={"fast_poll_interval_seconds": 3.0, "poll_interval_seconds": 5.0}
    )
    assert slow.poll_tick == 3.0


def test_the_pipeline_is_built_once_and_off_without_the_lane() -> None:
    module, *_ = _module()
    pipeline = module.pipeline()
    assert pipeline is not None and module.pipeline() is pipeline
    off, *_ = _module(lane={"enabled": False})
    assert off.pipeline() is None
    assert dict(off.strategy_rows()) == {"Lane": "off (record-only)"}
    off.on_migration(MINT)
    graduate = off.tracker.get(MINT)
    assert graduate is not None and graduate.signal_time is None


def test_screening_entries_builds_the_enricher_on_demand() -> None:
    module, *_ = _module(
        lane={"screen_entries": True}, screening={"preset": "balanced"}
    )
    pipeline = module.pipeline()
    assert pipeline is not None and "anti_rug" in pipeline.describe()
    assert module.enricher is not None
    assert module.enricher.config.max_acceptable_risk_score == 50.0


def test_status_strategy_and_provenance_rows() -> None:
    module, *_ = _module()
    module.poller.last_error = "rpc down"
    rows = dict(module.status_rows())
    assert rows["PumpPortal"] == "disconnected · 0 migrations"
    assert rows["Graduates"] == "0 followed · 0 readings"
    assert rows["Pool reads"] == "0 ok · 0 failed · rpc down"
    assert "Capture" not in rows and "RPC endpoints" not in rows
    strategy = dict(module.strategy_rows())
    assert strategy["Lane"] == "pumpswap_momentum"
    assert strategy["Signal"] == ">= 1.2x first price at 60s (+30s)"
    provenance = module.provenance()
    assert provenance["lane"]["min_ratio"] == 1.2
    assert provenance["capture_path"] is None
    assert provenance["rpc_endpoints"] == 0


def test_a_held_mint_is_marked_held_when_it_migrates(tmp_path: Path) -> None:
    module, *_ = _module()
    module.paper_executor.holdings.add(SAMPLE_PUMP_MINT, 5)
    rows: list[dict[str, Any]] = []
    module.tracker.record = rows.append
    module.on_migration(SAMPLE_PUMP_MINT)
    assert rows[-1]["held"] is True
    assert module.poller.due(0.0)[0] == SAMPLE_PUMP_MINT


@pytest.mark.regression("BUG-157")
def test_the_capture_is_rotated_and_pruned_by_its_own_policy(tmp_path: Path) -> None:
    module = PumpModule(
        source=FakePoolSource(),
        credentials=Credentials(),
        live_feeds=False,
        capture={
            "path": str(tmp_path / "capture.jsonl"),
            "max_bytes": 1024,
            "max_files": 3,
            "max_age_days": 2,
            "compress": False,
        },
    )
    recorder = module.recorder
    assert recorder is not None
    assert (recorder.policy.max_bytes, recorder.policy.max_files) == (1024, 3)
    assert recorder.policy.max_age_days == 2
    assert recorder.policy.compress_archives is False


async def test_an_unbound_module_reports_nowhere_and_a_given_client_is_used() -> None:
    class Client:
        async def get_pumpswap_pool_states(self, *_: Any, **__: Any) -> Any:
            return {}

    client = Client()
    module = PumpModule(
        client=client, credentials=Credentials(), capture={"path": None}
    )
    assert module.client is client
    module._rpc_ok()
    module._rpc_failed("down")
    module._feed_state(False, "closed")
    assert module.host is None


class _GenesisPool:
    """An RPC pool whose endpoints report the given genesis hashes."""

    def __init__(self, hashes: dict[str, str | None]) -> None:
        from trading_pump.infra.rpc_pool import RpcEndpoint

        self.hashes = hashes
        self.endpoints = [RpcEndpoint(url) for url in hashes]
        self.removed: list[str] = []

    async def endpoint_genesis_hash(self, endpoint: Any) -> str | None:
        return self.hashes[endpoint.url]

    def remove_endpoint(self, url: str) -> bool:
        self.removed.append(url)
        return True


DEVNET = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


@pytest.mark.regression("BUG-160")
async def test_an_endpoint_on_devnet_is_dropped_while_a_mainnet_one_is_left() -> None:
    from trading_pump.infra.rpc_pool import MAINNET_GENESIS_HASH

    module, _, _, host = _module()
    pool = _GenesisPool(
        {
            "https://dev.example/?api-key=K": DEVNET,
            "https://main.example": MAINNET_GENESIS_HASH,
        }
    )
    module.client = type("Client", (), {"rpc_pool": pool})()
    problems = await module.check_rpc_network()
    assert problems == ["dev.example serves devnet"]
    assert pool.removed == ["https://dev.example/?api-key=K"]
    [(event, _)] = host.events
    assert "left out of the pool" in event and "api-key" not in event
    assert host.degraded == {}


@pytest.mark.regression("BUG-160")
async def test_only_wrong_networks_keep_the_endpoints_and_report_degraded() -> None:
    module, _, _, host = _module()
    pool = _GenesisPool({"https://dev.example": DEVNET, "https://odd.example": "X"})
    module.client = type("Client", (), {"rpc_pool": pool})()
    problems = await module.check_rpc_network()
    assert problems == [
        "dev.example serves devnet",
        "odd.example serves an unknown network",
    ]
    assert pool.removed == []
    assert "PUMPFUN_RPC_URL" in host.degraded["rpc network"]


async def test_an_unconfirmed_endpoint_is_kept_and_mainnet_alone_is_quiet() -> None:
    from trading_pump.infra.rpc_pool import MAINNET_GENESIS_HASH

    module, _, _, host = _module()
    module.client = type(
        "Client",
        (),
        {"rpc_pool": _GenesisPool({"https://m.example": MAINNET_GENESIS_HASH})},
    )()
    assert await module.check_rpc_network() == []
    silent = _GenesisPool(
        {"https://quiet.example": None, "https://dev.example": DEVNET}
    )
    module.client = type("Client", (), {"rpc_pool": silent})()
    assert await module.check_rpc_network() == ["dev.example serves devnet"]
    assert silent.removed == ["https://dev.example"] and host.degraded == {}
    module.client = None
    assert await module.check_rpc_network() == []
    unbound = PumpModule(
        source=FakePoolSource(),
        credentials=Credentials(),
        live_feeds=False,
        capture={"path": None},
    )
    unbound.client = type(
        "Client", (), {"rpc_pool": _GenesisPool({"https://d.example": DEVNET})}
    )()
    assert await unbound.check_rpc_network() == ["d.example serves devnet"]
