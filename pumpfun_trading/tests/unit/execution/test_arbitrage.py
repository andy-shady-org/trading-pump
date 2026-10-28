"""Unit tests for ``execution/arbitrage.py``."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from pumpfun_trading.execution.arbitrage import (
    AtomicArbitrageBuilder,
    AtomicArbitrageExecutor,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys
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


@pytest.mark.regression("BUG-59")
async def test_atomic_arbitrage_builder_and_executor_unverified_and_dry_run():
    kp = Keypair()
    mock_client = MagicMock(spec=PumpFunExecutionClient)
    mock_client.wallet = kp.pubkey()
    mock_client.keypair = kp
    mock_client._to_pubkey = lambda s: (
        Pubkey.from_string(s) if isinstance(s, str) else s
    )
    mock_client.get_bonding_curve_pda.return_value = (
        "11111111111111111111111111111111",
        255,
    )

    real_ix = Instruction(program_id=Pubkey.default(), data=b"", accounts=[])
    mock_client.build_set_compute_unit_limit_instruction.return_value = real_ix
    mock_client.build_set_compute_unit_price_instruction.return_value = real_ix
    mock_client.build_buy_instruction.return_value = real_ix
    mock_client.build_sell_instruction.return_value = real_ix
    mock_client.build_raydium_swap_instruction.return_value = real_ix
    mock_client.build_jito_tip_instruction.return_value = real_ix
    mock_client._wsol_open_instructions.return_value = [real_ix]
    mock_client._wsol_close_instruction.return_value = real_ix
    mock_client.get_token_program_for_mint = AsyncMock(
        return_value=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    )
    mock_client.get_latest_blockhash = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    mock_client.send_jito_bundle_with_fallback = AsyncMock(return_value="tx_sig_123")

    builder = AtomicArbitrageBuilder(mock_client)
    keys = RaydiumPoolKeys.from_dict(
        {
            "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
            "amm_open_orders": "HRk9CMrT112pT3fT1W6Vv6W4uQkKxL5mP2vL4Y4mU3v",
            "amm_target_orders": "CZza3YqqiTo2uvU42ZbWTpG2vH2m44kZ2V6iY3Yq4vY",
            "pool_coin_token_account": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "pool_pc_token_account": "8yKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_program_id": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
            "serum_market": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_bids": "AxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_asks": "BxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_event_queue": "CxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_coin_vault": "DxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_pc_vault": "ExKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "serum_vault_signer": "FxKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "coin_mint": "CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
            "pc_mint": "So11111111111111111111111111111111111111112",
            "lp_mint": "Lp11111111111111111111111111111111111111112",
        }
    )

    opp_pump = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=keys,
        leg1_min_amount_out=1_000_000,
        leg2_min_amount_out=120_000_000,
    )

    opp_ray = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="raydium_to_pump",
        pump_spot_price=0.00005,
        raydium_spot_price=0.00004,
        spread_pct=0.25,
        optimal_input_sol=0.08,
        expected_output_sol=0.095,
        gross_profit_sol=0.015,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.004,
        net_profit_sol=0.010,
        timestamp=time.time(),
        pool_keys=keys,
        leg1_min_amount_out=2_000_000,
        leg2_min_amount_out=95_000_000,
    )

    # Test instruction generation
    ixs1 = builder.build_arbitrage_instructions(
        opp_pump, priority_fee_micro_lamports=100_000
    )
    assert len(ixs1) >= 4

    ixs2 = builder.build_arbitrage_instructions(opp_ray, tip_lamports=5_000_000)
    assert len(ixs2) >= 4

    # Test error cases
    opp_no_pool = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="pump_to_raydium",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=None,
    )
    with pytest.raises(ValueError, match="Raydium pool keys required"):
        builder.build_arbitrage_instructions(opp_no_pool)

    opp_bad_dir = ArbitrageOpportunity(
        mint="CzLSujWBLFsSjncfkh59rQD4ETecfgzWrmAyHiVpump",
        direction="invalid_direction",
        pump_spot_price=0.00003,
        raydium_spot_price=0.00004,
        spread_pct=0.33,
        optimal_input_sol=0.1,
        expected_output_sol=0.12,
        gross_profit_sol=0.02,
        estimated_fees_sol=0.001,
        estimated_jito_tip_sol=0.005,
        net_profit_sol=0.014,
        timestamp=time.time(),
        pool_keys=keys,
    )
    with pytest.raises(ValueError, match="Unknown arbitrage direction"):
        builder.build_arbitrage_instructions(opp_bad_dir)

    # Test building versioned transaction with string blockhash and Hash blockhash
    tx1 = await builder.build_arbitrage_transaction(
        opp_pump, recent_blockhash="11111111111111111111111111111111"
    )
    assert tx1 is not None

    tx2 = await builder.build_arbitrage_transaction(
        opp_pump, recent_blockhash=Hash.from_string("11111111111111111111111111111111")
    )
    assert tx2 is not None

    # Test executor
    executor_dry = AtomicArbitrageExecutor(mock_client, builder=builder, dry_run=True)
    res_dry = await executor_dry.execute_arbitrage(opp_pump)
    assert res_dry["success"] is True
    assert res_dry["status"] == "simulated"

    executor_live = AtomicArbitrageExecutor(mock_client, builder=builder, dry_run=False)
    # Unverified (placeholder) reserves never execute live (BUG-59).
    res_blocked = await executor_live.execute_arbitrage(opp_pump)
    assert res_blocked["success"] is False and res_blocked["status"] == "blocked"
    mock_client.send_jito_bundle_with_fallback.assert_not_awaited()

    import dataclasses

    opp_pump = dataclasses.replace(opp_pump, reserves_verified=True)
    res_live = await executor_live.execute_arbitrage(opp_pump)
    assert res_live["success"] is True
    assert res_live["signature"] == "tx_sig_123"

    # Test executor live failure branch
    mock_client.send_jito_bundle_with_fallback = AsyncMock(
        side_effect=RuntimeError("RPC timeout")
    )
    res_fail = await executor_live.execute_arbitrage(opp_pump)
    assert res_fail["success"] is False
    assert "RPC timeout" in res_fail["error"]
