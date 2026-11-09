"""Unit tests for ``float_capture.py``: the Float capture (FEAT-179)."""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
from typing import Any

import base58
import pytest

from trading_pump import float_events as fe
from trading_pump.config.settings import FloatSettings
from trading_pump.float_capture import (
    CPMM_TRADE_ROW,
    FEE_CYCLE_ROW,
    LAUNCH_EVENT,
    LOGS_NOTIFICATION,
    MIGRATION_ROW,
    PLATFORMS_ROW,
    READING_ROW,
    TRADE_ROW,
    TRADER_ROW,
    FloatFeed,
    FloatWatcher,
    RpcFloatSource,
    token_owner_and_amount,
)
from trading_pump.tests.support import float_payloads as payloads

ACCOUNTS = payloads.ACCOUNTS
SOL = "So11111111111111111111111111111111111111112"
COIN = "4QDPF5TtNAKtU5p5pvcq9h9b44nRSikRzNrKzsUfLoat"
CURVE = "zYm8oYadcdGes4jPRU4h2tcg4cjNVExYiyQnJParuBN"
CPMM_POOL = "9f13JFmgNwusTQmY86S7EA1aG4qULw39UgGN19wenCex"
VAULT_0 = "9W1jk3Xp24MmwagZ7wqkFjf9Dt7d2yjQH9xZULmbSSai"
VAULT_1 = "DtiEPPzwXSF8cXTEmxDsjwhQotfzGzx6UaveL9ozwiuW"
OWNER = "7fMwZddcRnuwWsZQT5Eg9cqa9of516sgBZQruH1pj5b8"


def _account(name: str) -> dict[str, Any]:
    entry = ACCOUNTS[name]
    return {"owner": entry["owner"], "data": entry["data"]}


def token_account(owner: str, amount: int) -> dict[str, Any]:
    raw = bytes(32) + base58.b58decode(owner) + struct.pack("<Q", amount) + bytes(93)
    return {"owner": "Tokenkeg", "data": [base64.b64encode(raw).decode(), "base64"]}


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeSource:
    """Accounts by address, transactions by signature, holders by mint."""

    def __init__(self) -> None:
        self.accounts: dict[str, Any] = {
            CURVE: _account("launch_pool"),
            COIN: _account("mint"),
            CPMM_POOL: _account("cpmm_pool"),
            fe.FLOAT_CONFIG: _account("float_config"),
            fe.FLOAT_PLATFORMS[0]: _account("platform"),
            VAULT_0: token_account(OWNER, 400),
            VAULT_1: token_account(OWNER, 900),
        }
        self.transactions: dict[str, Any] = {}
        self.holders: dict[str, list[tuple[str, int]]] = {}
        self.fail: Exception | None = None
        self.reads: list[list[str]] = []

    async def get_accounts(self, addresses: Any) -> list[Any]:
        self.reads.append(list(addresses))
        if self.fail is not None:
            raise self.fail
        return [self.accounts.get(address) for address in addresses]

    async def get_transaction(self, signature: str) -> Any:
        if self.fail is not None:
            raise self.fail
        answer = self.transactions.get(signature)
        if isinstance(answer, list):
            return answer.pop(0)
        return answer

    async def largest_accounts(self, mint: str) -> list[tuple[str, int]]:
        return list(self.holders.get(mint, []))


class FakeSocket:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.error = error

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(message)


def _watcher(
    **settings: Any,
) -> tuple[FloatWatcher, FakeSource, list[dict[str, Any]], Clock, FloatFeed]:
    rows: list[dict[str, Any]] = []
    clock = Clock()
    source = FakeSource()
    float_settings = FloatSettings(enabled=True, **settings)
    watcher = FloatWatcher(
        settings=float_settings, source=source, record=rows.append, clock=clock
    )
    feed = FloatFeed(
        connect_url=lambda: "wss://rpc.example/?api-key=SECRET",
        stream_url="wss://rpc.example",
        settings=float_settings,
        on_logs=watcher.on_logs,
        clock=clock,
    )
    watcher.feed = feed
    return watcher, source, rows, clock, feed


async def _settle(watcher: FloatWatcher) -> None:
    while watcher._tasks:
        await asyncio.gather(*list(watcher._tasks))


def _of(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["event"] == event]


# -- the source --------------------------------------------------------------------
class FakeClient:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[Any] = []

    async def _get_accounts(self, addresses: list[str], *, timeout_seconds: float):
        self.calls.append(("accounts", addresses, timeout_seconds))
        return [None for _ in addresses]

    async def _request_rpc_json(self, payload: dict, *, timeout_seconds: float):
        self.calls.append(("rpc", payload["method"], payload["params"][1]))
        return self.answer

    async def get_token_largest_accounts(self, mint: str, *, timeout_seconds: float):
        return [("Account", 5)]


async def test_the_rpc_source_reads_through_the_sdk_client() -> None:
    client = FakeClient({"result": {"slot": 1}})
    source = RpcFloatSource(client, timeout_seconds=3.0)
    assert await source.get_accounts(["A"]) == [None]
    assert await source.get_transaction("Sig") == {"slot": 1}
    assert client.calls[1][2]["maxSupportedTransactionVersion"] == 1
    assert await source.largest_accounts(COIN) == [("Account", 5)]
    client.answer = {"result": None}
    assert await source.get_transaction("Sig") is None
    client.answer = {"error": {"code": -32000}}
    with pytest.raises(RuntimeError, match="getTransaction error"):
        await source.get_transaction("Sig")


def test_a_token_accounts_owner_and_amount() -> None:
    assert token_owner_and_amount(token_account(OWNER, 7)) == (OWNER, 7)
    assert token_owner_and_amount(None) == (None, None)
    assert token_owner_and_amount({"data": [base64.b64encode(b"x").decode()]}) == (
        None,
        None,
    )


# -- the stream --------------------------------------------------------------------
def _notification(subscription: int, signature: Any, logs: Any, err: Any = None):
    return {
        "jsonrpc": "2.0",
        "method": LOGS_NOTIFICATION,
        "params": {
            "subscription": subscription,
            "result": {
                "context": {"slot": 467_000_000},
                "value": {"signature": signature, "err": err, "logs": logs},
            },
        },
    }


async def test_the_feed_subscribes_its_mentions_and_hands_on_the_logs() -> None:
    seen: list[tuple[Any, ...]] = []
    messages: list[int] = []
    feed = FloatFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: seen.append(args),
        on_message=lambda: messages.append(1),
    )
    assert feed.mention(fe.FLOAT_PROGRAM_ID, "program")
    assert not feed.mention(fe.FLOAT_PROGRAM_ID, "program")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    (request,) = ws.sent
    assert request["method"] == "logsSubscribe"
    assert request["params"] == [
        {"mentions": [fe.FLOAT_PROGRAM_ID]},
        {"commitment": "confirmed"},
    ]
    await feed.on_stream_message({"id": request["id"], "result": 5}, ws)
    await feed.on_stream_message(_notification(5, "Sig", ["Program log: x"]), ws)
    assert seen == [("Sig", 467_000_000, None, ["Program log: x"])]
    assert messages == [1]
    await feed.on_stream_message(_notification(5, None, []), ws)
    await feed.on_stream_message(_notification(5, "Sig", "not a list"), ws)
    await feed.on_stream_message({"method": LOGS_NOTIFICATION}, ws)
    await feed.on_stream_message("not a dict", ws)
    await feed.on_stream_message({"method": "slotNotification"}, ws)
    await feed.on_stream_message({"id": 999, "result": 1}, ws)
    await feed.on_stream_message({"id": "x", "result": 1}, ws)
    assert feed.stats["malformed_notifications"] == 3
    assert feed.stats["subscribed"] == 1 and feed.stats["mentions_program"] == 1


async def test_a_mention_ends_at_its_time_and_a_reconnect_resubscribes() -> None:
    clock = Clock()
    feed = FloatFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: None,
        clock=clock,
    )
    feed.mention("Pool", "cpmm", until=1_100.0)
    feed.mention("Forever", "program")
    await feed.flush()  # not connected: kept
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    ids = {m["params"][0]["mentions"][0]: m["id"] for m in ws.sent}
    await feed.on_stream_message({"id": ids["Pool"], "result": 7}, ws)
    await feed.on_stream_message(_notification(7, "S", []), ws)  # no on_message
    await feed.on_stream_message({"id": ids["Forever"], "error": {"code": 1}}, ws)
    clock.now = 1_100.0
    await feed.flush()
    assert ws.sent[-1]["method"] == "logsUnsubscribe" and ws.sent[-1]["params"] == [7]
    assert list(feed.mentions) == ["Forever"] and feed.stats["mentions_ended"] == 1
    assert feed.stats["subscribe_refused"] == 1
    feed.forget("Unknown")
    feed.on_stream_ended()
    again = FakeSocket()
    await feed.on_stream_connected(again)
    assert [m["params"][0]["mentions"] for m in again.sent] == [["Forever"]]


async def test_a_reply_for_a_mention_already_gone_is_refused() -> None:
    feed = FloatFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: None,
    )
    feed.mention("Pool", "cpmm")
    ws = FakeSocket()
    await feed.on_stream_connected(ws)
    feed.forget("Pool")
    await feed.on_stream_message({"id": ws.sent[0]["id"], "result": 3}, ws)
    assert feed.stats["subscribe_refused"] == 1
    feed.mention("Gone", "cpmm")
    feed.mentions.pop("Gone")
    await feed.flush()
    assert len(ws.sent) == 1  # a queued mention that left is not sent


async def test_a_failed_send_stays_queued() -> None:
    feed = FloatFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: None,
    )
    feed.mention("Pool", "cpmm")
    feed.ws = FakeSocket(error=ConnectionResetError("closing"))
    with pytest.raises(ConnectionResetError):
        await feed.flush()
    assert feed._queued == ["Pool"]
    feed._ending.append(9)
    with pytest.raises(ConnectionResetError):
        await feed.flush()
    assert feed._ending == [9]


def test_the_stream_hooks_report_state_and_redact(caplog) -> None:
    states: list[tuple[bool, str]] = []
    feed = FloatFeed(
        connect_url=lambda: "wss://x/?api-key=SECRET",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: None,
        on_state=lambda connected, detail: states.append((connected, detail)),
    )
    assert feed.stream_connect_url().endswith("SECRET")
    with caplog.at_level(logging.INFO, logger="trading_pump.float_capture"):
        feed.on_stream_error("No WebSocket message for 600s")
        feed.on_stream_exception(RuntimeError("wss://x/?api-key=SECRET refused"), 1.0)
        feed.connected = True
        feed.on_stream_closed()
        feed.on_stream_closed()
        feed.stream_log("hello")
    assert "SECRET" not in caplog.text and "SECRET" not in states[1][1]
    assert [connected for connected, _ in states] == [False, False, False]
    assert not feed.stream_stop_requested()
    feed.stop()
    assert feed.stream_stop_requested()


async def test_the_feed_runs_the_shared_websocket_loop(monkeypatch) -> None:
    feed = FloatFeed(
        connect_url=lambda: "wss://x",
        stream_url="wss://x",
        settings=FloatSettings(enabled=True),
        on_logs=lambda *args: None,
    )
    ran: list[Any] = []

    async def fake_run(host: Any) -> None:
        ran.append(host)

    monkeypatch.setattr("trading_pump.float_capture.run_websocket_stream", fake_run)
    await feed.run()
    assert ran == [feed]


# -- launches, trades, fee cycles --------------------------------------------------
async def test_a_launch_is_recorded_with_its_curve_and_mint() -> None:
    watcher, source, rows, _, feed = _watcher(trader_lookups_per_second=0)
    watcher.start()
    assert set(feed.mentions) == {fe.FLOAT_PROGRAM_ID, *fe.FLOAT_PLATFORMS}
    await watcher.refresh_platforms()
    watcher.on_logs(
        payloads.LAUNCH_SIGNATURE, payloads.LAUNCH_SLOT, None, payloads.LAUNCH_LOGS
    )
    await _settle(watcher)
    (launch,) = _of(rows, LAUNCH_EVENT)
    assert (launch["pool"], launch["mint"], launch["quote_mint"]) == (CURVE, COIN, SOL)
    assert launch["launcher"] == OWNER and launch["symbol"] == "FI"
    assert (
        launch["name"] == "Finance Inu" and launch["uri_host"] == "float.mypinata.cloud"
    )
    assert launch["curve_total_base_sell"] == 732_500_000_000_000
    assert launch["platform"] == fe.FLOAT_PLATFORMS[0]
    assert launch["fee_bps_a_side"] == 100.0
    assert launch["token_program"] == "spl-token"
    assert launch["mint_authority"] is None and launch["freeze_authority"] is None
    assert launch["signature"] == payloads.LAUNCH_SIGNATURE
    assert len(_of(rows, TRADE_ROW)) == 0  # this launch's logs carry no trade
    assert watcher.stats["launches"] == 1


async def test_a_launch_whose_reads_fail_or_say_nothing_is_still_recorded() -> None:
    watcher, source, rows, _, _ = _watcher()
    source.fail = RuntimeError("rpc down")
    watcher.on_logs("A", 1, None, payloads.LAUNCH_LOGS)
    await _settle(watcher)
    (launch,) = _of(rows, LAUNCH_EVENT)
    assert launch["lookup_error"] == "rpc down" and "platform" not in launch
    source.fail = None
    source.accounts = {}
    watcher.on_logs("B", 1, None, payloads.LAUNCH_LOGS)
    await _settle(watcher)
    second = _of(rows, LAUNCH_EVENT)[1]
    assert "platform" not in second and "token_program" not in second


async def test_a_launch_event_that_does_not_decode_is_counted() -> None:
    watcher, _, rows, _, _ = _watcher()
    bad = base64.b64encode(fe.FLOAT_LAUNCH_EVENT + bytes(10)).decode()
    watcher.on_logs(
        "Sig",
        1,
        None,
        [f"Program {fe.FLOAT_PROGRAM_ID} invoke [1]", f"Program data: {bad}"],
    )
    await _settle(watcher)
    assert rows == [] and watcher.stats["undecoded_launches"] == 1


async def test_trades_are_rows_and_their_signers_are_looked_up_with_retries() -> None:
    watcher, source, rows, _, _ = _watcher()
    signer_tx = {
        "blockTime": 1_794_000_000,
        "transaction": {
            "message": {"header": {"numRequiredSignatures": 1}, "accountKeys": [OWNER]}
        },
    }
    source.transactions[payloads.BUY_SIGNATURE] = [None, signer_tx]
    watcher.on_logs(payloads.BUY_SIGNATURE, payloads.BUY_SLOT, None, payloads.BUY_LOGS)
    watcher.on_logs(payloads.BUY_SIGNATURE, payloads.BUY_SLOT, None, payloads.BUY_LOGS)
    (trade,) = _of(rows, TRADE_ROW)
    assert (trade["pool"], trade["side"], trade["slot"]) == (
        CURVE,
        "buy",
        payloads.BUY_SLOT,
    )
    assert trade["amount_in"] > 0 and trade["timestamp"] == 1_000.0
    assert watcher.stats["duplicates"] == 1
    assert await watcher.lookup_traders(5) == 2  # not served, then served
    (trader,) = _of(rows, TRADER_ROW)
    assert trader["fee_payer"] == OWNER and trader["block_time"] == 1_794_000_000
    assert trader["venue"] == "curve" and watcher.stats["trader_lookups_retried"] == 1


async def test_a_lookup_never_served_or_failing_is_counted() -> None:
    watcher, source, rows, _, _ = _watcher()
    watcher.on_logs("S1", 1, None, payloads.SELL_LOGS)
    assert await watcher.lookup_traders(10) == 3
    (trader,) = _of(rows, TRADER_ROW)
    assert trader["fee_payer"] is None and trader["signers"] == []
    source.fail = RuntimeError("timeout")
    watcher.on_logs("S2", 1, None, payloads.SELL_LOGS)
    assert await watcher.lookup_traders(10) == 1
    assert watcher.stats["trader_lookup_errors"] == 1


def test_the_lookup_queue_has_a_cap_and_can_be_off() -> None:
    watcher, *_ = _watcher(max_queued_lookups=1)
    watcher.on_logs("S1", 1, None, payloads.SELL_LOGS)
    watcher.on_logs("S2", 1, None, payloads.SELL_LOGS)
    assert len(watcher._traders) == 1 and watcher.stats["trader_lookups_dropped"] == 1
    off, *_ = _watcher(trader_lookups_per_second=0)
    off.on_logs("S1", 1, None, payloads.SELL_LOGS)
    assert len(off._traders) == 0


def test_failed_truncated_and_undecodable_transactions() -> None:
    watcher, _, rows, _, _ = _watcher()
    watcher.on_logs("F", 1, {"InstructionError": [0, "x"]}, payloads.BUY_LOGS)
    bad = base64.b64encode(fe.TRADE_EVENT + bytes(5)).decode()
    watcher.on_logs(
        "T",
        1,
        None,
        [
            f"Program {fe.LAUNCHLAB_PROGRAM_ID} invoke [1]",
            f"Program data: {bad}",
            "Log truncated",
        ],
    )
    assert rows == []
    assert watcher.stats["failed_transactions"] == 1
    assert watcher.stats["truncated_logs"] == 1
    assert watcher.stats["undecoded_trades"] == 1


def test_seen_signatures_are_kept_to_their_cap() -> None:
    watcher, *_ = _watcher(seen_signatures=2)
    for signature in ("A", "B", "C"):
        watcher.on_logs(signature, 1, None, [])
    assert list(watcher._seen) == ["B", "C"]


def test_fee_cycles_keep_their_instructions_and_event_bytes() -> None:
    watcher, _, rows, _, _ = _watcher()
    watcher.on_logs(payloads.CLAIM_SIGNATURE, 5, None, payloads.CLAIM_LOGS)
    (cycle,) = _of(rows, FEE_CYCLE_ROW)
    assert cycle["instructions"] == ["ClaimCoinFees", "Harvest"]
    assert [event["discriminator"] for event in cycle["events"]] == [
        "779681b76ac3418b",
        "db61a270881945a8",
    ]
    assert base64.b64decode(cycle["events"][0]["data"])[:8].hex() == "779681b76ac3418b"


# -- migrations and graduates ------------------------------------------------------
MIGRATE_LOGS = [
    f"Program {fe.LAUNCHLAB_PROGRAM_ID} invoke [1]",
    "Program log: Instruction: MigrateToCpswap",
    f"Program {fe.LAUNCHLAB_PROGRAM_ID} success",
]


async def _migrate(watcher: FloatWatcher, source: FakeSource) -> None:
    signature = payloads.MIGRATION_TX["transaction"]["signatures"][0]
    source.transactions[signature] = payloads.MIGRATION_TX
    source.holders[COIN] = [(VAULT_1, 267_500_000_000_000), ("Holder1", 10)]
    source.accounts["Holder1"] = token_account(OWNER, 10)
    watcher.on_logs(signature, 466_177_688, None, MIGRATE_LOGS)
    await _settle(watcher)


async def test_a_migration_records_the_curve_cpmm_pool_and_holders_and_follows_it() -> (
    None
):
    watcher, source, rows, clock, feed = _watcher()
    await _migrate(watcher, source)
    (migration,) = _of(rows, MIGRATION_ROW)
    assert (migration["pool"], migration["mint"], migration["cpmm_pool"]) == (
        CURVE,
        COIN,
        CPMM_POOL,
    )
    assert migration["curve"]["real_quote"] == 395_623_386_925
    assert migration["holders"] == [
        {
            "account": VAULT_1,
            "owner": OWNER,
            "amount": 267_500_000_000_000,
            "pool": True,
        },
        {"account": "Holder1", "owner": OWNER, "amount": 10, "pool": False},
    ]
    assert migration["followed"] and migration["block_time"] == 1_793_982_718
    assert feed.mentions[CPMM_POOL].until == 1_000.0 + 7_200.0
    graduate = watcher.graduates[COIN]
    assert (graduate.vault_0, graduate.vault_1) == (VAULT_0, VAULT_1)

    watcher.on_logs(payloads.CPMM_SWAP_SIGNATURE, 9, None, payloads.CPMM_SWAP_LOGS)
    (swap,) = _of(rows, CPMM_TRADE_ROW)
    assert swap["mint"] == COIN and swap["output_amount"] == 6_693_865
    assert watcher._traders[-1][1] == "cpmm"

    assert await watcher.read_pools() == 1
    (reading,) = _of(rows, READING_ROW)
    pool = fe.decode_cpmm_pool(_account("cpmm_pool"))
    assert pool is not None
    assert reading["vault_0_amount"] == 400 and reading["vault_1_amount"] == 900
    assert reading["reserve_0"] == 400 - pool.held_fees_0
    assert reading["mint_0"] == SOL
    clock.now += 1_800.0
    assert await watcher.read_pools() == 0  # readings over, logs still followed
    clock.now += 5_400.0
    await watcher.read_pools()
    assert watcher.graduates == {} and watcher.stats["graduates_ended"] == 1
    assert "migrations" in watcher.stats


async def test_a_reading_of_missing_accounts_and_a_failed_read() -> None:
    watcher, source, rows, _, _ = _watcher()
    await _migrate(watcher, source)
    source.accounts.pop(CPMM_POOL)
    await watcher.read_pools()
    reading = _of(rows, READING_ROW)[-1]
    assert reading["held_fees_0"] is None and reading["reserve_0"] is None
    source.fail = RuntimeError("down")
    await watcher.read_pools()
    assert watcher.stats["reading_errors"] == 1


async def test_a_swap_on_a_pool_not_followed_is_skipped() -> None:
    watcher, _, rows, _, _ = _watcher()
    watcher.on_logs(payloads.CPMM_SWAP_SIGNATURE, 9, None, payloads.CPMM_SWAP_LOGS)
    bad = base64.b64encode(fe.CPMM_SWAP_EVENT + bytes(3)).decode()
    watcher.on_logs(
        "X",
        9,
        None,
        [f"Program {fe.CPMM_PROGRAM_ID} invoke [1]", f"Program data: {bad}"],
    )
    assert _of(rows, CPMM_TRADE_ROW) == [] and len(watcher._traders) == 0


async def test_migrations_that_cannot_be_read_or_followed() -> None:
    watcher, source, rows, _, _ = _watcher(max_graduates=1)
    watcher.on_logs("NotServed", 1, None, MIGRATE_LOGS)
    await _settle(watcher)
    assert watcher.stats["undecoded_migrations"] == 1
    source.fail = RuntimeError("down")
    watcher.on_logs("Failing", 1, None, MIGRATE_LOGS)
    await _settle(watcher)
    assert watcher.stats["migration_lookup_errors"] == 1
    source.fail = None
    await _migrate(watcher, source)
    watcher.graduates["Other"] = watcher.graduates.pop(COIN)
    watcher._seen.clear()
    await _migrate(watcher, source)
    assert not _of(rows, MIGRATION_ROW)[-1]["followed"]
    assert watcher.stats["graduates_list_full"] == 1


async def test_a_migration_without_holders_or_pool_accounts() -> None:
    watcher, source, rows, _, _ = _watcher()
    signature = payloads.MIGRATION_TX["transaction"]["signatures"][0]
    source.transactions[signature] = payloads.MIGRATION_TX
    source.accounts = {}
    watcher.on_logs(signature, 1, None, MIGRATE_LOGS)
    await _settle(watcher)
    (migration,) = _of(rows, MIGRATION_ROW)
    assert migration["curve"] is None and migration["holders"] == []
    assert not migration["followed"]


async def test_a_watcher_without_a_feed_records_but_subscribes_nothing() -> None:
    watcher, source, rows, _, _ = _watcher()
    watcher.feed = None
    watcher.start()
    await _migrate(watcher, source)
    assert _of(rows, MIGRATION_ROW)[0]["followed"]
    await watcher.refresh_platforms()
    assert watcher.status_text().startswith("disconnected")


# -- the platform list and the periodic work ---------------------------------------
async def test_the_platform_list_is_read_and_a_new_platform_followed() -> None:
    watcher, source, rows, _, feed = _watcher()
    watcher.start()
    raw = bytearray(base64.b64decode(ACCOUNTS["float_config"]["data"][0]))
    raw[106] = 4
    new = base58.b58encode(bytes(range(32))).decode()
    raw[107 + 96 : 107 + 128] = base58.b58decode(new)
    source.accounts[fe.FLOAT_CONFIG] = {
        "owner": fe.FLOAT_PROGRAM_ID,
        "data": [base64.b64encode(raw).decode()],
    }
    await watcher.refresh_platforms()
    assert new in feed.mentions and watcher.stats["platforms_added"] == 1
    (listed,) = _of(rows, PLATFORMS_ROW)
    assert listed["platforms"][fe.FLOAT_PLATFORMS[0]] == 100.0
    assert listed["platforms"][new] is None


async def test_an_unreadable_platform_list_keeps_the_known_one() -> None:
    watcher, source, rows, _, _ = _watcher()
    source.accounts[fe.FLOAT_CONFIG] = None
    await watcher.refresh_platforms()
    assert watcher.stats["platform_list_unreadable"] == 1
    assert set(_of(rows, PLATFORMS_ROW)[0]["platforms"]) == set(fe.FLOAT_PLATFORMS)
    source.fail = RuntimeError("down")
    await watcher.refresh_platforms()
    assert watcher.stats["platform_refresh_errors"] == 1


async def test_run_does_the_periodic_work_until_stopped() -> None:
    watcher, source, rows, clock, feed = _watcher(
        flush_interval_seconds=1.0, trader_lookups_per_second=2.0
    )
    watcher.start()
    watcher.on_logs("S1", 1, None, payloads.SELL_LOGS)
    ws = FakeSocket()
    feed.ws = ws
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)
        clock.now += seconds

    stops = iter([False, False, True])
    await watcher.run(lambda: next(stops), sleep)
    assert pauses == [1.0, 1.0]
    assert _of(rows, PLATFORMS_ROW) and len(ws.sent) == 4
    assert source.reads[0] == [fe.FLOAT_CONFIG]
    assert watcher.stats["trader_lookups_retried"] == 2  # 2 a second, not served


async def test_a_failing_pass_does_not_end_the_loop(monkeypatch) -> None:
    watcher, *_ = _watcher()

    async def broken() -> None:
        raise RuntimeError("bug")

    watcher.refresh_platforms = broken
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("trading_pump.float_capture.asyncio.sleep", fake_sleep)
    stops = iter([False, True])
    await watcher.run(lambda: next(stops))
    assert watcher.stats["loop_errors"] == 1 and slept == [0.5]


async def test_stop_cancels_the_lookups_and_the_status_counts() -> None:
    watcher, source, _, _, feed = _watcher()
    release = asyncio.Event()

    async def slow(addresses: Any) -> list[Any]:
        await release.wait()
        return []

    source.get_accounts = slow
    watcher.on_logs("L", 1, None, payloads.LAUNCH_LOGS)
    assert len(watcher._tasks) == 1
    await watcher.stop()
    assert watcher._tasks == set()
    feed.connected = True
    assert watcher.status_text() == (
        "connected · 1 launches · 0 trades · 0 migrations · 0 graduates followed"
    )


async def test_a_launch_without_launchlabs_event_keeps_floats_fields() -> None:
    watcher, _, rows, _, _ = _watcher()
    records = fe.read_logs(payloads.LAUNCH_LOGS)
    (raw,) = records.data_of(fe.FLOAT_PROGRAM_ID, fe.FLOAT_LAUNCH_EVENT)
    data = base64.b64encode(raw).decode()
    watcher.on_logs(
        "Only",
        1,
        None,
        [f"Program {fe.FLOAT_PROGRAM_ID} invoke [1]", f"Program data: {data}"],
    )
    await _settle(watcher)
    (launch,) = _of(rows, LAUNCH_EVENT)
    assert launch["symbol"] == "FI" and "name" not in launch


async def test_run_without_a_feed() -> None:
    watcher, *_ = _watcher()
    watcher.feed = None

    async def sleep(seconds: float) -> None:
        return None

    stops = iter([False, True])
    await watcher.run(lambda: next(stops), sleep)
    assert "loop_errors" not in watcher.stats
