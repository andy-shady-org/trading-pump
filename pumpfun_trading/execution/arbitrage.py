"""Atomic multi-hop transaction bundle assembly and Jito MEV execution for cross-venue arbitrage."""

from __future__ import annotations

import time
from typing import Any, Optional, Union

from solders.hash import Hash
from solders.instruction import Instruction
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.jito import JITO_TIP_ACCOUNTS
from pumpfun_trading.strategies.arbitrage import ArbitrageOpportunity


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

        if opportunity.direction == "pump_to_raydium":
            if not pool_keys:
                raise ValueError(
                    "Raydium pool keys required for pump_to_raydium arbitrage"
                )

            # Leg 1: Buy on Pump.fun (SOL -> Token)
            buy_ix = self.client.build_buy_instruction(
                mint=mint,
                bonding_curve=bonding_curve_str,
                token_amount=leg1_min_tokens,
                max_sol_cost=input_lamports,
            )
            instructions.append(buy_ix)

            # Leg 2: Sell on Raydium AMM v4 (Token -> SOL)
            user_pubkey = self.client.wallet
            mint_pubkey = self.client._to_pubkey(mint)
            user_token_ata = get_associated_token_address(
                user_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
            )

            # Source: User Token ATA, Destination: WSOL / User Wallet
            raydium_sell_ix = self.client.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=leg1_min_tokens,
                min_amount_out=leg2_min_sol,
                user_source_token_account=str(user_token_ata),
                user_destination_token_account=str(
                    user_token_ata
                ),  # Routed through ATA or WSOL
            )
            instructions.append(raydium_sell_ix)

        elif opportunity.direction == "raydium_to_pump":
            if not pool_keys:
                raise ValueError(
                    "Raydium pool keys required for raydium_to_pump arbitrage"
                )

            user_pubkey = self.client.wallet
            mint_pubkey = self.client._to_pubkey(mint)
            user_token_ata = get_associated_token_address(
                user_pubkey, mint_pubkey, TOKEN_PROGRAM_ID
            )

            # Leg 1: Buy on Raydium AMM v4 (SOL -> Token)
            raydium_buy_ix = self.client.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=input_lamports,
                min_amount_out=leg1_min_tokens,
                user_source_token_account=str(user_token_ata),
                user_destination_token_account=str(user_token_ata),
            )
            instructions.append(raydium_buy_ix)

            # Leg 2: Sell on Pump.fun (Token -> SOL)
            sell_ix = self.client.build_sell_instruction(
                mint=mint,
                bonding_curve=bonding_curve_str,
                token_amount=leg1_min_tokens,
                min_sol_output=leg2_min_sol,
            )
            instructions.append(sell_ix)

        else:
            raise ValueError(f"Unknown arbitrage direction: {opportunity.direction}")

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
        instructions = self.build_arbitrage_instructions(
            opportunity=opportunity,
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
