"""Unit tests for the shared test support code in ``tests/support/``.

``support/`` is not source, so it has no mirrored package; these tests pin
the factories, fakes and payload builders that other tests rely on. The
payload tests round-trip through the real decoder, so a layout drift in
``sdk/pumpfun_execution.py`` fails here first.
"""

from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from trading_pump.config.env import decode_keypair
from trading_pump.sdk import jito as jito_module
from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.sdk.jito import JITO_TIP_ACCOUNTS, JitoBundleStatus, JitoClient
from trading_pump.strategies.filters import ScreeningSettings
from trading_pump.tests.support import constants, payloads
from trading_pump.tests.support.factories import make_screening
from trading_pump.tests.support.fakes import (
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


def test_make_screening_defaults_match_the_settings() -> None:
    assert make_screening() == ScreeningSettings()


def test_make_screening_overrides_win_over_defaults() -> None:
    settings = make_screening(min_holder_count=6, enable_cluster_analysis=False)

    assert settings.min_holder_count == 6
    assert settings.enable_cluster_analysis is False


# --- payloads --------------------------------------------------------------------


def test_bonding_curve_bytes_round_trip_through_sdk_decoder() -> None:
    raw = payloads.bonding_curve_bytes(real_sol_reserves=5, complete=True)

    decoded = PumpFunExecutionClient.decode_bonding_curve_data(raw)

    assert decoded["virtual_token_reserves"] == constants.INITIAL_VIRTUAL_TOKEN_RESERVES
    assert decoded["virtual_sol_reserves"] == constants.INITIAL_VIRTUAL_SOL_RESERVES
    assert decoded["real_token_reserves"] == constants.INITIAL_REAL_TOKEN_RESERVES
    assert decoded["real_sol_reserves"] == 5
    assert decoded["token_total_supply"] == constants.TOKEN_TOTAL_SUPPLY
    assert decoded["complete"] is True


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
