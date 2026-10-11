from __future__ import annotations

import json

from rich.console import Console

from pumpfun_trading.engines.replay import (
    PaperTradingEngine,
    ReplayEngine,
    render_replay_dashboard,
    render_replay_summary,
    render_replay_trades,
    run_replay,
)


def test_paper_trading_engine_data_loading(tmp_path):
    # Non-existent file
    assert PaperTradingEngine.load_history(tmp_path / "missing.json") == []

    # Empty file
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("   \n", encoding="utf-8")
    assert PaperTradingEngine.load_history(empty_file) == []

    # Invalid JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not valid json}", encoding="utf-8")
    assert PaperTradingEngine.load_history(bad_json) == []

    # JSON with wrapper object
    wrapped_json = tmp_path / "wrapped.json"
    wrapped_json.write_text(
        json.dumps({"snapshots": [{"mint": "Mint1", "price": 1.0}]}), encoding="utf-8"
    )
    assert len(PaperTradingEngine.load_history(wrapped_json)) == 1

    # JSONL loading with comments / blank lines / bad lines
    jsonl_file = tmp_path / "history.jsonl"
    jsonl_content = (
        '{"mint": "Mint1", "price": 1.0}\n\n'
        "{bad json line}\n"
        '{"mint": "Mint2", "price": 2.0}\n'
    )
    jsonl_file.write_text(jsonl_content, encoding="utf-8")
    records = PaperTradingEngine.load_history(jsonl_file)
    assert len(records) == 2
    assert records[0]["mint"] == "Mint1"
    assert records[1]["mint"] == "Mint2"


def test_paper_trading_engine_helpers():
    snapshot = {
        "mint": "MintABC",
        "name": "Token ABC",
        "timestamp": 12345678,
        "marketCapSol": "50.5",
        "price": "1.25",
        "buy_signal": True,
        "sell_signal": False,
    }
    assert PaperTradingEngine._snapshot_mint(snapshot) == "MintABC"
    assert PaperTradingEngine._snapshot_mint({}) == "unknown-mint"
    assert PaperTradingEngine._snapshot_name(snapshot) == "Token ABC"
    assert PaperTradingEngine._snapshot_name({}) == "unknown"
    assert PaperTradingEngine._snapshot_timestamp(snapshot) == 12345678
    assert PaperTradingEngine._snapshot_price(snapshot) == 1.25
    assert PaperTradingEngine._snapshot_float(snapshot, "marketCapSol") == 50.5
    assert PaperTradingEngine._snapshot_float(snapshot, "nonexistent") == 0.0
    assert PaperTradingEngine._snapshot_float({"bad": "not_a_float"}, "bad") == 0.0
    assert PaperTradingEngine._buy_signal(snapshot) is True
    assert PaperTradingEngine._buy_signal({"signal": "BUY"}) is True
    assert PaperTradingEngine._buy_signal({"should_buy": True}) is True
    assert PaperTradingEngine._sell_signal({"signal": "exit"}) is True
    assert PaperTradingEngine._sell_signal({"should_sell": True}) is True


def test_paper_trading_engine_simulation_and_metrics():
    engine = PaperTradingEngine(
        initial_cash=100.0,
        max_positions=2,
        fee_bps=100,
        slippage_bps=100,
        buy_fraction=0.5,
        take_profit=1.5,
        stop_loss=0.8,
    )

    snapshots = [
        # Ignore zero price
        {"mint": "MintZero", "price": 0.0},
        # Buy Mint1
        {
            "mint": "Mint1",
            "name": "M1",
            "price": 10.0,
            "timestamp": 100,
            "buy_signal": True,
        },
        # Hold Mint1
        {"mint": "Mint1", "name": "M1", "price": 12.0, "timestamp": 101},
        # Buy Mint2
        {
            "mint": "Mint2",
            "name": "M2",
            "price": 5.0,
            "timestamp": 102,
            "buy_signal": True,
        },
        # Try to buy Mint3 (exceeds max_positions 2)
        {
            "mint": "Mint3",
            "name": "M3",
            "price": 1.0,
            "timestamp": 103,
            "buy_signal": True,
        },
        # Mint1 take profit (performance (26-10)/10 = 1.6 >= 1.5)
        {"mint": "Mint1", "name": "M1", "price": 26.0, "timestamp": 104},
        # Mint2 stop loss (performance (0.5-5)/5 = -0.9 <= -0.8)
        {"mint": "Mint2", "name": "M2", "price": 0.5, "timestamp": 105},
    ]

    summary = engine.run(snapshots)
    assert summary["total_trades"] == 4  # 2 buys, 2 sells
    assert summary["buy_count"] == 2
    assert summary["sell_count"] == 2
    assert summary["win_rate"] == 0.5
    assert "profit_factor" in summary
    assert "max_drawdown" in summary


def test_paper_trading_engine_run_and_render(tmp_path):
    snapshots = [
        {
            "mint": "MintA",
            "name": "A",
            "price": 10.0,
            "timestamp": 1000,
            "buy_signal": True,
        },
        {"mint": "MintA", "name": "A", "price": 11.0, "timestamp": 1010},
        {
            "mint": "MintA",
            "name": "A",
            "price": 12.0,
            "timestamp": 1020,
            "sell_signal": True,
        },
    ]
    file_path = tmp_path / "dataset.json"
    file_path.write_text(json.dumps(snapshots), encoding="utf-8")

    engine = ReplayEngine(initial_cash=200.0)
    summary = run_replay(file_path, engine=engine)
    assert summary["total_trades"] == 2  # 1 buy, 1 sell
    assert len(summary["trades"]) == 2

    # Test rendering functions
    console = Console(width=120, file=None, record=True)
    render_replay_summary(summary, console)
    render_replay_trades(summary["trades"], console)
    output = console.export_text()
    assert "Mint Name" in output
    assert "MintA" in output
    assert "A" in output
    render_replay_trades([], console)  # Empty trades
    render_replay_dashboard(summary, console)

    # Test filtering by mint and mint_name
    summary_mint = run_replay(file_path, mint="MintA")
    assert summary_mint["total_trades"] == 2
    summary_mint_name = run_replay(file_path, mint_name="A")
    assert summary_mint_name["total_trades"] == 2
    summary_none = run_replay(file_path, mint="NonExistent")
    assert summary_none["total_trades"] == 0
