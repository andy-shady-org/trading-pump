"""Tests for the Pump fee program ``FeeConfig`` decoder (`sdk/fee_config.py`, BUG-138)."""

from __future__ import annotations

import base64
import struct
from unittest.mock import AsyncMock

import pytest
from solders.pubkey import Pubkey

from trading_pump.sdk.curve import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RAW,
    TOTAL_TOKEN_SUPPLY_RAW,
)
from trading_pump.sdk.execution_types import PUMP_FEE_PROGRAM_ID
from trading_pump.sdk.fee_config import (
    FEE_CONFIG_DISCRIMINATOR,
    FeeTier,
    Fees,
    bonding_curve_fee_bps,
    curve_market_cap_lamports,
    decode_fee_config,
    select_fee_tier,
)
from trading_pump.sdk.pumpfun_execution import PumpFunCurveMixin

pytestmark = pytest.mark.regression("BUG-138")

ADMIN = Pubkey.from_string(PUMP_FEE_PROGRAM_ID)
LAMPORTS = 1_000_000_000


def _fees(lp: int, protocol: int, creator: int) -> bytes:
    return struct.pack("<QQQ", lp, protocol, creator)


def _tiers(tiers: list[tuple[int, tuple[int, int, int]]]) -> bytes:
    out = struct.pack("<I", len(tiers))
    for threshold, fees in tiers:
        out += threshold.to_bytes(16, "little") + _fees(*fees)
    return out


# Synthetic tiers for the layout and selection logic only: the live schedule
# is read from chain at startup and is not pinned here.
TIERS = [
    (0, (0, 95, 30)),  # 1.25% below 420 SOL
    (420 * LAMPORTS, (0, 93, 5)),
    (1_470 * LAMPORTS, (0, 90, 1)),
]


def _account(tiers=TIERS, *, exotic: bool = True) -> bytes:
    data = (
        FEE_CONFIG_DISCRIMINATOR
        + bytes([254])
        + bytes(ADMIN)
        + _fees(25, 5, 0)
        + _tiers(tiers)
        + _tiers([(0, (20, 5, 0))])
    )
    return data + (_fees(30, 5, 0) if exotic else b"")


def test_decode_fee_config_follows_the_idl_layout() -> None:
    config = decode_fee_config(_account())
    assert config.bump == 254
    assert config.admin == str(ADMIN)
    assert config.flat_fees == Fees(25, 5, 0)
    assert [t.market_cap_lamports_threshold for t in config.fee_tiers] == [
        0,
        420 * LAMPORTS,
        1_470 * LAMPORTS,
    ]
    assert config.fee_tiers[0].fees.bonding_curve_bps == 125
    assert config.stable_fee_tiers == (FeeTier(0, Fees(20, 5, 0)),)
    assert config.exotic_flat_fees == Fees(30, 5, 0)
    # Accounts written before `exotic_flat_fees` existed still decode.
    assert decode_fee_config(_account(exotic=False)).exotic_flat_fees is None


@pytest.mark.parametrize(
    "data, message",
    [
        (b"\x00" * 64, "discriminator"),
        (_account()[:60], "too short"),
        (
            FEE_CONFIG_DISCRIMINATOR
            + bytes([1])
            + bytes(ADMIN)
            + _fees(0, 0, 0)
            + struct.pack("<I", 1_000),
            "tier count",
        ),
        (_account([(0, (0, 5_000, 0))]), "implausible fee tier"),
    ],
)
def test_decode_fee_config_rejects_malformed_accounts(
    data: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        decode_fee_config(data)


def test_tier_selection_matches_calculate_fee_tier() -> None:
    tiers = decode_fee_config(_account()).fee_tiers
    assert select_fee_tier(tiers, 0).bonding_curve_bps == 125
    assert select_fee_tier(tiers, 420 * LAMPORTS - 1).bonding_curve_bps == 125
    assert select_fee_tier(tiers, 420 * LAMPORTS).bonding_curve_bps == 98
    assert select_fee_tier(tiers, 10**15).bonding_curve_bps == 91
    # Below the first threshold the first tier applies.
    raised = (FeeTier(100, Fees(0, 50, 0)), FeeTier(200, Fees(0, 40, 0)))
    assert select_fee_tier(raised, 10).protocol_fee_bps == 50
    with pytest.raises(ValueError):
        select_fee_tier((), 0)


def test_bonding_curve_fee_uses_the_curve_market_cap_in_lamports() -> None:
    config = decode_fee_config(_account())
    launch = curve_market_cap_lamports(
        INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW, TOTAL_TOKEN_SUPPLY_RAW
    )
    assert launch == pytest.approx(27.96 * LAMPORTS, rel=1e-3)
    assert (
        bonding_curve_fee_bps(
            config,
            INITIAL_VIRTUAL_SOL_LAMPORTS,
            INITIAL_VIRTUAL_TOKEN_RAW,
            TOTAL_TOKEN_SUPPLY_RAW,
        )
        == 125
    )
    # 500 SOL market cap: the second tier.
    v_token = 1_000_000_000_000_000 * 60 // 500
    assert bonding_curve_fee_bps(config, 60 * LAMPORTS, v_token, 10**15) == 98
    with pytest.raises(ValueError):
        curve_market_cap_lamports(1, 0, 1)


class _Client(PumpFunCurveMixin):
    pump_fee_bps = 125

    def __init__(self, response: dict) -> None:
        self.rpc = AsyncMock(return_value=response)
        self._request_rpc_json = self.rpc  # type: ignore[method-assign]


def _response(data: bytes, owner: str = PUMP_FEE_PROGRAM_ID) -> dict:
    return {
        "result": {
            "value": {
                "owner": owner,
                "data": [base64.b64encode(data).decode(), "base64"],
            }
        }
    }


async def test_client_reads_caches_and_applies_the_fee_tiers() -> None:
    client = _Client(_response(_account([(0, (0, 100, 50))])))
    config = await client.get_pump_fee_config()
    assert config is not None and config.fee_tiers[0].fees.bonding_curve_bps == 150
    await client.get_pump_fee_config()
    client.rpc.assert_awaited_once()  # cached
    assert (
        client.curve_fee_bps(INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW)
        == 150
    )
    assert client.curve_fee_bps(0, 1) == 125
    assert client.rpc.await_args is not None
    params = client.rpc.await_args.args[0]["params"]
    assert params[0] == client.fee_config_address()


@pytest.mark.parametrize(
    "response",
    [
        {"result": {"value": None}},
        _response(_account(), owner="11111111111111111111111111111111"),
        _response(b"garbage"),
    ],
)
async def test_client_falls_back_to_the_flat_fee_when_the_config_is_unusable(
    response: dict,
) -> None:
    client = _Client(response)
    assert await client.get_pump_fee_config() is None
    assert (
        client.curve_fee_bps(INITIAL_VIRTUAL_SOL_LAMPORTS, INITIAL_VIRTUAL_TOKEN_RAW)
        == 125
    )


async def test_client_keeps_the_last_good_config_when_a_refresh_fails() -> None:
    client = _Client(_response(_account()))
    first = await client.get_pump_fee_config()
    client._request_rpc_json = AsyncMock(side_effect=RuntimeError("rpc down"))  # type: ignore[method-assign]
    assert await client.get_pump_fee_config(max_age_seconds=0.0) is first
