"""Unit tests for Yellowstone Geyser streaming client and binary parsers."""

import asyncio
import base64
import struct

import base58
import pytest

from pumpfun_trading.streams.geyser import (
    BUY_DISCRIMINATOR,
    COMPLETE_EVENT_DISCRIMINATOR,
    CREATE_DISCRIMINATOR,
    PUMP_PROGRAM_ID,
    SELL_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
    BondingCurveBinaryParser,
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    GeyserAccountUpdate,
    GeyserConnectionState,
    GeyserStreamMetrics,
    GeyserSubscriptionFilter,
    GeyserTransactionUpdate,
    GeyserTransportUnavailableError,
    TradeEventUpdate,
    TradeInstructionBinaryParser,
    YellowstoneGeyserClient,
)


def _build_mock_bonding_curve_bytes(
    virtual_tokens: int = 1_073_000_000_000_000,
    virtual_sol: int = 30_000_000_000,
    real_tokens: int = 793_100_000_000_000,
    real_sol: int = 0,
    total_supply: int = 1_000_000_000_000_000,
    complete: bool = False,
) -> bytes:
    discriminator = bytes([23, 108, 143, 219, 112, 126, 121, 100])
    payload = struct.pack(
        "<QQQQQ?",
        virtual_tokens,
        virtual_sol,
        real_tokens,
        real_sol,
        total_supply,
        complete,
    )
    return discriminator + payload


def _build_mock_trade_event_bytes(
    mint_b58: str = "SoL1111111111111111111111111111111111111111",
    sol_amount: int = 1_000_000_000,
    token_amount: int = 35_000_000_000_000,
    is_buy: bool = True,
    user_b58: str = "UsEr111111111111111111111111111111111111111",
    timestamp: int = 1728600000,
    v_sol: int = 31_000_000_000,
    v_tokens: int = 1_038_000_000_000_000,
    r_sol: int = 1_000_000_000,
    r_tokens: int = 758_100_000_000_000,
) -> bytes:
    mint_bytes = base58.b58decode(mint_b58)
    if len(mint_bytes) < 32:
        mint_bytes = mint_bytes.ljust(32, b"\x00")
    user_bytes = base58.b58decode(user_b58)
    if len(user_bytes) < 32:
        user_bytes = user_bytes.ljust(32, b"\x00")

    payload = struct.pack(
        "<32sQQ?32sqQQQQ",
        mint_bytes[:32],
        sol_amount,
        token_amount,
        is_buy,
        user_bytes[:32],
        timestamp,
        v_sol,
        v_tokens,
        r_sol,
        r_tokens,
    )
    return TRADE_EVENT_DISCRIMINATOR + payload


def _build_mock_complete_event_bytes(
    user_b58: str = "UsEr111111111111111111111111111111111111111",
    mint_b58: str = "SoL1111111111111111111111111111111111111111",
    curve_b58: str = "Curv111111111111111111111111111111111111111",
    timestamp: int = 1728600000,
) -> bytes:
    user_bytes = base58.b58decode(user_b58).ljust(32, b"\x00")[:32]
    mint_bytes = base58.b58decode(mint_b58).ljust(32, b"\x00")[:32]
    curve_bytes = base58.b58decode(curve_b58).ljust(32, b"\x00")[:32]

    payload = struct.pack(
        "<32s32s32sq",
        user_bytes,
        mint_bytes,
        curve_bytes,
        timestamp,
    )
    return COMPLETE_EVENT_DISCRIMINATOR + payload


def test_constants_and_subscription_filter():
    assert len(CREATE_DISCRIMINATOR) == 8
    assert len(BUY_DISCRIMINATOR) == 8
    assert len(SELL_DISCRIMINATOR) == 8
    assert len(TRADE_EVENT_DISCRIMINATOR) == 8
    assert len(COMPLETE_EVENT_DISCRIMINATOR) == 8

    sub_filter = GeyserSubscriptionFilter(programs=[PUMP_PROGRAM_ID])
    assert sub_filter.programs == [PUMP_PROGRAM_ID]
    assert sub_filter.slots is True
    assert sub_filter.accounts == {}
    assert sub_filter.transactions == {}


def test_bonding_curve_binary_parser_success():
    raw = _build_mock_bonding_curve_bytes(
        virtual_tokens=1_000_000_000_000_000,
        virtual_sol=30_000_000_000,
        real_tokens=800_000_000_000_000,
        real_sol=0,
        total_supply=1_000_000_000_000_000,
        complete=False,
    )

    update = BondingCurveBinaryParser.parse_account_data(
        raw,
        mint="Mint111111111111111111111111111111111111111",
        bonding_curve_pubkey="Curve11111111111111111111111111111111111111",
        slot=12345,
    )

    assert isinstance(update, BondingCurveStateUpdate)
    assert update.mint == "Mint111111111111111111111111111111111111111"
    assert update.slot == 12345
    assert update.virtual_token_reserves == 1_000_000_000_000_000
    assert update.virtual_sol_reserves == 30_000_000_000
    assert update.real_token_reserves == 800_000_000_000_000
    assert update.real_sol_reserves == 0
    assert update.token_total_supply == 1_000_000_000_000_000
    assert update.complete is False
    assert update.price_sol == pytest.approx(0.00000003, rel=1e-4)
    assert update.market_cap_sol == pytest.approx(30.0, rel=1e-4)

    d = update.to_dict()
    assert d["virtual_token_reserves"] == 1_000_000_000_000_000
    assert d["price_sol"] == update.price_sol

    # Test parse_raw_reserves
    reserves = BondingCurveBinaryParser.parse_raw_reserves(raw)
    assert reserves == (
        1_000_000_000_000_000,
        30_000_000_000,
        800_000_000_000_000,
        0,
        1_000_000_000_000_000,
        False,
    )


def test_bonding_curve_binary_parser_zero_reserves_and_short_buffer():
    raw_zero = _build_mock_bonding_curve_bytes(virtual_tokens=0, virtual_sol=0)
    update = BondingCurveBinaryParser.parse_account_data(raw_zero)
    assert update.price_sol == 0.0
    assert update.market_cap_sol == 0.0

    with pytest.raises(ValueError, match="too short"):
        BondingCurveBinaryParser.parse_account_data(b"too_short_bytes")

    with pytest.raises(ValueError, match="too short for reserves"):
        BondingCurveBinaryParser.parse_raw_reserves(b"short")


def test_trade_instruction_binary_parser_buy_and_sell():
    buy_bytes = BUY_DISCRIMINATOR + struct.pack("<QQ", 500_000_000, 1_000_000_000)
    buy_parsed = TradeInstructionBinaryParser.parse_buy_instruction(buy_bytes)
    assert buy_parsed["amount"] == 500_000_000
    assert buy_parsed["max_sol_cost"] == 1_000_000_000

    sell_bytes = SELL_DISCRIMINATOR + struct.pack("<QQ", 200_000_000, 800_000_000)
    sell_parsed = TradeInstructionBinaryParser.parse_sell_instruction(sell_bytes)
    assert sell_parsed["amount"] == 200_000_000
    assert sell_parsed["min_sol_output"] == 800_000_000

    with pytest.raises(ValueError, match="Buy instruction data too short"):
        TradeInstructionBinaryParser.parse_buy_instruction(b"short")

    with pytest.raises(ValueError, match="Sell instruction data too short"):
        TradeInstructionBinaryParser.parse_sell_instruction(b"short")


def test_trade_event_binary_parser():
    raw_event = _build_mock_trade_event_bytes(
        sol_amount=2_000_000_000,
        token_amount=50_000_000_000_000,
        is_buy=True,
    )
    event = TradeInstructionBinaryParser.parse_trade_event_buffer(
        raw_event, slot=999, signature="sig_test_123"
    )
    assert isinstance(event, TradeEventUpdate)
    assert event.sol_amount_lamports == 2_000_000_000
    assert event.sol_amount == 2.0
    assert event.token_amount == 50_000_000_000_000
    assert event.is_buy is True
    assert event.slot == 999
    assert event.signature == "sig_test_123"
    assert event.price_sol > 0

    d = event.to_dict()
    assert d["sol_amount"] == 2.0
    assert d["is_buy"] is True

    # Bad discriminator
    bad_disc = bytes([0] * 8) + raw_event[8:]
    assert TradeInstructionBinaryParser.parse_trade_event_buffer(bad_disc) is None

    # Too short
    assert TradeInstructionBinaryParser.parse_trade_event_buffer(b"short") is None


def test_complete_event_binary_parser():
    raw_complete = _build_mock_complete_event_bytes()
    event = TradeInstructionBinaryParser.parse_complete_event_buffer(
        raw_complete, slot=1001, signature="sig_complete"
    )
    assert isinstance(event, CompleteEventUpdate)
    assert event.slot == 1001
    assert event.signature == "sig_complete"

    bad_disc = bytes([0] * 8) + raw_complete[8:]
    assert TradeInstructionBinaryParser.parse_complete_event_buffer(bad_disc) is None
    assert TradeInstructionBinaryParser.parse_complete_event_buffer(b"short") is None


def test_program_log_event_parser():
    raw_trade = _build_mock_trade_event_bytes()
    b64_trade = base64.b64encode(raw_trade).decode("ascii")
    log_trade = f"Program data: {b64_trade}"

    parsed_trade = TradeInstructionBinaryParser.parse_program_log_event(
        log_trade, slot=555
    )
    assert isinstance(parsed_trade, TradeEventUpdate)
    assert parsed_trade.slot == 555

    raw_comp = _build_mock_complete_event_bytes()
    b64_comp = base64.b64encode(raw_comp).decode("ascii")
    log_comp = f"Program data: {b64_comp}"

    parsed_comp = TradeInstructionBinaryParser.parse_program_log_event(
        log_comp, slot=556
    )
    assert isinstance(parsed_comp, CompleteEventUpdate)
    assert parsed_comp.slot == 556

    # Non-matching logs
    assert (
        TradeInstructionBinaryParser.parse_program_log_event(
            "Program log: instruction buy"
        )
        is None
    )
    assert (
        TradeInstructionBinaryParser.parse_program_log_event(
            "Program data: !!!invalid_base64!!!"
        )
        is None
    )
    assert (
        TradeInstructionBinaryParser.parse_program_log_event("Program data: AAA=")
        is None
    )


def test_geyser_stream_metrics():
    metrics = GeyserStreamMetrics()
    assert metrics.average_latency_ms == 0.0

    metrics.record_received()
    assert metrics.messages_received == 1

    metrics.record_processed(1.5, slot=100)
    metrics.record_processed(2.5, slot=105)
    assert metrics.messages_processed == 2
    assert metrics.last_slot == 105
    assert metrics.average_latency_ms == 2.0
    assert metrics.peak_processing_latency_ms == 2.5

    metrics.record_drop()
    assert metrics.dropped_messages == 1

    metrics.record_reconnect()
    assert metrics.reconnect_count == 1

    summary = metrics.summary()
    assert summary["messages_received"] == 1
    assert summary["messages_processed"] == 2
    assert summary["dropped_messages"] == 1
    assert summary["reconnect_count"] == 1
    assert summary["last_slot"] == 105
    assert summary["avg_latency_ms"] == 2.0


async def _idle_transport(client_ref):
    while client_ref._running:
        await asyncio.sleep(0.02)


@pytest.mark.regression("BUG-55")
async def test_geyser_client_lifecycle_and_dispatch():
    client = YellowstoneGeyserClient(
        endpoint="mock.geyser.rpc:443",
        keepalive_interval=0.1,
        max_queue_size=10,
        custom_transport=_idle_transport,
    )

    received_bonding: list[BondingCurveStateUpdate] = []
    received_trades: list[TradeEventUpdate] = []
    received_completes: list[CompleteEventUpdate] = []
    received_accounts: list[GeyserAccountUpdate] = []
    received_txs: list[GeyserTransactionUpdate] = []

    client.on_bonding_curve(lambda update: received_bonding.append(update))
    client.on_trade(lambda update: received_trades.append(update))
    client.on_complete(lambda update: received_completes.append(update))
    client.on_account(lambda update: received_accounts.append(update))
    client.on_transaction(lambda update: received_txs.append(update))

    client.subscribe_bonding_curves(["CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"])
    client.subscribe_transactions(["Wallet1111111111111111111111111111111111111"])

    # Subscriptions target the bonding-curve PDA, not the mint (BUG-55).
    curve = client.bonding_curve_address("CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump")
    assert client.filter.accounts["pump_curves"] == [curve]
    assert (
        "Wallet1111111111111111111111111111111111111"
        in client.filter.transactions["pump_txs"]
    )

    await client.start()
    assert client.state in (
        GeyserConnectionState.CONNECTING,
        GeyserConnectionState.CONNECTED,
    )

    # Let keepalive trigger once
    await asyncio.sleep(0.15)

    # Dispatch account update (Pump.fun curve)
    raw_curve = _build_mock_bonding_curve_bytes()
    b_update = await client.dispatch_raw_account(
        pubkey="CurvePubkey1111111111111111111111111111111",
        owner=PUMP_PROGRAM_ID,
        lamports=2_000_000,
        data=raw_curve,
        slot=1000,
        mint="Mint11111111111111111111111111111111111111",
    )
    assert b_update is not None
    assert len(received_bonding) == 1
    assert len(received_accounts) == 1

    # Dispatch account update (non-pump owner)
    non_pump = await client.dispatch_raw_account(
        pubkey="OtherPubkey111111111111111111111111111111",
        owner="OtherProgram111111111111111111111111111111",
        lamports=1_000_000,
        data=b"other_data",
        slot=1001,
    )
    assert non_pump is None
    assert len(received_accounts) == 2

    # Dispatch transaction with trade and complete logs
    raw_trade = _build_mock_trade_event_bytes()
    raw_comp = _build_mock_complete_event_bytes()
    logs = [
        f"Program data: {base64.b64encode(raw_trade).decode('ascii')}",
        f"Program data: {base64.b64encode(raw_comp).decode('ascii')}",
    ]

    events = await client.dispatch_raw_transaction(
        signature="tx_sig_123",
        slot=1002,
        logs=logs,
    )
    assert len(events) == 2
    assert len(received_trades) == 1
    assert len(received_completes) == 1
    assert len(received_txs) == 1

    # Stop client
    await client.stop()
    assert client.state == GeyserConnectionState.CLOSED


async def test_geyser_client_queue_overflow_and_async_callback_error():
    client = YellowstoneGeyserClient(
        endpoint="mock.geyser.rpc:443",
        keepalive_interval=0.0,
        max_queue_size=2,
    )

    # Async callback that throws error
    async def failing_callback(event):
        raise RuntimeError("Callback crash test")

    client.on_account(failing_callback)

    # Fill queue past capacity
    await client.dispatch_raw_account("pubkey1", "owner1", 100, b"data1", 1)
    await client.dispatch_raw_account("pubkey2", "owner2", 100, b"data2", 2)
    await client.dispatch_raw_account("pubkey3", "owner3", 100, b"data3", 3)

    assert client.metrics.dropped_messages >= 1


async def test_geyser_client_custom_transport_and_reconnection():
    reconnect_attempts = 0

    async def flaky_transport(client_ref):
        nonlocal reconnect_attempts
        reconnect_attempts += 1
        if reconnect_attempts < 2:
            raise ConnectionResetError("Simulated stream drop")
        await asyncio.sleep(0.05)

    client = YellowstoneGeyserClient(
        endpoint="mock.geyser.rpc:443",
        reconnect_initial_backoff=0.01,
        reconnect_max_backoff=0.05,
        keepalive_interval=0.0,
        custom_transport=flaky_transport,
    )

    await client.start()
    await asyncio.sleep(0.1)
    await client.stop()

    assert client.metrics.reconnect_count >= 1


async def test_geyser_client_listen_generator_and_idempotent_start():
    client = YellowstoneGeyserClient(
        endpoint="mock.geyser.rpc:443",
        keepalive_interval=0.05,
        custom_transport=_idle_transport,
    )

    await client.start()
    # Idempotent start
    await client.start()

    # Enqueue an item
    raw_curve = _build_mock_bonding_curve_bytes()
    await client.dispatch_raw_account(
        pubkey="CurvePubkey1111111111111111111111111111111",
        owner=PUMP_PROGRAM_ID,
        lamports=2_000_000,
        data=raw_curve,
        slot=1000,
    )

    items = []

    async def consumer():
        async for item in client.listen():
            items.append(item)
            if len(items) >= 2:
                break

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await client.stop()
    await consumer_task

    assert len(items) >= 1


def test_trade_event_zero_reserves_pricing():
    event = TradeEventUpdate(
        mint="Mint111111111111111111111111111111111111111",
        sol_amount_lamports=1_000_000_000,
        token_amount=1_000_000,
        is_buy=True,
        user="User111111111111111111111111111111111111111",
        timestamp=100,
        virtual_sol_reserves=0,
        virtual_token_reserves=0,
        real_sol_reserves=0,
        real_token_reserves=0,
    )
    assert event.price_sol == 0.0


async def test_geyser_client_duplicate_subscriptions_and_malformed_curve():
    client = YellowstoneGeyserClient(
        endpoint="mock.geyser.rpc:443",
    )
    # Duplicate subscriptions
    mint_a = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"
    mint_b = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    client.subscribe_bonding_curves([mint_a, mint_b, "not-a-mint"])
    client.subscribe_bonding_curves([mint_a])
    assert client.filter.accounts["pump_curves"] == [
        client.bonding_curve_address(mint_a),
        client.bonding_curve_address(mint_b),
    ]

    # Sync callback exception
    def sync_failing_callback(event):
        raise ValueError("Sync callback test error")

    client.on_bonding_curve(sync_failing_callback)

    # Dispatch malformed bonding curve data (Pump owner, but < 49 bytes)
    result = await client.dispatch_raw_account(
        pubkey="MalformedCurvePubkey",
        owner=PUMP_PROGRAM_ID,
        lamports=1000,
        data=b"too_short",
        slot=500,
    )
    assert result is None


MINT = "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump"


@pytest.mark.regression("BUG-55")
async def test_geyser_without_transport_fails_fast():
    """BUG-55: no transport means a clear error, never a fake CONNECTED state."""
    client = YellowstoneGeyserClient(endpoint="grpc.example:443")
    assert client.has_transport is False
    with pytest.raises(GeyserTransportUnavailableError):
        await client.start()
    assert client.state == GeyserConnectionState.DISCONNECTED

    client.subscribe_bonding_curves([MINT])
    curve = client.bonding_curve_address(MINT)
    assert curve != MINT
    assert client._curve_to_mint[curve] == MINT
