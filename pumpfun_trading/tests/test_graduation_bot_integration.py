"""Integration tests for live bot Raydium graduation detection and migration sniping."""

from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import (
    RaydiumPoolKeys,
    TokenScreeningVerdict,
    TradingBotConfig,
)
from pumpfun_trading.sdk.raydium import (
    RAYDIUM_AUTHORITY_V4,
    SERUM_PROGRAM_ID_V3,
    WSOL_MINT,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
)

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"
SAMPLE_MINT = "So11111111111111111111111111111111111111112"
GRAD_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def make_pool_keys(mint: str = GRAD_MINT) -> RaydiumPoolKeys:
    return RaydiumPoolKeys(
        amm_id=str(Keypair().pubkey()),
        amm_authority=RAYDIUM_AUTHORITY_V4,
        amm_open_orders=str(Keypair().pubkey()),
        amm_target_orders=str(Keypair().pubkey()),
        pool_coin_token_account=str(Keypair().pubkey()),
        pool_pc_token_account=str(Keypair().pubkey()),
        serum_program_id=SERUM_PROGRAM_ID_V3,
        serum_market=str(Keypair().pubkey()),
        serum_bids=str(Keypair().pubkey()),
        serum_asks=str(Keypair().pubkey()),
        serum_event_queue=str(Keypair().pubkey()),
        serum_coin_vault=str(Keypair().pubkey()),
        serum_pc_vault=str(Keypair().pubkey()),
        serum_vault_signer=str(Keypair().pubkey()),
        coin_mint=mint,
        pc_mint=WSOL_MINT,
        lp_mint=str(Keypair().pubkey()),
    )


@pytest.fixture
def bot(tmp_path):
    config = TradingBotConfig(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=5.0,
        enable_raydium_migration_sniping=True,
        raydium_pre_migration_sol_threshold=80.0,
        raydium_buy_amount_sol=0.02,
        raydium_slippage_bps=500,
        enable_anti_rug_filters=False,
        dry_run=True,
    )
    return TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


@pytest.mark.asyncio
async def test_bonding_curve_reserve_tracking_and_complete_exit(bot):
    # Receive bonding curve reserve updates
    update_1 = BondingCurveStateUpdate(
        mint=GRAD_MINT,
        bonding_curve_pubkey="Curve1111111111111111111111111111111111111",
        slot=100,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=50_000_000_000,
        real_token_reserves=500_000_000_000_000,
        real_sol_reserves=50_000_000_000,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00005,
        market_cap_sol=50.0,
        timestamp=1000.0,
    )
    await bot._handle_bonding_curve_state_update(update_1)

    cand = bot.graduation_engine.get_candidate(GRAD_MINT)
    assert cand is not None
    assert cand.real_sol_reserves == 50.0
    assert cand.is_completed is False

    # Mark active position to test exit on complete event
    bot.active_positions[GRAD_MINT] = {
        "name": "GraduatingToken",
        "entry_market_cap": 30.0,
        "current_market_cap": 65.0,
        "token_amount": 100_000,
        "dry_run": True,
    }

    complete_ev = CompleteEventUpdate(
        mint=GRAD_MINT,
        user="Deployer1111111111111111111111111111111111",
        bonding_curve="Curve1111111111111111111111111111111111111",
        timestamp=1020,
    )
    await bot._handle_complete_event_update(complete_ev)

    # BUG-44: the completed curve rejects sells, so the position waits for the pool
    assert GRAD_MINT in bot.active_positions
    assert bot.graduation_engine.get_candidate(GRAD_MINT).is_completed is True

    # Once the Raydium pool appears, the held position exits through the AMM
    await bot._handle_raydium_pool_update(make_pool_keys(GRAD_MINT))
    assert GRAD_MINT not in bot.active_positions


@pytest.mark.asyncio
async def test_raydium_pool_update_snipes_graduation(bot):
    pool_keys = make_pool_keys(GRAD_MINT)

    # Feed Raydium pool creation update
    await bot._handle_raydium_pool_update(pool_keys)

    # Bot should have sniped the token on Raydium
    assert GRAD_MINT in bot.active_positions
    pos = bot.active_positions[GRAD_MINT]
    assert pos["entry_reason"] == "raydium_graduation_snipe"
    assert pos["raydium_pool_id"] == pool_keys.amm_id

    # Check status snapshot
    snapshot = bot.get_status_snapshot()
    assert snapshot["enable_raydium_migration_sniping"] is True
    assert snapshot["graduation_tracked_candidates"] >= 1


@pytest.mark.asyncio
async def test_raydium_snipe_rejected_by_anti_rug_screening(bot):
    bot.config = TradingBotConfig(
        enable_raydium_migration_sniping=True,
        enable_anti_rug_filters=True,
        dry_run=True,
    )
    bot.strategy.config = bot.config

    pool_keys = make_pool_keys(GRAD_MINT)

    # Mock screening to fail
    failing_verdict = TokenScreeningVerdict(
        mint=GRAD_MINT,
        passed=False,
        risk_score=85.0,
        reasons=["High creator dumping history"],
    )

    with patch.object(
        bot, "_enrich_and_screen_token", new_callable=AsyncMock
    ) as mock_screen:
        mock_screen.return_value = failing_verdict
        await bot._handle_raydium_pool_update(pool_keys)

    # Should not buy
    assert GRAD_MINT not in bot.active_positions
    assert bot._last_event == f"screen_rejected {GRAD_MINT[:8]}"


@pytest.mark.asyncio
async def test_raydium_snipe_disabled_by_config(bot):
    bot.config = TradingBotConfig(
        enable_raydium_migration_sniping=False,
        dry_run=True,
    )
    bot.strategy.config = bot.config

    pool_keys = make_pool_keys(GRAD_MINT)
    await bot._handle_raydium_pool_update(pool_keys)

    assert GRAD_MINT not in bot.active_positions


@pytest.mark.asyncio
async def test_handle_message_with_raydium_pool_payload(bot):
    pool_keys = make_pool_keys(GRAD_MINT)
    msg = {
        "event": "raydium_pool_created",
        "poolKeys": pool_keys.to_dict(),
    }

    await bot._handle_message(msg)
    assert GRAD_MINT in bot.active_positions
    assert bot.active_positions[GRAD_MINT]["entry_reason"] == "raydium_graduation_snipe"
