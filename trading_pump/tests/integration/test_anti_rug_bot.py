"""Integration tests for Anti-Rug & Dev-Dumping Heuristic Screening in TradingBot runtime."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_pump.api.client import PumpFunApiClient
from trading_pump.bot.run import TradingBot
from trading_pump.streams.geyser import BondingCurveStateUpdate
from trading_pump.tests.support.constants import SAMPLE_PRIVATE_KEY
from trading_pump.tests.support.factories import make_config
from trading_pump.tests.support.fakes import FakeCurves

SAMPLE_MINT = "So11111111111111111111111111111111111111112"
SAMPLE_MINT_TOXIC = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


@pytest.fixture
def bot(tmp_path):
    config = make_config(
        buy_amount_sol=0.01,
        take_profit=1.5,
        stop_loss=0.85,
        min_market_cap_sol=10.0,
        enable_tiered_take_profit=False,
        enable_trailing_stop=False,
        enable_anti_rug_filters=True,
        max_dev_24h_launches=5,
        max_creator_initial_holding_pct=0.10,
        max_top5_holder_concentration_pct=0.15,
        max_acceptable_risk_score=40.0,
        # The sample mints are not ``…pump`` vanity mints (BUG-108).
        require_pump_mint_suffix=False,
        dry_run=True,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    # Paper buys read the curve (BUG-145).
    FakeCurves(default_market_cap=30.0).install(bot)
    return bot


async def test_bot_enrich_and_screen_clean_token(bot):
    # Mock API coin data and creator coins
    clean_coin_data = {
        "mint": SAMPLE_MINT,
        "name": "CleanCoin",
        "symbol": "CLN",
        "creator": "DevClean11111111111111111111111111111111111",
        "twitter": "https://x.com/CleanCoin",
        "telegram": "https://t.me/CleanCoinPortal",
        "website": "https://cleancoin.sol",
        "creatorHoldingPct": 0.03,  # 3%
        "holders": [
            {
                "address": "DevClean11111111111111111111111111111111111",
                "amount": 30_000_000_000_000,
            },
            {
                "address": "User111111111111111111111111111111111111",
                "amount": 10_000_000_000_000,
            },
        ],
    }

    bot.api.get_coin = AsyncMock(return_value=clean_coin_data)
    bot.api.get_creator_coins = AsyncMock(
        return_value=[
            {"mint": SAMPLE_MINT, "created_timestamp": (time.time() - 100) * 1000}
        ]
    )

    verdict = await bot._enrich_and_screen_token(SAMPLE_MINT)
    assert verdict.passed is True
    assert verdict.risk_score == 0.0
    assert verdict.is_clean is True

    # Check cached
    cached = bot.screening_cache.get(SAMPLE_MINT)
    assert cached is not None
    assert cached.passed is True


async def test_bot_enrich_and_screen_serial_rugger(bot):
    toxic_coin_data = {
        "mint": SAMPLE_MINT_TOXIC,
        "name": "ScamCoin",
        "symbol": "SCAM",
        "creator": "DevSerialRugger1111111111111111111111111111",
        "creatorHoldingPct": 0.02,
    }

    bot.api.get_coin = AsyncMock(return_value=toxic_coin_data)
    # Creator launched 12 tokens in last 24h
    now_ms = time.time() * 1000
    bot.api.get_creator_coins = AsyncMock(
        return_value=[
            {"mint": f"Mint_{i}", "created_timestamp": now_ms - (i * 1000)}
            for i in range(12)
        ]
    )

    verdict = await bot._enrich_and_screen_token(SAMPLE_MINT_TOXIC)
    assert verdict.passed is False
    assert verdict.risk_score >= 35.0
    assert verdict.flags.get("dev_serial_launcher") is True


async def test_bot_enrich_and_screen_excessive_creator_holding(bot):
    excessive_holding_data = {
        "mint": SAMPLE_MINT_TOXIC,
        "name": "DevDumpCoin",
        "creator": "DevGreedy11111111111111111111111111111111111",
        "creatorHoldingPct": 0.25,  # 25% creator allocation
    }

    bot.api.get_coin = AsyncMock(return_value=excessive_holding_data)
    bot.api.get_creator_coins = AsyncMock(return_value=[])

    verdict = await bot._enrich_and_screen_token(SAMPLE_MINT_TOXIC)
    assert verdict.passed is False
    assert verdict.risk_score >= 30.0
    assert verdict.flags.get("creator_excess_holding") is True


async def test_bot_enrich_and_screen_disabled_filters(bot):
    bot.config = make_config(dry_run=False, enable_anti_rug_filters=False)

    verdict = await bot._enrich_and_screen_token(SAMPLE_MINT)
    assert verdict.passed is True
    assert verdict.risk_score == 0.0
    assert "disabled" in verdict.reasons[0].lower()


async def test_geyser_bonding_curve_update_blocks_scam_and_buys_clean(bot):
    clean_coin_data = {
        "mint": SAMPLE_MINT,
        "name": "CleanMoon",
        "creator": "CleanDev111",
        "creatorHoldingPct": 0.02,
        "twitter": "https://x.com/CleanMoon",
        "telegram": "https://t.me/CleanMoon",
    }
    toxic_coin_data = {
        "mint": SAMPLE_MINT_TOXIC,
        "name": "ScamRug",
        "creator": "ScamDev111",
        "creatorHoldingPct": 0.40,  # 40% holding
    }

    async def mock_get_coin(mint):
        if mint == SAMPLE_MINT:
            return clean_coin_data
        return toxic_coin_data

    bot.api.get_coin = AsyncMock(side_effect=mock_get_coin)
    bot.api.get_creator_coins = AsyncMock(return_value=[])

    # 1. Toxic coin update via Geyser
    toxic_update = BondingCurveStateUpdate(
        mint=SAMPLE_MINT_TOXIC,
        bonding_curve_pubkey="ToxicCurve",
        slot=100,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(toxic_update)
    assert SAMPLE_MINT_TOXIC not in bot.active_positions
    assert "screen_rejected" in bot._last_event

    # 2. Clean coin update via Geyser
    clean_update = BondingCurveStateUpdate(
        mint=SAMPLE_MINT,
        bonding_curve_pubkey="CleanCurve",
        slot=101,
        virtual_token_reserves=1_000_000_000_000_000,
        virtual_sol_reserves=30_000_000_000,
        real_token_reserves=800_000_000_000_000,
        real_sol_reserves=0,
        token_total_supply=1_000_000_000_000_000,
        complete=False,
        price_sol=0.00003,
        market_cap_sol=30.0,
        timestamp=time.time(),
    )
    await bot._handle_bonding_curve_state_update(clean_update)
    assert SAMPLE_MINT in bot.active_positions


async def test_new_token_event_blocks_scam_and_buys_clean(bot):
    toxic_event_payload = {
        "mint": SAMPLE_MINT_TOXIC,
        "name": "ToxicToken",
        "marketCapSol": 25.0,
        "creatorHoldingPct": 0.35,  # 35% holding
    }
    clean_event_payload = {
        "mint": SAMPLE_MINT,
        "name": "CleanToken",
        "marketCapSol": 25.0,
        "traderPublicKey": "DevClean11111111111111111111111111111111111",
        "creatorHoldingPct": 0.04,
        "twitter": "https://x.com/CleanToken",
    }

    bot.api.get_creator_coins = AsyncMock(return_value=[])

    # 1. Toxic event
    await bot._handle_new_token_event(toxic_event_payload)
    assert SAMPLE_MINT_TOXIC not in bot.active_positions
    assert "screen_rejected" in bot._last_event

    # 2. Clean event
    await bot._handle_new_token_event(clean_event_payload)
    assert SAMPLE_MINT in bot.active_positions


async def test_bot_status_snapshot_screening_telemetry(bot):
    bot.screening_cache.set(
        SAMPLE_MINT,
        bot.strategy.screen_token(SAMPLE_MINT, use_cache=False),
    )
    snapshot = bot.get_status_snapshot()
    assert snapshot["enable_anti_rug_filters"] is True
    assert snapshot["screening_cache_size"] == 1


async def test_api_client_get_creator_coins():
    client = PumpFunApiClient(base_url="https://frontend-api-v3.pump.fun")

    with patch.object(client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = [{"mint": "Coin1"}, {"mint": "Coin2"}]
        res = await client.get_creator_coins("CreatorWallet123", limit=10)
        assert len(res) == 2
        mock_get.assert_called_once_with(
            "/coins/user-created-coins/CreatorWallet123",
            params={"limit": 10, "offset": 0},
        )

    # Test fallback path
    with patch.object(client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [
            RuntimeError("Endpoint 404"),
            [{"mint": "FallbackCoin"}],
        ]
        res = await client.get_creator_coins("CreatorWallet123", limit=10)
        assert len(res) == 1
        assert mock_get.call_count == 2


@pytest.mark.regression("BUG-57")
async def test_bot_enrich_and_screen_api_error_branches(bot):
    # 1. API get_coin failure
    bot.api.get_coin = AsyncMock(side_effect=RuntimeError("Network error"))
    verdict_api_fail = await bot._enrich_and_screen_token("FailMint1")
    # No dev or holder data at all fails closed (BUG-57)
    assert verdict_api_fail.passed is False
    assert verdict_api_fail.flags.get("missing_dev_data") is True

    # 2. Creator coins returns dictionary with "coins"
    coin_dict_data = {
        "mint": "DictMint",
        "creator": "CreatorDict",
        "dev_holding_pct": 0.04,
        "holders": [{"address": "CreatorDict", "amount": 40_000}],
    }
    bot.api.get_coin = AsyncMock(return_value=coin_dict_data)
    bot.api.get_creator_coins = AsyncMock(
        return_value={"coins": [{"mint": "C1"}, {"mint": "C2"}]}
    )
    verdict_dict = await bot._enrich_and_screen_token("DictMint")
    assert verdict_dict.passed is True

    # 3. Creator coins query throws exception
    bot.api.get_creator_coins = AsyncMock(side_effect=RuntimeError("RPC timeout"))
    verdict_creator_exc = await bot._enrich_and_screen_token("ExcMint")
    assert verdict_creator_exc.passed is True

    # 4. PDA computation failure
    bot.execution.get_bonding_curve_pda = MagicMock(
        side_effect=RuntimeError("PDA error")
    )
    verdict_pda_fail = await bot._enrich_and_screen_token("PdaFailMint")
    assert verdict_pda_fail is True or verdict_pda_fail.passed is True


async def test_should_buy_screening_verdict_rejection(bot):
    from trading_pump.bot.strategy import TokenScreeningVerdict

    bad_verdict = TokenScreeningVerdict(
        mint="RejectedMint",
        passed=False,
        risk_score=85.0,
        reasons=["Serial rugger"],
    )
    assert (
        bot._should_buy(
            "RejectedMint",
            market_cap_sol=30.0,
            screening_verdict=bad_verdict,
        )
        is False
    )
