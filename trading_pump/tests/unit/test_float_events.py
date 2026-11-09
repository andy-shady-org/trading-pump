"""Unit tests for ``float_events.py``: Float, LaunchLab and CPMM decoders
(FEAT-179), pinned to records read from mainnet."""

from __future__ import annotations

import base64
import struct
from typing import Any

import base58

from trading_pump import float_events as fe
from trading_pump.tests.support import float_payloads as payloads

ACCOUNTS = payloads.ACCOUNTS
SOL = "So11111111111111111111111111111111111111112"
COIN = "4QDPF5TtNAKtU5p5pvcq9h9b44nRSikRzNrKzsUfLoat"
CURVE = "zYm8oYadcdGes4jPRU4h2tcg4cjNVExYiyQnJParuBN"
CPMM_POOL = "9f13JFmgNwusTQmY86S7EA1aG4qULw39UgGN19wenCex"


def _account(name: str) -> dict[str, Any]:
    entry = ACCOUNTS[name]
    return {"owner": entry["owner"], "data": entry["data"]}


def _raw(name: str) -> bytes:
    return base64.b64decode(ACCOUNTS[name]["data"][0])


# -- logs --------------------------------------------------------------------------
def test_read_logs_attributes_data_and_names_to_the_running_program() -> None:
    records = fe.read_logs(payloads.LAUNCH_LOGS)
    assert [(owner[:6], raw[:8]) for owner, raw in records.data] == [
        ("LanMV9", fe.POOL_CREATE_EVENT),
        ("3KguFi", fe.FLOAT_LAUNCH_EVENT),
    ]
    assert records.instructions_of(fe.FLOAT_PROGRAM_ID) == ["LaunchKeyed"]
    assert records.instructions_of(fe.LAUNCHLAB_PROGRAM_ID) == ["InitializeV2"]
    assert not records.truncated


def test_read_logs_joins_multi_part_data_and_skips_what_is_not_base64() -> None:
    first, second = base64.b64encode(b"ab").decode(), base64.b64encode(b"cd").decode()
    records = fe.read_logs(
        [
            "Program X111 invoke [1]",
            f"Program data: {first} {second}",
            "Program data: !!not base64!!",
            "Program log: something else",
            "Program X111 success",
            "Program data: outside any program",
            "Program Y111 failed: custom error",
            "Log truncated",
        ]
    )
    assert records.data == (("X111", b"abcd"),)
    assert records.instructions == () and records.truncated


def test_records_filter_by_program_and_discriminator() -> None:
    records = fe.read_logs(payloads.CLAIM_LOGS)
    assert records.instructions_of(fe.FLOAT_PROGRAM_ID) == ["ClaimCoinFees", "Harvest"]
    assert records.data_of(fe.LAUNCHLAB_PROGRAM_ID, fe.TRADE_EVENT) == []


# -- LaunchLab events --------------------------------------------------------------
def _trade(logs: list[str]) -> fe.TradeEvent:
    (raw,) = fe.read_logs(logs).data_of(fe.LAUNCHLAB_PROGRAM_ID, fe.TRADE_EVENT)
    event = fe.decode_trade_event(raw)
    assert event is not None
    return event


def test_a_buy_matches_its_reserves_and_fees() -> None:
    buy = _trade(payloads.BUY_LOGS)
    values = buy.values
    assert (buy.pool, buy.side, buy.pool_status, buy.exact_in) == (
        CURVE,
        "buy",
        "fund",
        True,
    )
    fees = sum(values[k] for k in ("protocol_fee", "platform_fee", "creator_fee"))
    assert (
        values["amount_out"] == values["real_base_after"] - values["real_base_before"]
    )
    assert values["amount_in"] == (
        values["real_quote_after"] - values["real_quote_before"] + fees
    )
    assert buy.row_fields()["side"] == "buy" and buy.row_fields()["pool"] == CURVE


def test_a_sell_matches_its_reserves_and_fees() -> None:
    sell = _trade(payloads.SELL_LOGS)
    values = sell.values
    fees = sum(
        values[k] for k in ("protocol_fee", "platform_fee", "creator_fee", "share_fee")
    )
    assert sell.side == "sell"
    assert values["amount_in"] == values["real_base_before"] - values["real_base_after"]
    assert values["amount_out"] == (
        values["real_quote_before"] - values["real_quote_after"] - fees
    )


def test_a_trade_event_of_another_shape_is_not_decoded() -> None:
    (raw,) = fe.read_logs(payloads.BUY_LOGS).data_of(
        fe.LAUNCHLAB_PROGRAM_ID, fe.TRADE_EVENT
    )
    assert fe.decode_trade_event(raw[:-1]) is None
    assert fe.decode_trade_event(b"\x00" * 8 + raw[8:]) is None
    assert fe.decode_trade_event(raw[:144] + bytes([2, 0, 1])) is None
    assert fe.decode_trade_event(raw[:144] + bytes([0, 3, 1])) is None


def test_the_pool_create_event_gives_the_curves_terms() -> None:
    (raw,) = fe.read_logs(payloads.LAUNCH_LOGS).data_of(
        fe.LAUNCHLAB_PROGRAM_ID, fe.POOL_CREATE_EVENT
    )
    event = fe.decode_pool_create_event(raw)
    assert event is not None
    assert (event.pool, event.name, event.symbol, event.decimals) == (
        CURVE,
        "Finance Inu",
        "FI",
        6,
    )
    assert event.uri_host == "float.mypinata.cloud"
    assert (event.curve, event.supply, event.total_base_sell) == (
        "constant",
        1_000_000_000_000_000,
        732_500_000_000_000,
    )
    assert event.total_quote_fund_raising == 395_623_385_978
    assert event.migrate_type == 1 and event.vesting_locked == 0
    assert fe.decode_pool_create_event(b"\x00" * len(raw)) is None
    assert fe.decode_pool_create_event(raw[:120]) is None
    assert fe.decode_pool_create_event(raw[:118]) is None  # a name past the end


def _create_event(curve: bytes, uri: str = "https://x.example/a") -> bytes:
    def string(text: str) -> bytes:
        return struct.pack("<I", len(text)) + text.encode()

    return (
        fe.POOL_CREATE_EVENT
        + bytes(96)
        + bytes([9])
        + string("N")
        + string("S")
        + string(uri)
        + curve
        + struct.pack("<3Q", 1, 2, 3)
        + bytes([0])
    )


def test_fixed_and_linear_curves_and_unknown_kinds() -> None:
    fixed = fe.decode_pool_create_event(
        _create_event(bytes([1]) + struct.pack("<2Q", 10, 20) + bytes([0]))
    )
    assert fixed is not None and (fixed.curve, fixed.total_base_sell) == ("fixed", None)
    assert (fixed.supply, fixed.total_quote_fund_raising) == (10, 20)
    assert (fixed.vesting_locked, fixed.vesting_cliff, fixed.vesting_unlock) == (
        1,
        2,
        3,
    )
    linear = fe.decode_pool_create_event(
        _create_event(bytes([2]) + struct.pack("<2Q", 10, 20) + bytes([1]))
    )
    assert linear is not None and linear.curve == "linear" and linear.migrate_type == 1
    assert fe.decode_pool_create_event(_create_event(bytes([3]) + bytes(17))) is None
    bad_uri = fe.decode_pool_create_event(
        _create_event(bytes([1]) + bytes(17), uri="http://[::1")
    )
    assert bad_uri is not None and bad_uri.uri_host is None


# -- accounts ----------------------------------------------------------------------
def test_a_launchlab_pool_reads_its_platform_curve_and_vaults() -> None:
    pool = fe.decode_launchlab_pool(_account("launch_pool"))
    assert pool is not None
    assert (pool.status, pool.base_mint, pool.quote_mint) == (2, COIN, SOL)
    assert pool.platform == fe.FLOAT_PLATFORMS[0]
    assert pool.real_quote == 395_623_386_925 and pool.base_decimals == 6
    terms = pool.terms()
    assert terms["base_vault"] == "DeSdyfomEKbpU46KDEoM8MmgdVSPJjXeLEjCciuUtzi7"
    assert terms["virtual_quote"] == 227_589_797_310
    other = dict(_account("launch_pool"), owner=fe.CPMM_PROGRAM_ID)
    assert fe.decode_launchlab_pool(other) is None
    assert fe.decode_launchlab_pool(None) is None


def test_account_bytes_needs_the_owner_and_base64() -> None:
    assert fe.account_bytes({"owner": "X", "data": ["AAAA"]}, "X") == b"\x00\x00\x00"
    assert fe.account_bytes({"owner": "X", "data": ["!"]}, "X") is None
    assert fe.account_bytes({"owner": "X", "data": None}, "X") == b""
    assert fe.account_bytes({}, "X") is None


def test_a_platform_config_gives_its_fees() -> None:
    fees = fe.decode_platform_fees(fe.FLOAT_PLATFORMS[0], _account("platform"))
    assert fees is not None
    assert (fees.platform_fee_bps, fees.creator_fee_bps) == (60.0, 15.0)
    assert fees.total_fee_bps == 100.0
    short = {"owner": fe.LAUNCHLAB_PROGRAM_ID, "data": [base64.b64encode(bytes(100))]}
    assert fe.decode_platform_fees("P", short) is None


def test_floats_config_lists_its_platforms() -> None:
    assert fe.decode_float_platforms(_account("float_config")) == fe.FLOAT_PLATFORMS
    raw = bytearray(_raw("float_config"))
    for count in (0, 9):
        raw[106] = count
        value = {"owner": fe.FLOAT_PROGRAM_ID, "data": [base64.b64encode(raw).decode()]}
        assert fe.decode_float_platforms(value) is None
    short = {
        "owner": fe.FLOAT_PROGRAM_ID,
        "data": [base64.b64encode(bytes(50)).decode()],
    }
    assert fe.decode_float_platforms(short) is None
    overrun = bytearray(110)
    overrun[106] = 2
    value = {"owner": fe.FLOAT_PROGRAM_ID, "data": [base64.b64encode(overrun).decode()]}
    assert fe.decode_float_platforms(value) is None


def test_a_cpmm_pool_gives_its_vaults_mints_and_held_fees() -> None:
    pool = fe.decode_cpmm_pool(_account("cpmm_pool"))
    assert pool is not None
    assert (pool.mint_0, pool.mint_1) == (SOL, COIN)
    assert pool.vault_0 == "9W1jk3Xp24MmwagZ7wqkFjf9Dt7d2yjQH9xZULmbSSai"
    raw = _raw("cpmm_pool")
    protocol, fund = (
        struct.unpack_from("<Q", raw, 341)[0],
        struct.unpack_from("<Q", raw, 357)[0],
    )
    creator = struct.unpack_from("<Q", raw, 397)[0]
    assert pool.held_fees_0 == protocol + fund + creator
    assert fe.decode_cpmm_pool(_account("launch_pool")) is None


# -- Float and CPMM events ---------------------------------------------------------
def test_floats_launch_event_names_the_coin_curve_and_launcher() -> None:
    (raw,) = fe.read_logs(payloads.LAUNCH_LOGS).data_of(
        fe.FLOAT_PROGRAM_ID, fe.FLOAT_LAUNCH_EVENT
    )
    launch = fe.decode_float_launch(raw)
    assert launch is not None
    assert (launch.mint, launch.quote_mint, launch.pool) == (COIN, SOL, CURVE)
    assert (
        launch.launcher
        == launch.second_key
        == ("7fMwZddcRnuwWsZQT5Eg9cqa9of516sgBZQruH1pj5b8")
    )
    assert launch.symbol == "FI"
    no_symbol = fe.decode_float_launch(raw[:170])
    assert no_symbol is not None and no_symbol.symbol is None
    assert fe.decode_float_launch(raw[:100]) is None


def test_a_cpmm_swap_event_is_decoded() -> None:
    (raw,) = fe.read_logs(payloads.CPMM_SWAP_LOGS).data_of(
        fe.CPMM_PROGRAM_ID, fe.CPMM_SWAP_EVENT
    )
    swap = fe.decode_cpmm_swap(raw)
    assert swap is not None
    assert (swap.pool, swap.input_mint, swap.output_mint) == (CPMM_POOL, SOL, COIN)
    assert (swap.input_amount, swap.output_amount) == (10_000, 6_693_865)
    assert swap.base_input and swap.creator_fee_on_input
    fields = swap.row_fields()
    assert fields["trade_fee"] == 3 and fields["creator_fee"] == 97
    assert fe.decode_cpmm_swap(raw[:-1]) is None


# -- the migration -----------------------------------------------------------------
def test_the_migration_names_the_curve_coin_and_cpmm_pool() -> None:
    migration = fe.decode_migration(payloads.MIGRATION_TX)
    assert migration is not None
    assert (migration.pool, migration.base_mint, migration.quote_mint) == (
        CURVE,
        COIN,
        SOL,
    )
    assert migration.platform == fe.FLOAT_PLATFORMS[0]
    assert migration.cpmm_pool == CPMM_POOL
    assert migration.cpmm_base_vault == "DtiEPPzwXSF8cXTEmxDsjwhQotfzGzx6UaveL9ozwiuW"
    assert migration.cpmm_quote_vault == "9W1jk3Xp24MmwagZ7wqkFjf9Dt7d2yjQH9xZULmbSSai"
    assert migration.slot == 466_177_688 and migration.block_time == 1_793_982_718
    assert fe.transaction_signers(payloads.MIGRATION_TX) == [
        "RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw",
        "DCwEWHxwKwfSptzUa4vn9yDZu3qVN2wUkg7gvTbCsEoy",
    ]


def _tx(instructions: list[dict[str, Any]], inner: list[Any] | None = None) -> dict:
    keys = [fe.LAUNCHLAB_PROGRAM_ID] + [f"Key{i}" for i in range(20)]
    return {
        "transaction": {"signatures": ["Sig"], "message": {"accountKeys": keys}},
        "meta": {"innerInstructions": inner or []},
        "_instructions": instructions,
    }


def test_a_migration_inside_another_program_is_found_and_others_are_not() -> None:
    data = base58.b58encode(fe.MIGRATE_TO_CPSWAP + b"\x00").decode()
    accounts = list(range(1, 21))
    inner = [
        {"instructions": [{"programIdIndex": 0, "data": data, "accounts": accounts}]}
    ]
    tx = _tx([])
    tx["meta"]["innerInstructions"] = inner
    migration = fe.decode_migration(tx)
    assert migration is not None and migration.pool == "Key17"
    assert migration.slot is None and migration.signature == "Sig"
    others = [
        {"programIdIndex": 99, "data": data, "accounts": accounts},
        {"programIdIndex": 1, "data": data, "accounts": accounts},
        {"programIdIndex": 0, "data": "0OIl", "accounts": accounts},
        {"programIdIndex": 0, "data": data, "accounts": accounts[:5]},
        {"programIdIndex": 0, "data": base58.b58encode(b"x" * 8).decode()},
    ]
    tx = _tx([])
    tx["transaction"]["message"]["instructions"] = others
    assert fe.decode_migration(tx) is None
    assert fe.decode_migration(None) is None
    assert fe.transaction_signers(None) == []
