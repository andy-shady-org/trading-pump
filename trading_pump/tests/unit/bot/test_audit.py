"""Unit tests for ``bot/audit.py``."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from trading_pump.bot.audit import (
    _as_timestamp,
    _normalize_text,
    _payload_for,
    export_audit_records,
    filter_audit_records,
    load_audit_records,
    render_audit_table,
    summarize_audit_records,
)
from trading_pump.ops.retention import compress_file_to_gzip


def test_load_audit_records_reads_jsonl(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps({"type": "trade", "state": "buying", "payload": {"mint": "abc"}})
        + "\n"
        + json.dumps(
            {"type": "event", "state": "holding", "payload": {"message": "ok"}}
        )
        + "\n",
        encoding="utf-8",
    )

    records = load_audit_records(path)
    assert len(records) == 2
    assert records[0]["type"] == "trade"


def test_load_audit_records_reads_gzip_and_directory(tmp_path):
    import gzip

    # Write chunk 1 as .jsonl.1.gz
    gz_file = tmp_path / "audit.jsonl.1.gz"
    with gzip.open(gz_file, "wt", encoding="utf-8") as f:
        f.write(
            json.dumps({"timestamp": 100, "type": "trade", "payload": {"mint": "M1"}})
            + "\n"
        )

    # Write chunk 2 as active uncompressed audit.jsonl
    active_file = tmp_path / "audit.jsonl"
    active_file.write_text(
        json.dumps({"timestamp": 200, "type": "trade", "payload": {"mint": "M2"}})
        + "\n",
        encoding="utf-8",
    )

    # Test reading single gz file
    rec_gz = load_audit_records(gz_file)
    assert len(rec_gz) == 1
    assert rec_gz[0]["payload"]["mint"] == "M1"

    # Test reading entire directory containing mixed active and gz files
    rec_dir = load_audit_records(tmp_path)
    assert len(rec_dir) == 2
    assert rec_dir[0]["payload"]["mint"] == "M1"
    assert rec_dir[1]["payload"]["mint"] == "M2"


def test_filter_audit_records_supports_common_filters(tmp_path):
    path = tmp_path / "audit.jsonl"
    records = [
        {
            "timestamp": 1700000000,
            "type": "trade",
            "state": "buying",
            "payload": {
                "mint": "So11111111111111111111111111111111111111112",
                "reason": "take_profit",
                "status": "success",
            },
        },
        {
            "timestamp": 1700003600,
            "type": "event",
            "state": "selling",
            "payload": {"message": "stop loss hit", "reason": "stop_loss"},
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )

    loaded = load_audit_records(path)
    filtered = filter_audit_records(
        loaded,
        record_type="trade",
        state="buying",
        mint="So11111111111111111111111111111111111111112",
        reason="take_profit",
        status="success",
    )

    assert len(filtered) == 1
    assert (
        filtered[0]["payload"]["mint"] == "So11111111111111111111111111111111111111112"
    )


def test_summarize_audit_records_counts_by_reason_and_type():
    records = [
        {"type": "trade", "state": "buying", "payload": {"reason": "take_profit"}},
        {"type": "trade", "state": "selling", "payload": {"reason": "take_profit"}},
        {"type": "event", "state": "holding", "payload": {"message": "event"}},
    ]

    summary = summarize_audit_records(records)
    assert summary["total_records"] == 3
    assert summary["by_type"]["trade"] == 2
    assert summary["by_reason"]["take_profit"] == 2


def test_export_audit_records_writes_json(tmp_path):
    path = tmp_path / "filtered.json"
    records = [{"type": "trade", "payload": {"reason": "risk_kill"}}]

    result = export_audit_records(records, path)

    assert result == str(path)
    assert (
        json.loads(path.read_text(encoding="utf-8"))[0]["payload"]["reason"]
        == "risk_kill"
    )


def test_audit_timestamp_and_helpers():
    assert _as_timestamp(None) is None
    assert _as_timestamp(12345) == 12345.0
    assert _as_timestamp("   ") is None
    assert _as_timestamp("12345.67") == 12345.67
    assert _as_timestamp("2024-01-01T00:00:00Z") is not None
    assert _as_timestamp("2024-01-01") is not None
    assert _as_timestamp("not-a-date") is None

    assert _normalize_text(None) == ""
    assert _normalize_text("  HeLLo  ") == "hello"

    assert _payload_for({}) == {}
    assert _payload_for({"payload": {"k": "v"}}) == {"k": "v"}
    assert _payload_for({"payload": "invalid"}) == {}


def test_audit_filter_records():
    records = [
        {
            "timestamp": 1700000000.0,
            "type": "trade",
            "state": "buying",
            "mint": "Mint1",
            "payload": {
                "token_name": "CoinOne",
                "reason": "signal",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000100.0,
            "type": "lifecycle",
            "payload": {
                "previous_state": "idle",
                "state": "monitoring",
                "mint": "Mint2",
                "token_name": "CoinTwo",
                "reason": "startup",
                "status": "ok",
            },
        },
    ]

    # Filter by record_type
    assert len(filter_audit_records(records, record_type="trade")) == 1

    # Filter by state
    assert len(filter_audit_records(records, state="monitoring")) == 1

    # Filter by dates
    assert len(filter_audit_records(records, date_from="1700000050.0")) == 1
    assert len(filter_audit_records(records, date_to="1700000050.0")) == 1

    # Filter by mint
    assert len(filter_audit_records(records, mint="Mint1")) == 1

    # Filter by token_name / mint_name
    assert len(filter_audit_records(records, token_name="CoinTwo")) == 1
    assert len(filter_audit_records(records, mint_name="CoinTwo")) == 1
    assert len(filter_audit_records(records, mint_name="CoinOne")) == 1

    # Filter by reason
    assert len(filter_audit_records(records, reason="signal")) == 1

    # Filter by status
    assert len(filter_audit_records(records, status="ok")) == 1

    # Limit
    assert len(filter_audit_records(records, limit=1)) == 1


def test_audit_summarize_render_and_export(tmp_path):
    records = [
        {
            "timestamp": 1700000000.0,
            "type": "trade",
            "state": "buying",
            "mint": "Mint1",
            "payload": {
                "token_name": "CoinOne",
                "reason": "signal",
                "status": "success",
                "action": "buy",
            },
        }
    ]

    summary = summarize_audit_records(records)
    assert summary["total_records"] == 1
    assert "by_type" in summary

    console = Console(file=None, record=True)
    render_audit_table(records, console)
    render_audit_table([], console)

    export_path = tmp_path / "out.json"
    export_audit_records(records, str(export_path))
    assert export_path.exists()


def test_audit_buy_and_sell_prices_rendering_and_filters():
    records = [
        {
            "timestamp": 1700000000.0,
            "type": "trade",
            "state": "buying",
            "mint": "MintBuy1",
            "payload": {
                "token_name": "BuyCoin",
                "action": "buy",
                "buy_price": 0.000035,
                "reason": "signal_entry",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000100.0,
            "type": "trade",
            "state": "selling",
            "mint": "MintSell1",
            "payload": {
                "token_name": "SellCoin",
                "action": "sell",
                "buy_price": 0.000035,
                "sell_price": 0.000085,
                "reason": "take_profit",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000200.0,
            "type": "trade",
            "state": "selling",
            "mint": "MintSell2",
            "payload": {
                "token_name": "BigCoin",
                "action": "sell",
                "entry_price": 1.25,
                "exit_price": 2.50,
                "reason": "moonbag_trailing",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000300.0,
            "type": "trade",
            "state": "buying",
            "mint": "MintMicro1",
            "payload": {
                "token_name": "MicroPumpCoin",
                "action": "buy",
                "buy_price": 0.00000002796,  # 2.796e-8 SOL (~0.0280 µSOL)
                "reason": "bonding_curve_snipe",
                "status": "success",
            },
        },
    ]

    console = Console(width=200, file=None, record=True)
    render_audit_table(records, console)
    rendered = console.export_text()

    assert "Buy Price" in rendered
    assert "Sell Price" in rendered
    assert "35.0000 µSOL" in rendered
    assert "85.0000 µSOL" in rendered
    assert "0.0280 µSOL" in rendered
    assert "1.2500 SOL" in rendered
    assert "2.5000 SOL" in rendered

    # Filter by min_buy_price
    assert len(filter_audit_records(records, min_buy_price=0.5)) == 1
    # Filter by max_buy_price
    assert len(filter_audit_records(records, max_buy_price=0.0001)) == 3
    # Filter by min_sell_price
    assert len(filter_audit_records(records, min_sell_price=1.0)) == 1
    # Filter by max_sell_price
    assert len(filter_audit_records(records, max_sell_price=0.001)) == 1
    # Filter combined
    assert (
        len(filter_audit_records(records, min_buy_price=0.00001, max_sell_price=0.0001))
        == 1
    )


def test_audit_module_all_branches(tmp_path):
    # Non-existent file
    assert load_audit_records(tmp_path / "missing.jsonl") == []

    # File with comments, blank lines, and corrupted JSON
    audit_file = tmp_path / "sample_audit.jsonl"
    audit_file.write_text(
        "# comment\n\n{invalid json}\n"
        + json.dumps({"timestamp": 1234, "type": "trade", "payload": {"status": "ok"}})
        + "\n",
        encoding="utf-8",
    )
    records = load_audit_records(audit_file)
    assert len(records) == 1

    # summarize empty and non-empty
    assert summarize_audit_records([])["total_records"] == 0

    # export audit to nested dir
    out_file = tmp_path / "nested" / "export.json"
    assert export_audit_records(records, str(out_file)) == str(out_file)
    assert out_file.exists()


def test_audit_and_replay_corrupted_and_multi_archive_ingestion(tmp_path: Path):
    from trading_pump.bot.audit import load_audit_records

    audit_dir = tmp_path / "audit_dir"
    audit_dir.mkdir()

    # File 1: uncompressed JSONL with valid and invalid lines
    f1 = audit_dir / "audit.jsonl"
    f1.write_text(
        json.dumps(
            {"timestamp": 100.0, "mint": "m1", "action": "buy", "state": "buying"}
        )
        + "\n"
        + "invalid json line\n"
        + json.dumps(
            {"timestamp": 105.0, "mint": "m1", "action": "sell", "state": "selling"}
        )
        + "\n",
        encoding="utf-8",
    )

    # File 2: compressed JSONL
    f2 = audit_dir / "audit.jsonl.1"
    f2.write_text(
        json.dumps(
            {"timestamp": 90.0, "mint": "m2", "action": "buy", "state": "buying"}
        )
        + "\n",
        encoding="utf-8",
    )
    compress_file_to_gzip(f2)

    # Load from directory
    records = load_audit_records(audit_dir)
    assert len(records) >= 3
    # Check chronological ordering
    assert records[0]["timestamp"] <= records[1]["timestamp"]

    # Load non-existent path
    assert load_audit_records(tmp_path / "non_existent.jsonl") == []


def test_audit_helpers_and_table_rendering(tmp_path: Path):
    from trading_pump.bot.audit import (
        _extract_buy_price,
        _extract_sell_price,
        _normalize_text,
        export_audit_records,
        render_audit_table,
        summarize_audit_records,
    )

    assert _normalize_text(None) == ""
    assert _normalize_text("  TEST  ") == "test"

    # Price extractors with different fields and invalid values
    assert _extract_buy_price({"unit_price_sol": 0.00005}) == 0.00005
    assert _extract_buy_price({"payload": {"execution_price": "0.00006"}}) == 0.00006
    assert _extract_buy_price({"type": "buy", "entry": 0.00007}) == 0.00007
    assert _extract_buy_price({"type": "buy", "entry": -1.0}) is None
    assert _extract_buy_price({"type": "buy", "entry": "invalid"}) is None
    assert _extract_buy_price({}) is None

    assert _extract_sell_price({"sell_price": 0.00008}) == 0.00008
    assert _extract_sell_price({"payload": {"exit_price": "0.00009"}}) == 0.00009
    assert _extract_sell_price({"type": "sell", "exit": 0.00010}) == 0.00010
    assert _extract_sell_price({"type": "sell", "exit": -0.5}) is None
    assert _extract_sell_price({"type": "sell", "exit": "abc"}) is None
    assert _extract_sell_price({}) is None

    # Summarize records
    records = [
        {
            "timestamp": 1000.0,
            "type": "buy",
            "mint": "m1",
            "sol_amount": 0.1,
            "tokens": 1000,
            "buy_price": 0.0001,
        },
        {
            "timestamp": 1050.0,
            "type": "sell",
            "mint": "m1",
            "sol_amount": 0.15,
            "tokens": 1000,
            "sell_price": 0.00015,
        },
    ]
    summary = summarize_audit_records(records)
    assert summary["total_records"] == 2

    # Render table and export
    render_audit_table(records)
    export_path = tmp_path / "audit_exp.json"
    export_audit_records(records, export_path)
    assert export_path.exists()
