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
    NewPoolInfo,
    PoolReading,
    RpcPoolSource,
    buy_tokens_out,
    is_valid_mint,
    sell_lamports_gross,
    sell_lamports_out,
)
from trading_pump.sdk.execution_types import (
    PUMP_FEE_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
)
from trading_pump.sdk.fee_config import FEE_CONFIG_DISCRIMINATOR
from trading_pump.sdk.pumpswap import (
    PUMP_AMM_PROGRAM_ID,
    fee_config_address,
    global_config_address,
)
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT
from trading_pump.tests.support.factories import make_reading
from trading_pump.tests.support.payloads import (
    GRADUATE_MINT,
    GRADUATE_MINT_B64,
    GRADUATE_MINT_SUPPLY,
    GRADUATED_GLOBAL_CONFIG_B64,
)


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
    """``get_pumpswap_pool_states`` and ``_get_accounts`` from canned values,
    answered by address (the fee accounts and any mint in ``mints``)."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.rejected: dict[str, str] = {}
        self.fee_config: dict[str, Any] | None = None
        self.global_config: dict[str, Any] | None = None
        self.mints: dict[str, dict[str, Any] | None] = {}
        self.reads: list[list[str]] = []
        self.signatures: list[dict[str, Any]] = []
        self.remembered: dict[str, tuple[str, str, str, bool]] = {}

    async def get_pumpswap_pool_states(
        self, mints: Any, *, rejected: Any = None, timeout_seconds: float = 5.0
    ) -> dict[str, dict[str, Any]]:
        assert timeout_seconds == 7.0
        rejected.update(self.rejected)
        return {m: self.states[m] for m in mints if m in self.states}

    async def _get_accounts(
        self, addresses: list[str], *, timeout_seconds: float = 5.0
    ) -> list[dict[str, Any] | None]:
        self.reads.append(list(addresses))
        table = {
            str(fee_config_address()): self.fee_config,
            str(global_config_address()): self.global_config,
            **self.mints,
        }
        return [table.get(address) for address in addresses]

    async def get_signatures_for_address(
        self, address: str, *, limit: int, timeout_seconds: float = 5.0
    ) -> list[dict[str, Any]]:
        self.reads.append([f"signatures:{address}:{limit}"])
        return list(self.signatures)

    def remember_pumpswap_pool(
        self,
        mint: str,
        address: str,
        base_vault: str,
        quote_vault: str,
        *,
        sol_is_base: bool = False,
    ) -> None:
        self.remembered[mint] = (address, base_vault, quote_vault, sol_is_base)


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


def _mint(supply: int, owner: str = TOKEN_PROGRAM_ID_STR) -> dict[str, Any]:
    """An SPL mint: COption authority (36 bytes), supply, decimals 6, ..."""
    return _account(
        owner, bytes(36) + struct.pack("<Q", supply) + bytes([6, 1]) + bytes(36)
    )


GLOBAL_CONFIG = _account(
    PUMP_AMM_PROGRAM_ID, base64.b64decode(GRADUATED_GLOBAL_CONFIG_B64)
)


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
    client.fee_config = _account(
        PUMP_FEE_PROGRAM_ID,
        _fee_config_bytes(
            [(0, 20, 93, 30), (300 * 10**9, 20, 5, 5), (10**18, 20, 5, 0)]
        ),
    )
    client.global_config = GLOBAL_CONFIG
    client.mints[SAMPLE_MINT] = _mint(10**15)
    now = [0.0]
    source = RpcPoolSource(client, clock=lambda: now[0])

    low = make_reading(SAMPLE_MINT, scale=0.5)  # ~205 SOL market cap
    high = make_reading(SAMPLE_MINT)  # ~411 SOL

    assert (await source.swap_fee(low)).bps == 143
    fee = await source.swap_fee(high)
    assert (fee.bps, fee.source) == (30, FEE_SOURCE_TIER)
    # The fee accounts and the mint come in one call, then from the cache.
    assert client.reads == [
        [str(fee_config_address()), str(global_config_address()), SAMPLE_MINT]
    ]
    now[0] = 301.0
    await source.swap_fee(high)
    assert len(client.reads) == 2 and client.reads[1][-1] == SAMPLE_MINT

    # Each mint's supply has its own age: a mint first read later is not
    # read again when only the fee accounts are due.
    client.mints[SAMPLE_PUMP_MINT] = _mint(10**15)
    now[0] = 400.0
    await source.swap_fee(make_reading(SAMPLE_PUMP_MINT))
    assert client.reads[2] == [SAMPLE_PUMP_MINT]
    now[0] = 650.0
    await source.swap_fee(make_reading(SAMPLE_PUMP_MINT))
    assert client.reads[3] == [str(fee_config_address()), str(global_config_address())]


async def test_without_tiers_the_global_config_total_is_used_with_the_floor() -> None:
    client = FakeClient()
    client.global_config = GLOBAL_CONFIG
    fee = await RpcPoolSource(client).swap_fee(make_reading(SAMPLE_MINT))
    assert (fee.bps, fee.source) == (30, FEE_SOURCE_GLOBAL)

    floored = await RpcPoolSource(client, fee_bps_floor=100).swap_fee(
        make_reading(SAMPLE_MINT)
    )
    assert (floored.bps, floored.source) == (100, FEE_SOURCE_FLOOR)


async def test_unreadable_fee_accounts_raise_unless_an_earlier_read_is_kept() -> None:
    client = FakeClient()
    client.fee_config = _account("SomeoneElse", b"x")
    client.global_config = _account(PUMP_AMM_PROGRAM_ID, b"too short")
    source = RpcPoolSource(client)
    with pytest.raises(RuntimeError, match="fee accounts could not be read"):
        await source.swap_fee(make_reading(SAMPLE_MINT))

    client.fee_config, client.global_config = None, GLOBAL_CONFIG
    now = [0.0]
    kept = RpcPoolSource(client, clock=lambda: now[0])
    assert (await kept.swap_fee(make_reading(SAMPLE_MINT))).bps == 30
    client.global_config = None
    now[0] = 1_000.0
    assert (await kept.swap_fee(make_reading(SAMPLE_MINT))).bps == 30


# The live tiers either side of a fresh graduate (2026-10-29): below 420 SOL
# 2 + 93 + 30 bps, from 420 SOL 20 + 5 + 95 bps.
GRADUATE_TIERS = [(0, 2, 93, 30), (420 * 10**9, 20, 5, 95)]
# A real buy of GRADUATE_MINT at 432 SOL on the 1B basis that paid 125 bps
# (signature 4SyECFgRLeWq...): reserves from its BuyEvent, the quote with the
# pool's virtual reserve.
BOUNDARY_READING = PoolReading(
    GRADUATE_MINT,
    at=0.0,
    base_reserve=202_829_773_604_369,
    quote_reserve=87_683_120_819,
)


@pytest.mark.regression("BUG-162")
async def test_the_fee_tier_is_picked_on_the_mints_real_supply() -> None:
    client = FakeClient()
    client.fee_config = _account(PUMP_FEE_PROGRAM_ID, _fee_config_bytes(GRADUATE_TIERS))
    client.global_config = GLOBAL_CONFIG
    client.mints[GRADUATE_MINT] = {
        "owner": TOKEN_2022_PROGRAM_ID_STR,
        "data": [GRADUATE_MINT_B64, "base64"],
    }
    source = RpcPoolSource(client)

    assert BOUNDARY_READING.market_cap_sol == pytest.approx(432.3, abs=0.1)
    assert BOUNDARY_READING.fee_market_cap_lamports(GRADUATE_MINT_SUPPLY) == (
        87_683_120_819 * GRADUATE_MINT_SUPPLY // 202_829_773_604_369
    )
    fee = await source.swap_fee(BOUNDARY_READING)
    # 416 SOL on the burnt supply: the below-420 tier, as the program charged
    # (the 1B basis picked 120 bps).
    assert (fee.bps, fee.source) == (125, FEE_SOURCE_TIER)

    full = RpcPoolSource(client)
    client.mints[GRADUATE_MINT] = _mint(10**15, owner=TOKEN_2022_PROGRAM_ID_STR)
    assert (await full.swap_fee(BOUNDARY_READING)).bps == 120


@pytest.mark.regression("BUG-162")
@pytest.mark.parametrize(
    "mint_account",
    [
        None,
        _mint(10**15, owner="SomeoneElse"),
        _account(TOKEN_PROGRAM_ID_STR, b"short"),
        _mint(0),
    ],
)
async def test_an_unknown_supply_is_an_unknown_fee_and_is_read_again(
    mint_account: dict[str, Any] | None,
) -> None:
    client = FakeClient()
    client.fee_config = _account(PUMP_FEE_PROGRAM_ID, _fee_config_bytes(GRADUATE_TIERS))
    client.global_config = GLOBAL_CONFIG
    client.mints[SAMPLE_MINT] = mint_account
    source = RpcPoolSource(client)

    with pytest.raises(RuntimeError, match="supply of mint .* could not be read"):
        await source.swap_fee(make_reading(SAMPLE_MINT))
    client.mints[SAMPLE_MINT] = _mint(10**15)
    assert (await source.swap_fee(make_reading(SAMPLE_MINT))).bps == 125
    # The fee accounts were still fresh: only the mint was read again.
    assert client.reads[1] == [SAMPLE_MINT]


@pytest.mark.regression("BUG-162")
async def test_a_known_supply_is_kept_when_a_later_read_fails() -> None:
    client = FakeClient()
    client.fee_config = _account(PUMP_FEE_PROGRAM_ID, _fee_config_bytes(GRADUATE_TIERS))
    client.global_config = GLOBAL_CONFIG
    client.mints[SAMPLE_MINT] = _mint(10**15)
    now = [0.0]
    source = RpcPoolSource(client, clock=lambda: now[0])
    assert (await source.swap_fee(make_reading(SAMPLE_MINT))).bps == 125

    client.mints[SAMPLE_MINT] = None
    now[0] = 301.0
    assert (await source.swap_fee(make_reading(SAMPLE_MINT))).bps == 125


def test_a_drained_pool_has_no_fee_market_cap() -> None:
    drained = PoolReading(SAMPLE_MINT, at=1.0, base_reserve=0, quote_reserve=5)
    assert drained.fee_market_cap_lamports(10**15) == 0


# -- FEAT-80: pools found by the new-pool feed ----------------------------------


def test_a_registered_pool_is_handed_to_the_client() -> None:
    client = FakeClient()
    source = RpcPoolSource(client)
    source.register_pool(SAMPLE_MINT, "Pool", "Base", "Quote")
    source.register_pool(SAMPLE_PUMP_MINT, "P2", "B2", "Q2", sol_is_base=True)
    assert client.remembered == {
        SAMPLE_MINT: ("Pool", "Base", "Quote", False),
        SAMPLE_PUMP_MINT: ("P2", "B2", "Q2", True),
    }


@pytest.mark.parametrize(
    ("signatures", "limit", "expected"),
    [
        # The whole history fit: created at the oldest signature.
        ([{"blockTime": 30}, {"blockTime": 10}], 5, NewPoolInfo(10.0, True, 2, 6)),
        # The lookup was full: the oldest seen is an upper bound.
        ([{"blockTime": 30}, {"blockTime": 20}], 2, NewPoolInfo(20.0, False, 2, 6)),
        # No block times (or none at all): no creation time.
        ([{"signature": "x"}], 5, NewPoolInfo(None, True, 1, 6)),
    ],
)
async def test_inspect_new_pool_dates_the_pool_by_its_signatures(
    signatures: list[dict[str, Any]], limit: int, expected: NewPoolInfo
) -> None:
    client = FakeClient()
    client.signatures = signatures
    client.mints[SAMPLE_MINT] = _mint(10**15)
    source = RpcPoolSource(client)

    info = await source.inspect_new_pool("Pool", SAMPLE_MINT, limit=limit)

    assert info == expected
    assert client.reads == [[f"signatures:Pool:{limit}"], [SAMPLE_MINT]]


@pytest.mark.parametrize(
    "mint_account",
    [
        None,
        _mint(10**15, owner=PUMP_AMM_PROGRAM_ID),
        {"owner": TOKEN_PROGRAM_ID_STR, "data": [123, "base64"]},
        _account(TOKEN_2022_PROGRAM_ID_STR, bytes(44)),
    ],
)
async def test_unreadable_decimals_are_none(
    mint_account: dict[str, Any] | None,
) -> None:
    client = FakeClient()
    client.mints[SAMPLE_MINT] = mint_account
    info = await RpcPoolSource(client).inspect_new_pool("Pool", SAMPLE_MINT, limit=5)
    assert info.decimals is None


async def test_rpc_source_reads_token_names_from_the_mints() -> None:
    from trading_pump.names import TokenName

    client = FakeClient()
    client.mints[GRADUATE_MINT] = _account(
        TOKEN_2022_PROGRAM_ID_STR, base64.b64decode(GRADUATE_MINT_B64)
    )
    client.mints[SAMPLE_MINT] = _mint(10**15)  # an SPL mint: no name in it
    source = RpcPoolSource(client, timeout_seconds=7.0)

    names = await source.read_names([GRADUATE_MINT, SAMPLE_MINT, SAMPLE_PUMP_MINT])

    assert names == {GRADUATE_MINT: TokenName("the future is bright", "bright")}
    assert client.reads == [[GRADUATE_MINT, SAMPLE_MINT, SAMPLE_PUMP_MINT]]
    assert source.stats == {"name_reads": 1}
    assert await source.read_names([]) == {}
    assert len(client.reads) == 1
