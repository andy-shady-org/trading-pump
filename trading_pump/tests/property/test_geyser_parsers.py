"""Property tests for the zero-copy parsers in ``streams/geyser.py``.

Payloads come from ``tests/support/payloads.py``, which mirrors the
Yellowstone / Anchor byte layouts (AGENTS.md: zero-copy alignment checks).
Every u64 / i64 / bool field and every pubkey must survive a round trip, and
short or foreign buffers must be rejected rather than misread.
"""

from __future__ import annotations

import base64

import pytest
from hypothesis import given
from hypothesis import strategies as st
from solders.pubkey import Pubkey

from trading_pump.streams.geyser import (
    TRADE_EVENT_DISCRIMINATOR,
    BondingCurveBinaryParser,
    CompleteEventUpdate,
    TradeEventUpdate,
    TradeInstructionBinaryParser,
)
from trading_pump.tests.support.payloads import (
    bonding_curve_bytes,
    buy_instruction_bytes,
    complete_event_bytes,
    sell_instruction_bytes,
    trade_event_bytes,
)

u64 = st.integers(min_value=0, max_value=2**64 - 1)
i64 = st.integers(min_value=-(2**63), max_value=2**63 - 1)
pubkeys = st.binary(min_size=32, max_size=32).map(
    lambda raw: str(Pubkey.from_bytes(raw))
)


@given(
    v_tokens=u64,
    v_sol=u64,
    r_tokens=u64,
    r_sol=u64,
    supply=u64,
    complete=st.booleans(),
    trailing=st.binary(max_size=64),
)
def test_curve_account_round_trips_every_field(
    v_tokens: int,
    v_sol: int,
    r_tokens: int,
    r_sol: int,
    supply: int,
    complete: bool,
    trailing: bytes,
) -> None:
    data = (
        bonding_curve_bytes(
            virtual_token_reserves=v_tokens,
            virtual_sol_reserves=v_sol,
            real_token_reserves=r_tokens,
            real_sol_reserves=r_sol,
            token_total_supply=supply,
            complete=complete,
        )
        + trailing
    )

    state = BondingCurveBinaryParser.parse_account_data(memoryview(data))

    assert (
        state.virtual_token_reserves,
        state.virtual_sol_reserves,
        state.real_token_reserves,
        state.real_sol_reserves,
        state.token_total_supply,
        state.complete,
    ) == (v_tokens, v_sol, r_tokens, r_sol, supply, complete)
    assert BondingCurveBinaryParser.parse_raw_reserves(data) == (
        v_tokens,
        v_sol,
        r_tokens,
        r_sol,
        supply,
        complete,
    )
    if v_tokens == 0:
        assert state.price_sol == 0.0
        assert state.market_cap_sol == 0.0


@given(size=st.integers(min_value=0, max_value=48))
def test_curve_account_shorter_than_layout_is_rejected(size: int) -> None:
    data = bonding_curve_bytes()[:size]

    with pytest.raises(ValueError):
        BondingCurveBinaryParser.parse_account_data(data)
    with pytest.raises(ValueError):
        BondingCurveBinaryParser.parse_raw_reserves(data)


@given(
    mint=pubkeys,
    user=pubkeys,
    sol=u64,
    tokens=u64,
    is_buy=st.booleans(),
    timestamp=i64,
    v_sol=u64,
    v_tokens=u64,
    r_sol=u64,
    r_tokens=u64,
)
def test_trade_event_round_trips_every_field(
    mint: str,
    user: str,
    sol: int,
    tokens: int,
    is_buy: bool,
    timestamp: int,
    v_sol: int,
    v_tokens: int,
    r_sol: int,
    r_tokens: int,
) -> None:
    data = trade_event_bytes(
        mint=mint,
        user=user,
        sol_amount=sol,
        token_amount=tokens,
        is_buy=is_buy,
        timestamp=timestamp,
        virtual_sol_reserves=v_sol,
        virtual_token_reserves=v_tokens,
        real_sol_reserves=r_sol,
        real_token_reserves=r_tokens,
    )

    event = TradeInstructionBinaryParser.parse_trade_event_buffer(data, slot=7)
    from_log = TradeInstructionBinaryParser.parse_program_log_event(
        "Program data: " + base64.b64encode(data).decode("ascii")
    )

    assert isinstance(event, TradeEventUpdate)
    assert (event.mint, event.user, event.is_buy, event.timestamp) == (
        mint,
        user,
        is_buy,
        timestamp,
    )
    assert (event.sol_amount_lamports, event.token_amount) == (sol, tokens)
    assert (
        event.virtual_sol_reserves,
        event.virtual_token_reserves,
        event.real_sol_reserves,
        event.real_token_reserves,
    ) == (v_sol, v_tokens, r_sol, r_tokens)
    assert event.slot == 7
    assert isinstance(from_log, TradeEventUpdate)
    assert from_log.mint == mint


@given(user=pubkeys, mint=pubkeys, curve=pubkeys, timestamp=i64)
def test_complete_event_round_trips_every_field(
    user: str, mint: str, curve: str, timestamp: int
) -> None:
    data = complete_event_bytes(
        user=user, mint=mint, bonding_curve=curve, timestamp=timestamp
    )

    event = TradeInstructionBinaryParser.parse_complete_event_buffer(data)

    assert isinstance(event, CompleteEventUpdate)
    assert (event.user, event.mint, event.bonding_curve, event.timestamp) == (
        user,
        mint,
        curve,
        timestamp,
    )


@given(data=st.binary(max_size=200))
def test_event_parsers_reject_foreign_or_short_buffers(data: bytes) -> None:
    trade = TradeInstructionBinaryParser.parse_trade_event_buffer(data)
    complete = TradeInstructionBinaryParser.parse_complete_event_buffer(data)

    if len(data) < 129 or data[:8] != TRADE_EVENT_DISCRIMINATOR:
        assert trade is None
    assert complete is None or len(data) >= 112


@given(text=st.text(max_size=300))
def test_program_log_parser_never_raises_on_arbitrary_logs(text: str) -> None:
    result = TradeInstructionBinaryParser.parse_program_log_event(text)

    assert result is None or isinstance(result, (TradeEventUpdate, CompleteEventUpdate))


@given(amount=u64, limit=u64)
def test_buy_and_sell_instruction_data_round_trip(amount: int, limit: int) -> None:
    assert TradeInstructionBinaryParser.parse_buy_instruction(
        buy_instruction_bytes(amount, limit)
    ) == {"amount": amount, "max_sol_cost": limit}
    assert TradeInstructionBinaryParser.parse_sell_instruction(
        sell_instruction_bytes(amount, limit)
    ) == {"amount": amount, "min_sol_output": limit}
