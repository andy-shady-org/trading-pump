"""Unit tests for ``execution/arbitrage.py``."""

from __future__ import annotations

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.strategies.arbitrage import ArbitrageOpportunity
from pumpfun_trading.tests.support.factories import make_pool_keys


async def test_atomic_arbitrage_builder_and_executor() -> None:
    """Test assembly of atomic multi-hop transactions with dual-leg swaps and dynamic Jito tips."""
    kp = Keypair()
    priv_b58 = kp.to_base58_string() if hasattr(kp, "to_base58_string") else str(kp)
    client = PumpFunExecutionClient(private_key_b58=priv_b58)
    builder = AtomicArbitrageBuilder(client)
    executor = AtomicArbitrageExecutor(
        execution_client=client, builder=builder, dry_run=True
    )

    keys = make_pool_keys("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", unique=False)
    opp = ArbitrageOpportunity(
        mint=keys.coin_mint,
        direction="pump_to_raydium",
        pump_spot_price=0.000030,
        raydium_spot_price=0.000045,
        spread_pct=0.50,
        optimal_input_sol=0.10,
        expected_output_sol=0.14,
        gross_profit_sol=0.04,
        estimated_fees_sol=0.0003,
        estimated_jito_tip_sol=0.02,
        net_profit_sol=0.0197,
        timestamp=1700000000.0,
        pool_keys=keys,
        pump_reserves=(30_000_000_000, 1_000_000_000_000_000),
        raydium_reserves=(85_000_000_000, 200_000_000_000_000),
        leg1_min_amount_out=3_000_000_000,
        leg2_min_amount_out=135_000_000,
    )

    # 1. Build atomic instructions
    ixs = builder.build_arbitrage_instructions(opp)
    assert len(ixs) >= 4  # compute_limit, compute_price, leg1, leg2, tip
    assert ixs[0].program_id == Pubkey.from_string(
        "ComputeBudget111111111111111111111111111111"
    )

    # 2. Reverse direction instruction check
    rev_opp = ArbitrageOpportunity(
        mint=keys.coin_mint,
        direction="raydium_to_pump",
        pump_spot_price=0.000045,
        raydium_spot_price=0.000030,
        spread_pct=0.50,
        optimal_input_sol=0.10,
        expected_output_sol=0.14,
        gross_profit_sol=0.04,
        estimated_fees_sol=0.0003,
        estimated_jito_tip_sol=0.02,
        net_profit_sol=0.0197,
        timestamp=1700000000.0,
        pool_keys=keys,
        leg1_min_amount_out=3_000_000_000,
        leg2_min_amount_out=135_000_000,
    )
    rev_ixs = builder.build_arbitrage_instructions(rev_opp)
    assert len(rev_ixs) >= 4

    # 3. Dry-run simulation execution
    sim_res = await executor.execute_arbitrage(opp)
    assert sim_res["success"] is True
    assert sim_res["status"] == "simulated"
    assert sim_res["net_profit_sol"] == opp.net_profit_sol
