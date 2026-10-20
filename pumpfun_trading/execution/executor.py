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
from pumpfun_trading.sdk.costs import (
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
)
from pumpfun_trading.sdk.curve import (
    INITIAL_VIRTUAL_SOL_LAMPORTS,
    INITIAL_VIRTUAL_TOKEN_RAW,
    calculate_buy_tokens_out,
    calculate_market_cap_sol,
    calculate_sell_sol_out,
)
from pumpfun_trading.sdk.execution import (
    PUMP_DEFAULT_FEE_BPS,
    MayhemModeCurveError,
    NonStandardCurveError,
    NotPumpFunCurveError,
    PumpFunExecutionClient,
)
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
    # Fees, tip and rent of the trade transaction (FEAT-49); ``None`` if unknown.
    costs: TransactionCosts | None = None


class OrderExecutor:
    """Handles low-level order creation, signing, Jito MEV bundling, retry loops, and direct RPC execution."""

    # Post-trade balance reads lag the confirmation; poll a few times (BUG-49/73).
    balance_retry_attempts: int = 3
    balance_retry_delay_seconds: float = 0.5
    # Upper bound for reading fees/tips from getTransaction after a fill.
    cost_capture_timeout_seconds: float = 8.0

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
        # Mints whose closing sell failed; later sells skip the close (BUG-96).
        self._close_disabled_mints: set[str] = set()

    def get_lock(self, mint: str) -> asyncio.Lock:
        if mint not in self._locks:
            self._locks[mint] = asyncio.Lock()
        return self._locks[mint]

    async def _capture_costs(
        self, signature: str, mint: str, *, is_buy: bool
    ) -> TransactionCosts | None:
        """Real fee, tip, rent and swap amount from the transaction (FEAT-49)."""
        getter = getattr(self.execution, "get_transaction_costs", None)
        if getter is None:
            return None
        try:
            costs = await asyncio.wait_for(
                getter(signature, mint, is_buy=is_buy),
                timeout=self.cost_capture_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Could not read costs of %s (%s): %s", signature, mint, exc)
            return None
        return costs if isinstance(costs, TransactionCosts) else None

    def _model_costs(
        self, *, rent_lamports: int = 0, signature: str | None = None
    ) -> TransactionCosts | None:
        """Modelled fee, tip and rent for paper trades and live fallbacks."""
        model = getattr(self.execution, "model_trade_costs", None)
        if model is None:
            return None
        try:
            costs = model(rent_lamports=rent_lamports, signature=signature)
        except Exception as exc:
            logger.debug("Could not model trade costs: %s", exc)
            return None
        return costs if isinstance(costs, TransactionCosts) else None

    def _should_close_token_account(
        self, mint: str, token_amount: int, pre_tokens: int | None
    ) -> bool:
        """Close only when the sell empties the account; a non-empty close fails."""
        return (
            bool(getattr(self.config, "close_token_account_on_full_exit", True))
            and mint not in self._close_disabled_mints
            and pre_tokens is not None
            and token_amount > 0
            and pre_tokens == token_amount
        )

    def _fee_bps(self) -> int:
        fee = getattr(self.execution, "pump_fee_bps", PUMP_DEFAULT_FEE_BPS)
        return fee if isinstance(fee, int) else PUMP_DEFAULT_FEE_BPS

    async def _fetch_curve_reserves(
        self, mint: str, *, reject_non_standard: bool = False
    ) -> tuple[int, int] | None:
        """Returns live ``(virtual_sol_lamports, virtual_token_raw)`` or ``None``.

        With ``reject_non_standard`` a curve that fails the layout checks raises
        :class:`NonStandardCurveError` (BUG-104), a mayhem-mode curve raises
        :class:`MayhemModeCurveError` unless ``skip_mayhem_mode`` is off, and a mint without a curve owned
        by the Pump.fun program raises :class:`NotPumpFunCurveError` (BUG-108),
        instead of returning ``None``.
        """
        if self.execution is None:
            return None
        try:
            state = await self.execution.get_bonding_curve_state(mint)
            if (
                reject_non_standard
                and bool(getattr(self.config, "skip_mayhem_mode", True))
                and state.get("is_mayhem_mode") is True
            ):
                raise MayhemModeCurveError(f"curve of {mint} is in mayhem mode")
            v_sol = int(state.get("virtual_sol_reserves", 0))
            v_token = int(state.get("virtual_token_reserves", 0))
        except (NonStandardCurveError, NotPumpFunCurveError) as exc:
            if reject_non_standard:
                raise
            logger.debug("Curve reserves unavailable for %s: %s", mint, exc)
            return None
        except Exception as exc:
            logger.debug("Curve reserves unavailable for %s: %s", mint, exc)
            return None
        if v_sol <= 0 or v_token <= 0:
            return None
        return v_sol, v_token

    def _paper_entry_slippage_bps(self) -> int:
        value = getattr(self.config, "paper_entry_slippage_bps", 0)
        if not isinstance(value, int):
            return 0
        return max(0, min(5_000, value))

    @staticmethod
    def _entry_drift(
        reserves: tuple[int, int] | None, signal_market_cap_sol: float | None
    ) -> float | None:
        """Curve market cap now against the signal's, as a share (``0.08`` = +8%)."""
        if reserves is None or not signal_market_cap_sol or signal_market_cap_sol <= 0:
            return None
        current = calculate_market_cap_sol(reserves[0], reserves[1])
        if current <= 0:
            return None
        return float(current) / float(signal_market_cap_sol) - 1.0

    @staticmethod
    def _drift_refused_buy(
        mint: str,
        amount_sol: float,
        reason: str,
        drift: float,
        limit: float,
        dry_run: bool,
    ) -> ExecutionResult:
        """A momentum buy skipped because the price ran away from the signal."""
        logger.info(
            "Skipping buy of %s: curve moved %+.1f%% since the signal (limit %.1f%%)",
            mint,
            drift * 100.0,
            limit * 100.0,
        )
        return ExecutionResult(
            success=False,
            mint=mint,
            is_buy=True,
            amount_sol=amount_sol,
            reason=reason,
            error=f"entry_drift: {drift:+.4f} > {limit:.4f}",
            dry_run=dry_run,
            metadata={"fill_drift_pct": round(drift, 4)},
        )

    @staticmethod
    def _refused_buy(
        mint: str, amount_sol: float, reason: str, exc: Exception, dry_run: bool
    ) -> ExecutionResult:
        """A buy refused because the curve is not a standard Pump.fun curve."""
        logger.warning("Skipping buy of %s: %s", mint, exc)
        if isinstance(exc, NotPumpFunCurveError):
            kind = "not_pump_fun"
        elif isinstance(exc, MayhemModeCurveError):
            kind = "mayhem_mode"
        else:
            kind = "non_standard_curve"
        return ExecutionResult(
            success=False,
            mint=mint,
            is_buy=True,
            amount_sol=amount_sol,
            reason=reason,
            error=f"{kind}: {exc}",
            dry_run=dry_run,
        )

    def _resolve_dynamic_slippage(
        self,
        mint: str,
        notional_sol: float,
        *,
        is_buy: bool,
        urgency: str,
        reserves: tuple[int, int] | None,
    ) -> DynamicSlippageResult:
        """Resolve slippage from live reserves and the real SOL notional (BUG-52)."""
        v_sol_sol: float | None = None
        v_token: int | None = None
        if reserves is not None:
            v_sol_sol = reserves[0] / 1_000_000_000.0
            v_token = reserves[1]
            try:
                self.execution_policy.record_curve_update(mint, v_sol_sol, v_token)
            except Exception as exc:
                logger.debug("Could not record curve update for %s: %s", mint, exc)
        return self.execution_policy.resolve_parameters(
            mint,
            notional_sol,
            virtual_sol_reserves=v_sol_sol,
            virtual_token_reserves=v_token,
            is_buy=is_buy,
            urgency=urgency,
        )

    def _estimate_buy_tokens(
        self, amount_sol: float, reserves: tuple[int, int] | None
    ) -> int:
        """Expected fill from the pre-trade curve (fee-adjusted, no slippage haircut)."""
        v_sol, v_token = reserves or (
            INITIAL_VIRTUAL_SOL_LAMPORTS,
            INITIAL_VIRTUAL_TOKEN_RAW,
        )
        lamports = int(amount_sol * 1_000_000_000)
        return calculate_buy_tokens_out(
            lamports, v_sol, v_token, fee_bps=self._fee_bps()
        )

    def _estimate_sell_lamports(
        self, token_amount: int, reserves: tuple[int, int] | None
    ) -> int:
        """Expected proceeds from the pre-trade curve (fee-adjusted, no slippage haircut)."""
        if reserves is None or token_amount <= 0:
            return 0
        v_sol, v_token = reserves
        return calculate_sell_sol_out(
            token_amount, v_token, v_sol, fee_bps=self._fee_bps()
        )

    async def _read_token_balance(self, mint: str, attempts: int = 1) -> int | None:
        """Token balance in raw units, or ``None`` if every read failed (BUG-35/73)."""
        for attempt in range(max(1, attempts)):
            try:
                return int(await self.execution.get_token_balance(mint))
            except Exception as exc:
                logger.debug("Token balance read failed for %s: %s", mint, exc)
            if attempt + 1 < attempts:
                await asyncio.sleep(self.balance_retry_delay_seconds)
        return None

    async def _read_sol_lamports(self) -> int | None:
        try:
            balance = await self.execution.get_balance_sol()
            if not isinstance(balance, (int, float)):
                return None
            return int(round(float(balance) * 1_000_000_000))
        except Exception as exc:
            logger.debug("SOL balance read failed: %s", exc)
            return None

    async def _detect_token_increase(self, mint: str, pre: int | None) -> int | None:
        """Poll until the token balance rises above ``pre``; returns the delta."""
        if pre is None:
            return None
        for attempt in range(self.balance_retry_attempts):
            post = await self._read_token_balance(mint)
            if post is not None and post > pre:
                return post - pre
            if attempt + 1 < self.balance_retry_attempts:
                await asyncio.sleep(self.balance_retry_delay_seconds)
        return None

    async def _detect_token_decrease(
        self, mint: str, pre: int | None, token_amount: int
    ) -> bool:
        """True once the token balance dropped by at least ``token_amount``."""
        if pre is None or token_amount <= 0:
            return False
        for attempt in range(self.balance_retry_attempts):
            post = await self._read_token_balance(mint)
            if post is not None and pre - post >= token_amount:
                return True
            if attempt + 1 < self.balance_retry_attempts:
                await asyncio.sleep(self.balance_retry_delay_seconds)
        return False

    async def _measure_sol_proceeds(
        self, pre_lamports: int | None, expected_lamports: int
    ) -> int | None:
        """Net lamports received, from the wallet SOL balance before vs after (BUG-48).

        Deltas above 1.5x the expected curve output are rejected, since another
        trade may have moved the wallet balance concurrently.
        """
        if pre_lamports is None:
            return None
        for attempt in range(self.balance_retry_attempts):
            post = await self._read_sol_lamports()
            if post is not None:
                delta = post - pre_lamports
                if delta > 0 and (
                    expected_lamports <= 0 or delta <= expected_lamports * 1.5
                ):
                    return delta
            if attempt + 1 < self.balance_retry_attempts:
                await asyncio.sleep(self.balance_retry_delay_seconds)
        return None

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
        signal_market_cap_sol: float | None = None,
        max_entry_drift_pct: float = 0.0,
    ) -> ExecutionResult:
        """Buy ``amount_sol`` of ``mint`` (paper or live).

        With ``max_entry_drift_pct`` > 0 and a ``signal_market_cap_sol`` the buy
        is skipped when the curve at the fill is more than that share above the
        signal; live, the slippage is also capped at the remaining headroom.
        """
        is_dry_run = self.dry_run if dry_run is None else dry_run
        drift_limit = max(0.0, float(max_entry_drift_pct or 0.0))
        if not signal_market_cap_sol or signal_market_cap_sol <= 0:
            drift_limit = 0.0

        try:
            reserves = await self._fetch_curve_reserves(mint, reject_non_standard=True)
        except (NonStandardCurveError, NotPumpFunCurveError) as exc:
            return self._refused_buy(mint, amount_sol, reason, exc, is_dry_run)
        resolved_slippage = slippage_bps
        dynamic_params: DynamicSlippageResult | None = None
        if resolved_slippage is None and getattr(
            self.config, "enable_dynamic_slippage", True
        ):
            dynamic_params = self._resolve_dynamic_slippage(
                mint,
                amount_sol,
                is_buy=True,
                urgency=urgency,
                reserves=reserves,
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
            delay = float(getattr(self.config, "paper_entry_delay_seconds", 0.0) or 0.0)
            if delay > 0 and reserves is not None:
                # A live buy lands after screening and confirmation; price the
                # paper fill from the curve as it is then, not at the signal.
                await asyncio.sleep(delay)
                try:
                    reserves = (
                        await self._fetch_curve_reserves(mint, reject_non_standard=True)
                        or reserves
                    )
                except (NonStandardCurveError, NotPumpFunCurveError) as exc:
                    return self._refused_buy(mint, amount_sol, reason, exc, True)
            drift = self._entry_drift(reserves, signal_market_cap_sol)
            if drift_limit > 0 and drift is not None and drift > drift_limit:
                return self._drift_refused_buy(
                    mint, amount_sol, reason, drift, drift_limit, True
                )
            penalty_bps = self._paper_entry_slippage_bps()
            simulated_token_amount = self._estimate_buy_tokens(amount_sol, reserves)
            if simulated_token_amount <= 0:
                simulated_token_amount = 100_000_000
            simulated_token_amount = (
                simulated_token_amount * (10_000 - penalty_bps) // 10_000
            )

            dry_signature = f"dry_run_buy_{mint[:8]}_{int(time.time())}"
            metadata: dict[str, Any] = {}
            if reserves is not None:
                # Paper entries are priced from the same curve as exits (BUG-104),
                # worsened by the configured latency penalty.
                metadata["entry_market_cap_sol"] = (
                    calculate_market_cap_sol(reserves[0], reserves[1])
                    * 10_000
                    / (10_000 - penalty_bps)
                )
            if penalty_bps or delay > 0:
                metadata["paper_entry_slippage_bps"] = penalty_bps
                metadata["paper_entry_delay_seconds"] = delay
            if drift_limit > 0 and drift is not None:
                metadata["fill_drift_pct"] = round(drift, 4)
            return ExecutionResult(
                success=True,
                signature=dry_signature,
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=simulated_token_amount,
                reason=reason,
                dry_run=True,
                metadata=metadata,
                # A fresh position pays the token-account rent (FEAT-49).
                costs=self._model_costs(
                    rent_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS,
                    signature=dry_signature,
                ),
            )

        if drift_limit > 0:
            drift = self._entry_drift(reserves, signal_market_cap_sol)
            if drift is not None:
                if drift > drift_limit:
                    return self._drift_refused_buy(
                        mint, amount_sol, reason, drift, drift_limit, False
                    )
                # The fill may not land above signal * (1 + limit).
                headroom_bps = int(((1.0 + drift_limit) / (1.0 + drift) - 1.0) * 10_000)
                headroom_bps = max(1, headroom_bps)
                resolved_slippage = (
                    headroom_bps
                    if resolved_slippage is None
                    else min(int(resolved_slippage), headroom_bps)
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
            # Pre-trade snapshot so the fill is post - pre, not the whole ATA (BUG-49).
            pre_tokens = await self._read_token_balance(mint)
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
            acquired = await self._detect_token_increase(mint, pre_tokens)
            if not confirmed and acquired is None:
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
            if not confirmed:
                # Confirmation polling timed out but the tokens arrived (BUG-73).
                logger.warning(
                    "Buy %s for %s landed after confirmation timeout", signature, mint
                )

            if acquired is not None:
                acquired_tokens, fill_source = acquired, "balance_delta"
            else:
                acquired_tokens = self._estimate_buy_tokens(amount_sol, reserves)
                fill_source = "pre_trade_quote"

            costs = await self._capture_costs(signature, mint, is_buy=True)
            spent_sol = amount_sol
            if costs is not None and costs.swap_sol and costs.swap_sol > 0:
                # Actual SOL paid into the curve, not the requested size.
                spent_sol = costs.swap_sol
            if costs is None:
                rent = TOKEN_ACCOUNT_RENT_LAMPORTS if pre_tokens == 0 else 0
                costs = self._model_costs(rent_lamports=rent, signature=signature)
            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=True,
                amount_sol=spent_sol,
                token_amount=acquired_tokens,
                reason=reason,
                metadata={
                    "fill_source": fill_source,
                    "confirmed": bool(confirmed),
                    "requested_sol": amount_sol,
                },
                costs=costs,
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
        close_token_account: bool = False,
    ) -> ExecutionResult:
        """Sell on the bonding curve.

        ``close_token_account`` marks a full exit: the token account is closed in
        the same transaction to refund its rent (BUG-96), but only if the live
        balance equals ``token_amount``.
        """
        is_dry_run = self.dry_run if dry_run is None else dry_run

        effective_urgency = urgency
        if effective_urgency == "normal" and (
            "emergency" in reason.lower()
            or "panic" in reason.lower()
            or "stop_loss" in reason.lower()
        ):
            effective_urgency = "emergency"

        reserves = await self._fetch_curve_reserves(mint)
        expected_lamports = self._estimate_sell_lamports(token_amount, reserves)
        resolved_slippage = slippage_bps
        if resolved_slippage is None and getattr(
            self.config, "enable_dynamic_slippage", True
        ):
            notional_lamports = expected_lamports or min_sol_output_lamports
            dynamic_params = self._resolve_dynamic_slippage(
                mint,
                (
                    (notional_lamports / 1_000_000_000.0)
                    if notional_lamports > 0
                    else 0.01
                ),
                is_buy=False,
                urgency=effective_urgency,
                reserves=reserves,
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
            if est_sol <= 0.0 and reserves is not None:
                try:
                    eff_slip = (
                        resolved_slippage
                        if resolved_slippage is not None
                        else getattr(self.execution, "default_slippage_bps", 250)
                    )
                    lamports = self.execution.calculate_sell_sol_output(
                        token_amount,
                        reserves[1],
                        reserves[0],
                        slippage_bps=eff_slip,
                    )
                    est_sol = float(lamports) / 1_000_000_000.0
                except Exception:
                    pass
            dry_signature = f"dry_run_sell_{mint[:8]}_{int(time.time())}"
            closes = close_token_account and bool(
                getattr(self.config, "close_token_account_on_full_exit", True)
            )
            return ExecutionResult(
                success=True,
                signature=dry_signature,
                mint=mint,
                is_buy=False,
                amount_sol=est_sol,
                token_amount=token_amount,
                reason=reason,
                dry_run=True,
                metadata={"closed_token_account": closes},
                costs=self._model_costs(
                    rent_lamports=-TOKEN_ACCOUNT_RENT_LAMPORTS if closes else 0,
                    signature=dry_signature,
                ),
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
            if min_sol_lamports <= 0 and reserves is not None:
                try:
                    min_sol_lamports = self.execution.calculate_sell_sol_output(
                        token_amount,
                        reserves[1],
                        reserves[0],
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

            pre_sol = await self._read_sol_lamports()
            pre_tokens = await self._read_token_balance(mint)
            closes = close_token_account and self._should_close_token_account(
                mint, token_amount, pre_tokens
            )
            try:
                if closes:
                    signature = await self.execution.sell(
                        mint,
                        bonding_curve,
                        token_amount,
                        min_sol_output=min_sol_lamports,
                        slippage_bps=effective_slippage_bps,
                        close_token_account=True,
                    )
                else:
                    signature = await self.execution.sell(
                        mint,
                        bonding_curve,
                        token_amount,
                        min_sol_output=min_sol_lamports,
                        slippage_bps=effective_slippage_bps,
                    )
            except Exception as exc:
                if closes:
                    self._close_disabled_mints.add(mint)
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
            if not confirmed and not await self._detect_token_decrease(
                mint, pre_tokens, token_amount
            ):
                if closes:
                    # Retry without the close in case it made the sell fail.
                    self._close_disabled_mints.add(mint)
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
            if not confirmed:
                # Confirmation polling timed out but the tokens left (BUG-73).
                logger.warning(
                    "Sell %s for %s landed after confirmation timeout", signature, mint
                )

            self._close_disabled_mints.discard(mint)
            costs = await self._capture_costs(signature, mint, is_buy=False)
            proceeds: int | None
            if (
                costs is not None
                and costs.source == COST_SOURCE_TRANSACTION_META
                and costs.swap_lamports is not None
                and costs.swap_lamports > 0
            ):
                # Exact swap output from the transaction meta (BUG-48, FEAT-49).
                proceeds, proceeds_source = costs.swap_lamports, "transaction_meta"
            else:
                proceeds = await self._measure_sol_proceeds(pre_sol, expected_lamports)
                if proceeds is not None:
                    # The wallet delta is already net of fee and tip.
                    proceeds_source, costs = "sol_balance_delta", None
                else:
                    if expected_lamports > 0:
                        proceeds, proceeds_source = expected_lamports, "pre_trade_quote"
                    else:
                        proceeds = max(0, min_sol_lamports)
                        proceeds_source = "min_out"
                    costs = self._model_costs(
                        rent_lamports=-TOKEN_ACCOUNT_RENT_LAMPORTS if closes else 0,
                        signature=signature,
                    )
            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=False,
                amount_sol=float(proceeds) / 1_000_000_000.0,
                token_amount=token_amount,
                reason=reason,
                metadata={
                    "proceeds_source": proceeds_source,
                    "confirmed": bool(confirmed),
                    "closed_token_account": closes,
                },
                costs=costs,
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
            dry_signature = f"dry_run_raydium_buy_{mint[:8]}_{int(time.time())}"
            return ExecutionResult(
                success=True,
                signature=dry_signature,
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=100_000_000,
                reason=reason,
                dry_run=True,
                costs=self._model_costs(
                    rent_lamports=TOKEN_ACCOUNT_RENT_LAMPORTS,
                    signature=dry_signature,
                ),
            )

        async with self.get_lock(mint):
            logger.info(
                "Executing Raydium snipe for %s with %.4f SOL", mint, amount_sol
            )
            pre_tokens = await self._read_token_balance(mint)
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
            acquired = await self._detect_token_increase(mint, pre_tokens)
            if not confirmed and acquired is None:
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

            # Record the token balance delta, not 0 (BUG-50). Without a pre-trade
            # snapshot the full post-trade balance is the best available figure.
            fill_source = "balance_delta"
            if acquired is None:
                acquired = await self._read_token_balance(
                    mint, attempts=self.balance_retry_attempts
                )
                fill_source = "post_trade_balance"
            costs = await self._capture_costs(signature, mint, is_buy=True)
            if costs is None:
                rent = TOKEN_ACCOUNT_RENT_LAMPORTS if pre_tokens == 0 else 0
                costs = self._model_costs(rent_lamports=rent, signature=signature)
            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=True,
                amount_sol=amount_sol,
                token_amount=max(0, acquired or 0),
                reason=reason,
                metadata={"fill_source": fill_source, "confirmed": bool(confirmed)},
                costs=costs,
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
            dry_signature = f"dry_run_raydium_sell_{mint[:8]}_{int(time.time())}"
            return ExecutionResult(
                success=True,
                signature=dry_signature,
                mint=mint,
                is_buy=False,
                token_amount=token_amount,
                reason=reason,
                dry_run=True,
                costs=self._model_costs(signature=dry_signature),
            )

        async with self.get_lock(mint):
            logger.info("Executing Raydium sell for %s (%d tokens)", mint, token_amount)
            pre_sol = await self._read_sol_lamports()
            pre_tokens = await self._read_token_balance(mint)
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
            if not confirmed and not await self._detect_token_decrease(
                mint, pre_tokens, token_amount
            ):
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

            # Proceeds are the wallet delta, so fee and tip are already netted out.
            proceeds = await self._measure_sol_proceeds(pre_sol, 0)
            return ExecutionResult(
                success=True,
                signature=signature,
                mint=mint,
                is_buy=False,
                amount_sol=float(proceeds or 0) / 1_000_000_000.0,
                token_amount=token_amount,
                reason=reason,
                metadata={
                    "proceeds_source": (
                        "sol_balance_delta" if proceeds is not None else "unknown"
                    ),
                    "confirmed": bool(confirmed),
                },
            )
