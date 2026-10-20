"""PumpSwap reads and sell transactions for graduated Pump.fun coins (BUG-123)."""

import base64
from typing import Any, Optional

from solders.instruction import Instruction
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import CloseAccountParams
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
)

from .execution_types import WSOL_MINT_STR
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


class PumpSwapExecutionMixin(TransactionTransportMixin):
    """Find a graduated coin's canonical PumpSwap pool, price it and sell into it."""

    async def _get_accounts(
        self, addresses: list[str], *, timeout_seconds: float = 5.0
    ) -> list[Optional[dict[str, Any]]]:
        parsed = await self._request_rpc_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    addresses,
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            },
            max_retries=2,
            timeout_seconds=timeout_seconds,
        )
        values = (parsed.get("result") or {}).get("value") or []
        return [
            values[index] if index < len(values) else None
            for index in range(len(addresses))
        ]

    @staticmethod
    def _account_bytes(value: Optional[dict[str, Any]]) -> bytes:
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
        slippage_bps: Optional[int] = None,
        tip_lamports: Optional[int] = None,
        close_token_account: bool = False,
    ) -> VersionedTransaction:
        """PumpSwap sell into a WSOL ATA, then unwrap; optionally close the token account.

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
        slippage_bps: Optional[int] = None,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
        close_token_account: bool = False,
    ) -> str:
        """Sell a graduated coin into its PumpSwap pool (Jito bundle or RPC)."""
        should_jito = self.use_jito if use_jito is None else use_jito
        tip_lamports = None
        if should_jito:
            tip_lamports = await self.calculate_dynamic_jito_tip(
                trade_amount_sol=0.01, conviction_score=conviction_score
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
