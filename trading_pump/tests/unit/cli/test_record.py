"""Unit tests for ``cli/record.py``: the market, Jupiter-quote and bar recorders.

pumpfun-recorder's stream harvester, synthetic scenarios and REST trade
export were retired with the pumpbot replay engine; their tests went with
them (git history up to v0.3.0rc8).
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from trading_pump.cli import record as record_cli
from trading_pump.cli.record import build_record_parser, run_record_cli


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    """The CLI console, recording instead of writing to the terminal."""
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(record_cli, "console", console)
    return console


def test_record_cli_without_a_recorder_exits_2(output: Console) -> None:
    with pytest.raises(SystemExit) as exc:
        run_record_cli(build_record_parser().parse_args([]))

    assert exc.value.code == 2
    assert "Choose a recorder" in output.export_text()


def test_record_main_parses_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(record_cli, "run_record_cli", seen.append)
    monkeypatch.setattr("sys.argv", ["trading-pump-recorder", "--market"])

    record_cli.main()

    assert seen[0].market is True


def _klines(url: str, params: Any) -> Any:
    pair = params["symbol"]
    if pair == "GONEUSDT":
        raise record_cli.slow_lane.HttpStatusError(400, "Invalid symbol.")
    if pair == "BLOCKUSDT":
        raise record_cli.slow_lane.HttpStatusError(451, "restricted")
    return [[86_400_000, "1", "2", "0.5", "1.5", "9", 172_799_999, "13", 3]]


def _gecko_pools(url: str, params: Any) -> Any:
    if "Gone" in url:
        return {"data": []}
    return {"data": [{"attributes": {"address": "PoolX", "name": "JUP / SOL"}}]}


# What the stand-in answers, by URL fragment, checked in order.
_SLOW_LANE_ANSWERS: tuple[tuple[str, Callable[[str, Any], Any]], ...] = (
    ("/api/v3/klines", _klines),
    (
        "/price/v3",
        lambda url, params: {
            "JUPmint": {"usdPrice": 0.3, "liquidity": 1e6, "decimals": 6}
        },
    ),
    (
        "/swap/v1/quote",
        lambda url, params: {"inAmount": "1", "outAmount": "5000000", "routePlan": []},
    ),
    ("/tokens/", _gecko_pools),
    (
        "/ohlcv/day",
        lambda url, params: {
            "data": {"attributes": {"ohlcv_list": [[86400, 1, 2, 0.5, 1.5, 9]]}}
        },
    ),
)


class _SlowLaneHttp:
    """Offline stand-in for ``slow_lane.AiohttpJson`` (FEAT-65 recorder)."""

    instances: list[_SlowLaneHttp] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        self.closed = False
        self.urls: list[str] = []
        self.params: list[Any] = []
        _SlowLaneHttp.instances.append(self)

    async def get_json(
        self, url: str, *, params: Any = None, headers: Any = None
    ) -> Any:
        self.urls.append(url)
        self.params.append(params)
        for fragment, answer in _SLOW_LANE_ANSWERS:
            if fragment in url:
                return answer(url, params)
        raise RuntimeError("hour bars down")

    async def post_json(self, url: str, payload: Any, *, headers: Any = None) -> Any:
        self.urls.append(url)
        return {"result": [{"slot": 1, "prioritizationFee": 10}]}

    async def close(self) -> None:
        self.closed = True


def _token_file(tmp_path: Path) -> str:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "tokens": [
                    {"symbol": "JUP", "mint": "JUPmint"},
                    {"symbol": "GONE", "mint": "Gone"},
                ]
            }
        )
    )
    return str(path)


def test_record_cli_jupiter_quotes_writes_its_own_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    _SlowLaneHttp.instances.clear()
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://rpc.example/?api-key=secret123")
    monkeypatch.chdir(tmp_path)
    args = build_record_parser().parse_args(
        [
            "--jupiter-quotes",
            "--tokens",
            _token_file(tmp_path),
            "--quote-sizes",
            "0.02",
            "--request-gap",
            "0",
            "--duration",
            "0.01",
            "--flush-interval",
            "0.01",
        ]
    )
    run_record_cli(args)

    path = tmp_path / record_cli.DEFAULT_QUOTES_OUTPUT
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert {r["event"] for r in rows} == {"price", "quote", "fee_sample"}
    assert {r["venue"] for r in rows} == {"jupiter", "solana"}
    assert not (tmp_path / "market_replay.jsonl").exists()
    assert _SlowLaneHttp.instances[0].closed
    text = output.export_text()
    assert "keyless" in text and "Fee samples: on" in text
    assert "secret123" not in text and "Quote Recorder Summary" in text


def test_record_cli_jupiter_quotes_without_fee_samples_stops_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.setenv("PUMPFUN_RPC_URL", "https://rpc.example")

    async def interrupted(*_: Any, **__: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(record_cli.slow_lane.QuoteRecorder, "run", interrupted)
    args = build_record_parser().parse_args(
        ["--jupiter-quotes", "--no-fee-samples", "-o", str(tmp_path / "q.jsonl")]
    )
    run_record_cli(args)
    assert "Fee samples: off" in output.export_text()


def test_record_cli_backfill_bars_reports_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.chdir(tmp_path)
    args = build_record_parser().parse_args(
        ["--backfill-bars", "--tokens", _token_file(tmp_path), "--request-gap", "0"]
    )
    run_record_cli(args)

    rows = [
        json.loads(line)
        for line in (tmp_path / record_cli.DEFAULT_BARS_OUTPUT).read_text().splitlines()
    ]
    assert [(r["symbol"], r["timeframe"], r["pool"]) for r in rows] == [
        ("JUP", "day", "PoolX")
    ]
    text = output.export_text()
    assert "Bar Backfill Summary" in text
    assert "JUP hour: hour bars down" in text
    assert "Pools missing" in text and "Page limit reached" in text
    assert "Host: https://api.geckoterminal.com" in text


def test_record_cli_backfill_bars_from_binance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    _SlowLaneHttp.instances.clear()
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.chdir(tmp_path)
    args = build_record_parser().parse_args(
        [
            "--backfill-bars",
            "--bar-source",
            "binance",
            "--tokens",
            _token_file(tmp_path),
            "--bar-timeframes",
            "day",
            "--bar-since",
            "2024-01-01",
            "--request-gap",
            "0",
        ]
    )
    run_record_cli(args)

    rows = [
        json.loads(line)
        for line in (tmp_path / record_cli.DEFAULT_BINANCE_BARS_OUTPUT)
        .read_text()
        .splitlines()
    ]
    assert [(r["symbol"], r["venue"], r["pair"], r["timestamp"]) for r in rows] == [
        ("JUP", "binance", "JUPUSDT", 86_400.0)
    ]
    assert not (tmp_path / record_cli.DEFAULT_BARS_OUTPUT).exists()
    http = _SlowLaneHttp.instances[0]
    assert http.urls[0] == f"{record_cli.slow_lane.BINANCE_URL}/api/v3/klines"
    assert http.params[0]["startTime"] == 1_704_067_200_000 and http.closed
    text = output.export_text()
    assert "Binance Bar Backfill" in text and "Since: 2024-01-01" in text
    assert "Pairs missing" in text and "GONE: no Binance pair GONEUSDT" in text
    assert "Max pages: 100" in text and "Pools missing" not in text


def test_record_cli_backfill_writes_one_unrotated_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    """A full Binance download is ~100 MB: it must not rotate at 50 MB."""
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    policies: list[Any] = []
    real = record_cli.ReplayRecorder

    def recorder(**kwargs: Any) -> Any:
        policies.append(kwargs.get("policy"))
        return real(**kwargs)

    monkeypatch.setattr(record_cli, "ReplayRecorder", recorder)
    out = tmp_path / "bars.jsonl"
    args = build_record_parser().parse_args(
        [
            "--backfill-bars",
            "--bar-source",
            "binance",
            "--tokens",
            _token_file(tmp_path),
            "--request-gap",
            "0",
            "-o",
            str(out),
        ]
    )
    run_record_cli(args)
    assert policies == [record_cli.BACKFILL_RETENTION]
    assert policies[0].max_bytes == 0  # RotatedFileSink never rotates
    # trading-core 0.2.2 locks each sink's file with a ``.lock`` beside it (TC-7).
    written = sorted(p.name for p in tmp_path.iterdir() if p.suffix != ".lock")
    assert written == ["bars.jsonl", "tokens.json"]


def test_record_cli_binance_page_limit_and_blocked_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    _SlowLaneHttp.instances.clear()
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.setattr(record_cli.slow_lane, "BINANCE_BARS_PER_PAGE", 1)
    # No --request-gap: the Binance default applies (zeroed to keep this fast).
    monkeypatch.setattr(
        record_cli.slow_lane, "DEFAULT_BINANCE_REQUEST_GAP_SECONDS", 0.0
    )
    tokens = tmp_path / "tokens.json"
    tokens.write_text(
        json.dumps(
            {
                "tokens": [
                    {"symbol": "JUP", "mint": "JUPmint"},
                    {"symbol": "BLOCK", "mint": "Blocked"},
                ]
            }
        )
    )
    out = tmp_path / "b.jsonl"
    args = build_record_parser().parse_args(
        [
            "--backfill-bars",
            "--bar-source",
            "binance",
            "--bar-base-url",
            "https://api.binance.example",
            "--tokens",
            str(tokens),
            "--bar-timeframes",
            "day",
            "--bar-max-pages",
            "1",
            "-o",
            str(out),
        ]
    )
    run_record_cli(args)
    assert _SlowLaneHttp.instances[0].urls[-1].startswith("https://api.binance.example")
    text = output.export_text()
    assert "Since: listing" in text and "raise it to fetch the rest" in text
    assert "Binance refused this host (HTTP 451" in text


def test_record_cli_bar_since_needs_binance_and_a_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    args = build_record_parser().parse_args(
        ["--backfill-bars", "--bar-since", "2024-01-01", "-o", str(tmp_path / "x")]
    )
    with pytest.raises(SystemExit) as exc:
        run_record_cli(args)
    assert exc.value.code == 2
    assert "--bar-since needs --bar-source binance" in output.export_text()
    with pytest.raises(SystemExit):
        build_record_parser().parse_args(["--bar-since", "01/01/2024"])
    assert record_cli.utc_date("2024-01-01") == 1_704_067_200.0


def test_record_cli_market_writes_its_own_file_and_resumes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    # FEAT-74: its own directory, its own rotation, a state file by default.
    _SlowLaneHttp.instances.clear()
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    monkeypatch.chdir(tmp_path)
    seen: dict[str, Any] = {}

    async def fake_run(self: Any, *, stop: Any, duration_seconds: Any) -> Any:
        seen.update(
            chains=self.config.chains,
            sample=self.config.sample,
            lists=self.config.lists,
            max_followed=self.config.max_followed,
            state=self.state_path,
            duration=duration_seconds,
            policy=self.sink.policy,
        )
        self.sink.record_snapshot({"event": "market_stats", "venue": "market"})
        self.stats.new_pools = 4
        self.stats.ended = {"dead": 1}
        return self.stats

    monkeypatch.setattr(record_cli.market_recorder.MarketRecorder, "run", fake_run)
    args = build_record_parser().parse_args(
        [
            "--market",
            "--market-chains",
            "solana,base",
            "--market-sample",
            "solana:pump-fun=0.05",
            "--market-max-followed",
            "500",
            "--market-no-lists",
            "--duration",
            "5",
            "--flush-interval",
            "0.01",
        ]
    )
    run_record_cli(args)

    assert seen["chains"] == ("solana", "base")
    assert seen["sample"] == {"solana:pump-fun": 0.05}
    assert (seen["lists"], seen["max_followed"], seen["duration"]) == (False, 500, 5.0)
    assert seen["state"] == Path(record_cli.DEFAULT_MARKET_STATE)
    assert seen["policy"].max_age_days == 0 and seen["policy"].max_files == 300
    path = tmp_path / record_cli.DEFAULT_MARKET_OUTPUT
    assert [json.loads(line)["venue"] for line in path.read_text().splitlines()] == [
        "market"
    ]
    assert not (tmp_path / "market_replay.jsonl").exists()
    assert _SlowLaneHttp.instances[0].closed
    text = output.export_text()
    assert "Market Recorder (FEAT-74, record-only)" in text
    assert "Chains: solana, base" in text and "Lists: off" in text
    assert "Market Recorder Summary" in text and "dead 1" in text


def test_record_cli_market_refuses_an_unknown_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)
    args = build_record_parser().parse_args(
        ["--market", "--market-chains", "tron", "-o", str(tmp_path / "m.jsonl")]
    )
    with pytest.raises(SystemExit) as exc:
        run_record_cli(args)
    assert exc.value.code == 2
    assert "unknown chain" in output.export_text()


def test_record_cli_market_without_state_stops_on_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: Console
) -> None:
    monkeypatch.setattr(record_cli.slow_lane, "AiohttpJson", _SlowLaneHttp)

    async def interrupted(*_: Any, **__: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(record_cli.market_recorder.MarketRecorder, "run", interrupted)
    args = build_record_parser().parse_args(
        ["--market", "--market-state", "", "-o", str(tmp_path / "m.jsonl")]
    )
    run_record_cli(args)
    assert "(no state file)" in output.export_text()


def test_stop_on_signals_skips_loops_without_signal_support() -> None:
    import asyncio

    class Loop:
        def __init__(self, error: type[Exception] | None) -> None:
            self.error = error
            self.handlers: list[Any] = []

        def add_signal_handler(self, sig: Any, callback: Any) -> None:
            if self.error is not None:
                raise self.error
            self.handlers.append(sig)

    stop = asyncio.Event()
    working = Loop(None)
    record_cli.stop_on_signals(stop, working)
    assert len(working.handlers) == 2
    for error in (NotImplementedError, RuntimeError):
        record_cli.stop_on_signals(stop, Loop(error))


@pytest.mark.parametrize(
    ("flag", "stop"),
    [
        ("--market", KeyboardInterrupt()),
        ("--market", SystemExit(0)),
        ("--jupiter-quotes", KeyboardInterrupt()),
        ("--jupiter-quotes", SystemExit(0)),
    ],
)
def test_record_cli_stops_quietly_when_the_loop_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str, stop: BaseException
) -> None:
    """Ctrl-C and a clean exit end a recorder quietly, whatever Python's
    asyncio does with an interrupt raised inside the coroutine (3.11 and 3.14
    differ), so the loop itself is replaced here."""

    def interrupted(coroutine: Any) -> None:
        coroutine.close()
        raise stop

    monkeypatch.setattr(record_cli.asyncio, "run", interrupted)
    args = build_record_parser().parse_args([flag, "-o", str(tmp_path / "x.jsonl")])
    run_record_cli(args)


def test_record_cli_market_passes_a_failing_exit_code_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(coroutine: Any) -> None:
        coroutine.close()
        raise SystemExit(3)

    monkeypatch.setattr(record_cli.asyncio, "run", failed)
    args = build_record_parser().parse_args(["--market", "-o", str(tmp_path / "m")])
    with pytest.raises(SystemExit) as exc:
        run_record_cli(args)
    assert exc.value.code == 3
