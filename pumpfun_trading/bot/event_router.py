from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
    TradeEventUpdate,
)

logger = logging.getLogger(__name__)


class EventRouter:
    """Ingests and routes Yellowstone Geyser and WebSocket stream events to strategy hooks."""

    def __init__(
        self,
        on_curve_update: Optional[Callable[[BondingCurveStateUpdate], Awaitable[None]]] = None,
        on_trade_event: Optional[Callable[[TradeEventUpdate], Awaitable[None]]] = None,
        on_complete_event: Optional[Callable[[CompleteEventUpdate], Awaitable[None]]] = None,
        on_raydium_pool: Optional[Callable[[RaydiumPoolKeys], Awaitable[None]]] = None,
        on_ws_new_token: Optional[Callable[[dict[str, Any], Any], Awaitable[None]]] = None,
        on_ws_trade: Optional[Callable[[dict[str, Any], Any], Awaitable[None]]] = None,
    ) -> None:
        self.on_curve_update = on_curve_update
        self.on_trade_event = on_trade_event
        self.on_complete_event = on_complete_event
        self.on_raydium_pool = on_raydium_pool
        self.on_ws_new_token = on_ws_new_token
        self.on_ws_trade = on_ws_trade

    async def route_geyser_curve_update(self, update: BondingCurveStateUpdate) -> None:
        if self.on_curve_update:
            await self.on_curve_update(update)

    async def route_geyser_trade_update(self, update: TradeEventUpdate) -> None:
        if self.on_trade_event:
            await self.on_trade_event(update)

    async def route_geyser_complete_update(self, update: CompleteEventUpdate) -> None:
        if self.on_complete_event:
            await self.on_complete_event(update)

    async def route_raydium_pool(self, pool_keys: RaydiumPoolKeys) -> None:
        if self.on_raydium_pool:
            await self.on_raydium_pool(pool_keys)

    async def route_ws_message(self, data: Any, websocket: Any = None) -> None:
        if not isinstance(data, dict):
            return

        msg_type = data.get("type") or data.get("event") or data.get("txType") or ""
        if msg_type in {"new_token", "create", "mint", "newTokenCreated"}:
            if self.on_ws_new_token:
                await self.on_ws_new_token(data, websocket)
        else:
            if self.on_ws_trade:
                await self.on_ws_trade(data, websocket)
