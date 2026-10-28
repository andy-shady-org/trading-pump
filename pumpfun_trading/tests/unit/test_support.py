"""Unit tests for the shared test support code in ``tests/support/``.

``support/`` is not source, so it has no mirrored package; these tests pin
the factories, fakes and payload builders that other tests rely on. The
payload tests round-trip through the real parsers, so a layout drift in
``streams/geyser.py`` or ``sdk/execution.py`` fails here first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.config.env import decode_keypair
from pumpfun_trading.sdk import jito as jito_module
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.jito import JITO_TIP_ACCOUNTS, JitoBundleStatus, JitoClient
from pumpfun_trading.sdk.raydium import RAYDIUM_AUTHORITY_V4, SERUM_PROGRAM_ID_V3
from pumpfun_trading.streams.geyser import (
    BondingCurveBinaryParser,
    TradeInstructionBinaryParser,
)
from pumpfun_trading.tests.support import constants, payloads
from pumpfun_trading.tests.support.factories import (
    make_bot,
    make_config,
    make_pool_keys,
    make_position,
)
from pumpfun_trading.tests.support.fakes import (
    FakeAlertSink,
    FakeClock,
    FakeJito,
    FakeRpc,
)

# --- constants -------------------------------------------------------------------


def test_sample_private_key_decodes_to_deterministic_signer() -> None:
    first = decode_keypair(constants.SAMPLE_PRIVATE_KEY)
    second = decode_keypair(constants.SAMPLE_PRIVATE_KEY)

    assert first.pubkey() == second.pubkey()


@pytest.mark.parametrize(
    "mint", [constants.SAMPLE_MINT, constants.SAMPLE_PUMP_MINT, constants.WSOL_MINT]
)
def test_sample_mints_are_valid_pubkeys(mint: str) -> None:
    assert str(Pubkey.from_string(mint)) == mint


# --- factories -------------------------------------------------------------------


def test_make_config_defaults_are_small_and_never_live() -> None:
    config = make_config()

    assert isinstance(config, TradingBotConfig)
    assert config.buy_amount_sol == 0.01
    assert config.dry_run is True


def test_make_config_overrides_win_over_defaults() -> None:
    config = make_config(dry_run=False, max_active_positions=2)

    assert config.dry_run is False
    assert config.max_active_positions == 2
    assert config.buy_amount_sol == 0.01


def test_make_bot_with_tmp_path_writes_state_there(tmp_path: Path) -> None:
    bot = make_bot(tmp_path, max_active_positions=3)

    assert bot.config.max_active_positions == 3
    assert bot.config.dry_run is True
    assert bot.private_key_b58 == constants.SAMPLE_PRIVATE_KEY
    assert Path(str(bot.bot_status_path)) == tmp_path / "status.json"
    assert Path(str(bot.audit_log_path)) == tmp_path / "audit.jsonl"


def test_make_bot_explicit_config_is_used_as_is(tmp_path: Path) -> None:
    config = make_config(buy_amount_sol=0.02)

    bot = make_bot(tmp_path, config=config)

    assert bot.config.buy_amount_sol == 0.02


def test_make_bot_config_and_overrides_together_raises(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="either config"):
        make_bot(tmp_path, config=make_config(), dry_run=False)


def test_make_bot_bot_kwargs_reach_the_constructor(tmp_path: Path) -> None:
    status = tmp_path / "custom.json"

    bot = make_bot(tmp_path, bot_kwargs={"bot_status_path": str(status)})

    assert Path(str(bot.bot_status_path)) == status


def test_make_position_on_bot_opens_a_live_shaped_position(tmp_path: Path) -> None:
    bot = make_bot(tmp_path)

    position = make_position(bot, cost_sol=0.02, name="Tok")

    assert constants.SAMPLE_MINT in bot.position_manager
    assert bot.position_manager[constants.SAMPLE_MINT] is position
    assert position["cost_sol"] == 0.02
    assert position["name"] == "Tok"
    assert position["remaining_token_amount"] == 350_000_000_000


def test_make_position_accepts_a_bare_manager() -> None:
    manager = PositionManager(make_config())

    make_position(manager, constants.WSOL_MINT)

    assert len(manager) == 1
    assert constants.WSOL_MINT in manager


def test_make_pool_keys_unique_accounts_are_distinct_valid_pubkeys() -> None:
    keys = make_pool_keys()
    accounts = [keys.amm_id, keys.amm_open_orders, keys.serum_market, keys.lp_mint]

    assert len(set(accounts)) == len(accounts)
    for account in accounts:
        Pubkey.from_string(account)
    assert keys.amm_authority == RAYDIUM_AUTHORITY_V4
    assert keys.serum_program_id == SERUM_PROGRAM_ID_V3
    assert keys.coin_mint == constants.SAMPLE_MINT
    assert keys.pc_mint == constants.WSOL_MINT


def test_make_pool_keys_shared_default_and_overrides() -> None:
    keys = make_pool_keys(constants.WSOL_MINT, unique=False, lp_mint="Lp")

    assert keys.amm_id == keys.serum_market == str(Pubkey.default())
    assert keys.coin_mint == constants.WSOL_MINT
    assert keys.lp_mint == "Lp"


# --- payloads --------------------------------------------------------------------


def test_bonding_curve_bytes_round_trip_through_geyser_parser() -> None:
    raw = payloads.bonding_curve_bytes(real_sol_reserves=5, complete=True)

    update = BondingCurveBinaryParser.parse_account_data(raw, mint="M")

    assert update.virtual_token_reserves == constants.INITIAL_VIRTUAL_TOKEN_RESERVES
    assert update.virtual_sol_reserves == constants.INITIAL_VIRTUAL_SOL_RESERVES
    assert update.real_token_reserves == constants.INITIAL_REAL_TOKEN_RESERVES
    assert update.real_sol_reserves == 5
    assert update.token_total_supply == constants.TOKEN_TOTAL_SUPPLY
    assert update.complete is True


def test_bonding_curve_bytes_creator_lands_where_sdk_reads_it() -> None:
    creator = str(Pubkey.new_unique())
    raw = payloads.bonding_curve_bytes(creator=creator)

    decoded = PumpFunExecutionClient.decode_bonding_curve_data(raw)

    assert len(raw) == 81
    assert decoded["creator"] == creator
    assert decoded["virtual_sol_reserves"] == constants.INITIAL_VIRTUAL_SOL_RESERVES


def test_account_data_b64_matches_rpc_shape() -> None:
    raw = payloads.bonding_curve_bytes()

    data, encoding = payloads.account_data_b64(raw)

    assert encoding == "base64"
    assert payloads.base64.b64decode(data) == raw


@pytest.mark.parametrize("is_buy", [True, False])
def test_trade_event_bytes_round_trip_through_parser(is_buy: bool) -> None:
    user = str(Pubkey.new_unique())
    raw = payloads.trade_event_bytes(is_buy=is_buy, user=user, sol_amount=7)

    event = TradeInstructionBinaryParser.parse_trade_event_buffer(raw)

    assert event is not None
    assert event.mint == constants.SAMPLE_MINT
    assert event.user == user
    assert event.is_buy is is_buy
    assert event.sol_amount_lamports == 7
    assert event.timestamp == payloads.SAMPLE_TIMESTAMP


def test_complete_event_bytes_round_trip_through_parser() -> None:
    raw = payloads.complete_event_bytes(mint=constants.SAMPLE_PUMP_MINT)

    event = TradeInstructionBinaryParser.parse_complete_event_buffer(raw)

    assert event is not None
    assert event.mint == constants.SAMPLE_PUMP_MINT


def test_buy_and_sell_instruction_bytes_round_trip() -> None:
    buy = TradeInstructionBinaryParser.parse_buy_instruction(
        payloads.buy_instruction_bytes(10, 20)
    )
    sell = TradeInstructionBinaryParser.parse_sell_instruction(
        payloads.sell_instruction_bytes(30, 40)
    )

    assert buy == {"amount": 10, "max_sol_cost": 20}
    assert sell == {"amount": 30, "min_sol_output": 40}


# --- FakeClock -------------------------------------------------------------------


def test_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock(start=100.0)

    clock.sleep(2.5)
    clock.advance(1.0)

    assert clock.time() == clock.monotonic() == clock.perf_counter() == 103.5
    assert clock.sleeps == [2.5]


def test_fake_clock_refuses_to_go_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        FakeClock().advance(-1)


async def test_fake_clock_async_sleep_returns_result_without_waiting() -> None:
    clock = FakeClock(start=0.0)

    assert await clock.async_sleep(3600, result="done") == "done"
    assert clock.now == 3600


async def test_fake_clock_install_runs_a_polling_timeout_instantly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 12 s Jito confirmation poll times out on the fake clock, not in real time."""
    import asyncio

    clock = FakeClock(start=0.0)
    clock.install(monkeypatch, jito_module)
    clock.install_async_sleep(monkeypatch, jito_module)
    client = JitoClient(wallet=str(Pubkey.new_unique()))

    async def pending(_ids: list[str]) -> list[JitoBundleStatus]:
        return [JitoBundleStatus(bundle_id="b", status="Pending")]

    monkeypatch.setattr(client, "get_bundle_statuses", pending)

    with pytest.raises(TimeoutError):
        await client.wait_for_bundle_confirmation(
            "b", timeout_seconds=12.0, poll_interval=0.5
        )

    assert clock.now >= 12.0
    assert len(clock.sleeps) == 24
    assert asyncio.sleep is not clock.async_sleep


# --- FakeRpc ---------------------------------------------------------------------


async def test_fake_rpc_wraps_values_and_queues_answers() -> None:
    rpc = FakeRpc().on("getSlot", 1, 2)

    first = await rpc.request({"method": "getSlot", "id": 7})
    second = await rpc.request({"method": "getSlot"})
    third = await rpc.request({"method": "getSlot"})

    assert first == {"jsonrpc": "2.0", "id": 7, "result": 1}
    assert [second["result"], third["result"]] == [2, 2]
    assert rpc.methods_called() == ["getSlot"] * 3


async def test_fake_rpc_raises_exceptions_and_calls_responders() -> None:
    rpc = FakeRpc()
    rpc.on("getBalance", RuntimeError("HTTP 429"))
    rpc.on("echo", lambda payload: {"error": payload["params"]})

    with pytest.raises(RuntimeError, match="429"):
        await rpc.request({"method": "getBalance"})
    assert await rpc.request({"method": "echo", "params": [1]}) == {"error": [1]}


async def test_fake_rpc_unregistered_method_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="getHealth"):
        await FakeRpc().request({"method": "getHealth"})


def test_fake_rpc_on_without_answers_raises() -> None:
    with pytest.raises(ValueError):
        FakeRpc().on("getSlot")


async def test_fake_rpc_drives_execution_client_lookup() -> None:
    client = PumpFunExecutionClient(constants.SAMPLE_PRIVATE_KEY)
    rpc = FakeRpc().on(
        "getTokenLargestAccounts",
        {"value": [{"address": "A", "amount": "5"}, {"address": "B", "amount": "x"}]},
    )
    client.rpc_pool = rpc  # type: ignore[assignment]

    accounts = await client.get_token_largest_accounts(constants.SAMPLE_MINT)
    signature = await rpc.broadcast_transaction("dHg=")
    await rpc.close()

    assert accounts == [("A", 5)]
    assert rpc.calls[0]["params"][0] == constants.SAMPLE_MINT
    assert signature == rpc.broadcast_signature
    assert rpc.broadcasts == ["dHg="]
    assert rpc.closed is True
    assert rpc.endpoint_count == 1
    assert rpc.get_telemetry()["healthy_endpoints"] == 1
    await rpc.start_health_loop()
    await rpc.stop()


# --- FakeJito / FakeAlertSink ----------------------------------------------------


async def test_fake_jito_records_bundles_and_reports_status() -> None:
    jito = FakeJito(status="Failed")

    bundle_id = await jito.send_bundle(["tx1", "tx2"])
    status = await jito.wait_for_bundle_confirmation(bundle_id, timeout_seconds=1)
    floor = await jito.fetch_tip_floor()
    await jito.close()

    assert jito.bundles == [["tx1", "tx2"]]
    assert status.is_failed and not status.is_landed
    assert jito.get_tip_account() == JITO_TIP_ACCOUNTS[0]
    assert jito.calculate_tip_lamports(0.01, tip_floor=floor) == 100_000
    assert jito.closed is True


async def test_fake_jito_default_status_lands() -> None:
    status = await FakeJito().wait_for_bundle_confirmation("b")

    assert status.is_landed


async def test_fake_alert_sink_keeps_messages_unless_disabled() -> None:
    sink = FakeAlertSink()
    muted = FakeAlertSink(enabled=False)

    assert sink.send_alert("one") is True
    assert await sink.send_alert_async("two") is True
    assert muted.send_alert("dropped") is False
    assert sink.messages == ["one", "two"]
    assert muted.messages == []
