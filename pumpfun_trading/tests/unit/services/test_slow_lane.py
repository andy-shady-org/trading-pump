"""Unit tests for ``services/slow_lane.py`` (FEAT-65 phase 0, record-only)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pumpfun_trading.services import slow_lane
from pumpfun_trading.services.slow_lane import (
    AiohttpJson,
    GeckoTerminalClient,
    HttpStatusError,
    JupiterClient,
    QuoteRecorder,
    RequestPacer,
    SlowLaneToken,
)
from pumpfun_trading.tests.support.fakes import FakeClock

JUP = SlowLaneToken("JUP", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN")
BONK = SlowLaneToken("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")
SOL = SlowLaneToken("SOL", slow_lane.WSOL_MINT)
RPC = "https://rpc.example/?api-key=secret123"

Responder = Callable[[str, Mapping[str, Any], Any], Any]


class FakeHttp:
    """Answers by URL fragment; a responder may return a value or raise."""

    def __init__(self, routes: dict[str, Responder]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, Any], dict[str, str], Any]] = []
        self.closed = False

    def _answer(
        self, url: str, params: Mapping[str, Any], headers: Mapping[str, str], body: Any
    ) -> Any:
        self.calls.append((url, dict(params), dict(headers), body))
        for fragment, responder in self.routes.items():
            if fragment in url:
                return responder(url, params, body)
        raise AssertionError(f"unexpected request {url}")

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return self._answer(url, params or {}, headers or {}, None)

    async def post_json(
        self, url: str, payload: Any, *, headers: Mapping[str, str] | None = None
    ) -> Any:
        return self._answer(url, {}, headers or {}, payload)

    async def close(self) -> None:
        self.closed = True


class Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record_snapshot(self, record: dict[str, Any]) -> None:
        self.rows.append(dict(record))

    def events(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.rows if r["event"] == name]


def _quote(out_amount: int, *legs: tuple[str, str]) -> dict[str, Any]:
    return {
        "inAmount": "20000000",
        "outAmount": str(out_amount),
        "otherAmountThreshold": str(out_amount - 1),
        "priceImpactPct": "0.0012",
        "slippageBps": 50,
        "contextSlot": 99,
        "routePlan": [
            {"swapInfo": {"label": label, "ammKey": key}} for label, key in legs
        ],
    }


def _prices(_url: str, _params: Mapping[str, Any], _body: Any) -> Any:
    return {
        JUP.mint: {"usdPrice": 0.32, "liquidity": 5e6, "decimals": 6, "blockId": 7},
        BONK.mint: {"usdPrice": 3e-6, "liquidity": 6e6, "decimals": 5},
    }


def _fees(_url: str, _params: Mapping[str, Any], body: Any) -> Any:
    accounts = body["params"]
    if accounts and accounts[0] == ["PoolBad"]:
        return {"error": {"code": -32602, "message": "bad"}}
    fees = [0, 0, 5000, 300] if accounts else [0, 0]
    return {
        "result": [{"slot": 10 + i, "prioritizationFee": f} for i, f in enumerate(fees)]
    }


# -- token list, sizes, env --------------------------------------------------


def test_default_token_list_matches_the_editable_config_copy() -> None:
    raw = json.loads(
        (Path(__file__).parents[4] / "configs" / "slow_lane_tokens.json").read_text()
    )
    from_file = slow_lane.load_token_list(
        Path(__file__).parents[4] / "configs" / "slow_lane_tokens.json"
    )
    assert from_file == slow_lane.load_token_list(None) == slow_lane.default_tokens()
    assert len(raw["tokens"]) == len(slow_lane.DEFAULT_TOKENS)


def test_load_token_list_accepts_a_bare_list_and_defaults_the_symbol(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps([{"mint": " Mint123456 "}]))
    assert slow_lane.load_token_list(path) == [SlowLaneToken("Mint12", "Mint123456")]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ({"tokens": []}, "non-empty"),
        ({"other": 1}, "non-empty"),
        ({"tokens": [{"symbol": "X"}]}, "needs a 'mint'"),
        ({"tokens": ["M"]}, "needs a 'mint'"),
        ({"tokens": [{"mint": "M"}, {"mint": "M"}]}, "duplicate"),
    ],
)
def test_load_token_list_rejects_bad_files(
    tmp_path: Path, content: Any, message: str
) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match=message):
        slow_lane.load_token_list(path)


def test_parse_sizes() -> None:
    assert slow_lane.parse_sizes(None) == slow_lane.DEFAULT_SIZES_SOL
    assert slow_lane.parse_sizes("0.5, 0.02,,0.5") == (0.02, 0.5)
    assert slow_lane.parse_sizes([0.1]) == (0.1,)
    for bad in ("", "0.1,-1", "0"):
        with pytest.raises(ValueError):
            slow_lane.parse_sizes(bad)


def test_rpc_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HELIUS_RPC_URL", raising=False)
    assert slow_lane.rpc_url_from_env() is None
    monkeypatch.setenv("PUMPFUN_RPC_URLS", " , https://b.example ,https://c")
    assert slow_lane.rpc_url_from_env() == "https://b.example"
    monkeypatch.setenv("HELIUS_RPC_URL", "https://helius.example")
    assert slow_lane.rpc_url_from_env() == "https://helius.example"
    monkeypatch.setenv("PUMPFUN_RPC_URL", "   ")
    assert slow_lane.rpc_url_from_env() is None


# -- clients -----------------------------------------------------------------


async def test_jupiter_client_is_keyless_by_default_and_keyed_by_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http = FakeHttp({"/swap/v1/quote": lambda *_: _quote(5, ("Orca", "P1"))})
    lite = JupiterClient.from_env(http)
    assert not lite.keyed and lite.base_url == slow_lane.JUPITER_LITE_URL
    await lite.quote(input_mint="A", output_mint="B", amount=12, slippage_bps=30)
    url, params, headers, _ = http.calls[-1]
    assert url == f"{slow_lane.JUPITER_LITE_URL}/swap/v1/quote"
    assert params["amount"] == "12" and params["slippageBps"] == "30"
    assert headers == {}

    monkeypatch.setenv(slow_lane.JUPITER_API_KEY_ENV, "k-123")
    keyed = JupiterClient.from_env(http)
    assert keyed.keyed and keyed.base_url == slow_lane.JUPITER_KEYED_URL
    await keyed.quote(input_mint="A", output_mint="B", amount=1)
    url, _params, headers, _ = http.calls[-1]
    # The key travels as a header, never in the URL (BUG-118).
    assert headers == {"x-api-key": "k-123"} and "k-123" not in url


async def test_jupiter_client_rejects_bad_payloads() -> None:
    http = FakeHttp(
        {"/swap/v1/quote": lambda *_: {"error": "no route"}, "/price/v3": lambda *_: []}
    )
    client = JupiterClient(http, base_url="https://jup.example/")
    with pytest.raises(ValueError, match="unexpected quote"):
        await client.quote(input_mint="A", output_mint="B", amount=1)
    assert await client.prices(["A", "B"]) == {}
    assert http.calls[-1][1] == {"ids": "A,B"}


async def test_geckoterminal_client_pool_and_bars() -> None:
    pools: dict[str, Any] = {
        "M1": {
            "data": [
                {
                    "attributes": {
                        "address": "P1",
                        "name": "M1 / SOL",
                        "reserve_in_usd": "12.5",
                    }
                }
            ]
        },
        "M2": {"data": []},
        "M3": {"data": [{"attributes": {}}]},
        "M4": [],
    }
    http = FakeHttp(
        {
            "/tokens/": lambda url, *_: pools[url.split("/tokens/")[1].split("/")[0]],
            "/ohlcv/": lambda *_: {
                "data": {
                    "attributes": {"ohlcv_list": [[1, 2, 3, 0.5, 2.5, 9], [1, 2], "x"]}
                }
            },
        }
    )
    gecko = GeckoTerminalClient(http)
    assert await gecko.top_pool("M1") == {
        "address": "P1",
        "name": "M1 / SOL",
        "reserve_usd": 12.5,
    }
    for mint in ("M2", "M3", "M4"):
        assert await gecko.top_pool(mint) is None
    bars = await gecko.ohlcv(
        "P1", timeframe="hour", before_timestamp=77, token_mint="M1"
    )
    assert bars == [[1, 2, 3, 0.5, 2.5, 9]]
    assert http.calls[-1][1] == {
        "limit": 1000,
        "currency": "usd",
        "before_timestamp": 77,
        "token": "M1",
    }
    await gecko.ohlcv("P1", timeframe="day")
    assert http.calls[-1][1] == {"limit": 1000, "currency": "usd"}


async def test_aiohttp_json_round_trip_and_rate_limit_headers() -> None:
    async def ok(request: web.Request) -> web.Response:
        return web.json_response(
            {"q": request.query.get("a"), "h": request.headers.get("x-k")}
        )

    async def empty(_request: web.Request) -> web.Response:
        return web.Response(text="")

    async def limited(_request: web.Request) -> web.Response:
        return web.Response(status=429, text="slow down", headers={"Retry-After": "3"})

    async def echo(request: web.Request) -> web.Response:
        return web.json_response({"got": await request.json()})

    app = web.Application()
    app.router.add_get("/ok", ok)
    app.router.add_get("/empty", empty)
    app.router.add_get("/limited", limited)
    app.router.add_post("/echo", echo)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    http = AiohttpJson(timeout_seconds=5)
    try:
        base = str(server.make_url(""))
        assert await http.get_json(
            f"{base}/ok", params={"a": 1}, headers={"x-k": "v"}
        ) == {"q": "1", "h": "v"}
        assert await http.get_json(f"{base}/empty") is None
        with pytest.raises(HttpStatusError) as caught:
            await http.get_json(f"{base}/limited?api-key=secret123")
        assert caught.value.status == 429 and caught.value.retry_after == 3.0
        assert "secret123" not in str(caught.value)
        assert await http.post_json(f"{base}/echo", {"x": 1}) == {"got": {"x": 1}}
    finally:
        await http.close()
        await http.close()
        await server.close()


def test_retry_after_headers() -> None:
    assert slow_lane._retry_after({"Retry-After": "2"}, now=0) == 2.0
    assert (
        slow_lane._retry_after(
            {"Retry-After": "soon", "x-ratelimit-reset": "105"}, now=100
        )
        == 5.0
    )
    assert slow_lane._retry_after({"x-ratelimit-reset": "90"}, now=100) == 0.0
    assert slow_lane._retry_after({"x-ratelimit-reset": "later"}, now=100) is None
    assert slow_lane._retry_after({}, now=100) is None


# -- pacing and retries ------------------------------------------------------


async def test_request_pacer_keeps_the_gap() -> None:
    clock = FakeClock(start=100.0)
    pacer = RequestPacer(2.0, sleep=clock.async_sleep, clock=clock.monotonic)
    await pacer.wait()
    clock.advance(0.5)
    await pacer.wait()
    clock.advance(5.0)
    await pacer.wait()
    assert clock.sleeps == [1.5]


async def test_paced_retries_rate_limits_and_server_errors_with_bounded_waits() -> None:
    clock = FakeClock()
    pacer = RequestPacer(0.0, sleep=clock.async_sleep, clock=clock.monotonic)
    answers: list[Any] = [
        HttpStatusError(429, "limited", retry_after=0.0),
        HttpStatusError(500, "oops"),
        HttpStatusError(429, "limited", retry_after=99.0),
        "done",
    ]

    async def call() -> Any:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert await slow_lane._paced(pacer, call, clock.async_sleep) == "done"
    # Retry-After 0 falls back to 10 s × attempt; a long reset is capped at 30 s.
    assert clock.sleeps == [10.0, 20.0, 30.0]

    async def always_limited() -> Any:
        raise HttpStatusError(429, "limited")

    with pytest.raises(HttpStatusError):
        await slow_lane._paced(pacer, always_limited, clock.async_sleep)

    async def not_found() -> Any:
        raise HttpStatusError(404, "missing")

    clock.sleeps.clear()
    with pytest.raises(HttpStatusError):
        await slow_lane._paced(pacer, not_found, clock.async_sleep)
    assert clock.sleeps == []


# -- rows ----------------------------------------------------------------------


def test_quote_rows_give_price_route_and_round_trip_cost() -> None:
    buy = slow_lane.quote_row(
        _quote(6_000_000, ("Orca", "P1"), ("Meteora", "P2")),
        token=JUP,
        side="buy",
        size_sol=0.02,
        decimals=6,
        now=5.0,
        latency_ms=12.34,
    )
    assert buy["event"] == "quote" and buy["venue"] == "jupiter"
    assert buy["route"] == ["Orca", "Meteora"] and buy["pools"] == ["P1", "P2"]
    assert buy["hops"] == 2 and buy["latency_ms"] == 12.3
    assert buy["price_sol"] == pytest.approx(0.02 / 6.0)
    assert buy["price_impact_pct"] == pytest.approx(0.0012)

    quote = _quote(19_800_000)
    quote["routePlan"] = [{"swapInfo": {}}, "junk", {"other": 1}]
    sell = slow_lane.quote_row(
        quote,
        token=JUP,
        side="sell",
        size_sol=0.02,
        decimals=None,
        now=6.0,
        latency_ms=1,
    )
    assert sell["route"] == ["?"] and sell["pools"] == []
    assert sell["round_trip_ratio"] == pytest.approx(0.99)
    assert sell["round_trip_cost_bps"] == pytest.approx(100.0)
    assert "decimals" not in sell and "price_sol" not in sell

    zero = slow_lane.quote_row(
        {"outAmount": "0"},
        token=JUP,
        side="sell",
        size_sol=0.0,
        decimals=6,
        now=1,
        latency_ms=0,
    )
    assert zero["round_trip_ratio"] == 0.0 and zero["price_impact_pct"] is None


def test_price_rows_skip_tokens_without_a_price() -> None:
    rows = slow_lane.price_rows(
        _prices("", {}, None) | {BONK.mint: "junk"}, [JUP, BONK, SOL], 9.0
    )
    assert [r["symbol"] for r in rows] == ["JUP"]
    assert rows[0]["liquidity_usd"] == 5e6 and rows[0]["decimals"] == 6


def test_fee_row_summarises_slots() -> None:
    assert slow_lane.fee_row(None, 1.0) is None
    assert slow_lane.fee_row([], 1.0) is None
    assert slow_lane.fee_row(["junk"], 1.0) is None
    quiet = slow_lane.fee_row([{"slot": 1, "prioritizationFee": 0}], 1.0)
    assert quiet is not None and quiet["nonzero_share"] == 0.0
    assert "nonzero_p50" not in quiet and quiet["account"] is None
    busy = slow_lane.fee_row(
        [
            {"slot": s, "prioritizationFee": f}
            for s, f in ((5, 0), (6, 100), (7, 900), (8, 0))
        ],
        2.0,
        account="Pool1",
        symbols=["JUP", "BONK", "JUP"],
    )
    assert busy is not None
    assert busy["symbols"] == ["BONK", "JUP"] and busy["slots"] == 4
    assert (busy["min_slot"], busy["max_slot"], busy["max"]) == (5, 8, 900)
    assert busy["nonzero_share"] == 0.5
    assert (busy["nonzero_p50"], busy["nonzero_p90"]) == (100, 900)


# -- quote recorder ------------------------------------------------------------


def _recorder(
    http: FakeHttp, sink: Sink, clock: FakeClock, **kwargs: Any
) -> QuoteRecorder:
    return QuoteRecorder(
        JupiterClient(http),
        sink,
        tokens=[SOL, JUP, BONK],
        sizes_sol=(0.02, 0.5),
        sleep=clock.async_sleep,
        clock=clock.time,
        monotonic=clock.monotonic,
        **kwargs,
    )


async def test_quote_cycle_records_prices_quotes_errors_and_pool_fees() -> None:
    def quote(_url: str, params: Mapping[str, Any], _body: Any) -> Any:
        if params["inputMint"] == slow_lane.WSOL_MINT:
            if params["outputMint"] == BONK.mint and params["amount"] == "500000000":
                raise HttpStatusError(
                    400, "no route: https://jup.example/q?api-key=secret123"
                )
            if params["outputMint"] == BONK.mint:
                return _quote(0, ("Raydium", "PoolB"))
            return _quote(6_000_000, ("Orca", "PoolA"), ("Bad", "PoolBad"))
        return _quote(19_900_000, ("Orca", "PoolA"))

    http = FakeHttp(
        {"/price/v3": _prices, "/swap/v1/quote": quote, "rpc.example": _fees}
    )
    sink = Sink()
    clock = FakeClock()
    recorder = _recorder(http, sink, clock, rpc_http=http, rpc_url=RPC)
    assert recorder.requests_per_cycle == 9
    await recorder.run_cycle()

    assert [r["symbol"] for r in sink.events("price")] == ["JUP", "BONK"]
    quotes = sink.events("quote")
    # SOL is the quote currency; BONK's empty buy gets no sell quote.
    assert [(q["symbol"], q["side"], q["size_sol"]) for q in quotes] == [
        ("JUP", "buy", 0.02),
        ("JUP", "sell", 0.02),
        ("JUP", "buy", 0.5),
        ("JUP", "sell", 0.5),
        ("BONK", "buy", 0.02),
    ]
    assert quotes[0]["decimals"] == 6 and quotes[0]["price_sol"] == pytest.approx(
        0.02 / 6
    )
    errors = sink.events("quote_error")
    assert len(errors) == 1 and errors[0]["status"] == 400
    assert "secret123" not in errors[0]["error"]
    fees = sink.events("fee_sample")
    assert [f["account"] for f in fees] == [None, "PoolB", "PoolA"]
    assert fees[2]["symbols"] == ["JUP"] and fees[2]["nonzero_p90"] == 5000
    rpc_bodies = [c[3] for c in http.calls if "rpc.example" in c[0]]
    assert rpc_bodies[0]["params"] == [] and rpc_bodies[1]["params"] == [["PoolB"]]
    stats = recorder.stats
    assert (stats.cycles, stats.quotes, stats.quote_errors, stats.price_rows) == (
        1,
        5,
        1,
        2,
    )
    # PoolBad answered an RPC error: counted, no row.
    assert (stats.fee_samples, stats.fee_errors) == (3, 1)

    # Within the fee interval no new fee sample is taken.
    await recorder.sample_fees()
    assert recorder.stats.fee_samples == 3


async def test_quote_recorder_counts_rate_limits_and_failed_samples() -> None:
    def limited(*_: Any) -> Any:
        raise HttpStatusError(429, "limited", retry_after=1.0)

    def broken(*_: Any) -> Any:
        raise RuntimeError("down")

    http = FakeHttp(
        {"/price/v3": broken, "/swap/v1/quote": limited, "rpc.example": broken}
    )
    sink = Sink()
    clock = FakeClock()
    recorder = _recorder(http, sink, clock, rpc_http=http, rpc_url=RPC, fee_max_pools=0)
    await recorder.run_cycle()
    stats = recorder.stats
    assert stats.price_errors == 1 and stats.fee_errors == 1
    assert stats.quote_errors == 4 and stats.rate_limited == 4
    assert {r["status"] for r in sink.events("quote_error")} == {429}


async def test_fee_samples_need_an_rpc_and_track_a_bounded_pool_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(slow_lane, "MAX_TRACKED_POOLS", 2)
    counter = iter(range(100))

    def quote(*_: Any) -> Any:
        return _quote(6_000_000, ("Orca", f"Pool{next(counter)}"))

    http = FakeHttp({"/price/v3": _prices, "/swap/v1/quote": quote})
    sink = Sink()
    clock = FakeClock()
    recorder = _recorder(http, sink, clock, fee_max_pools=5)
    await recorder.run_cycle()
    await recorder._fee_sample(None, [])
    assert sink.events("fee_sample") == []
    assert [a for a, _ in recorder.fee_accounts()] == [None, "Pool7", "Pool6"]


async def test_quote_recorder_run_stops_on_cycles_duration_or_event() -> None:
    import asyncio

    http = FakeHttp(
        {"/price/v3": _prices, "/swap/v1/quote": lambda *_: _quote(6_000_000)}
    )
    clock = FakeClock()
    recorder = _recorder(http, Sink(), clock, request_gap_seconds=0.0)
    stats = await recorder.run(interval_seconds=60, max_cycles=2)
    assert stats.cycles == 2
    # Waits for the next cycle in steps of at most 1 s.
    assert max(clock.sleeps) <= 1.0 and sum(clock.sleeps) == pytest.approx(60.0)

    timed = _recorder(http, Sink(), FakeClock(), request_gap_seconds=0.0)
    assert (await timed.run(interval_seconds=60, duration_seconds=90)).cycles == 2

    stop = asyncio.Event()
    stop.set()
    stopped = _recorder(http, Sink(), FakeClock())
    assert (await stopped.run(stop=stop)).cycles == 0


# -- bar backfill --------------------------------------------------------------


async def test_backfill_pages_back_de_duplicates_and_stops_at_the_history_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(slow_lane, "BARS_PER_PAGE", 3)
    pages = {
        None: [
            [300, 1, 2, 0.5, 1.5, 10],
            [200, 1, 2, 0.5, 1.5, 10],
            [100, 1, 2, 0.5, 1.5, 10],
        ],
        100: [
            [100, 1, 2, 0.5, 1.5, 10],
            [50, 1, 2, 0.5, 1.5, 10],
            [40, 1, 2, 0.5, 1.5, 10],
        ],
        40: [[40, 1, 2, 0.5, 1.5, 10]],
    }

    def ohlcv(url: str, params: Mapping[str, Any], _body: Any) -> Any:
        if "PoolHist" in url and "before_timestamp" in params:
            raise HttpStatusError(401, "history limit")
        if "PoolErr" in url:
            raise HttpStatusError(401, "not allowed")
        bars = pages[params.get("before_timestamp")]
        return {"data": {"attributes": {"ohlcv_list": bars}}}

    def pools(url: str, *_: Any) -> Any:
        mint = url.split("/tokens/")[1].split("/")[0]
        if mint == "Broken":
            raise RuntimeError("lookup down")
        address = {"Hist": "PoolHist", "Err": "PoolErr"}.get(mint, "Pool1")
        return (
            {"data": [{"attributes": {"address": address, "name": mint}}]}
            if mint != "None"
            else {"data": []}
        )

    http = FakeHttp({"/tokens/": pools, "/ohlcv/": ohlcv})
    sink = Sink()
    clock = FakeClock()
    tokens = [SlowLaneToken(s, s) for s in ("Good", "Hist", "Err", "None", "Broken")]
    stats = await slow_lane.backfill_bars(
        GeckoTerminalClient(http),
        sink,
        tokens=tokens,
        timeframes=["day"],
        max_pages=5,
        sleep=clock.async_sleep,
        monotonic=clock.monotonic,
    )
    good = [r["timestamp"] for r in sink.rows if r["symbol"] == "Good"]
    assert good == [300, 200, 100, 50, 40]
    assert sink.rows[0] == {
        "timestamp": 300.0,
        "event": "bar",
        "venue": "geckoterminal",
        "symbol": "Good",
        "mint": "Good",
        "pool": "Pool1",
        "pool_name": "Good",
        "timeframe": "day",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume_usd": 10.0,
    }
    assert [r["timestamp"] for r in sink.rows if r["symbol"] == "Hist"] == [
        300,
        200,
        100,
    ]
    assert stats.history_limited == 1
    assert stats.pools_missing == 1 and stats.tokens == 5
    # A 401 on the first page is an error, as is a failed pool lookup.
    assert stats.errors == 2
    assert [f.split(":")[0] for f in stats.failures] == ["Err day", "Broken pool"]
    assert stats.bars == 8
    # Requests are paced at the GeckoTerminal default gap.
    assert set(clock.sleeps) == {slow_lane.DEFAULT_BAR_REQUEST_GAP_SECONDS}


async def test_backfill_stops_on_a_page_error_and_rejects_unknown_timeframes() -> None:
    def ohlcv(*_: Any) -> Any:
        raise RuntimeError("timeout")

    http = FakeHttp(
        {
            "/tokens/": lambda *_: {"data": [{"attributes": {"address": "P"}}]},
            "/ohlcv/": ohlcv,
        }
    )
    clock = FakeClock()
    stats = await slow_lane.backfill_bars(
        GeckoTerminalClient(http),
        Sink(),
        tokens=[JUP],
        sleep=clock.async_sleep,
        monotonic=clock.monotonic,
    )
    assert stats.errors == 2 and stats.bars == 0
    with pytest.raises(ValueError, match="timeframe"):
        await slow_lane.backfill_bars(
            GeckoTerminalClient(http), Sink(), tokens=[JUP], timeframes=["week"]
        )
