"""Unit tests for Jito Block Engine JSON-RPC client, tip floor calculations, and bundle builder."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from pumpfun_trading.sdk.jito import (
    JITO_TIP_ACCOUNTS,
    JitoBundleStatus,
    JitoClient,
    JitoTipConfig,
    JitoTipFloor,
)

SAMPLE_PAYER_KEYPAIR = Keypair()
SAMPLE_PAYER_PUBKEY = SAMPLE_PAYER_KEYPAIR.pubkey()


def create_dummy_versioned_transaction() -> VersionedTransaction:
    ix = Instruction(
        program_id=Pubkey.from_string("11111111111111111111111111111111"),
        accounts=[],
        data=bytes([0, 1, 2, 3]),
    )
    blockhash = Hash.from_string("11111111111111111111111111111111")
    msg = MessageV0.try_compile(SAMPLE_PAYER_PUBKEY, [ix], [], blockhash)
    sig = SAMPLE_PAYER_KEYPAIR.sign_message(bytes(msg))
    return VersionedTransaction.populate(msg, [sig])


def test_jito_tip_floor_percentiles():
    floor = JitoTipFloor(
        time="2026-10-11T20:00:00Z",
        p25_landed_tip_sol=0.00002,
        p50_landed_tip_sol=0.00006,
        p75_landed_tip_sol=0.00015,
        p95_landed_tip_sol=0.002,
        p99_landed_tip_sol=0.008,
        ema_p50_landed_tip_sol=0.00007,
    )

    assert floor.get_percentile_sol("25th") == 0.00002
    assert floor.get_percentile_sol("p25") == 0.00002
    assert floor.get_percentile_sol("50th") == 0.00006
    assert floor.get_percentile_sol("75th") == 0.00015
    assert floor.get_percentile_sol("95th") == 0.002
    assert floor.get_percentile_sol("99th") == 0.008
    assert floor.get_percentile_sol("ema") == 0.00007
    assert floor.get_percentile_sol("other") == 0.00006  # fallback to 50th

    assert floor.get_percentile_lamports("25th") == 20_000
    assert floor.get_percentile_lamports("50th") == 60_000
    assert floor.get_percentile_lamports("75th") == 150_000
    assert floor.get_percentile_lamports("95th") == 2_000_000
    assert floor.get_percentile_lamports("99th") == 8_000_000


def test_jito_bundle_status_properties():
    landed = JitoBundleStatus(
        bundle_id="b1",
        status="Landed",
        slot=12345,
        confirmation_status="confirmed",
        transactions=["tx1"],
    )
    assert landed.is_landed is True
    assert landed.is_failed is False

    failed = JitoBundleStatus(
        bundle_id="b2",
        status="Failed",
        err={"InstructionError": [0, "Custom"]},
    )
    assert failed.is_landed is False
    assert failed.is_failed is True

    pending = JitoBundleStatus(
        bundle_id="b3",
        status="Pending",
        confirmation_status="processed",
    )
    assert pending.is_landed is False
    assert pending.is_failed is False


def test_jito_client_init_and_wallet_parsing():
    client_kp = JitoClient(wallet=SAMPLE_PAYER_KEYPAIR)
    assert client_kp.wallet == SAMPLE_PAYER_PUBKEY

    client_pk = JitoClient(wallet=SAMPLE_PAYER_PUBKEY)
    assert client_pk.wallet == SAMPLE_PAYER_PUBKEY

    client_str = JitoClient(wallet=str(SAMPLE_PAYER_PUBKEY))
    assert client_str.wallet == SAMPLE_PAYER_PUBKEY

    client_none = JitoClient(wallet=None)
    assert client_none.wallet is None


def test_jito_client_tip_account_rotation():
    client = JitoClient()
    accounts = [client.get_tip_account() for _ in range(len(JITO_TIP_ACCOUNTS) * 2)]

    assert accounts[0] == JITO_TIP_ACCOUNTS[0]
    assert accounts[1] == JITO_TIP_ACCOUNTS[1]
    assert accounts[len(JITO_TIP_ACCOUNTS)] == JITO_TIP_ACCOUNTS[0]

    random_account = client.get_tip_account(random_pick=True)
    assert random_account in JITO_TIP_ACCOUNTS


async def test_jito_client_refresh_tip_accounts():
    client = JitoClient()

    custom_tips = ["TipAccount111111111111111111111111111111111"]
    with patch.object(
        client, "_send_json_rpc", new=AsyncMock(return_value=custom_tips)
    ):
        refreshed = await client.refresh_tip_accounts()
        assert refreshed == custom_tips
        assert client.tip_accounts == custom_tips

    # Error handling fallback
    with patch.object(
        client, "_send_json_rpc", new=AsyncMock(side_effect=RuntimeError("RPC down"))
    ):
        refreshed_err = await client.refresh_tip_accounts()
        assert refreshed_err == custom_tips


async def test_jito_client_fetch_tip_floor_success_and_cache():
    client = JitoClient()

    mock_resp_data = [
        {
            "time": "2026-10-11T20:00:00Z",
            "landed_tips_25th_percentile": 0.000025,
            "landed_tips_50th_percentile": 0.000075,
            "landed_tips_75th_percentile": 0.0002,
            "landed_tips_95th_percentile": 0.0015,
            "landed_tips_99th_percentile": 0.006,
            "ema_landed_tips_50th_percentile": 0.00008,
        }
    ]

    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_resp_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        floor = await client.fetch_tip_floor()
        assert floor.p25_landed_tip_sol == 0.000025
        assert floor.p50_landed_tip_sol == 0.000075
        assert floor.p75_landed_tip_sol == 0.0002
        assert floor.p95_landed_tip_sol == 0.0015

        # Second call within TTL should return cached
        floor_cached = await client.fetch_tip_floor(max_age_seconds=60.0)
        assert floor_cached is floor
        mock_session.get.assert_called_once()


async def test_jito_client_fetch_tip_floor_failure_fallback():
    client = JitoClient()

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=RuntimeError("Network error"))

    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        floor = await client.fetch_tip_floor()
        assert floor.p50_landed_tip_sol == 0.00005  # Default fallback
        assert floor.get_percentile_lamports("50th") == 50_000


def test_jito_client_calculate_tip_lamports():
    config = JitoTipConfig(
        min_tip_lamports=10_000,
        max_tip_lamports=5_000_000,
        default_tip_lamports=100_000,
        tip_percentile="50th",
        tip_pct_of_trade=0.01,  # 1%
        conviction_scaling=True,
    )
    client = JitoClient(config=config)

    floor = JitoTipFloor(
        p25_landed_tip_sol=0.00002,
        p50_landed_tip_sol=0.00005,  # 50,000 lamports
        p75_landed_tip_sol=0.0001,
        p95_landed_tip_sol=0.001,
    )

    # Small trade: 0.001 SOL -> 1% is 10,000 lamports. Base tip = max(50_000, 10_000) = 50_000.
    # Conviction 1.0 -> 50_000.
    tip = client.calculate_tip_lamports(0.001, conviction_score=1.0, tip_floor=floor)
    assert tip == 50_000

    # High conviction 2.0x -> 50_000 * 2.0 = 100_000.
    tip_high = client.calculate_tip_lamports(
        0.001, conviction_score=2.0, tip_floor=floor
    )
    assert tip_high == 100_000

    # Large trade: 1.0 SOL -> 1% is 10,000,000 lamports. Base tip = max(50_000, 10_000_000) = 10_000_000.
    # Max cap is 5_000_000 -> clamped to 5_000_000.
    tip_large = client.calculate_tip_lamports(
        1.0, conviction_score=1.0, tip_floor=floor
    )
    assert tip_large == 5_000_000

    # Minimum clamp test
    config_low = JitoTipConfig(min_tip_lamports=50_000, max_tip_lamports=1_000_000)
    client_low = JitoClient(config=config_low)
    floor_low = JitoTipFloor(p50_landed_tip_sol=0.000005)  # 5,000 lamports
    tip_clamped = client_low.calculate_tip_lamports(
        0.0, conviction_score=0.1, tip_floor=floor_low
    )
    assert tip_clamped == 50_000


def test_jito_client_build_tip_instruction():
    client = JitoClient()

    ix = client.build_tip_instruction(
        payer=SAMPLE_PAYER_PUBKEY,
        tip_lamports=100_000,
        tip_account=JITO_TIP_ACCOUNTS[0],
    )

    assert str(ix.program_id) == "11111111111111111111111111111111"
    assert len(ix.accounts) == 2
    assert ix.accounts[0].pubkey == SAMPLE_PAYER_PUBKEY
    assert ix.accounts[0].is_signer is True
    assert ix.accounts[0].is_writable is True
    assert str(ix.accounts[1].pubkey) == JITO_TIP_ACCOUNTS[0]
    assert ix.accounts[1].is_signer is False
    assert ix.accounts[1].is_writable is True

    # Check data payload: instruction index 2 (4 bytes little endian) + 100_000 u64
    assert ix.data[:4] == bytes([2, 0, 0, 0])
    parsed_lamports = int.from_bytes(ix.data[4:12], byteorder="little")
    assert parsed_lamports == 100_000

    # Negative or zero tip raises ValueError
    with pytest.raises(ValueError):
        client.build_tip_instruction(SAMPLE_PAYER_PUBKEY, 0)


@pytest.mark.regression("BUG-02")
async def test_jito_client_send_bundle_validation():
    client = JitoClient()

    # Empty bundle
    with pytest.raises(ValueError, match="empty"):
        await client.send_bundle([])

    # Over limit bundle (>5 transactions)
    txs = [create_dummy_versioned_transaction() for _ in range(6)]
    with pytest.raises(ValueError, match="at most 5"):
        await client.send_bundle(txs)

    # Invalid transaction type
    with pytest.raises(TypeError, match="Unsupported transaction type"):
        await client.send_bundle([12345])  # type: ignore


async def test_jito_client_send_bundle_success():
    client = JitoClient()
    tx = create_dummy_versioned_transaction()

    mock_resp = {"jsonrpc": "2.0", "result": "bundle_id_12345", "id": 1}

    mock_session = MagicMock()
    mock_post_resp = AsyncMock()
    mock_post_resp.status = 200
    mock_post_resp.text = AsyncMock(return_value=json.dumps(mock_resp))
    mock_post_resp.__aenter__ = AsyncMock(return_value=mock_post_resp)
    mock_post_resp.__aexit__ = AsyncMock(return_value=None)
    mock_session.post = MagicMock(return_value=mock_post_resp)

    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        bundle_id = await client.send_bundle([tx])
        assert bundle_id == "bundle_id_12345"


async def test_jito_client_send_bundle_error_responses():
    client = JitoClient()
    tx = create_dummy_versioned_transaction()

    # HTTP Error
    mock_session = MagicMock()
    mock_post_resp = AsyncMock()
    mock_post_resp.status = 500
    mock_post_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_post_resp.__aenter__ = AsyncMock(return_value=mock_post_resp)
    mock_post_resp.__aexit__ = AsyncMock(return_value=None)
    mock_session.post = MagicMock(return_value=mock_post_resp)

    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await client.send_bundle([tx])

    # JSON-RPC Error
    mock_rpc_err = {
        "jsonrpc": "2.0",
        "error": {"code": -32000, "message": "Simulation failed"},
        "id": 1,
    }
    mock_post_resp.status = 200
    mock_post_resp.text = AsyncMock(return_value=json.dumps(mock_rpc_err))
    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        with pytest.raises(RuntimeError, match="Simulation failed"):
            await client.send_bundle([tx])


async def test_jito_client_get_bundle_statuses():
    client = JitoClient()

    empty_res = await client.get_bundle_statuses([])
    assert empty_res == []

    mock_resp = {
        "jsonrpc": "2.0",
        "result": {
            "context": {"slot": 200},
            "value": [
                {
                    "bundle_id": "bundle_1",
                    "slot": 200,
                    "confirmation_status": "confirmed",
                    "err": None,
                    "transactions": ["sig1"],
                },
                {
                    "bundle_id": "bundle_2",
                    "slot": 201,
                    "confirmation_status": "processed",
                    "err": {"InstructionError": [0, "Custom"]},
                    "transactions": ["sig2"],
                },
            ],
        },
        "id": 1,
    }

    with patch.object(
        client, "_send_json_rpc", new=AsyncMock(return_value=mock_resp["result"])
    ):
        statuses = await client.get_bundle_statuses(["bundle_1", "bundle_2"])
        assert len(statuses) == 2
        assert statuses[0].bundle_id == "bundle_1"
        assert statuses[0].is_landed is True
        assert statuses[1].bundle_id == "bundle_2"
        assert statuses[1].is_failed is True


async def test_jito_client_get_inflight_bundle_statuses():
    client = JitoClient()

    empty_res = await client.get_inflight_bundle_statuses([])
    assert empty_res == []

    mock_resp = {
        "context": {"slot": 300},
        "value": [
            {
                "bundle_id": "bundle_3",
                "status": "Landed",
                "landed_slot": 300,
            }
        ],
    }

    with patch.object(client, "_send_json_rpc", new=AsyncMock(return_value=mock_resp)):
        statuses = await client.get_inflight_bundle_statuses(["bundle_3"])
        assert len(statuses) == 1
        assert statuses[0].bundle_id == "bundle_3"
        assert statuses[0].status == "Landed"
        assert statuses[0].slot == 300


async def test_jito_client_wait_for_bundle_confirmation():
    client = JitoClient()

    landed_status = JitoBundleStatus(
        bundle_id="b_test",
        status="Landed",
        confirmation_status="confirmed",
    )

    with patch.object(
        client, "get_bundle_statuses", new=AsyncMock(return_value=[landed_status])
    ):
        res = await client.wait_for_bundle_confirmation(
            "b_test", timeout_seconds=2.0, poll_interval=0.01
        )
        assert res.is_landed is True

    # Timeout case
    pending_status = JitoBundleStatus(
        bundle_id="b_pending",
        status="Pending",
        confirmation_status="processed",
    )
    with patch.object(
        client, "get_bundle_statuses", new=AsyncMock(return_value=[pending_status])
    ):
        with pytest.raises(TimeoutError):
            await client.wait_for_bundle_confirmation(
                "b_pending", timeout_seconds=0.05, poll_interval=0.01
            )


async def test_jito_client_context_manager_and_close():
    client = JitoClient()
    session = await client._get_session()
    assert not session.closed

    await client.close()
    assert session.closed

    async with JitoClient() as ctx_client:
        s = await ctx_client._get_session()
        assert not s.closed
    assert s.closed


async def test_jito_client_additional_edge_cases():
    client = JitoClient()
    client.tip_accounts = []
    # get_tip_account refills default accounts if empty
    account = client.get_tip_account()
    assert account == JITO_TIP_ACCOUNTS[0]

    # Tip instruction with Pubkey tip_account
    tip_pk = Pubkey.from_string(JITO_TIP_ACCOUNTS[1])
    ix = client.build_tip_instruction(SAMPLE_PAYER_PUBKEY, 50_000, tip_account=tip_pk)
    assert ix.accounts[1].pubkey == tip_pk

    # calculate_tip_lamports with conviction_scaling=False
    client.config.conviction_scaling = False
    tip = client.calculate_tip_lamports(0.01, conviction_score=2.0)
    assert tip == client.config.default_tip_lamports

    # fetch_tip_floor with dict object directly
    mock_dict_resp = {
        "time": "2026-10-11T21:00:00Z",
        "landed_tips_50th_percentile": 0.00008,
    }
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_dict_resp)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_resp)

    client._cached_tip_floor = None
    with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
        floor = await client.fetch_tip_floor()
        assert floor.p50_landed_tip_sol == 0.00008

        # When subsequent fetch errors, returns cached floor
        mock_session.get = MagicMock(side_effect=RuntimeError("Err"))
        floor_after_err = await client.fetch_tip_floor(max_age_seconds=0.0)
        assert floor_after_err is floor

    # get_bundle_statuses and get_inflight_bundle_statuses with non-dict results
    with patch.object(
        client, "_send_json_rpc", new=AsyncMock(return_value="not_a_dict")
    ):
        assert await client.get_bundle_statuses(["id1"]) == []
        assert await client.get_inflight_bundle_statuses(["id1"]) == []

    # wait_for_bundle_confirmation ignoring other bundle ids
    status_other = JitoBundleStatus(bundle_id="other_id", status="Landed")
    status_target = JitoBundleStatus(bundle_id="target_id", status="Landed")
    with patch.object(
        client,
        "get_bundle_statuses",
        new=AsyncMock(return_value=[status_other, status_target]),
    ):
        res = await client.wait_for_bundle_confirmation(
            "target_id", timeout_seconds=1.0
        )
        assert res.bundle_id == "target_id"


@pytest.mark.regression("BUG-53")
def test_jito_confirmed_bundle_with_error_is_failed_not_landed():
    status = JitoBundleStatus(
        bundle_id="b",
        status="Landed",
        confirmation_status="confirmed",
        err={"Err": {"InstructionError": [2, {"Custom": 6002}]}},
    )
    assert status.is_failed and not status.is_landed


@pytest.mark.regression("BUG-53")
def test_jito_ok_null_err_counts_as_landed():
    status = JitoBundleStatus(
        bundle_id="b",
        status="Landed",
        confirmation_status="finalized",
        err={"Ok": None},
    )
    assert status.is_landed and not status.is_failed


@pytest.mark.regression("BUG-53")
async def test_jito_get_bundle_statuses_parses_ok_and_err():
    from pumpfun_trading.sdk.jito import JitoClient

    jito = JitoClient()
    jito._send_json_rpc = AsyncMock(
        return_value={
            "value": [
                {
                    "bundle_id": "a",
                    "confirmation_status": "confirmed",
                    "err": {"Ok": None},
                },
                {
                    "bundle_id": "b",
                    "confirmation_status": "confirmed",
                    "err": {"Err": 1},
                },
            ]
        }
    )
    ok, bad = await jito.get_bundle_statuses(["a", "b"])
    assert ok.status == "Landed" and ok.is_landed
    assert bad.status == "Failed" and not bad.is_landed
    await jito.close()
