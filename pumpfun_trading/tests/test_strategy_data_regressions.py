from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from pumpfun_trading.bot.enrichment import count_launches_last_24h
from pumpfun_trading.bot.position_manager import Position, PositionManager
from pumpfun_trading.execution.liquidator import OrderLiquidator
from pumpfun_trading.sdk.raydium import parse_raydium_initialize2_accounts
from pumpfun_trading.services.market_data import MarketDataService
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.cluster import SybilWashTradingDetector
from pumpfun_trading.strategies.filters import (
    DevWalletProfile,
    HolderDistribution,
    evaluate_holder_distribution,
    evaluate_token_heuristics,
)


def test_gini_above_configured_cap_is_hard_reject():
    # BUG-56: 0.85 < G <= 0.95 used to be a soft penalty only
    holders = [("whale", 1_000_000)] + [(f"w{i}", 1) for i in range(9)]
    dist = HolderDistribution(top_holders=holders)
    assert 0.85 < dist.compute_gini_coefficient() <= 0.95
    passed, _, reasons = evaluate_holder_distribution(dist, max_gini=0.85)
    assert passed is False
    assert any("Gini" in r for r in reasons)


def test_missing_dev_and_holder_data_fails_closed():
    # BUG-57
    config = TradingBotConfig(enable_anti_rug_filters=True, require_social_links=False)
    verdict = evaluate_token_heuristics(config, "NoDataMint", use_cache=False)
    assert verdict.passed is False
    assert verdict.flags["missing_dev_data"] is True
    assert verdict.flags["missing_holder_data"] is True

    partial = evaluate_token_heuristics(
        config,
        "PartialMint",
        dev_profile=DevWalletProfile(creator_address="Dev1"),
        use_cache=False,
    )
    assert partial.passed is True
    assert partial.flags["missing_holder_data"] is True


def test_empty_wash_window_means_no_wash_activity():
    # BUG-79: stale trades must not be analysed as if they were recent
    detector = SybilWashTradingDetector(time_window_seconds=300.0)
    churn = [
        {"user": "A", "is_buy": i % 2 == 0, "sol_amount": 1.0, "timestamp": 10.0}
        for i in range(8)
    ]
    verdict = detector.analyze_trades(churn, now=1_000_000.0)
    assert verdict.is_wash_trading is False
    assert verdict.total_volume_sol == 0.0


def test_24h_launch_count_keeps_zero_and_handles_seconds():
    # BUG-58
    now = 2_000_000_000.0
    old = [{"created_timestamp": (now - 5 * 86400) * 1000}] * 7
    assert count_launches_last_24h(old, now=now) == 0
    recent = [{"createdAt": now - 60}, {"created_timestamp": (now - 120) * 1000}]
    assert count_launches_last_24h(recent + old, now=now) == 2


async def test_missing_market_cap_is_zero_not_thirty():
    # BUG-80
    assert await MarketDataService().get_market_cap_sol({}) == 0.0


def test_raydium_initialize2_reads_pc_mint_from_accounts():
    # BUG-81
    accounts = [f"Acct{i}" for i in range(21)]
    keys = parse_raydium_initialize2_accounts(accounts)
    assert keys is not None
    assert keys.pc_mint == "Acct9"
    assert parse_raydium_initialize2_accounts(accounts, pc_mint="X").pc_mint == "X"


def test_position_from_dict_keeps_zero_remaining():
    # BUG-65
    pos = Position.from_dict(
        "M", {"initial_token_amount": 500, "remaining_token_amount": 0, "dry_run": True}
    )
    assert pos.remaining_token_amount == 0
    assert pos.initial_token_amount == 500


def test_record_sell_pre_grad_tier_does_not_touch_take_profit_ladder():
    # BUG-43 at the PositionManager level
    manager = PositionManager(TradingBotConfig(dry_run=True))
    manager.record_buy(
        mint="M", token_amount=1_000, cost_sol=0.01, entry_market_cap=30.0
    )
    closed, remaining = manager.record_sell(
        "M", sold_tokens=300, target_tier="pre_grad_1", is_partial=True
    )
    pos = manager.get_position("M")
    assert not closed and remaining == 700
    assert pos is not None
    assert pos["tier_1_executed"] is False
    assert pos["executed_pre_grad_tranches"] == [0]
    manager.clear_pending_exit("M", "tier_1")
    manager.clear_pending_exit("missing", 1)


async def test_liquidator_never_sells_phantom_balance():
    # BUG-65: remaining 0 must not become a 100M-token sell
    manager = PositionManager(TradingBotConfig(dry_run=False))
    manager.record_buy(mint="M", token_amount=0, cost_sol=0.01, entry_market_cap=30.0)
    executor = MagicMock()
    executor.execute_sell = AsyncMock()
    liquidator = OrderLiquidator(executor, manager)
    assert await liquidator.liquidate_position("M") is False
    executor.execute_sell.assert_not_called()
