"""Integration tests for live bot Raydium graduation detection and migration sniping."""

from unittest.mock import AsyncMock, patch

import pytest

from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import (
    TokenScreeningVerdict,
)
from pumpfun_trading.streams.geyser import (
    BondingCurveStateUpdate,
    CompleteEventUpdate,
)
from pumpfun_trading.tests.support.constants import SAMPLE_PRIVATE_KEY
from pumpfun_trading.tests.support.factories import make_config
from pumpfun_trading.tests.support.factories import make_pool_keys

SAMPLE_MINT = "So11111111111111111111111111111111111111112"
GRAD_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.fixture
def bot(tmp_path):
    config = make_config(
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


async def test_raydium_snipe_rejected_by_anti_rug_screening(bot):
    bot.config = make_config(
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


async def test_raydium_snipe_disabled_by_config(bot):
    bot.config = make_config(
        enable_raydium_migration_sniping=False,
        dry_run=True,
    )
    bot.strategy.config = bot.config

    pool_keys = make_pool_keys(GRAD_MINT)
    await bot._handle_raydium_pool_update(pool_keys)

    assert GRAD_MINT not in bot.active_positions


async def test_handle_message_with_raydium_pool_payload(bot):
    pool_keys = make_pool_keys(GRAD_MINT)
    msg = {
        "event": "raydium_pool_created",
        "poolKeys": pool_keys.to_dict(),
    }

    await bot._handle_message(msg)
    assert GRAD_MINT in bot.active_positions
    assert bot.active_positions[GRAD_MINT]["entry_reason"] == "raydium_graduation_snipe"
