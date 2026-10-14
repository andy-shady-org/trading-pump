from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pumpfun_trading.execution.policy import (
    AdaptiveExecutionPolicy,
    DynamicSlippageResult,
)
from pumpfun_trading.infra.rpc_pool import RpcConnectionPool
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
from pumpfun_trading.strategies.base import TradingBotConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Encapsulates the result of a buy or sell execution."""

    success: bool
    signature: str | None = None
    mint: str = ""
    is_buy: bool = True
    amount_sol: float = 0.0
    token_amount: int = 0
    reason: str = ""
    error: str | None = None
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class OrderExecutor:
    """Handles low-level order creation, signing, Jito MEV bundling, retry loops, and direct RPC execution."""

    def __init__(
        self,
        execution_client: PumpFunExecutionClient,
        config: TradingBotConfig | None = None,
        rpc_pool: RpcConnectionPool | None = None,
        use_jito: bool = False,
        dry_run: bool = False,
        execution_policy: AdaptiveExecutionPolicy | None = None,
    ) -> None:
        self.execution = execution_client
        self.config = config or TradingBotConfig()
        self.rpc_pool = rpc_pool
        self.use_jito = use_jito
        self.dry_run = dry_run or self.config.dry_run
        self.execution_policy = execution_policy or AdaptiveExecutionPolicy(self.config)
        self._locks: dict[str, asyncio.Lock] = {}
        self._exit_retry_queue: dict[str, dict[str, Any]] = {}

    def get_lock(self, mint: str) -> asyncio.Lock:
        if mint not in self._locks:
            self._locks[mint] = asyncio.Lock()
        return self._locks[mint]

    async def execute_buy(
        self,
        mint: str,
        amount_sol: float,
        *,
        slippage_bps: int | None = None,
        urgency: str = "normal",
        reason: str = "entry",
        token_name: str | None = None,
        dry_run: bool | None = None,
    ) -> ExecutionResult:
        is_dry_run = self.dry_run if dry_run is None else dry_run

        resolved_slippage = slippage_bps
        dynamic_params: DynamicSlippageResult | None = None
        if resolved_slippage is None and getattr(
            self.config, "enable_dynamic_slippage", True
        ):
            dynamic_params = self.execution_policy.resolve_parameters(
                mint,
                amount_sol,
                is_buy=True,
                urgency=urgency,
            )
            resolved_slippage = dynamic_params.slippage_bps

        if is_dry_run:
            logger.info(
                "DRY RUN BUY: %s @ %.4f SOL (slippage_bps=%s, urgency=%s)",
                mint,
                amount_sol,
                resolved_slippage,
                urgency,
            )
            simulated_token_amount = 0
            if self.execution is not None:
                try:
                    curve_state = await self.execution.get_bonding_curve_state(mint)
                    v_token = int(curve_state.get("virtual_token_reserves", 0))
                    v_sol = int(curve_state.get("virtual_sol_reserves", 0))
                    if v_token > 0 and v_sol > 0:
                        sol_lamports = int(amount_sol * 1_000_000_000)
                        eff_slip = (
                            resolved_slippage
                            if resolved_slippage is not None
                            else getattr(self.execution, "default_slippage_bps", 250)
                        )
                        calc_fn = getattr(
                            self.execution, "calculate_buy_tokens_out", None
                        )
                        if calc_fn:
                            simulated_token_amount = int(
                                calc_fn(
                                    sol_lamports,
                                    v_sol,
                                    v_token,
                                    slippage_bps=eff_slip,
                                )
                            )
                except Exception:
                    pass

            if simulated_token_amount <= 0:
                sol_lamports = int(amount_sol * 1_000_000_000)
                v_sol = 30_000_000_000
                v_token = 1_073_000_000_000_000
                if sol_lamports > 0:
                    simulated_token_amount = int(
                        v_token - (v_token * v_sol) // (v_sol + sol_lamports)
                    )
                else:
                    simulated_token_amount = 100_000_000

            return ExecutionResult(
                success=True,
                signature=f"dry_run_buy_{mint[:8]}_{int(time.time())}",
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=simulated_token_amount,
                reason=reason,
                dry_run=True,
            )

        async with self.get_lock(mint):
            try:
                bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
            except Exception as exc:
                logger.warning(
                    "Could not compute bonding curve PDA for %s: %s", mint, exc
                )
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error=f"buy_pda_failed: {exc}",
                )

            logger.info(
                "Buying %s with %.4f SOL (slippage_bps=%s)",
                mint,
                amount_sol,
                resolved_slippage,
            )
            try:
                signature = await self.execution.buy(
                    mint,
                    bonding_curve,
                    amount_sol,
                    slippage_bps=resolved_slippage,
                )
            except Exception as exc:
                logger.warning("Buy transaction failed for %s: %s", mint, exc)
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error=f"buy_failed: {exc}",
                )

            if not signature:
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error="buy_signature_missing",
                )

            confirmed = await self.execution.confirm_transaction(signature)
            if not confirmed:
                logger.warning(
                    "Buy confirmation failed for %s (sig=%s)", mint, signature
                )
                return ExecutionResult(
                    success=False,
                    signature=signature,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error="buy_confirmation_failed",
                )

            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=0,
                reason=reason,
            )

    async def execute_sell(
        self,
        mint: str,
        token_amount: int,
        *,
        slippage_bps: int | None = None,
        min_sol_output_lamports: int = 0,
        urgency: str = "normal",
        reason: str = "exit",
        dry_run: bool | None = None,
    ) -> ExecutionResult:
        is_dry_run = self.dry_run if dry_run is None else dry_run

        effective_urgency = urgency
        if effective_urgency == "normal" and (
            "emergency" in reason.lower()
            or "panic" in reason.lower()
            or "stop_loss" in reason.lower()
        ):
            effective_urgency = "emergency"

        resolved_slippage = slippage_bps
        if resolved_slippage is None and getattr(
            self.config, "enable_dynamic_slippage", True
        ):
            dynamic_params = self.execution_policy.resolve_parameters(
                mint,
                0.01,
                is_buy=False,
                urgency=effective_urgency,
            )
            resolved_slippage = dynamic_params.slippage_bps

        if is_dry_run:
            logger.info(
                "DRY RUN SELL: %s for %d tokens (slippage_bps=%s, urgency=%s)",
                mint,
                token_amount,
                resolved_slippage,
                effective_urgency,
            )
            est_sol = (
                float(min_sol_output_lamports) / 1_000_000_000.0
                if min_sol_output_lamports > 0
                else 0.0
            )
            if est_sol <= 0.0 and self.execution is not None:
                try:
                    curve_state = await self.execution.get_bonding_curve_state(mint)
                    v_token = int(curve_state.get("virtual_token_reserves", 0))
                    v_sol = int(curve_state.get("virtual_sol_reserves", 0))
                    if v_token > 0 and v_sol > 0:
                        eff_slip = (
                            resolved_slippage
                            if resolved_slippage is not None
                            else getattr(self.execution, "default_slippage_bps", 250)
                        )
                        lamports = self.execution.calculate_sell_sol_output(
                            token_amount,
                            v_token,
                            v_sol,
                            slippage_bps=eff_slip,
                        )
                        est_sol = float(lamports) / 1_000_000_000.0
                except Exception:
                    pass
            return ExecutionResult(
                success=True,
                signature=f"dry_run_sell_{mint[:8]}_{int(time.time())}",
                mint=mint,
                is_buy=False,
                amount_sol=est_sol,
                token_amount=token_amount,
                reason=reason,
                dry_run=True,
            )

        async with self.get_lock(mint):
            try:
                bonding_curve, _ = self.execution.get_bonding_curve_pda(mint)
            except Exception as exc:
                logger.warning(
                    "Could not compute bonding curve PDA for sell on %s: %s", mint, exc
                )
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error=f"sell_pda_failed: {exc}",
                )

            effective_slippage_bps = (
                resolved_slippage
                if resolved_slippage is not None
                else self.execution.default_slippage_bps
            )
            min_sol_lamports = min_sol_output_lamports
            if min_sol_lamports <= 0:
                try:
                    curve_state = await self.execution.get_bonding_curve_state(mint)
                    v_token = int(curve_state.get("virtual_token_reserves", 0))
                    v_sol = int(curve_state.get("virtual_sol_reserves", 0))
                    if v_token > 0 and v_sol > 0:
                        min_sol_lamports = self.execution.calculate_sell_sol_output(
                            token_amount,
                            v_token,
                            v_sol,
                            slippage_bps=effective_slippage_bps,
                        )
                except Exception as exc:
                    logger.debug(
                        "Could not compute curve sell output for %s: %s", mint, exc
                    )

            logger.info(
                "Selling %d units of %s (min_sol_lamports=%d, slippage_bps=%d, reason=%s)",
                token_amount,
                mint,
                min_sol_lamports,
                effective_slippage_bps,
                reason,
            )

            try:
                signature = await self.execution.sell(
                    mint,
                    bonding_curve,
                    token_amount,
                    min_sol_output=min_sol_lamports,
                    slippage_bps=effective_slippage_bps,
                )
            except Exception as exc:
                logger.warning("Sell transaction failed for %s: %s", mint, exc)
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error=f"sell_tx_failed: {exc}",
                )

            if not signature:
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error="sell_signature_missing",
                )

            confirmed = await self.execution.confirm_transaction(signature)
            if not confirmed:
                logger.warning(
                    "Sell confirmation failed for %s (sig=%s)", mint, signature
                )
                return ExecutionResult(
                    success=False,
                    signature=signature,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error="sell_confirmation_failed",
                )

            est_sol = (
                float(min_sol_lamports) / 1_000_000_000.0
                if min_sol_lamports > 0
                else 0.0
            )
            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=False,
                amount_sol=est_sol,
                token_amount=token_amount,
                reason=reason,
            )

    async def execute_raydium_buy(
        self,
        mint: str,
        pool_keys: RaydiumPoolKeys,
        amount_sol: float,
        *,
        slippage_bps: int | None = None,
        reason: str = "raydium_graduation_snipe",
        dry_run: bool | None = None,
    ) -> ExecutionResult:
        is_dry_run = self.dry_run if dry_run is None else dry_run

        if is_dry_run:
            logger.info("DRY RUN RAYDIUM BUY: %s @ %.4f SOL", mint, amount_sol)
            return ExecutionResult(
                success=True,
                signature=f"dry_run_raydium_buy_{mint[:8]}_{int(time.time())}",
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=100_000_000,
                reason=reason,
                dry_run=True,
            )

        async with self.get_lock(mint):
            logger.info(
                "Executing Raydium snipe for %s with %.4f SOL", mint, amount_sol
            )
            try:
                signature = await self.execution.swap_raydium(
                    pool_keys=pool_keys,
                    amount_in=int(amount_sol * 1_000_000_000),
                    is_buy=True,
                    slippage_bps=slippage_bps,
                )
            except Exception as exc:
                logger.warning("Raydium buy transaction failed for %s: %s", mint, exc)
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error=f"raydium_buy_failed: {exc}",
                )

            if not signature:
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error="raydium_buy_signature_missing",
                )

            confirmed = await self.execution.confirm_transaction(signature)
            if not confirmed:
                logger.warning(
                    "Raydium buy confirmation failed for %s (sig=%s)", mint, signature
                )
                return ExecutionResult(
                    success=False,
                    signature=signature,
                    mint=mint,
                    is_buy=True,
                    amount_sol=amount_sol,
                    reason=reason,
                    error="raydium_buy_confirmation_failed",
                )

            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=0,
                reason=reason,
            )

    async def execute_raydium_sell(
        self,
        mint: str,
        pool_keys: RaydiumPoolKeys,
        token_amount: int,
        *,
        slippage_bps: int | None = None,
        reason: str = "raydium_exit",
        dry_run: bool | None = None,
    ) -> ExecutionResult:
        is_dry_run = self.dry_run if dry_run is None else dry_run

        if is_dry_run:
            logger.info("DRY RUN RAYDIUM SELL: %s for %d tokens", mint, token_amount)
            return ExecutionResult(
                success=True,
                signature=f"dry_run_raydium_sell_{mint[:8]}_{int(time.time())}",
                mint=mint,
                is_buy=False,
                token_amount=token_amount,
                reason=reason,
                dry_run=True,
            )

        async with self.get_lock(mint):
            logger.info("Executing Raydium sell for %s (%d tokens)", mint, token_amount)
            try:
                signature = await self.execution.swap_raydium(
                    pool_keys=pool_keys,
                    amount_in=token_amount,
                    is_buy=False,
                    slippage_bps=slippage_bps,
                )
            except Exception as exc:
                logger.warning("Raydium sell transaction failed for %s: %s", mint, exc)
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error=f"raydium_sell_failed: {exc}",
                )

            if not signature:
                return ExecutionResult(
                    success=False,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error="raydium_sell_signature_missing",
                )

            confirmed = await self.execution.confirm_transaction(signature)
            if not confirmed:
                logger.warning(
                    "Raydium sell confirmation failed for %s (sig=%s)", mint, signature
                )
                return ExecutionResult(
                    success=False,
                    signature=signature,
                    mint=mint,
                    is_buy=False,
                    token_amount=token_amount,
                    reason=reason,
                    error="raydium_sell_confirmation_failed",
                )

            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=False,
                token_amount=token_amount,
                reason=reason,
            )
