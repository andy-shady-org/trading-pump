import json

from pumpfun_trading.bot.audit import (
    export_audit_records,
    filter_audit_records,
    load_audit_records,
    summarize_audit_records,
)


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


def test_audit_cli_price_filters(tmp_path):
    from unittest.mock import patch
    from pumpfun_trading.cli.audit import build_parser, run_audit_cli

    path = tmp_path / "audit.jsonl"
    records = [
        {
            "timestamp": 1700000000,
            "type": "trade",
            "state": "buying",
            "payload": {
                "mint": "MintA",
                "buy_price": 0.005,
                "action": "buy",
                "status": "success",
            },
        },
        {
            "timestamp": 1700000100,
            "type": "trade",
            "state": "selling",
            "payload": {
                "mint": "MintB",
                "buy_price": 0.005,
                "sell_price": 0.015,
                "action": "sell",
                "status": "success",
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(
        ["--path", str(path), "--min-sell-price", "0.010", "--json"]
    )
    with patch("pumpfun_trading.cli.audit.console.print") as mock_print:
        run_audit_cli(args)
        assert mock_print.called
        printed_arg = mock_print.call_args[0][0]
        data = json.loads(printed_arg)
        assert len(data) == 1
        assert data[0]["payload"]["mint"] == "MintB"
