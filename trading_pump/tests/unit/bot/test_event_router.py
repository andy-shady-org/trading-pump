"""Unit tests for ``bot/event_router.py``."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

from trading_pump.bot.event_router import EventRouter
from trading_pump.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)
from trading_pump.tests.support.constants import SAMPLE_MINT
from trading_pump.tests.support.factories import make_pool_keys


async def test_event_router_all_routes():
    curve_mock = AsyncMock()
    trade_mock = AsyncMock()
    complete_mock = AsyncMock()
    ray_mock = AsyncMock()
    ws_new_mock = AsyncMock()
    ws_trade_mock = AsyncMock()

    router = EventRouter(
        on_curve_update=curve_mock,
        on_trade_event=trade_mock,
        on_complete_event=complete_mock,
        on_raydium_pool=ray_mock,
        on_ws_new_token=ws_new_mock,
        on_ws_trade=ws_trade_mock,
    )

    curve_up = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="curve111",
        slot=12345,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=1000,
        real_sol_reserves=1000,
        token_total_supply=1000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=30.0,
    )
    await router.route_geyser_curve_update(curve_up)
    assert curve_mock.called

    trade_up = TradeEventUpdate(
        mint=SAMPLE_MINT,
        sol_amount_lamports=1_000_000_000,
        token_amount=100,
        is_buy=True,
        user="user111",
        timestamp=time.time(),
        virtual_sol_reserves=1000,
        virtual_token_reserves=1000,
        real_sol_reserves=1000,
        real_token_reserves=1000,
    )
    await router.route_geyser_trade_update(trade_up)
    assert trade_mock.called

    comp_up = CompleteEventUpdate(
        mint=SAMPLE_MINT,
        bonding_curve="curve111",
        user="user111",
        timestamp=time.time(),
    )
    await router.route_geyser_complete_update(comp_up)
    assert complete_mock.called

    pool_keys = make_pool_keys(unique=False)
    await router.route_raydium_pool(pool_keys)
    assert ray_mock.called

    # WS messages
    await router.route_ws_message("not_dict")
    await router.route_ws_message({"type": "create", "mint": SAMPLE_MINT})
    assert ws_new_mock.called

    await router.route_ws_message({"type": "trade", "mint": SAMPLE_MINT})
    assert ws_trade_mock.called
