"""Atomic multi-hop transaction bundle assembly and Jito MEV execution for cross-venue arbitrage."""

from __future__ import annotations

import time
from typing import Any, Optional, Union

from solders.hash import Hash
from solders.instruction import Instruction
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from solders.pubkey import Pubkey
from spl.token.instructions import (
    create_idempotent_associated_token_account,
    get_associated_token_address,
)

from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.sdk.jito import JITO_TIP_ACCOUNTS
from trading_pump.strategies.arbitrage import ArbitrageOpportunity


class AtomicArbitrageBuilder:
    """Builds atomic multi-hop transaction instructions for cross-venue arbitrage."""

    def __init__(self, execution_client: PumpFunExecutionClient) -> None:
        self.client = execution_client

    def build_arbitrage_instructions(
        self,
        opportunity: ArbitrageOpportunity,
        tip_account: Optional[str] = None,
        tip_lamports: Optional[int] = None,
        compute_unit_limit: int = 400_000,
        priority_fee_micro_lamports: int = 50_000,
        token_program: Optional[Pubkey] = None,
    ) -> list[Instruction]:
        """Assemble all atomic instructions for dual-leg swap and Jito validator tip."""
        instructions: list[Instruction] = []

        # 1. Compute budget limits
        instructions.append(
            self.client.build_set_compute_unit_limit_instruction(compute_unit_limit)
        )
        if priority_fee_micro_lamports > 0:
            instructions.append(
                self.client.build_set_compute_unit_price_instruction(
                    priority_fee_micro_lamports
                )
            )

        mint = opportunity.mint
        pool_keys = opportunity.pool_keys
        bonding_curve_str, _ = self.client.get_bonding_curve_pda(mint)

        input_lamports = int(round(opportunity.optimal_input_sol * 1_000_000_000))
        leg1_min_tokens = opportunity.leg1_min_amount_out
        leg2_min_sol = opportunity.leg2_min_amount_out

        if opportunity.direction not in {"pump_to_raydium", "raydium_to_pump"}:
            raise ValueError(f"Unknown arbitrage direction: {opportunity.direction}")
        if not pool_keys:
            raise ValueError(
                f"Raydium pool keys required for {opportunity.direction} arbitrage"
            )

        # Raydium trades SPL WSOL, Pump.fun trades native SOL: the WSOL ATA is the
        # SOL side of the Raydium leg and the mint ATA (with the mint's real token
        # program) is the token side. Source and destination never coincide (BUG-37).
        user_pubkey = self.client.wallet
        mint_program = token_program or TOKEN_PROGRAM_ID
        wsol_ata = get_associated_token_address(
            user_pubkey, self.client._to_pubkey(pool_keys.pc_mint), TOKEN_PROGRAM_ID
        )
        instructions.append(
            create_idempotent_associated_token_account(
                payer=user_pubkey,
                owner=user_pubkey,
                mint=self.client._to_pubkey(mint),
                token_program_id=mint_program,
            )
        )

        if opportunity.direction == "pump_to_raydium":
            # Leg 1: Buy on Pump.fun (SOL -> Token)
            instructions.append(
                self.client.build_buy_instruction(
                    mint=mint,
                    bonding_curve=bonding_curve_str,
                    token_amount=leg1_min_tokens,
                    max_sol_cost=input_lamports,
                    base_token_program=mint_program,
                )
            )
            # Leg 2: Sell on Raydium AMM v4 (token ATA -> WSOL ATA), then unwrap.
            instructions.extend(self.client._wsol_open_instructions(wsol_ata, 0))
            instructions.append(
                self.client.build_raydium_swap_instruction(
                    pool_keys=pool_keys,
                    amount_in_lamports=leg1_min_tokens,
                    min_amount_out=leg2_min_sol,
                    is_buy=False,
                    coin_token_program=mint_program,
                )
            )
            instructions.append(self.client._wsol_close_instruction(wsol_ata))
        else:
            # Leg 1: Wrap SOL, buy on Raydium AMM v4 (WSOL ATA -> token ATA), unwrap.
            instructions.extend(
                self.client._wsol_open_instructions(wsol_ata, input_lamports)
            )
            instructions.append(
                self.client.build_raydium_swap_instruction(
                    pool_keys=pool_keys,
                    amount_in_lamports=input_lamports,
                    min_amount_out=leg1_min_tokens,
                    is_buy=True,
                    coin_token_program=mint_program,
                )
            )
            instructions.append(self.client._wsol_close_instruction(wsol_ata))
            # Leg 2: Sell on Pump.fun (Token -> SOL)
            instructions.append(
                self.client.build_sell_instruction(
                    mint=mint,
                    bonding_curve=bonding_curve_str,
                    token_amount=leg1_min_tokens,
                    min_sol_output=leg2_min_sol,
                    base_token_program=mint_program,
                )
            )

        # 3. Dynamic Jito Tip Instruction
        tip_amt = (
            tip_lamports
            if tip_lamports is not None
            else int(round(opportunity.estimated_jito_tip_sol * 1_000_000_000))
        )
        if tip_amt > 0:
            tip_acc = tip_account or JITO_TIP_ACCOUNTS[0]
            tip_ix = self.client.build_jito_tip_instruction(
                tip_lamports=tip_amt, tip_account=tip_acc
            )
            instructions.append(tip_ix)

        return instructions

    async def build_arbitrage_transaction(
        self,
        opportunity: ArbitrageOpportunity,
        recent_blockhash: Optional[Union[Hash, str]] = None,
        tip_account: Optional[str] = None,
        tip_lamports: Optional[int] = None,
        compute_unit_limit: int = 400_000,
        priority_fee_micro_lamports: int = 50_000,
    ) -> VersionedTransaction:
        """Compile and sign atomic VersionedTransaction containing all dual-leg swap instructions."""
        # Raises if the mint owner can't be read; never guess SPL vs Token-2022.
        token_program = await self.client.get_token_program_for_mint(opportunity.mint)
        instructions = self.build_arbitrage_instructions(
            opportunity=opportunity,
            token_program=token_program,
            tip_account=tip_account,
            tip_lamports=tip_lamports,
            compute_unit_limit=compute_unit_limit,
            priority_fee_micro_lamports=priority_fee_micro_lamports,
        )

        if recent_blockhash is None:
            blockhash_str = await self.client.get_latest_blockhash()
            bh = Hash.from_string(blockhash_str)
        elif isinstance(recent_blockhash, str):
            bh = Hash.from_string(recent_blockhash)
        else:
            bh = recent_blockhash

        payer = self.client.keypair
        msg = MessageV0.try_compile(
            payer=payer.pubkey(),
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=bh,
        )
        return VersionedTransaction(msg, [payer])


class AtomicArbitrageExecutor:
    """Orchestrates live and dry-run execution of atomic cross-venue arbitrage bundles."""

    def __init__(
        self,
        execution_client: PumpFunExecutionClient,
        builder: Optional[AtomicArbitrageBuilder] = None,
        dry_run: bool = False,
    ) -> None:
        self.client = execution_client
        self.builder = builder or AtomicArbitrageBuilder(execution_client)
        self.dry_run = dry_run

    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
        tip_account: Optional[str] = None,
        tip_lamports: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute or simulate an atomic cross-venue arbitrage opportunity."""
        start_time = time.monotonic()

        if self.dry_run:
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            sig = f"dry_run_arb_{opportunity.mint[:8]}_{int(time.time())}"
            return {
                "success": True,
                "status": "simulated",
                "signature": sig,
                "opportunity": opportunity.to_dict(),
                "net_profit_sol": opportunity.net_profit_sol,
                "gross_profit_sol": opportunity.gross_profit_sol,
                "tip_sol": opportunity.estimated_jito_tip_sol,
                "latency_ms": elapsed_ms,
            }

        if not getattr(opportunity, "reserves_verified", False):
            # Live bundles only on reserves read from chain, never on placeholder
            # or estimated books (BUG-59).
            return {
                "success": False,
                "status": "blocked",
                "error": "arbitrage reserves not verified on-chain; live execution disabled",
                "opportunity": opportunity.to_dict(),
                "latency_ms": (time.monotonic() - start_time) * 1000.0,
            }

        try:
            tx = await self.builder.build_arbitrage_transaction(
                opportunity=opportunity,
                tip_account=tip_account,
                tip_lamports=tip_lamports,
            )

            # Submit via private Jito bundle engine
            sig = await self.client.send_jito_bundle_with_fallback([tx])
            elapsed_ms = (time.monotonic() - start_time) * 1000.0

            return {
                "success": True,
                "status": "landed",
                "signature": sig,
                "opportunity": opportunity.to_dict(),
                "net_profit_sol": opportunity.net_profit_sol,
                "gross_profit_sol": opportunity.gross_profit_sol,
                "tip_sol": opportunity.estimated_jito_tip_sol,
                "latency_ms": elapsed_ms,
            }

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            return {
                "success": False,
                "status": "reverted",
                "error": str(exc),
                "opportunity": opportunity.to_dict(),
                "net_profit_sol": 0.0,
                "gross_profit_sol": 0.0,
                "tip_sol": 0.0,
                "latency_ms": elapsed_ms,
            }


__all__ = [
    "AtomicArbitrageBuilder",
    "AtomicArbitrageExecutor",
]
