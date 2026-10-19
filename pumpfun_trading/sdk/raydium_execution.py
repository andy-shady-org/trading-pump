"""Raydium AMM v4 swap instruction and transaction builders for graduated tokens."""

from typing import Optional

from solders.instruction import Instruction
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import CloseAccountParams, SyncNativeParams
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
    sync_native,
)

from .raydium import (
    RaydiumPoolKeys,
    build_raydium_swap_instruction,
    calculate_raydium_swap_out,
)
from .execution_types import (
    WSOL_MINT_STR,
    TOKEN_PROGRAM_ID_STR,
)
from .transport import TransactionTransportMixin


class RaydiumExecutionMixin(TransactionTransportMixin):
    """Raydium swaps (wrapped-SOL handling, pool reserves, buy/sell transactions)."""

    def build_raydium_swap_instruction(
        self,
        pool_keys: RaydiumPoolKeys,
        amount_in_lamports: int,
        min_amount_out: int = 1,
        user_source_token_account: Optional[str] = None,
        user_destination_token_account: Optional[str] = None,
        *,
        is_buy: bool = True,
        coin_token_program: Pubkey | str | None = None,
    ) -> Instruction:
        """Construct Raydium AMM v4 swap instruction for this client wallet.

        Buys swap WSOL (pc) ATA -> token (coin) ATA; sells swap token ATA -> WSOL
        ATA (BUG-36).
        """
        pc_ata = str(
            get_associated_token_address(
                self.wallet, self._to_pubkey(pool_keys.pc_mint), TOKEN_PROGRAM_ID
            )
        )
        coin_ata = str(
            get_associated_token_address(
                self.wallet,
                self._to_pubkey(pool_keys.coin_mint),
                self._to_pubkey(coin_token_program or TOKEN_PROGRAM_ID_STR),
            )
        )
        default_source, default_dest = (
            (pc_ata, coin_ata) if is_buy else (coin_ata, pc_ata)
        )
        return build_raydium_swap_instruction(
            pool_keys=pool_keys,
            user_wallet=self.wallet,
            user_source_token_account=user_source_token_account or default_source,
            user_destination_token_account=(
                user_destination_token_account or default_dest
            ),
            amount_in_lamports=amount_in_lamports,
            min_amount_out=min_amount_out,
        )

    def _wsol_open_instructions(self, wsol_ata: Pubkey, lamports: int) -> list:
        """Create (idempotently) the WSOL ATA and optionally wrap ``lamports`` into it."""
        wsol_mint = self._to_pubkey(WSOL_MINT_STR)
        instructions: list = [
            create_idempotent_associated_token_account(
                payer=self.wallet, owner=self.wallet, mint=wsol_mint
            )
        ]
        if lamports > 0:
            instructions.append(
                transfer(
                    TransferParams(
                        from_pubkey=self.wallet, to_pubkey=wsol_ata, lamports=lamports
                    )
                )
            )
            instructions.append(
                sync_native(
                    SyncNativeParams(program_id=TOKEN_PROGRAM_ID, account=wsol_ata)
                )
            )
        return instructions

    def _wsol_close_instruction(self, wsol_ata: Pubkey) -> Instruction:
        """Close the WSOL ATA, unwrapping its lamports back to the wallet."""
        return close_account(
            CloseAccountParams(
                program_id=TOKEN_PROGRAM_ID,
                account=wsol_ata,
                dest=self.wallet,
                owner=self.wallet,
            )
        )

    async def _raydium_reserves(self, pool_keys: RaydiumPoolKeys) -> tuple[int, int]:
        """Returns (coin_reserve, pc_reserve) in raw units from the pool vaults."""
        reserves = []
        for vault in (
            pool_keys.pool_coin_token_account,
            pool_keys.pool_pc_token_account,
        ):
            parsed = await self._request_rpc_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountBalance",
                    "params": [str(vault), {"commitment": "confirmed"}],
                }
            )
            value = (parsed.get("result") or {}).get("value") or {}
            if "amount" not in value:
                raise RuntimeError(f"Raydium vault balance unavailable: {vault}")
            reserves.append(int(value["amount"]))
        return reserves[0], reserves[1]

    async def build_raydium_buy_tx(
        self,
        pool_keys: RaydiumPoolKeys,
        sol_amount: float,
        *,
        slippage_bps: Optional[int] = None,
        min_amount_out: int = 1,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        """Construct a Raydium AMM buy: wrap SOL -> swap -> unwrap (BUG-51).

        ``min_amount_out`` is derived from live pool reserves and ``slippage_bps``
        unless the caller passes a stricter value.
        """
        lamports = self.sol_to_lamports(sol_amount)
        slippage = self.normalize_slippage_bps(slippage_bps, self.default_slippage_bps)
        coin_reserve, pc_reserve = await self._raydium_reserves(pool_keys)
        _, quoted_min_out = calculate_raydium_swap_out(
            lamports, pc_reserve, coin_reserve, slippage_bps=slippage
        )
        if quoted_min_out <= 0:
            raise RuntimeError("Raydium quote returned zero output")
        min_out = max(int(min_amount_out), quoted_min_out)

        coin_program = await self.get_token_program_for_mint(pool_keys.coin_mint)
        wsol_ata = get_associated_token_address(
            self.wallet, self._to_pubkey(WSOL_MINT_STR), TOKEN_PROGRAM_ID
        )
        instructions = self._wsol_open_instructions(wsol_ata, lamports)
        instructions.append(
            create_idempotent_associated_token_account(
                payer=self.wallet,
                owner=self.wallet,
                mint=self._to_pubkey(pool_keys.coin_mint),
                token_program_id=coin_program,
            )
        )
        instructions.append(
            self.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=lamports,
                min_amount_out=min_out,
                is_buy=True,
                coin_token_program=coin_program,
            )
        )
        instructions.append(self._wsol_close_instruction(wsol_ata))
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    async def build_raydium_sell_tx(
        self,
        pool_keys: RaydiumPoolKeys,
        token_amount: int,
        *,
        slippage_bps: Optional[int] = None,
        min_sol_output: int | float = 1,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        """Construct a Raydium AMM sell: token ATA -> WSOL ATA, then unwrap (BUG-36)."""
        if isinstance(min_sol_output, float):
            min_out = self.sol_to_lamports(min_sol_output)
        else:
            min_out = int(min_sol_output)
        if slippage_bps is not None:
            coin_reserve, pc_reserve = await self._raydium_reserves(pool_keys)
            _, quoted_min_out = calculate_raydium_swap_out(
                int(token_amount),
                coin_reserve,
                pc_reserve,
                slippage_bps=self.normalize_slippage_bps(slippage_bps),
            )
            min_out = max(min_out, quoted_min_out)
        coin_program = await self.get_token_program_for_mint(pool_keys.coin_mint)
        wsol_ata = get_associated_token_address(
            self.wallet, self._to_pubkey(WSOL_MINT_STR), TOKEN_PROGRAM_ID
        )
        instructions = self._wsol_open_instructions(wsol_ata, 0)
        instructions.append(
            self.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=int(token_amount),
                min_amount_out=max(1, min_out),
                is_buy=False,
                coin_token_program=coin_program,
            )
        )
        instructions.append(self._wsol_close_instruction(wsol_ata))
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    async def raydium_buy(
        self,
        pool_keys: RaydiumPoolKeys,
        sol_amount: float,
        *,
        slippage_bps: Optional[int] = None,
        min_amount_out: int = 1,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
    ) -> str:
        """Execute a Raydium AMM v4 swap buy using Jito bundle or standard transaction."""
        should_jito = self.use_jito if use_jito is None else use_jito
        tip_lamports = None
        if should_jito:
            tip_lamports = await self.calculate_dynamic_jito_tip(
                trade_amount_sol=sol_amount, conviction_score=conviction_score
            )
        tx = await self.build_raydium_buy_tx(
            pool_keys=pool_keys,
            sol_amount=sol_amount,
            slippage_bps=slippage_bps,
            min_amount_out=min_amount_out,
            tip_lamports=tip_lamports,
        )
        if should_jito:
            return await self.send_jito_bundle_with_fallback([tx])
        return await self.send_transaction(tx)

    async def swap_raydium(
        self,
        pool_keys: RaydiumPoolKeys,
        amount_in: int,
        *,
        is_buy: bool = True,
        min_amount_out: int = 1,
        slippage_bps: Optional[int] = None,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
    ) -> str:
        """Execute a Raydium AMM v4 swap (buy or sell)."""
        if is_buy:
            sol_amount = float(amount_in) / 1_000_000_000.0
            return await self.raydium_buy(
                pool_keys=pool_keys,
                sol_amount=sol_amount,
                slippage_bps=slippage_bps,
                min_amount_out=min_amount_out,
                use_jito=use_jito,
                conviction_score=conviction_score,
            )
        else:
            should_jito = self.use_jito if use_jito is None else use_jito
            tip_lamports = None
            if should_jito:
                tip_lamports = await self.calculate_dynamic_jito_tip(
                    trade_amount_sol=0.01, conviction_score=conviction_score
                )
            tx = await self.build_raydium_sell_tx(
                pool_keys=pool_keys,
                token_amount=amount_in,
                slippage_bps=slippage_bps,
                min_sol_output=min_amount_out,
                tip_lamports=tip_lamports,
            )
            if should_jito:
                return await self.send_jito_bundle_with_fallback([tx])
            return await self.send_transaction(tx)
