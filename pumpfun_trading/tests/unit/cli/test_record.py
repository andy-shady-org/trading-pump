"""Unit tests for ``cli/record.py`` snapshot mapping and live harvester sources."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import re
import runpy
import sys
import types
import warnings
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from rich.console import Console

from pumpfun_trading.cli import record as record_cli
from pumpfun_trading.cli import record as record_module
from pumpfun_trading.cli.bot import build_parser as build_bot_parser
from pumpfun_trading.cli.record import build_record_parser, run_record_cli
from pumpfun_trading.streams.geyser import BondingCurveStateUpdate, TradeEventUpdate
from pumpfun_trading.tests.support.fakes import FakeClock

MINT = "RecMint1111111111111111111111111111111111"
_real_sleep = asyncio.sleep


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> Console:
    """The CLI console, recording instead of writing to the terminal."""
    console = Console(record=True, width=200, file=io.StringIO())
    monkeypatch.setattr(record_cli, "console", console)
    return console


@pytest.fixture
def stop_events(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Event]:
    """Swap the module's ``asyncio`` for a fast proxy that exposes the stop event.

    Only ``record_cli``'s own namespace is patched: ``sleep`` yields without waiting
    and every ``asyncio.Event`` the harvester creates is captured for the test.
    """
    created: list[asyncio.Event] = []

    class _CapturingEvent(asyncio.Event):
        def __init__(self) -> None:
            super().__init__()
            created.append(self)

    async def _fast_sleep(delay: float, result: Any = None) -> Any:
        await _real_sleep(0)
        return result

    proxy = types.SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio)}
    )
    proxy.Event = _CapturingEvent
    proxy.sleep = _fast_sleep
    monkeypatch.setattr(record_cli, "asyncio", proxy)
    return created


def _args(tmp_path: Path, *argv: str) -> Any:
    out = str(tmp_path / "harvest.jsonl")
    return record_cli.build_record_parser().parse_args(
        ["-o", out, "--batch-size", "1", "--flush-interval", "0.01", *argv]
    )


def _records(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "harvest.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _curve(mint: str = MINT) -> BondingCurveStateUpdate:
    return BondingCurveStateUpdate(
        mint=mint,
        bonding_curve_pubkey="Curve1",
        slot=100,
        virtual_token_reserves=1000,
        virtual_sol_reserves=100,
        real_token_reserves=500,
        real_sol_reserves=2_000_000_000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=30.0,
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (["not", "a", "dict"], None),
        ({"name": "NoMint"}, None),
        (
            {"mint": "M1", "marketCapSol": 31.5},
            {
                "timestamp": 5.0,
                "mint": "M1",
                "name": "M1",
                "source": "websocket",
                "market_cap_sol": 31.5,
            },
        ),
        (
            {"mint": "M2", "txType": "create", "timestamp": 9.0, "name": "Two"},
            {
                "timestamp": 9.0,
                "mint": "M2",
                "name": "Two",
                "source": "websocket",
                "txType": "create",
            },
        ),
        (
            {"mint": "M3", "txType": "SELL", "solAmount": 0.2},
            {
                "timestamp": 5.0,
                "mint": "M3",
                "name": "M3",
                "source": "websocket",
                "sol_amount": 0.2,
                "txType": "sell",
                "is_buy": False,
            },
        ),
    ],
)
def test_ws_message_to_snapshot_payload_maps_without_inventing_signals(
    payload: Any, expected: dict[str, Any] | None
) -> None:
    assert record_cli.ws_message_to_snapshot(payload, 5.0) == expected


def _fake_geyser(
    monkeypatch: pytest.MonkeyPatch,
    listen: Callable[[], AsyncIterator[Any]],
) -> MagicMock:
    client = MagicMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.listen = listen
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(record_cli, "YellowstoneGeyserClient", factory)
    return factory


def test_harvester_geyser_stop_requested_mid_stream_stops_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    async def listen() -> AsyncIterator[Any]:
        yield _curve()
        stop_events[0].set()
        yield _curve("SecondMint111111111111111111111111111111")

    factory = _fake_geyser(monkeypatch, listen)

    record_cli.run_record_cli(_args(tmp_path, "--geyser-endpoint", "grpc.test:443"))

    factory.assert_called_once_with(endpoint="grpc.test:443")
    factory.return_value.stop.assert_awaited_once()
    records = _records(tmp_path)
    assert [r["mint"] for r in records] == [MINT]
    assert records[0]["volume"] == pytest.approx(2.0)
    out = output.export_text()
    assert "Yellowstone Geyser" in out
    assert "Unique Tokens Observed" in out


def test_harvester_geyser_stream_exhausted_ignores_unknown_events_until_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    async def listen() -> AsyncIterator[Any]:
        yield object()
        yield _curve()

    _fake_geyser(monkeypatch, listen)
    monkeypatch.setenv("PUMPFUN_GEYSER_ENDPOINT", "grpc.env:443")

    record_cli.run_record_cli(_args(tmp_path, "--duration", "0.02"))

    assert stop_events[0].is_set()
    assert [r["mint"] for r in _records(tmp_path)] == [MINT]
    assert "Snapshots Recorded" in output.export_text()


class _FakeApiClient:
    def __init__(self, get_latest_coins: Callable[..., Any]) -> None:
        self.get_latest_coins = get_latest_coins

    async def __aenter__(self) -> _FakeApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def test_harvester_polling_error_is_logged_and_stop_breaks_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    async def failing(limit: int) -> Any:
        calls.append(limit)
        stop_events[0].set()
        raise RuntimeError("boom")

    monkeypatch.setattr(record_cli, "PumpFunApiClient", lambda: _FakeApiClient(failing))
    monkeypatch.delenv("PUMPFUN_GEYSER_ENDPOINT", raising=False)

    with caplog.at_level(logging.DEBUG, logger=record_cli.logger.name):
        record_cli.run_record_cli(_args(tmp_path))

    assert calls == [50]
    assert "Harvester polling error: boom" in caplog.text
    assert "WebSocket / REST" in output.export_text()
    assert not (tmp_path / "harvest.jsonl").exists() or _records(tmp_path) == []


def test_harvester_polling_records_quotes_without_buy_signal_until_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    coins = [
        "garbage",
        {"name": "NoMint"},
        {"mintAddress": "P1", "marketCapSol": 30.0, "name": "Poll"},
        {"mint": "P2"},
    ]
    monkeypatch.setattr(
        record_cli,
        "PumpFunApiClient",
        lambda: _FakeApiClient(AsyncMock(return_value=coins)),
    )
    monkeypatch.delenv("PUMPFUN_GEYSER_ENDPOINT", raising=False)

    record_cli.run_record_cli(_args(tmp_path, "--limit", "1"))

    records = _records(tmp_path)
    assert [r["mint"] for r in records] == ["P1"]
    assert records[0]["source"] == "poll"
    assert records[0]["price"] == pytest.approx(30.0 / 1_000_000_000.0)
    assert "is_buy" not in records[0] and "signal" not in records[0]
    assert re.search(r"Snapshots Recorded\s+│ 1 ", output.export_text())


class _Msg:
    def __init__(self, msg_type: aiohttp.WSMsgType, data: Any) -> None:
        self.type = msg_type
        self.data = data


class _FakeWs:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.sent: list[Any] = []

    async def __aenter__(self) -> _FakeWs:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def send_json(self, payload: Any) -> None:
        self.sent.append(payload)

    async def __aiter__(self) -> AsyncIterator[_Msg]:
        for item in self.items:
            if callable(item):
                item()
                continue
            yield item


class _FakeSession:
    def __init__(self, ws: _FakeWs, urls: list[str]) -> None:
        self.ws = ws
        self.urls = urls

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def ws_connect(self, url: str) -> _FakeWs:
        self.urls.append(url)
        return self.ws


def _patch_ws(
    monkeypatch: pytest.MonkeyPatch, items: list[Any]
) -> tuple[_FakeWs, list[str]]:
    ws = _FakeWs(items)
    urls: list[str] = []
    monkeypatch.setattr(aiohttp, "ClientSession", lambda **_: _FakeSession(ws, urls))
    monkeypatch.delenv("PUMPFUN_GEYSER_ENDPOINT", raising=False)
    return ws, urls


def _text(payload: Any) -> _Msg:
    return _Msg(aiohttp.WSMsgType.TEXT, json.dumps(payload))


def test_harvester_websocket_skips_noise_and_stops_at_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    ws, urls = _patch_ws(
        monkeypatch,
        [
            _Msg(aiohttp.WSMsgType.BINARY, b"\x00"),
            _Msg(aiohttp.WSMsgType.TEXT, "not json {"),
            _text({"message": "subscribed"}),
            _text({"mint": "WsMint1", "txType": "create", "name": "One"}),
            _text({"mint": "WsMint2", "txType": "buy", "solAmount": 0.5}),
            _text({"mint": "WsMint3", "txType": "buy"}),
        ],
    )

    record_cli.run_record_cli(
        _args(tmp_path, "--ws-url", "wss://feed.test/data", "--limit", "2")
    )

    assert urls == ["wss://feed.test/data"]
    assert ws.sent == [{"method": "subscribeNewToken"}]
    records = _records(tmp_path)
    assert [r["mint"] for r in records] == ["WsMint1", "WsMint2"]
    assert "is_buy" not in records[0]
    assert records[1]["is_buy"] is True
    assert all(r["source"] == "websocket" for r in records)
    assert "Market Harvesting Summary" in output.export_text()


def test_harvester_websocket_stop_requested_breaks_feed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    _patch_ws(
        monkeypatch,
        [
            _text({"mint": "WsMint1"}),
            lambda: stop_events[0].set(),
            _text({"mint": "WsMint2"}),
        ],
    )

    record_cli.run_record_cli(_args(tmp_path, "--ws-url", "wss://feed.test/data"))

    assert [r["mint"] for r in _records(tmp_path)] == ["WsMint1"]
    output.export_text()


def test_harvester_websocket_feed_closed_runs_until_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: Console,
    stop_events: list[asyncio.Event],
) -> None:
    _patch_ws(monkeypatch, [_text({"mint": "WsMint1"}), _text({"mint": "WsMint2"})])

    record_cli.run_record_cli(
        _args(tmp_path, "--ws-url", "wss://feed.test/data", "--duration", "0.02")
    )

    assert stop_events[0].is_set()
    assert [r["mint"] for r in _records(tmp_path)] == ["WsMint1", "WsMint2"]
    assert "Unique Tokens Observed │ 2" in output.export_text()


def test_record_module_run_as_script_generates_synthetic_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["pumpfun-recorder", "--synthetic", "flash_rug", "--synthetic-steps", "12"]
        + ["-o", str(out)],
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("pumpfun_trading.cli.record", run_name="__main__")

    lines = [line for line in out.read_text().splitlines() if line]
    assert len(lines) >= 12
    assert all("mint" in json.loads(line) for line in lines)


def test_record_cli_parser_and_execution(tmp_path: Path):
    """Test CLI argument parsing and dispatching for recorder tools."""
    parser = build_record_parser()
    args = parser.parse_args(
        [
            "-o",
            str(tmp_path / "cli_synth.jsonl"),
            "--synthetic",
            "flash_rug",
            "--synthetic-steps",
            "40",
        ]
    )
    assert args.output == str(tmp_path / "cli_synth.jsonl")
    assert args.synthetic == "flash_rug"
    assert args.synthetic_steps == 40

    run_record_cli(args)
    assert (tmp_path / "cli_synth.jsonl").exists()

    # Test bot parser --record-replay option
    bot_parser = build_bot_parser()
    bot_args = bot_parser.parse_args(["--record-replay", "custom_replay.jsonl"])
    assert bot_args.record_replay == "custom_replay.jsonl"


def test_record_cli_from_mint(tmp_path: Path):
    """Test CLI execution for REST export mode."""
    parser = build_record_parser()
    out = tmp_path / "cli_rest.jsonl"
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--from-mint",
            "TokenMint123",
            "--limit",
            "10",
        ]
    )

    with patch(
        "pumpfun_trading.cli.record.RestHistoryExporter.export_token_trades_to_file",
        new_callable=AsyncMock,
    ) as mock_exp:
        mock_exp.return_value = 5
        run_record_cli(args)
        assert mock_exp.called


def test_record_cli_harvester_geyser(tmp_path: Path):
    """Test CLI live stream harvester with Yellowstone Geyser."""
    parser = build_record_parser()
    out = tmp_path / "geyser_harvest.jsonl"
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--geyser-endpoint",
            "http://127.0.0.1:10000",
            "--limit",
            "3",
            "--flush-interval",
            "0.1",
        ]
    )

    async def fake_events():
        yield BondingCurveStateUpdate(
            mint="GeyserMint1111111111111111111111111111111",
            bonding_curve_pubkey="Curve1",
            slot=100,
            virtual_token_reserves=1000,
            virtual_sol_reserves=100,
            real_token_reserves=500,
            real_sol_reserves=50,
            token_total_supply=1000,
            complete=False,
            price_sol=0.001,
            market_cap_sol=30.0,
        )
        yield TradeEventUpdate(
            mint="GeyserMint1111111111111111111111111111111",
            sol_amount_lamports=100_000_000,
            token_amount=1000,
            is_buy=True,
            user="User1",
            timestamp=1700000000,
            virtual_sol_reserves=100,
            virtual_token_reserves=1000,
            real_sol_reserves=50,
            real_token_reserves=500,
        )
        from pumpfun_trading.streams.geyser import CompleteEventUpdate

        yield CompleteEventUpdate(
            mint="GeyserMint1111111111111111111111111111111",
            user="User1",
            bonding_curve="Curve1",
            timestamp=1700000001,
        )

    with patch("pumpfun_trading.cli.record.YellowstoneGeyserClient") as mock_geyser:
        instance = mock_geyser.return_value
        instance.start = AsyncMock()
        instance.stop = AsyncMock()
        instance.listen = fake_events

        run_record_cli(args)

    assert out.exists()


def test_record_cli_harvester_polling(tmp_path: Path):
    """Test CLI live stream harvester with REST polling."""
    parser = build_record_parser()
    out = tmp_path / "polling_harvest.jsonl"
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--limit",
            "2",
            "--duration",
            "1.0",
            "--flush-interval",
            "0.1",
        ]
    )

    with patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls:
        client = AsyncMock()
        client.get_latest_coins.return_value = [
            {
                "mint": "PollMint1",
                "name": "PollCoin1",
                "market_cap": 28.0,
                "volume": 1.0,
            },
            {
                "mint": "PollMint2",
                "name": "PollCoin2",
                "market_cap": 30.0,
                "volume": 2.0,
            },
        ]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        run_record_cli(args)

    assert out.exists()


def test_record_main_entrypoint(tmp_path: Path):
    """Test main() CLI entrypoint invocation."""
    from pumpfun_trading.cli.record import main

    with patch(
        "sys.argv",
        [
            "pumpfun-recorder",
            "--synthetic",
            "gradual_grind",
            "-o",
            str(tmp_path / "main_synth.jsonl"),
            "--synthetic-steps",
            "10",
        ],
    ):
        main()
    assert (tmp_path / "main_synth.jsonl").exists()


def test_record_cli_exceptions_and_polling_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Test record CLI error branches, duration triggers, and signal handlers."""
    # Poll waits run on a fake clock instead of real seconds; the limit, not
    # the (fake-time) duration, ends the run.
    clock = FakeClock()
    clock.install(monkeypatch, record_module)
    clock.install_async_sleep(monkeypatch, record_module)
    out = tmp_path / "poll_branch.jsonl"
    parser = build_record_parser(parser=argparse.ArgumentParser())

    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--limit",
            "1",
            "--duration",
            "60.0",
            "--flush-interval",
            "0.05",
        ]
    )

    with patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls:
        client = AsyncMock()
        client.get_latest_coins.side_effect = [
            "not a list",
            [
                {"non_dict": 1},
                {"mint": ""},
                {"mint": "PollMint1", "market_cap": 28.0, "volume": 1.0},
            ],
        ]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        run_record_cli(args)

    assert out.exists()
    assert "PollMint1" in out.read_text()


def test_record_cli_keyboard_interrupt(tmp_path: Path):
    """Test CLI top-level KeyboardInterrupt handling."""
    parser = build_record_parser()
    args = parser.parse_args(["-o", str(tmp_path / "ki.jsonl")])

    with patch("pumpfun_trading.cli.record.asyncio.run", side_effect=KeyboardInterrupt):
        run_record_cli(args)

    # Subparsers build parser check
    root_parser = argparse.ArgumentParser()
    subparsers = root_parser.add_subparsers()
    rec_p = build_record_parser(subparsers=subparsers)
    assert rec_p is not None


def test_record_cli_interrupted_while_streaming(tmp_path: Path):
    """Test CLI interruption handling during stream loop."""
    parser = build_record_parser()
    out = tmp_path / "stream_ki.jsonl"
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--flush-interval",
            "0.05",
        ]
    )

    with patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls:
        client = AsyncMock()
        client.get_latest_coins.return_value = [{"mint": "M1", "market_cap": 28.0}]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        # Simulate sleep raising KeyboardInterrupt in main loop
        with patch(
            "pumpfun_trading.cli.record.asyncio.sleep",
            side_effect=[None, KeyboardInterrupt],
        ):
            run_record_cli(args)


def test_record_cli_signal_handler_and_geyser_none(tmp_path: Path):
    """Test signal handler exception and geyser endpoint None check."""
    out = tmp_path / "sig_handler.jsonl"
    parser = build_record_parser()
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--limit",
            "1",
            "--duration",
            "1.0",
            "--flush-interval",
            "0.01",
        ]
    )

    with (
        patch("asyncio.get_running_loop") as mock_get_loop,
        patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls,
    ):
        loop = MagicMock()
        loop.add_signal_handler.side_effect = RuntimeError("Not main thread")
        mock_get_loop.return_value = loop

        client = AsyncMock()
        client.get_latest_coins.return_value = [{"mint": "SigMint", "market_cap": 25.0}]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        run_record_cli(args)

    assert out.exists()


def test_record_cli_sleep_loop_duration_and_cancel(tmp_path: Path):
    """Test sleep loop duration exit and cancellation inside harvester."""
    out = tmp_path / "duration_exit.jsonl"
    parser = build_record_parser()
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--duration",
            "0.01",
            "--flush-interval",
            "0.01",
        ]
    )

    with patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls:
        client = AsyncMock()
        # Return list with non-dict to exercise line 282
        client.get_latest_coins.return_value = [
            "not_a_dict",
            {"mint": "Coin1", "market_cap": 25.0},
        ]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        run_record_cli(args)

    assert out.exists()


def test_record_cli_geyser_none_endpoint_inside_task(tmp_path: Path):
    """Test _stream_geyser directly when geyser_endpoint is None."""
    out = tmp_path / "geyser_none.jsonl"
    parser = build_record_parser()
    args = parser.parse_args(
        [
            "-o",
            str(out),
            "--duration",
            "0.05",
            "--flush-interval",
            "0.01",
        ]
    )

    # Pass geyser_endpoint as empty string or None to ensure clean return
    args.geyser_endpoint = None
    with patch("pumpfun_trading.cli.record.PumpFunApiClient") as mock_client_cls:
        client = AsyncMock()
        client.get_latest_coins.return_value = [{"mint": "C1", "market_cap": 20.0}]
        client.__aenter__.return_value = client
        mock_client_cls.return_value = client

        run_record_cli(args)

    assert out.exists()
