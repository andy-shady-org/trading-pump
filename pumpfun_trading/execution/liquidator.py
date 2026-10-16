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
        slippage_bps: int | None = None,
        urgency: str = "emergency",
    ) -> bool:
        if not self.position_manager.has_position(mint):
            return False

        pos = self.position_manager.get_position(mint) or {}
        raw_amount = pos.get("remaining_token_amount")
        if raw_amount is None:
            raw_amount = pos.get("token_amount")
        token_amount = int(raw_amount or 0)
        if token_amount <= 0:
            # Never invent a sell size for an unknown or empty position (BUG-65).
            logger.warning(
                "Skipping liquidation for %s: no tracked token balance", mint
            )
            return False

        logger.warning(
            "Liquidating position for %s (%d tokens, reason: %s, urgency: %s)",
            mint,
            token_amount,
            reason,
            urgency,
        )

        eff_slippage = (
            slippage_bps
            if slippage_bps is not None
            else getattr(self.config, "max_exit_slippage_bps", 5000)
        )

        result = await self.executor.execute_sell(
            mint=mint,
            token_amount=token_amount,
            slippage_bps=eff_slippage,
            urgency=urgency,
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
        slippage_bps: int | None = None,
        urgency: str = "emergency",
    ) -> list[str]:
        mints_to_liquidate = self.position_manager.get_mints()
        if not mints_to_liquidate:
            return []

        logger.warning(
            "Engaging emergency liquidation across %d active positions: %s (urgency=%s)",
            len(mints_to_liquidate),
            reason,
            urgency,
        )

        semaphore = asyncio.Semaphore(max_concurrency)
        liquidated: list[str] = []

        async def _liquidate_with_sem(mint: str) -> None:
            async with semaphore:
                success = await self.liquidate_position(
                    mint=mint,
                    reason=reason,
                    slippage_bps=slippage_bps,
                    urgency=urgency,
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
