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
from trading_pump.pools import CONDITION_POOL_FEED
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
    assert module.files() == (("Capture", str(tmp_path / "capture.jsonl")),)
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
    assert module.files() == ()
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


@pytest.mark.regression("BUG-163")
def test_the_migration_feed_waits_out_a_quiet_spell_before_reconnecting() -> None:
    """The migration-only subscription is silent between graduations; in
    rc.9's first 24 h the longest gap was 1,081 s and 56 gaps passed 300 s,
    so the old 300 s idle timeout reconnected about twice an hour for nothing.
    The 20 s pings stay the dead-socket check."""
    module, *_ = _module()

    assert module.feed.stream_idle_timeout_seconds == 1800.0 > 1_081
    assert module.feed.stream_heartbeat_seconds == 20.0


# -- rc11: per-lane exits (FEAT-79) and the instant lane (FEAT-78) ---------------
def _held(
    strategy: str | None, mark: float, *, opened_at: float = 0.0, stale: bool = False
) -> Position:
    return Position(
        MINT,
        size=10.0,
        entry_price=1.0,
        cost_basis=10.0,
        opened_at=opened_at,
        mark_price=mark,
        price_stale=stale,
        strategy=strategy,
    )


def test_a_lane_with_exits_sells_on_its_own_wider_take_profit() -> None:
    module, *_ = _module(
        lane={"exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.15}}
    )
    # +30%: under the lane's +50% target, so no exit (the engine's +20% would).
    assert module.should_exit(_held("pumpswap_momentum", 1.3), None, 10.0) is None
    decision = module.should_exit(_held("pumpswap_momentum", 1.5), None, 10.0)
    assert decision is not None and decision.reason == "take_profit"
    stop = module.should_exit(_held("pumpswap_momentum", 0.85), None, 10.0)
    assert stop is not None and stop.reason == "stop_loss"
    # A position of no known lane is left to the engine's exits.
    assert module.should_exit(_held("manual", 2.0), None, 10.0) is None
    assert module.should_exit(_held(None, 2.0), None, 10.0) is None


def test_a_lane_without_exits_leaves_the_engine_exits_in_charge() -> None:
    module, *_ = _module()
    assert module.should_exit(_held("pumpswap_momentum", 5.0), None, 10.0) is None


def test_the_instant_lane_exits_and_a_stale_price_only_times_out() -> None:
    module, *_ = _module(instant={"enabled": True})
    held = _held("pumpswap_instant", 1.6)
    decision = module.should_exit(held, None, 10.0)
    assert decision is not None and decision.reason == "take_profit"
    stale = _held("pumpswap_instant", 0.1, stale=True)
    assert module.should_exit(stale, None, 10.0) is None
    late = module.should_exit(stale, None, 1_800.0)
    assert late is not None and late.reason == "max_hold"


def test_strategy_rows_and_provenance_name_both_lanes() -> None:
    module, *_ = _module(
        instant={
            "enabled": True,
            "exits": {
                "take_profit_pct": 0.5,
                "stop_loss_pct": 0.15,
                "trailing_drop_pct": 0.2,
                "max_hold_seconds": 1800,
            },
        },
        lane={"exits": {"stop_loss_pct": 0.2}},
    )
    rows = dict(module.strategy_rows())
    assert rows["Instant Lane"] == "pumpswap_instant"
    assert rows["Instant Signal"] == ">= 1x and < 1.1x first price at 60s (+30s)"
    assert rows["Instant pool"] == "first MC 1000-2000 SOL"
    assert rows["Instant Exits"] == "TP +50% · SL -15% · trail 20% · max 30 min"
    assert rows["Lane"] == "pumpswap_momentum" and rows["Exits"] == "SL -20%"
    assert module.provenance()["instant"]["enabled"] is True
    target, *_ = _module(lane={"exits": {"take_profit_pct": 0.5}})
    assert dict(target.strategy_rows())["Exits"] == "TP +50%"


def test_the_pipeline_runs_with_the_instant_lane_alone() -> None:
    module, *_ = _module(instant={"enabled": True}, lane={"enabled": False})
    assert module.pipeline() is not None
    assert module.tracker.signal_after_seconds == 60.0
    off, *_ = _module(lane={"enabled": False})
    assert off.pipeline() is None and off.tracker.signal_after_seconds is None


# -- FEAT-80: the new-pool capture ----------------------------------------------


async def test_the_new_pool_feed_runs_only_when_enabled_and_stops_with_the_module() -> (
    None
):
    module = PumpModule(
        source=FakePoolSource(),
        credentials=Credentials(rpc_urls=("https://rpc.example/?api-key=SECRET",)),
        capture={"path": None},
        new_pools={"enabled": True, "warmup_seconds": 0},
    )
    started: list[str] = []

    async def run_forever(name: str) -> None:
        started.append(name)
        await asyncio.sleep(3600)

    module.feed.run = lambda: run_forever("feed")
    module.pool_feed.run = lambda: run_forever("pools")
    await module.start()
    await asyncio.sleep(0)
    assert sorted(started) == ["feed", "pools"] and len(module._tasks) == 3
    assert module.pool_feed.stream_url == "wss://rpc.example"
    assert module.pool_feed.stream_connect_url().endswith("api-key=SECRET")
    await module.stop()
    assert module._tasks == [] and module.pool_feed.stream_stop_requested()


def test_new_pool_rows_status_and_provenance(tmp_path: Path) -> None:
    module, _, _, host = _module(new_pools={"enabled": True})
    rows = dict(module.status_rows())
    assert rows["New pools"].startswith("disconnected · 0 new followed")
    assert module.provenance()["new_pools"]["enabled"] is True
    module._pool_feed_state(False, "connection closed")
    assert host.degraded[CONDITION_POOL_FEED] == "connection closed"
    module.bind(None)  # type: ignore[arg-type]
    module._pool_feed_state(True, "")
    off, *_ = _module()
    assert "New pools" not in dict(off.status_rows())
