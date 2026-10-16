from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.recorder import ReplayRecorder
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.cli.bot import build_parser as build_bot_parser
from pumpfun_trading.cli import record as record_module
from pumpfun_trading.cli.record import build_record_parser, run_record_cli
from pumpfun_trading.engines.generators import (
    RestHistoryExporter,
    SyntheticReplayGenerator,
)
from pumpfun_trading.engines.replay import PaperTradingEngine, run_replay
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.tests.support.fakes import FakeClock
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    TradeEventUpdate,
)


async def test_replay_recorder_lifecycle(tmp_path: Path):
    """Test ReplayRecorder buffering, background batching, and graceful closing."""
    log_file = tmp_path / "test_nested" / "market.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file,
        batch_size=10,
        flush_interval_seconds=0.2,
    )

    assert not recorder.is_running
    assert recorder.records_written == 0
    assert recorder.queue_size == 0

    await recorder.start()
    assert recorder.is_running
    assert log_file.parent.exists()

    # Enqueue 15 records (should trigger 1 batch immediately + 5 buffered)
    for i in range(15):
        recorder.record_snapshot(
            {
                "timestamp": 1700000000.0 + i,
                "mint": f"Mint{i}",
                "price": 0.000000028 + (i * 0.000000001),
                "market_cap_sol": 28.0 + (i * 0.1),
            }
        )

    # Allow worker to flush
    await asyncio.sleep(0.3)
    assert recorder.records_written >= 10

    # Enqueue 5 more and close gracefully
    for i in range(15, 20):
        recorder.record_snapshot(
            {
                "timestamp": 1700000000.0 + i,
                "mint": f"Mint{i}",
                "price": 0.000000028,
                "market_cap_sol": 28.0,
            }
        )

    await recorder.close()
    assert not recorder.is_running
    assert recorder.records_written == 20

    # Verify file contents
    assert log_file.exists()
    lines = [
        line.strip()
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 20
    first_record = json.loads(lines[0])
    assert first_record["mint"] == "Mint0"
    assert first_record["price"] == pytest.approx(0.000000028)


async def test_trading_bot_replay_recording_hook(tmp_path: Path):
    """Test TradingBot integration with ReplayRecorder during market events."""
    replay_file = tmp_path / "bot_replay.jsonl"

    config = TradingBotConfig(
        buy_amount_sol=0.01,
        replay_log_path=str(replay_file),
    )

    with (
        patch("pumpfun_trading.bot.run.build_execution_client"),
        patch("pumpfun_trading.bot.run.YellowstoneGeyserClient"),
    ):
        bot = TradingBot(
            private_key_b58="1" * 64,
            rpc_url="http://127.0.0.1:8899",
            config=config,
            dry_run=True,
            replay_log_path=replay_file,
        )

        assert bot.replay_recorder is not None
        await bot.replay_recorder.start()

        # Simulate bonding curve update
        curve_update = BondingCurveStateUpdate(
            mint="RecordMint1111111111111111111111111111111",
            bonding_curve_pubkey="CurvePubkey11111111111111111111111111111",
            slot=1000,
            virtual_token_reserves=1_000_000_000_000,
            virtual_sol_reserves=30_000_000_000,
            real_token_reserves=800_000_000_000,
            real_sol_reserves=5_000_000_000,
            token_total_supply=1_000_000_000_000,
            complete=False,
            price_sol=0.000000030,
            market_cap_sol=30.0,
            timestamp=1700000100.0,
        )
        await bot._handle_bonding_curve_state_update(curve_update)

        # Simulate Geyser trade event
        trade_event = TradeEventUpdate(
            mint="RecordMint1111111111111111111111111111111",
            sol_amount_lamports=500_000_000,
            token_amount=15_000_000,
            is_buy=True,
            user="BuyerWallet111111111111111111111111111111",
            timestamp=1700000105,
            virtual_sol_reserves=30_500_000_000,
            virtual_token_reserves=985_000_000_000,
            real_sol_reserves=5_500_000_000,
            real_token_reserves=785_000_000_000,
        )
        await bot._handle_trade_event_update(trade_event)

        # Simulate new token discovery
        await bot._handle_new_token_event(
            {
                "mint": "NewCoinMint11111111111111111111111111111",
                "name": "NewCoin",
                "market_cap": 27.96,
            }
        )

        # Simulate WebSocket trade update
        await bot._handle_trade_update(
            {
                "mint": "NewCoinMint11111111111111111111111111111",
                "is_buy": True,
                "sol_amount": 0.25,
                "token_amount": 8_000_000,
                "market_cap": 28.2,
                "timestamp": 1700000120.0,
            }
        )

        await bot.close()

    assert replay_file.exists()
    lines = [
        json.loads(line)
        for line in replay_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) >= 4
    mints = {record["mint"] for record in lines}
    assert "RecordMint1111111111111111111111111111111" in mints
    assert "NewCoinMint11111111111111111111111111111" in mints


def test_synthetic_replay_generator(tmp_path: Path):
    """Test SyntheticReplayGenerator across all preset price trajectories."""
    scenarios = [
        "pump_and_dump",
        "stagnant_curve",
        "multi_tier_take_profit",
        "gradual_grind",
        "flash_rug",
    ]

    for sc in scenarios:
        records = SyntheticReplayGenerator.generate(scenario=sc, steps=30, seed=123)
        assert len(records) == 30
        assert records[0]["signal"] == "buy"
        assert all("price" in r and "market_cap_sol" in r for r in records)

    # Test file export and simulation execution
    out_file = tmp_path / "synthetic_run.jsonl"
    count = SyntheticReplayGenerator.generate_to_file(
        path=out_file, scenario="multi_tier_take_profit", steps=50
    )
    assert count == 50
    assert out_file.exists()

    # Verify PaperTradingEngine backtest executes without errors
    engine = PaperTradingEngine(initial_cash=10.0, take_profit=2.0, stop_loss=0.85)
    summary = run_replay(out_file, engine=engine)
    assert summary["initial_cash"] == 10.0
    assert summary["total_trades"] >= 1
    assert "profit_factor" in summary


def test_synthetic_generator_invalid_scenario():
    """Ensure invalid scenario name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown scenario 'invalid_curve'"):
        SyntheticReplayGenerator.generate(scenario="invalid_curve")


async def test_rest_history_exporter(tmp_path: Path):
    """Test RestHistoryExporter fetching and serializing historical trades."""
    mock_client = AsyncMock(spec=PumpFunApiClient)
    mock_client.get_trade_history.return_value = [
        {
            "timestamp": 1700000050.0,
            "price": 0.000000030,
            "is_buy": False,
            "sol_amount": 0.2,
            "token_amount": 6_000_000,
            "user": "Seller1",
        },
        {
            "timestamp": 1700000010.0,
            "price": 0.000000028,
            "is_buy": True,
            "sol_amount": 0.5,
            "token_amount": 17_000_000,
            "user": "Buyer1",
        },
    ]
    mock_client.get_coin.return_value = {
        "mint": "HistoricalMint111111111111111111111111",
        "name": "HistoricalCoin",
        "symbol": "HIST",
    }

    out_file = tmp_path / "rest_export.jsonl"
    count = await RestHistoryExporter.export_token_trades_to_file(
        client=mock_client,
        mint="HistoricalMint111111111111111111111111",
        output_path=out_file,
    )

    assert count == 2
    assert out_file.exists()
    lines = [
        json.loads(line)
        for line in out_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 2
    # Verify chronological sorting (1700000010 before 1700000050)
    assert lines[0]["timestamp"] == 1700000010.0
    assert lines[0]["name"] == "HistoricalCoin"
    assert lines[0]["is_buy"] is True
    assert lines[1]["timestamp"] == 1700000050.0
    assert lines[1]["is_buy"] is False


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


async def test_replay_recorder_edge_cases(tmp_path: Path):
    """Test ReplayRecorder edge cases like write errors and closed state."""
    log_file = tmp_path / "edge_market.jsonl"
    recorder = ReplayRecorder(output_path=log_file, batch_size=5)

    # Calling record_snapshot when closed
    recorder._closed = True
    recorder.record_snapshot({"mint": "ClosedMint"})
    assert recorder.queue_size == 0

    # Test empty batch write
    await recorder._write_batch([])
    assert recorder.records_written == 0

    # Test write batch exception logging
    recorder._closed = False
    with patch.object(recorder, "_sync_append", side_effect=OSError("Disk full")):
        await recorder._write_batch([{"test": 1}])

    # Test record snapshot exception handling
    with patch.object(
        recorder._queue, "put_nowait", side_effect=Exception("Queue broken")
    ):
        recorder.record_snapshot({"test": 1})

    # Test flush with items
    recorder._queue.put_nowait({"mint": "FlushMint"})
    await recorder.flush()
    assert recorder.records_written == 1

    # Test close when task raises exception
    await recorder.start()
    if recorder._worker_task is not None:
        recorder._worker_task.cancel()
    await recorder.close()


async def test_rest_history_exporter_branches(tmp_path: Path):
    """Test RestHistoryExporter branch conditions (non-dict payloads, empty lists)."""
    mock_client = AsyncMock(spec=PumpFunApiClient)
    mock_client.get_trade_history.return_value = "not a list"
    mock_client.get_coin.return_value = "not a dict"

    records = await RestHistoryExporter.export_token_trades(mock_client, "Mint1")
    assert records == []

    # Non-dict item inside list
    mock_client.get_trade_history.return_value = [
        "not a dict item",
        {
            "timestamp": 123,
            "price": 0.1,
            "is_buy": True,
            "sol_amount": 0.1,
            "token_amount": 100,
        },
    ]
    records = await RestHistoryExporter.export_token_trades(mock_client, "Mint1")
    assert len(records) == 1


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


async def test_replay_recorder_drain_and_worker_branches(tmp_path: Path):
    """Test ReplayRecorder queue draining when multiple items are available."""
    log_file = tmp_path / "drain_market.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=5, flush_interval_seconds=0.1
    )

    # Put 4 items into queue before start so worker drains them in one batch
    recorder.record_snapshot({"item": 1})
    recorder.record_snapshot({"item": 2})
    recorder.record_snapshot({"item": 3})
    recorder.record_snapshot({"item": 4})
    assert recorder.queue_size == 4

    await recorder.start()
    # Call start again (branch line 50->exit when already running)
    await recorder.start()

    await asyncio.sleep(0.2)
    assert recorder.records_written == 4
    await recorder.close()


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


async def test_replay_recorder_worker_inner_drain(tmp_path: Path):
    """Test ReplayRecorder worker inner draining loop."""
    log_file = tmp_path / "inner_drain.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=3, flush_interval_seconds=0.01
    )
    await recorder.start()
    recorder._queue.put_nowait({"item": 1})
    recorder._queue.put_nowait({"item": 2})
    recorder._queue.put_nowait({"item": 3})
    await asyncio.sleep(0.05)
    await recorder.close()
    assert recorder.records_written == 3


async def test_replay_recorder_flush_and_close_branches(tmp_path: Path):
    """Test ReplayRecorder flush QueueEmpty branch and close without start."""
    log_file = tmp_path / "flush_empty.jsonl"
    recorder = ReplayRecorder(output_path=log_file, batch_size=5)

    # Close without start
    await recorder.close()
    assert not recorder.is_running

    # Flush with 1 item triggering QueueEmpty on next iteration
    recorder._queue.put_nowait({"item": 1})
    await recorder.flush()
    assert recorder.records_written == 1


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


async def test_replay_recorder_worker_error(tmp_path: Path):
    """Test ReplayRecorder worker exception resiliency."""
    log_file = tmp_path / "worker_err.jsonl"
    recorder = ReplayRecorder(
        output_path=log_file, batch_size=2, flush_interval_seconds=0.05
    )
    await recorder.start()

    # Trigger exception in _write_batch inside worker
    with patch.object(
        recorder, "_write_batch", side_effect=[Exception("Batch error"), None]
    ):
        recorder.record_snapshot({"mint": "Mint1"})
        recorder.record_snapshot({"mint": "Mint2"})
        await asyncio.sleep(0.15)

    await recorder.close()


def test_replay_load_history_gzip_and_directory(tmp_path: Path):
    """Test PaperTradingEngine.load_history with .gz and directory datasets."""
    import gzip

    # File 1: compressed .jsonl.gz
    f1 = tmp_path / "replay_01.jsonl.gz"
    with gzip.open(f1, "wt", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": 100,
                    "mint": "M1",
                    "price": 0.00000001,
                    "buy_signal": True,
                }
            )
            + "\n"
        )

    # File 2: active .jsonl
    f2 = tmp_path / "replay_02.jsonl"
    f2.write_text(
        json.dumps(
            {"timestamp": 200, "mint": "M2", "price": 0.00000002, "sell_signal": True}
        )
        + "\n",
        encoding="utf-8",
    )

    records = PaperTradingEngine.load_history(tmp_path)
    assert len(records) == 2
    assert records[0]["mint"] == "M1"
    assert records[1]["mint"] == "M2"
