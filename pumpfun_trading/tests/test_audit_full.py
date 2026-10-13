from __future__ import annotations

from rich.console import Console

from pumpfun_trading.bot.audit import (
    _as_timestamp,
    _normalize_text,
    _payload_for,
    export_audit_records,
    filter_audit_records,
    render_audit_table,
    summarize_audit_records,
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
    ]

    console = Console(width=200, file=None, record=True)
    render_audit_table(records, console)
    rendered = console.export_text()

    assert "Buy Price" in rendered
    assert "Sell Price" in rendered
    assert "0.000035 SOL" in rendered
    assert "0.000085 SOL" in rendered
    assert "1.2500 SOL" in rendered
    assert "2.5000 SOL" in rendered

    # Filter by min_buy_price
    assert len(filter_audit_records(records, min_buy_price=0.5)) == 1
    # Filter by max_buy_price
    assert len(filter_audit_records(records, max_buy_price=0.0001)) == 2
    # Filter by min_sell_price
    assert len(filter_audit_records(records, min_sell_price=1.0)) == 1
    # Filter by max_sell_price
    assert len(filter_audit_records(records, max_sell_price=0.001)) == 1
    # Filter combined
    assert (
        len(filter_audit_records(records, min_buy_price=0.00001, max_sell_price=0.0001))
        == 1
    )
