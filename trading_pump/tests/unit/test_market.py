"""Unit tests for ``market.py``: readings, swap maths, the RPC pool source."""

from __future__ import annotations

import base64
import struct
from typing import Any

import pytest

from trading_pump.market import (
    FEE_SOURCE_FLOOR,
    FEE_SOURCE_GLOBAL,
    FEE_SOURCE_TIER,
    PoolReading,
    RpcPoolSource,
    buy_tokens_out,
    is_valid_mint,
    sell_lamports_gross,
    sell_lamports_out,
)
from trading_pump.sdk.execution_types import PUMP_FEE_PROGRAM_ID
from trading_pump.sdk.fee_config import FEE_CONFIG_DISCRIMINATOR
from trading_pump.sdk.pumpswap import PUMP_AMM_PROGRAM_ID
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading
from trading_pump.tests.support.payloads import GRADUATED_GLOBAL_CONFIG_B64


def test_a_standard_graduation_reads_like_the_capture() -> None:
    reading = make_reading(SAMPLE_PUMP_MINT, at=10.0)

    assert reading.market_cap_sol == pytest.approx(410.83, abs=0.01)
    assert reading.pool_sol == 85.0
    assert reading.pool_tokens == pytest.approx(206_900_000.0)
    assert reading.price == pytest.approx(reading.market_cap_sol / 1e9)
    assert reading.market_cap_lamports == round(reading.market_cap_sol * 1e9)
    assert reading.age(15.0) == 5.0 and reading.age(5.0) == 0.0
    assert reading.capture_row(source="graduation") == {
        "timestamp": 10.0,
        "mint": SAMPLE_PUMP_MINT,
        "event": "curve_poll",
        "source": "graduation",
        "price": reading.market_cap_sol / 1e9,
        "market_cap_sol": round(reading.market_cap_sol, 6),
        "pool_sol": 85.0,
        "pool_tokens": round(reading.pool_tokens, 6),
    }


def test_a_drained_pool_is_a_reading_with_no_price() -> None:
    drained = PoolReading(SAMPLE_MINT, at=1.0, base_reserve=0, quote_reserve=5)

    assert drained.drained
    assert drained.price == 0.0 and drained.market_cap_sol == 0.0
    assert drained.pool_tokens == 0.0
    assert buy_tokens_out(drained, 1_000, 30) == 0
    assert sell_lamports_out(drained, 1_000, 30) == 0


def test_swap_maths_is_constant_product_with_the_fee_on_the_quote_side() -> None:
    reading = PoolReading(
        SAMPLE_MINT, at=0.0, base_reserve=1_000_000, quote_reserve=1_000_000
    )

    # 10,030 in, 30 bps on top: 10,000 swapped -> 1e6 * 1e4 / 1.01e6 tokens.
    assert buy_tokens_out(reading, 10_030, 30) == 9_900
    assert buy_tokens_out(reading, 0, 30) == 0
    assert buy_tokens_out(reading, 10_000, -5) == 9_900
    assert sell_lamports_gross(reading, 10_000) == 9_900
    assert sell_lamports_out(reading, 10_000, 30) == 9_900 * 9_970 // 10_000
    assert sell_lamports_out(reading, 0, 30) == 0


def test_is_valid_mint() -> None:
    assert is_valid_mint(SAMPLE_MINT)
    assert not is_valid_mint("not-a-mint")


class FakeClient:
    """``get_pumpswap_pool_states`` and ``_get_accounts`` from canned values."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.rejected: dict[str, str] = {}
        self.accounts: list[dict[str, Any] | None] = [None, None]
        self.account_reads = 0

    async def get_pumpswap_pool_states(
        self, mints: Any, *, rejected: Any = None, timeout_seconds: float = 5.0
    ) -> dict[str, dict[str, Any]]:
        assert timeout_seconds == 7.0
        rejected.update(self.rejected)
        return {m: self.states[m] for m in mints if m in self.states}

    async def _get_accounts(
        self, addresses: list[str], *, timeout_seconds: float = 5.0
    ) -> list[dict[str, Any] | None]:
        self.account_reads += 1
        return list(self.accounts)


def _fee_config_bytes(tiers: list[tuple[int, int, int, int]]) -> bytes:
    data = FEE_CONFIG_DISCRIMINATOR + bytes([255]) + bytes(32)
    data += struct.pack("<QQQ", 0, 95, 0)  # flat fees
    data += struct.pack("<I", len(tiers))
    for threshold, lp, protocol, creator in tiers:
        data += threshold.to_bytes(16, "little") + struct.pack(
            "<QQQ", lp, protocol, creator
        )
    data += struct.pack("<I", 0)  # stable tiers
    return data


def _account(owner: str, raw: bytes) -> dict[str, Any]:
    return {"owner": owner, "data": [base64.b64encode(raw).decode(), "base64"]}


async def test_rpc_source_turns_pool_states_into_readings() -> None:
    client = FakeClient()
    client.states[SAMPLE_MINT] = {"pool": "P", "base_reserve": 10, "quote_reserve": 20}
    client.rejected[SAMPLE_PUMP_MINT] = "not_pumpswap"
    source = RpcPoolSource(client, timeout_seconds=7.0)

    readings, rejected = await source.read_pools(
        [SAMPLE_MINT, SAMPLE_PUMP_MINT], now=99.0
    )

    assert readings == {SAMPLE_MINT: PoolReading(SAMPLE_MINT, 99.0, 10, 20, "P")}
    assert rejected == {SAMPLE_PUMP_MINT: "not_pumpswap"}
    assert source.stats == {"pool_reads": 1}


async def test_the_fee_tier_matching_the_market_cap_wins_and_is_cached() -> None:
    client = FakeClient()
    client.accounts = [
        _account(
            PUMP_FEE_PROGRAM_ID,
            _fee_config_bytes(
                [(0, 20, 93, 30), (300 * 10**9, 20, 5, 5), (10**18, 20, 5, 0)]
            ),
        ),
        _account(PUMP_AMM_PROGRAM_ID, base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64)),
    ]
    now = [0.0]
    source = RpcPoolSource(client, clock=lambda: now[0])

    low = make_reading(SAMPLE_MINT, scale=0.5)  # ~205 SOL market cap
    high = make_reading(SAMPLE_MINT)  # ~411 SOL

    assert (await source.swap_fee(low)).bps == 143
    fee = await source.swap_fee(high)
    assert (fee.bps, fee.source) == (30, FEE_SOURCE_TIER)
    assert client.account_reads == 1
    now[0] = 301.0
    await source.swap_fee(high)
    assert client.account_reads == 2


async def test_without_tiers_the_global_config_total_is_used_with_the_floor() -> None:
    client = FakeClient()
    client.accounts = [
        None,
        _account(PUMP_AMM_PROGRAM_ID, base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64)),
    ]
    fee = await RpcPoolSource(client).swap_fee(make_reading(SAMPLE_MINT))
    assert (fee.bps, fee.source) == (30, FEE_SOURCE_GLOBAL)

    floored = await RpcPoolSource(client, fee_bps_floor=100).swap_fee(
        make_reading(SAMPLE_MINT)
    )
    assert (floored.bps, floored.source) == (100, FEE_SOURCE_FLOOR)


async def test_unreadable_fee_accounts_raise_unless_an_earlier_read_is_kept() -> None:
    client = FakeClient()
    client.accounts = [
        _account("SomeoneElse", b"x"),
        _account(PUMP_AMM_PROGRAM_ID, b"too short"),
    ]
    source = RpcPoolSource(client)
    with pytest.raises(RuntimeError, match="fee accounts could not be read"):
        await source.swap_fee(make_reading(SAMPLE_MINT))

    client.accounts = [
        None,
        _account(PUMP_AMM_PROGRAM_ID, base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64)),
    ]
    now = [0.0]
    kept = RpcPoolSource(client, clock=lambda: now[0])
    assert (await kept.swap_fee(make_reading(SAMPLE_MINT))).bps == 30
    client.accounts = [None, None]
    now[0] = 1_000.0
    assert (await kept.swap_fee(make_reading(SAMPLE_MINT))).bps == 30
