"""PumpSwap reads and sell transactions for graduated Pump.fun coins (BUG-123)."""

import base64
from collections.abc import Sequence
from typing import Any

from solders.instruction import Instruction
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
)
from spl.token.models import CloseAccountParams

from .execution_types import GET_MULTIPLE_ACCOUNTS_LIMIT, WSOL_MINT_STR
from .pumpswap import (
    PUMP_AMM_PROGRAM_ID,
    PumpSwapGlobalConfig,
    PumpSwapPool,
    PumpSwapPoolUnavailableError,
    build_pumpswap_sell_instruction,
    canonical_pool_address,
    decode_global_config,
    decode_pool,
    global_config_address,
    pumpswap_market_cap_sol,
    pumpswap_sell_quote,
    token_account_amount,
)
from .transport import TransactionTransportMixin

# Accounts read per observed pool on a batched poll: the pool and its two vaults.
POOL_ACCOUNTS_PER_MINT = 3


class PumpSwapExecutionMixin(TransactionTransportMixin):
    """Find a graduated coin's canonical PumpSwap pool, price it and sell into it."""

    # mint -> (pool, base vault, quote vault), filled by the first batched read
    # (FEAT-73); a pool's vault addresses never change.
    _pumpswap_vaults: dict[str, tuple[str, str, str]]
    # Mints whose pool holds SOL as its base and the coin as its quote
    # (FEAT-80: how most non-graduate PumpSwap pools are made).
    _pumpswap_sol_base: set[str]

    @staticmethod
    def _account_bytes(value: dict[str, Any] | None) -> bytes:
        return base64.b64decode(((value or {}).get("data") or [""])[0])

    async def get_pumpswap_pool(
        self, mint: str
    ) -> tuple[PumpSwapPool, PumpSwapGlobalConfig, dict[str, Any]]:
        """The canonical pool, the fee config and the raw vault accounts.

        Raises :class:`PumpSwapPoolUnavailableError` while the pool does not
        exist yet or is not owned by the PumpSwap program.
        """
        self.is_valid_mint(mint)
        pool_address = str(canonical_pool_address(mint))
        config_address = str(global_config_address())
        pool_value, config_value = await self._get_accounts(
            [pool_address, config_address]
        )
        for name, value in (("pool", pool_value), ("global_config", config_value)):
            if not value:
                raise PumpSwapPoolUnavailableError(
                    f"PumpSwap {name} for {mint} not found on-chain"
                )
            if str(value.get("owner") or "") != PUMP_AMM_PROGRAM_ID:
                raise PumpSwapPoolUnavailableError(
                    f"PumpSwap {name} for {mint} is not owned by the PumpSwap program"
                )
        pool = decode_pool(pool_address, self._account_bytes(pool_value))
        if pool.base_mint != mint or pool.quote_mint != WSOL_MINT_STR:
            raise PumpSwapPoolUnavailableError(
                f"PumpSwap pool {pool_address} does not pair {mint} with SOL"
            )
        config = decode_global_config(self._account_bytes(config_value))
        base_vault, quote_vault = await self._get_accounts(
            [pool.base_vault, pool.quote_vault]
        )
        if not base_vault or not quote_vault:
            raise PumpSwapPoolUnavailableError(
                f"PumpSwap vaults for {mint} not found on-chain"
            )
        return pool, config, {"base": base_vault, "quote": quote_vault}

    async def get_pumpswap_market_state(self, mint: str) -> dict[str, Any]:
        """Reserves, fees and market cap of the coin's PumpSwap pool.

        ``market_cap_sol`` is on the bonding-curve basis, so exits keep comparing
        like with like after graduation.
        """
        pool, config, vaults = await self.get_pumpswap_pool(mint)
        base_reserve = token_account_amount(self._account_bytes(vaults["base"]))
        quote_reserve = (
            token_account_amount(self._account_bytes(vaults["quote"]))
            + pool.virtual_quote_reserves
        )
        if base_reserve <= 0 or quote_reserve <= 0:
            raise PumpSwapPoolUnavailableError(f"PumpSwap pool for {mint} is empty")
        return {
            "pool": pool.address,
            "base_reserve": base_reserve,
            "quote_reserve": quote_reserve,
            "fee_bps": config.total_fee_bps,
            "market_cap_sol": pumpswap_market_cap_sol(base_reserve, quote_reserve),
            "base_token_program": str(vaults["base"].get("owner") or ""),
        }

    def remember_pumpswap_pool(
        self,
        mint: str,
        address: str,
        base_vault: str,
        quote_vault: str,
        *,
        sol_is_base: bool = False,
    ) -> None:
        """Read ``mint`` from this pool from now on (FEAT-80: a new pool that
        is not the mint's canonical one, found by the new-pool feed).
        ``sol_is_base``: the pool holds SOL as its base and ``mint`` as its
        quote, the reverse of a graduation pool."""
        cache = getattr(self, "_pumpswap_vaults", None)
        if cache is None:
            cache = self._pumpswap_vaults = {}
        cache[str(mint)] = (str(address), str(base_vault), str(quote_vault))
        flipped = self._sol_base_mints()
        if sol_is_base:
            flipped.add(str(mint))
        else:
            flipped.discard(str(mint))

    def _sol_base_mints(self) -> set[str]:
        flipped = getattr(self, "_pumpswap_sol_base", None)
        if flipped is None:
            flipped = self._pumpswap_sol_base = set()
        return flipped

    async def get_pumpswap_pool_states(
        self,
        mints: Sequence[str],
        *,
        rejected: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, dict[str, Any]]:
        """Batch-read the canonical PumpSwap pools of graduated coins (FEAT-73).

        The first read of a mint resolves its pool (at most 100 pools per
        ``getMultipleAccounts`` call) and caches the vault addresses; every read
        then fetches the pool and both vaults, 33 mints per call. Returns
        ``pool``, ``base_reserve``, ``quote_reserve`` (with the pool's virtual
        quote reserve) and ``market_cap_sol`` on the curve basis; a drained pool
        is returned with a market cap of 0, not dropped. Every other mint goes
        to ``rejected`` with a reason (``missing``, ``not_pumpswap``,
        ``not_sol_pair``, ``decode_error``). An RPC failure raises.
        """
        unique = list(dict.fromkeys(str(m) for m in mints if m))
        cache = getattr(self, "_pumpswap_vaults", None)
        if cache is None:
            cache = self._pumpswap_vaults = {}
        reasons: dict[str, str] = {}
        unknown = [mint for mint in unique if mint not in cache]
        await self._resolve_pools(unknown, cache, reasons, timeout_seconds)
        known = [mint for mint in unique if mint in cache]
        states = await self._read_pools(known, cache, reasons, timeout_seconds)
        if rejected is not None:
            rejected.update(reasons)
        return states

    async def _resolve_pools(
        self,
        mints: list[str],
        cache: dict[str, tuple[str, str, str]],
        reasons: dict[str, str],
        timeout_seconds: float,
    ) -> None:
        """Find each new mint's canonical pool and cache its vault addresses."""
        for start in range(0, len(mints), GET_MULTIPLE_ACCOUNTS_LIMIT):
            chunk = mints[start : start + GET_MULTIPLE_ACCOUNTS_LIMIT]
            addresses = [str(canonical_pool_address(mint)) for mint in chunk]
            values = await self._get_accounts(
                addresses, timeout_seconds=timeout_seconds
            )
            for mint, address, value in zip(chunk, addresses, values, strict=True):
                pool, reason = self._observed_pool(mint, address, value)
                if pool is None:
                    reasons[mint] = reason
                else:
                    cache[mint] = (address, pool.base_vault, pool.quote_vault)

    async def _read_pools(
        self,
        mints: list[str],
        cache: dict[str, tuple[str, str, str]],
        reasons: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, dict[str, Any]]:
        """Read each cached pool and both its vaults, 33 mints per call."""
        states: dict[str, dict[str, Any]] = {}
        per_call = GET_MULTIPLE_ACCOUNTS_LIMIT // POOL_ACCOUNTS_PER_MINT
        for start in range(0, len(mints), per_call):
            chunk = mints[start : start + per_call]
            addresses = [address for mint in chunk for address in cache[mint]]
            values = await self._get_accounts(
                addresses, timeout_seconds=timeout_seconds
            )
            for index, mint in enumerate(chunk):
                accounts = values[
                    index
                    * POOL_ACCOUNTS_PER_MINT : (index + 1)
                    * POOL_ACCOUNTS_PER_MINT
                ]
                state, reason = self._pool_state(mint, cache[mint][0], accounts)
                if state is None:
                    reasons[mint] = reason
                else:
                    states[mint] = state
        return states

    def _pool_state(
        self, mint: str, address: str, accounts: list[dict[str, Any] | None]
    ) -> tuple[dict[str, Any] | None, str]:
        """The pool's reserves from its pool and vault accounts, or why not."""
        pool_value, base_value, quote_value = accounts
        pool, reason = self._observed_pool(mint, address, pool_value)
        if pool is None:
            return None, reason
        if not base_value or not quote_value:
            return None, "missing"
        try:
            base_amount = token_account_amount(self._account_bytes(base_value))
            quote_amount = token_account_amount(self._account_bytes(quote_value))
        except Exception:
            return None, "decode_error"
        if mint in self._sol_base_mints():
            # SOL is the pool's base (FEAT-80): the coin is the quote side,
            # and the virtual quote reserve (0 on such pools) is not SOL.
            base_reserve, quote_reserve = quote_amount, base_amount
        else:
            base_reserve = base_amount
            quote_reserve = quote_amount + pool.virtual_quote_reserves
        return {
            "pool": pool.address,
            "base_reserve": base_reserve,
            "quote_reserve": quote_reserve,
            "market_cap_sol": pumpswap_market_cap_sol(base_reserve, quote_reserve),
        }, ""

    def _observed_pool(
        self, mint: str, address: str, value: dict[str, Any] | None
    ) -> tuple[PumpSwapPool | None, str]:
        """The decoded canonical pool of ``mint``, or ``None`` and why not."""
        if not value:
            return None, "missing"
        if str(value.get("owner") or "") != PUMP_AMM_PROGRAM_ID:
            return None, "not_pumpswap"
        try:
            pool = decode_pool(address, self._account_bytes(value))
        except Exception:
            return None, "decode_error"
        pair = (pool.base_mint, pool.quote_mint)
        expected = (
            (WSOL_MINT_STR, mint)
            if mint in self._sol_base_mints()
            else (mint, WSOL_MINT_STR)
        )
        if pair != expected:
            return None, "not_sol_pair"
        return pool, ""

    async def quote_pumpswap_sell(
        self, mint: str, token_amount: int, *, slippage_bps: int = 0
    ) -> int:
        """Lamports out for selling ``token_amount`` raw tokens into the pool."""
        state = await self.get_pumpswap_market_state(mint)
        return pumpswap_sell_quote(
            int(token_amount),
            int(state["base_reserve"]),
            int(state["quote_reserve"]),
            fee_bps=int(state["fee_bps"]),
            slippage_bps=slippage_bps,
        )

    async def build_pumpswap_sell_tx(
        self,
        mint: str,
        token_amount: int,
        *,
        slippage_bps: int | None = None,
        tip_lamports: int | None = None,
        close_token_account: bool = False,
    ) -> VersionedTransaction:
        """PumpSwap sell into a WSOL ATA, then unwrap; optionally close the token
        account.

        ``min_quote_amount_out`` always comes from the live pool reserves.
        """
        slippage = self.normalize_slippage_bps(slippage_bps, self.default_slippage_bps)
        pool, config, vaults = await self.get_pumpswap_pool(mint)
        base_reserve = token_account_amount(self._account_bytes(vaults["base"]))
        quote_reserve = (
            token_account_amount(self._account_bytes(vaults["quote"]))
            + pool.virtual_quote_reserves
        )
        min_out = pumpswap_sell_quote(
            int(token_amount),
            base_reserve,
            quote_reserve,
            fee_bps=config.total_fee_bps,
            slippage_bps=slippage,
        )
        if min_out <= 0:
            raise PumpSwapPoolUnavailableError(
                f"PumpSwap quote for {mint} returned zero output"
            )
        base_program = self._to_pubkey(
            str(vaults["base"].get("owner") or "")
            or await self.get_token_program_for_mint(mint)
        )
        wsol_mint = self._to_pubkey(WSOL_MINT_STR)
        wsol_ata = get_associated_token_address(
            self.wallet, wsol_mint, TOKEN_PROGRAM_ID
        )
        instructions: list[Instruction] = [
            create_idempotent_associated_token_account(
                payer=self.wallet, owner=self.wallet, mint=wsol_mint
            ),
            build_pumpswap_sell_instruction(
                pool=pool,
                config=config,
                user=self.wallet,
                base_token_program=base_program,
                quote_token_program=TOKEN_PROGRAM_ID,
                user_quote_account=wsol_ata,
                base_amount_in=int(token_amount),
                min_quote_amount_out=min_out,
            ),
            self._close_account_instruction(wsol_ata, TOKEN_PROGRAM_ID),
        ]
        if close_token_account:
            # A full exit refunds the token account rent too (BUG-96).
            instructions.append(
                self._close_account_instruction(
                    get_associated_token_address(
                        self.wallet, self._to_pubkey(mint), base_program
                    ),
                    base_program,
                )
            )
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    def _close_account_instruction(
        self, account: Pubkey, program: Pubkey
    ) -> Instruction:
        return close_account(
            CloseAccountParams(
                program_id=program,
                account=account,
                dest=self.wallet,
                owner=self.wallet,
            )
        )

    async def pumpswap_sell(
        self,
        mint: str,
        token_amount: int,
        *,
        slippage_bps: int | None = None,
        use_jito: bool | None = None,
        conviction_score: float = 1.0,
        close_token_account: bool = False,
    ) -> str:
        """Sell a graduated coin into its PumpSwap pool (Jito bundle or RPC)."""
        should_jito, tip_lamports = await self.resolve_trade_tip(
            is_buy=False,
            trade_amount_sol=0.01,
            conviction_score=conviction_score,
            use_jito=use_jito,
        )
        tx = await self.build_pumpswap_sell_tx(
            mint,
            token_amount,
            slippage_bps=slippage_bps,
            tip_lamports=tip_lamports,
            close_token_account=close_token_account,
        )
        if should_jito:
            return await self.send_jito_bundle_with_fallback([tx])
        return await self.send_transaction(tx)
