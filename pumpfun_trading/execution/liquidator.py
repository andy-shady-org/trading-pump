from __future__ import annotations

import asyncio
import logging

from pumpfun_trading.bot.position_manager import PositionManager
from pumpfun_trading.execution.executor import OrderExecutor
from pumpfun_trading.strategies.base import TradingBotConfig

logger = logging.getLogger(__name__)


class OrderLiquidator:
    """Manages panic exits, emergency portfolio liquidation, and circuit breaker locking."""

    def __init__(
        self,
        executor: OrderExecutor,
        position_manager: PositionManager,
        config: TradingBotConfig | None = None,
    ) -> None:
        self.executor = executor
        self.position_manager = position_manager
        self.config = config or TradingBotConfig()

    async def liquidate_position(
        self,
        mint: str,
        *,
        reason: str = "emergency_liquidation",
        slippage_bps: int | None = 2500,
    ) -> bool:
        if not self.position_manager.has_position(mint):
            return False

        pos = self.position_manager.get_position(mint) or {}
        token_amount = int(
            pos.get("remaining_token_amount") or pos.get("token_amount") or 100_000_000
        )

        logger.warning(
            "Liquidating position for %s (%d tokens, reason: %s)",
            mint,
            token_amount,
            reason,
        )

        result = await self.executor.execute_sell(
            mint=mint,
            token_amount=token_amount,
            slippage_bps=slippage_bps,
            reason=reason,
        )

        if result.success or result.dry_run:
            self.position_manager.remove_position(mint)
            return True

        return False

    async def liquidate_all_positions(
        self,
        *,
        reason: str = "emergency_liquidation",
        max_concurrency: int = 5,
        slippage_bps: int | None = 2500,
    ) -> list[str]:
        mints_to_liquidate = self.position_manager.get_mints()
        if not mints_to_liquidate:
            return []

        logger.warning(
            "Engaging emergency liquidation across %d active positions: %s",
            len(mints_to_liquidate),
            reason,
        )

        semaphore = asyncio.Semaphore(max_concurrency)
        liquidated: list[str] = []

        async def _liquidate_with_sem(mint: str) -> None:
            async with semaphore:
                success = await self.liquidate_position(
                    mint=mint,
                    reason=reason,
                    slippage_bps=slippage_bps,
                )
                if success:
                    liquidated.append(mint)

        tasks = [_liquidate_with_sem(mint) for mint in mints_to_liquidate]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "Emergency liquidation complete. Liquidated %d/%d positions.",
            len(liquidated),
            len(mints_to_liquidate),
        )
        return liquidated
