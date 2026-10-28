"""Unit tests for ``services/market_recorder.py`` (FEAT-74, record-only).

Payload shapes follow GeckoTerminal and DexScreener answers recorded on
2026-10-26 (Solana new pools, Base Uniswap v4, BSC trending)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from trading_pump.services import market_recorder as mr
from trading_pump.services.slow_lane import HttpStatusError
from trading_pump.tests.support.fakes import FakeClock

START = 1_793_000_000.0


def gecko_pool(
    address: str,
    *,
    network: str = "solana",
    dex: str = "meteora-dbc",
    created: str = "2026-10-26T15:49:42Z",
    reserve: str | None = "2631.6049",
) -> dict[str, Any]:
    return {
        "id": f"{network}_{address}",
        "type": "pool",
        "attributes": {
            "address": address,
            "name": "NEXA / SOL",
            "pool_created_at": created,
            "base_token_price_usd": "0.0000028635",
            "fdv_usd": "2880.699713",
            "market_cap_usd": None,
            "reserve_in_usd": reserve,
            "price_change_percentage": {"m5": "-16.669", "h1": "-16.669", "h24": "-1"},
            "transactions": {"h1": {"buys": 6, "sells": 4}},
            "volume_usd": {"m5": "632.5", "h1": "632.5", "h24": "632.5"},
        },
        "relationships": {
            "base_token": {"data": {"id": f"{network}_Base{address}", "type": "token"}},
            "quote_token": {"data": {"id": f"{network}_Quote", "type": "token"}},
            "dex": {"data": {"id": dex, "type": "dex"}},
        },
    }


def dex_pair(
    address: str,
    *,
    price: str = "0.001301",
    liquidity: float | None = 13_010.91,
    h1: tuple[int, int] = (3, 0),
    m5: tuple[int, int] = (3, 0),
) -> dict[str, Any]:
    pair: dict[str, Any] = {
        "chainId": "base",
        "dexId": "uniswap",
        "pairAddress": address,
        "priceNative": "0.0000005573",
        "priceUsd": price,
        "txns": {
            "m5": {"buys": m5[0], "sells": m5[1]},
            "h1": {"buys": h1[0], "sells": h1[1]},
            "h24": {"buys": 3, "sells": 0},
        },
        "volume": {"h24": 69.87, "h6": 69.87, "h1": 69.87, "m5": 69.87},
        "priceChange": {"m5": 0.07, "h1": 0.07, "h6": 0.07, "h24": 0.07},
        "fdv": 13011,
        "marketCap": 13011,
    }
    if liquidity is not None:
        pair["liquidity"] = {"usd": liquidity, "base": 9946226, "quote": 0.0299}
    return pair


Responder = Callable[[str, Mapping[str, Any]], Any]


class FakeHttp:
    """Answers by URL fragment, most specific first."""

    def __init__(self, routes: dict[str, Responder]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        self.calls.append((url, dict(params or {})))
        for fragment in sorted(self.routes, key=len, reverse=True):
            if fragment in url:
                return self.routes[fragment](url, params or {})
        raise AssertionError(f"unexpected request {url}")

    async def post_json(self, url: str, payload: Any, **_: Any) -> Any:
        raise AssertionError("no POSTs")

    async def close(self) -> None:
        return None


class Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record_snapshot(self, record: dict[str, Any]) -> None:
        self.rows.append(dict(record))

    def events(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["event"] == name]


def _recorder(
    routes: dict[str, Responder],
    *,
    clock: FakeClock | None = None,
    state_path: Path | None = None,
    **config: Any,
) -> tuple[mr.MarketRecorder, FakeHttp, Sink, FakeClock]:
    clock = clock or FakeClock(START)
    http, sink = FakeHttp(routes), Sink()
    values: dict[str, Any] = {"gecko_gap_seconds": 0.0, "dexscreener_gap_seconds": 0.0}
    values.update(config)
    recorder = mr.MarketRecorder(
        http,
        sink,
        mr.MarketRecorderConfig(**values),
        state_path=state_path,
        sleep=clock.async_sleep,
        clock=clock.time,
        monotonic=clock.monotonic,
    )
    return recorder, http, sink, clock


def _pages(*pages: list[dict[str, Any]]) -> Responder:
    def answer(_url: str, params: Mapping[str, Any]) -> Any:
        page = int(params.get("page", 1))
        return {"data": pages[page - 1] if page <= len(pages) else []}

    return answer


def _pairs(*pairs: dict[str, Any]) -> Responder:
    return lambda _url, _params: {"pairs": list(pairs)}


# --- config and parsing --------------------------------------------------------


def test_config_validates_and_maps_ages_to_intervals() -> None:
    config = mr.MarketRecorderConfig()
    assert config.chains == ("solana", "base", "bsc")
    assert config.max_age_seconds == 604_800.0
    assert [config.interval_for(a) for a in (0, 1_800, 1_801, 21_600, 9e9)] == [
        30.0,
        30.0,
        120.0,
        120.0,
        600.0,
    ]
    assert config.share_for("solana", "pump-fun") == 0.1
    assert config.share_for("base", "uniswap-v4-base") == 1.0
    for bad, match in (
        ({"chains": ("solana", "tron")}, "unknown chain"),
        ({"chains": ()}, "unknown chain"),
        ({"tiers": ((0.0, 30.0),)}, "positive"),
        ({"tiers": ((100.0, 1.0), (50.0, 2.0))}, "ordered"),
        ({"sample": {"pump-fun": 0.5}}, "chain:dex"),
        ({"sample": {"solana:pump-fun": 2.0}}, "chain:dex"),
    ):
        with pytest.raises(ValueError, match=match):
            mr.MarketRecorderConfig(**bad)


def test_cli_strings_parse_to_chains_and_samples() -> None:
    assert mr.parse_chains(None) == mr.DEFAULT_CHAINS
    assert mr.parse_chains(" Solana, base ,") == ("solana", "base")
    assert mr.parse_sample(None) == mr.DEFAULT_SAMPLE
    assert mr.parse_sample("solana:pump-fun=0.25, bsc:four-meme=0.5,") == {
        "solana:pump-fun": 0.25,
        "bsc:four-meme": 0.5,
    }
    with pytest.raises(ValueError, match="chain:dex=share"):
        mr.parse_sample("solana:pump-fun")


def test_gecko_and_dexscreener_records_are_compacted() -> None:
    fields = mr.gecko_pool_fields(gecko_pool("PoolA", dex="pump-fun"), "solana")
    assert fields["pool"] == "PoolA" and fields["dex"] == "pump-fun"
    assert fields["base_token"] == "BasePoolA" and fields["quote_token"] == "Quote"
    assert fields["created_at"] == pytest.approx(1_793_029_782.0)
    assert fields["liquidity_usd"] == pytest.approx(2631.6049)
    assert fields["txns_h1"] == [6, 4] and fields["market_cap_usd"] is None
    assert fields["price_change_pct"]["m5"] == pytest.approx(-16.669)
    # Odd values degrade to None instead of raising.
    odd = gecko_pool("PoolB", created="soon", reserve="n/a")
    odd["relationships"]["dex"] = {"data": {"id": 7}}
    odd["relationships"]["base_token"] = {"data": {"id": "unprefixed"}}
    odd_fields = mr.gecko_pool_fields(odd, "solana")
    assert odd_fields["created_at"] is None and odd_fields["liquidity_usd"] is None
    assert odd_fields["dex"] is None and odd_fields["base_token"] == "unprefixed"
    assert mr.gecko_pool_fields({}, "solana")["pool"] is None

    snap = mr.dexscreener_snapshot(dex_pair("0xabc", liquidity=None))
    assert snap["liquidity_usd"] is None and snap["price_usd"] == pytest.approx(
        0.001301
    )
    assert snap["txns"] == {"m5": [3, 0], "h1": [3, 0], "h24": [3, 0]}
    assert snap["volume_usd"]["h6"] == pytest.approx(69.87)


# --- discovery ---------------------------------------------------------------


async def test_discovery_follows_new_pools_and_samples_pump_fun_curves() -> None:
    page1 = [
        gecko_pool("DbcPool", dex="meteora-dbc"),
        gecko_pool("PumpIn", dex="pump-fun"),
        gecko_pool("PumpOut", dex="pump-fun"),
        {"attributes": {}},  # no address: skipped
    ]
    recorder, http, sink, _ = _recorder(
        {"/new_pools": _pages(page1)},
        sample={"solana:pump-fun": 0.0},
        chains=("solana",),
    )
    assert await recorder.discover("solana") == 3
    rows = sink.events(mr.POOL_EVENT)
    assert [(r["pool"], r["followed"], r["sample_share"]) for r in rows] == [
        ("DbcPool", True, 1.0),
        ("PumpIn", False, 0.0),
        ("PumpOut", False, 0.0),
    ]
    assert all(r["venue"] == "market" and r["source"] == "new" for r in rows)
    assert set(recorder.followed) == {("solana", "DbcPool")}
    # First run: two pages read (the second empty), no gap counted.
    assert [c[1]["page"] for c in http.calls] == [1, 2]
    assert recorder.stats.discovery_gaps == 0

    # Next pass: stops at the first known pool; new ones above it are added.
    http.routes["/new_pools"] = _pages([gecko_pool("Fresh"), gecko_pool("DbcPool")])
    http.calls.clear()
    assert await recorder.discover("solana") == 1
    assert [c[1]["page"] for c in http.calls] == [1]


async def test_discovery_counts_a_gap_when_every_page_is_new() -> None:
    recorder, _, _, _ = _recorder(
        {"/new_pools": _pages([gecko_pool("A")], [gecko_pool("B")], [gecko_pool("C")])},
        chains=("solana",),
        max_new_pool_pages=2,
    )
    recorder._remember("solana", "Old")
    assert await recorder.discover("solana") == 2
    assert recorder.stats.discovery_gaps == 1


async def test_momentum_lists_follow_old_coins_once_with_their_rank() -> None:
    trending = [
        gecko_pool(
            "OldCoin",
            network="bsc",
            dex="pancakeswap-v3-bsc",
            created="2025-08-31T08:07:27Z",
        ),
        gecko_pool("Second", network="bsc"),
    ]
    recorder, http, sink, _ = _recorder(
        {
            "/trending_pools": lambda _u, _p: {"data": trending},
            "/pools": lambda _u, _p: {"data": [gecko_pool("Second", network="bsc")]},
        },
        chains=("bsc",),
    )
    assert await recorder.refresh_lists("bsc") == 2
    lists = sink.events(mr.LIST_EVENT)
    assert [(r["list"], r["pools"]) for r in lists] == [
        ("trending_5m", ["OldCoin", "Second"]),
        ("trending_1h", ["OldCoin", "Second"]),
        ("top_volume_24h", ["Second"]),
    ]
    pools = sink.events(mr.POOL_EVENT)
    assert [(r["pool"], r["source"], r["rank"]) for r in pools] == [
        ("OldCoin", "trending_5m", 1),
        ("Second", "trending_5m", 2),
    ]
    old = recorder.followed[("bsc", "OldCoin")]
    assert old.created_at is not None and old.created_at < START
    queries = [c[1] for c in http.calls]
    assert queries[0] == {"duration": "5m", "page": 1}
    assert queries[2] == {"sort": "h24_volume_usd_desc", "page": 1}
    assert recorder.stats.list_entries == 5


async def test_discovery_pass_runs_on_its_intervals_and_survives_errors() -> None:
    calls = {"n": 0}

    def flaky(_url: str, _params: Mapping[str, Any]) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise HttpStatusError(404, "gone")
        return {"data": []}

    recorder, http, _, clock = _recorder(
        {"/new_pools": flaky, "/trending_pools": flaky, "/pools": flaky},
        chains=("solana",),
    )
    await recorder.discovery_pass()  # new pools fail; the lists still run
    assert recorder.stats.errors == 1 and recorder.stats.list_calls == 3
    http.calls.clear()
    await recorder.discovery_pass()  # nothing due yet
    assert http.calls == []
    clock.advance(301.0)
    await recorder.discovery_pass()
    assert len(http.calls) == 1 + 3  # new pools (one empty page) and three lists

    off, off_http, _, _ = _recorder(
        {"/new_pools": _pages([])}, chains=("solana",), lists=False
    )
    await off.discovery_pass()
    assert [c[0].rsplit("/", 1)[-1] for c in off_http.calls] == ["new_pools"]


# --- following ---------------------------------------------------------------


async def test_snapshots_are_batched_per_chain_and_skip_unchanged_rows() -> None:
    pools = [f"0x{i:040x}" for i in range(31)]
    recorder, http, sink, clock = _recorder(
        {"/latest/dex/pairs/": _pairs(*[dex_pair(p.upper()) for p in pools])},
        chains=("base", "eth"),
    )
    for pool in pools:
        recorder._follow("base", {"pool": pool}, source="new", rank=None, now=START)
    recorder._follow("eth", {"pool": "0xeth"}, source="new", rank=None, now=START)
    assert await recorder.snapshot_due() == 31
    urls = [c[0] for c in http.calls]
    assert [u.split("/pairs/")[1].split("/")[0] for u in urls] == [
        "base",
        "base",
        "ethereum",
    ]
    assert urls[0].count(",") == 29 and urls[1].endswith(pools[30])
    snap = sink.events(mr.SNAPSHOT_EVENT)[0]
    assert snap["chain"] == "base" and snap["source"] == "new"
    assert snap["dex"] == "uniswap" and snap["age_seconds"] == 0.0
    assert recorder.followed[("eth", "0xeth")].missing == 1

    # Nothing due 10 s later; at 30 s all are due but unchanged: not written.
    http.calls.clear()
    clock.advance(10.0)
    assert await recorder.snapshot_due() == 0 and http.calls == []
    clock.advance(20.0)
    assert await recorder.snapshot_due() == 0
    assert recorder.stats.snapshots_unchanged == 31
    # The heartbeat writes an unchanged pool anyway.
    clock.advance(1_800.0)
    assert await recorder.snapshot_due() == 31


async def test_pools_end_when_dead_missing_or_too_old() -> None:
    answers: dict[str, dict[str, Any]] = {
        "Quiet": dex_pair("Quiet", liquidity=200.0, h1=(0, 0), m5=(0, 0)),
        "Curve": dex_pair("Curve", liquidity=None, h1=(0, 0), m5=(0, 0)),
        "Busy": dex_pair("Busy", liquidity=200.0, h1=(5, 1)),
        "Deep": dex_pair("Deep", liquidity=50_000.0, h1=(0, 0)),
    }

    def pairs(url: str, _params: Mapping[str, Any]) -> Any:
        asked = url.rsplit("/", 1)[-1].split(",")
        return {"pairs": [answers[a] for a in asked if a in answers]}

    recorder, _, sink, clock = _recorder(
        {"/latest/dex/pairs/": pairs}, chains=("solana",)
    )
    for pool in ("Quiet", "Curve", "Busy", "Deep", "Gone"):
        recorder._follow("solana", {"pool": pool}, source="new", rank=None, now=START)
    await recorder.snapshot_due()
    assert len(recorder.followed) == 5  # too young to be dead
    clock.advance(3_600.0)
    for _ in range(4):
        await recorder.snapshot_due()
        clock.advance(600.0)
    ends = {r["pool"]: r["cause"] for r in sink.events(mr.END_EVENT)}
    assert ends == {"Quiet": "dead", "Curve": "dead", "Gone": "missing"}
    assert {p for _, p in recorder.followed} == {"Busy", "Deep"}
    assert recorder.stats.ended == {"dead": 2, "missing": 1}

    clock.advance(7 * 86_400.0)
    await recorder.snapshot_due()
    assert recorder.followed == {}
    assert recorder.stats.ended["max_age"] == 2
    assert sink.events(mr.END_EVENT)[-1]["followed_seconds"] > 604_800


async def test_a_full_follow_list_refuses_new_pools_and_errors_are_counted() -> None:
    def limited(_url: str, _params: Mapping[str, Any]) -> Any:
        raise HttpStatusError(429, "slow down")

    recorder, _, _, _ = _recorder(
        {"/latest/dex/pairs/": limited}, chains=("solana",), max_followed=1
    )
    now = START
    assert recorder._follow("solana", {"pool": "A"}, source="new", rank=None, now=now)
    assert not recorder._follow(
        "solana", {"pool": "A"}, source="new", rank=None, now=now
    )
    assert not recorder._follow(
        "solana", {"pool": "B"}, source="new", rank=None, now=now
    )
    assert not recorder._follow(
        "solana", {"pool": ""}, source="new", rank=None, now=now
    )
    assert recorder.stats.full == 1
    assert await recorder.snapshot_due() == 0
    assert (recorder.stats.errors, recorder.stats.rate_limited) == (1, 1)

    def broken(_url: str, _params: Mapping[str, Any]) -> Any:
        raise ValueError("not JSON")

    recorder.http.routes["/latest/dex/pairs/"] = broken  # type: ignore[attr-defined]
    assert await recorder.snapshot_due() == 0
    assert (recorder.stats.errors, recorder.stats.rate_limited) == (2, 1)
    # An empty or odd answer counts as missing, not as an error.
    recorder.http.routes["/latest/dex/pairs/"] = lambda _u, _p: []  # type: ignore[attr-defined]
    recorder.followed[("solana", "A")].last_snapshot_at = 0.0
    await recorder.snapshot_due()
    assert recorder.followed[("solana", "A")].missing == 1


# --- state and loop ----------------------------------------------------------


async def test_state_round_trips_and_skips_old_or_foreign_pools(tmp_path: Path) -> None:
    state = tmp_path / "market" / "state.json"
    recorder, _, _, clock = _recorder({}, chains=("solana", "base"), state_path=state)
    recorder._follow(
        "solana", {"pool": "Keep"}, source="trending_1h", rank=3, now=START
    )
    recorder._follow("base", {"pool": "Old"}, source="new", rank=None, now=START - 9e5)
    recorder._remember("solana", "Seen1")
    assert recorder.save_state(force=True)
    assert not recorder.save_state()  # not due yet
    clock.advance(61.0)
    assert recorder.save_state()

    again, _, _, _ = _recorder({}, clock=clock, chains=("solana",), state_path=state)
    assert again.load_state() == 1
    kept = again.followed[("solana", "Keep")]
    assert (kept.source, kept.rank) == ("trending_1h", 3)
    assert "Seen1" in again.seen["solana"]

    raw = json.loads(state.read_text())
    raw["followed"].append({"chain": "solana", "unknown": 1})
    state.write_text(json.dumps(raw))
    assert again.load_state() == 1  # the bad row is skipped
    state.write_text(json.dumps({**raw, "version": 99}))
    assert again.load_state() == 0
    state.write_text("{")
    assert again.load_state() == 0
    assert _recorder({}, state_path=tmp_path / "none.json")[0].load_state() == 0
    assert _recorder({})[0].save_state(force=True) is False
    assert _recorder({})[0].load_state() == 0


async def test_run_discovers_follows_writes_stats_and_saves_state(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    recorder, _, sink, clock = _recorder(
        {
            "/new_pools": _pages([gecko_pool("PoolA")]),
            "/trending_pools": lambda _u, _p: {"data": []},
            "/pools": lambda _u, _p: {"data": []},
            "/latest/dex/pairs/": _pairs(dex_pair("PoolA")),
        },
        chains=("solana",),
        state_path=state,
        stats_interval_seconds=30.0,
    )
    stats = await recorder.run(duration_seconds=90.0, tick_seconds=5.0)
    assert stats.new_pools == 1 and stats.snapshots >= 1
    assert sink.events(mr.STATS_EVENT)[-1]["following"] == 1
    assert sink.events(mr.STATS_EVENT)[-1]["by_chain"] == {"solana": 1}
    assert json.loads(state.read_text())["followed"][0]["pool"] == "PoolA"
    assert clock.now >= START + 90.0


async def test_run_stops_on_the_event_and_tolerates_an_unwritable_state(
    tmp_path: Path,
) -> None:
    import asyncio

    blocker = tmp_path / "file"
    blocker.write_text("x")
    recorder, _, sink, _ = _recorder(
        {"/new_pools": _pages([])},
        chains=("solana",),
        lists=False,
        state_path=blocker / "state.json",  # parent is a file: cannot be written
        state_interval_seconds=0.0,
    )
    stop = asyncio.Event()
    stop.set()
    await recorder.run(stop=stop)
    assert recorder.stats.errors >= 1
    assert sink.events(mr.STATS_EVENT)

    looping, _, _, _ = _recorder(
        {"/new_pools": _pages([])},
        chains=("solana",),
        lists=False,
        state_path=blocker / "state.json",
        state_interval_seconds=0.0,
    )
    await looping.run(duration_seconds=3.0, tick_seconds=1.0)
    assert looping.stats.errors >= 2  # each pass's save failed and was counted


async def test_a_pool_dexscreener_has_not_indexed_waits_and_is_kept_for_a_while() -> (
    None
):
    # A brand-new pool can be missing from DexScreener for a minute or two: it
    # is retried on its interval (not every tick) and kept for 10 minutes.
    recorder, http, sink, clock = _recorder(
        {"/latest/dex/pairs/": _pairs()}, chains=("solana",)
    )
    recorder._follow("solana", {"pool": "Young"}, source="new", rank=None, now=START)
    for _ in range(3):
        await recorder.snapshot_due()
        clock.advance(1.0)
    assert len(http.calls) == 1  # one try, then wait 30 s
    for _ in range(8):
        clock.advance(30.0)
        await recorder.snapshot_due()
    assert recorder.followed[("solana", "Young")].missing >= mr.MISSING_LIMIT
    assert sink.events(mr.END_EVENT) == []  # still inside the grace period
    http.routes["/latest/dex/pairs/"] = _pairs(dex_pair("Young"))
    clock.advance(30.0)
    assert await recorder.snapshot_due() == 1
    assert recorder.followed[("solana", "Young")].missing == 0


async def test_seen_lists_are_bounded_and_unknown_state_chains_ignored(
    tmp_path: Path,
) -> None:
    recorder, _, _, _ = _recorder({}, chains=("solana",))
    for i in range(mr.SEEN_PER_CHAIN + 3):
        recorder._remember("solana", f"P{i}")
    assert len(recorder.seen["solana"]) == mr.SEEN_PER_CHAIN
    assert "P0" not in recorder.seen["solana"]
    assert await recorder.snapshot_batch("solana", []) == 0

    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "version": mr.STATE_VERSION,
                "followed": [],
                "seen": {"solana": ["A", 7], "tron": ["B"]},
            }
        )
    )
    loaded, _, _, _ = _recorder({}, chains=("solana",), state_path=state)
    assert loaded.load_state() == 0
    assert list(loaded.seen["solana"]) == ["A"] and "tron" not in loaded.seen


async def test_pools_the_pair_call_misses_are_found_by_their_token() -> None:
    # Live BSC data (2026-10-26): four.meme curves are listed as
    # "<token>:4meme", and some PancakeSwap Infinity / Uniswap v4 pools are not
    # indexed at all while the coin's main pair is.
    curve = "0x27c605ce84b893c5fd673d3202ecaec289c5ffff"
    v4_pool, v4_token = "0xb2842060d68177ff20", "0xtokenv4"
    lonely_pool, lonely_token = "0xlonely", "0xtokenlonely"

    def token_pair(base: str, address: str, liquidity: float) -> dict[str, Any]:
        pair = dex_pair(address, liquidity=liquidity)
        pair["baseToken"] = {"address": base.upper()}
        return pair

    def tokens(url: str, _params: Mapping[str, Any]) -> Any:
        assert url.split("/tokens/v1/")[1].startswith("bsc/")
        return [
            token_pair(
                curve, "0x27c605ce84b893C5fd673d3202EcAeC289c5fFff:4meme", 900.0
            ),
            token_pair(v4_token, "0xSmallPair", 1_000.0),
            token_pair(v4_token, "0xMainPair", 80_000.0),
            "noise",
        ]

    recorder, http, sink, _ = _recorder(
        {"/latest/dex/pairs/": _pairs(), "/tokens/v1/": tokens}, chains=("bsc",)
    )
    for pool, token in (
        (curve, curve),
        (v4_pool, v4_token),
        (lonely_pool, lonely_token),
    ):
        recorder._follow(
            "bsc",
            {"pool": pool, "base_token": token},
            source="new",
            rank=None,
            now=START,
        )
    recorder._follow("bsc", {"pool": "0xnotoken"}, source="new", rank=None, now=START)
    assert await recorder.snapshot_due() == 2
    snaps = {r["pool"]: r for r in sink.events(mr.SNAPSHOT_EVENT)}
    assert snaps[curve]["matched"] == "pool" and "pair_address" not in snaps[curve]
    assert snaps[v4_pool]["matched"] == "token"
    assert snaps[v4_pool]["pair_address"] == "0xMainPair"  # the most liquid one
    assert recorder.followed[("bsc", lonely_pool)].missing == 1
    assert recorder.followed[("bsc", "0xnotoken")].missing == 1
    assert (recorder.stats.token_lookups, recorder.stats.token_matched) == (1, 2)
    # Only pools with a known token are looked up, each token once.
    token_url = [u for u, _ in http.calls if "/tokens/v1/" in u][0]
    assert token_url.rsplit("/", 1)[-1].split(",") == [curve, v4_token, lonely_token]

    # A failed or odd token lookup leaves the pools missing; nothing is raised.
    def down(_url: str, _params: Mapping[str, Any]) -> Any:
        raise HttpStatusError(404, "no")

    def odd(_url: str, _params: Mapping[str, Any]) -> Any:
        return {"pairs": []}

    for answer in (down, odd):
        again, _, _, _ = _recorder(
            {"/latest/dex/pairs/": _pairs(), "/tokens/v1/": answer},
            chains=("bsc",),
        )
        again._follow(
            "bsc",
            {"pool": curve, "base_token": curve},
            source="new",
            rank=None,
            now=START,
        )
        assert await again.snapshot_due() == 0
        assert again.followed[("bsc", curve)].missing == 1
