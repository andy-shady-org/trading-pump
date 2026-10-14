from __future__ import annotations

import pytest
from pumpfun_trading.bot.position_manager import Position, PositionManager
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import ExitAction


@pytest.fixture
def base_config() -> TradingBotConfig:
    return TradingBotConfig(
        buy_amount_sol=0.1,
        take_profit=1.5,
        stop_loss=0.8,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.5,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.5,
        trailing_stop_drop_pct=0.15,
        min_sell_balance=1000,
        dry_run=True,
    )


def test_position_dataclass_properties():
    pos = Position(
        mint="Mint111",
        name="TestToken",
        entry_market_cap=30.0,
        current_market_cap=60.0,
        peak_market_cap=60.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        cost_sol=0.1,
        buy_price=0.0001,
    )
    assert pos.token_amount == 1_000_000
    assert pos.performance == 2.0
    assert pos.peak_performance == 2.0
    assert pos.buy_price == 0.0001
    assert pos.entry_price == 0.0001

    pos.entry_price = 0.0002
    assert pos.buy_price == 0.0002

    pos_dict = pos.to_dict()
    assert pos_dict["name"] == "TestToken"
    assert pos_dict["entry_market_cap"] == 30.0
    assert pos_dict["buy_price"] == 0.0002
    assert pos_dict["entry_price"] == 0.0002

    restored = Position.from_dict("Mint111", pos_dict)
    assert restored.mint == "Mint111"
    assert restored.performance == 2.0
    assert restored.buy_price == 0.0002
    assert restored.entry_price == 0.0002


def test_position_manager_buy_price_recording(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    pos = pm.record_buy(
        mint="MintBuyP",
        token_amount=2_000_000,
        cost_sol=0.2,
        entry_market_cap=40.0,
        name="BuyPToken",
        buy_price=0.0001,
    )
    assert pos["buy_price"] == 0.0001
    assert pos["entry_price"] == 0.0001
    fetched = pm.get_position("MintBuyP")
    assert fetched is not None
    assert fetched["buy_price"] == 0.0001


def test_position_manager_buy_and_get(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    assert len(pm) == 0
    assert not pm.has_position("Mint111")

    pos = pm.record_buy(
        mint="Mint111",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
        name="SolCat",
        reason="test_buy",
        dry_run=True,
    )

    assert pos["name"] == "SolCat"
    assert pos["token_amount"] == 1_000_000
    assert len(pm) == 1
    assert pm.has_position("Mint111")
    assert "Mint111" in pm
    assert pm["Mint111"]["name"] == "SolCat"
    assert pm.get_mints() == ["Mint111"]
    assert pm.get_position("Mint111") is not None
    assert pm.get_position("Unknown") is None


def test_position_manager_price_updates_and_peak(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="Mint111",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
        name="SolCat",
    )

    entry_mc, curr_mc, peak_mc = pm.update_price("Mint111", 45.0)
    assert entry_mc == 30.0
    assert curr_mc == 45.0
    assert peak_mc == 45.0

    # Price drops: peak should remain 45.0
    entry_mc, curr_mc, peak_mc = pm.update_price("Mint111", 40.0)
    assert curr_mc == 40.0
    assert peak_mc == 45.0

    # Non-existent mint update price
    entry_mc, curr_mc, peak_mc = pm.update_price("NonExistent", 50.0)
    assert entry_mc == 0.0
    assert curr_mc == 50.0


def test_position_manager_evaluate_exit_tiered_take_profit(
    base_config: TradingBotConfig,
):
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="Mint111",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
    )

    # 1. Price at 1.5x (45.0): HOLD (Tier 1 is at 2.0x = 60.0)
    dec = pm.evaluate_exit("Mint111", current_market_cap=45.0)
    assert dec is not None
    assert dec.action == ExitAction.HOLD

    # 2. Price at 2.0x (60.0): Trigger Tier 1 Partial Exit (50% = 500,000 tokens)
    dec = pm.evaluate_exit("Mint111", current_market_cap=60.0)
    assert dec is not None
    assert dec.action == ExitAction.PARTIAL_EXIT
    assert dec.sell_tokens == 500_000
    assert dec.target_tier == 1

    # Record Tier 1 sell
    closed, remaining = pm.record_sell(
        "Mint111", sold_tokens=500_000, target_tier=1, is_partial=True
    )
    assert not closed
    assert remaining == 500_000
    assert pm["Mint111"]["tier_1_executed"] is True

    # 3. Price at 3.5x (105.0): Trigger Tier 2 Partial Exit (25% of initial = 250,000 tokens)
    dec = pm.evaluate_exit("Mint111", current_market_cap=105.0)
    assert dec is not None
    assert dec.action == ExitAction.PARTIAL_EXIT
    assert dec.sell_tokens == 250_000
    assert dec.target_tier == 2

    # Record Tier 2 sell
    closed, remaining = pm.record_sell(
        "Mint111", sold_tokens=250_000, target_tier=2, is_partial=True
    )
    assert not closed
    assert remaining == 250_000
    assert pm["Mint111"]["tier_2_executed"] is True
    assert pm["Mint111"]["moonbag_active"] is True


def test_position_manager_evaluate_exit_stop_loss(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="Mint111",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
    )

    # Price drops to 23.0 (23/30 = 76.6% <= 80% stop loss)
    dec = pm.evaluate_exit("Mint111", current_market_cap=23.0)
    assert dec is not None
    assert dec.action == ExitAction.FULL_EXIT
    assert dec.exit_type == "stop_loss"


def test_position_manager_pnl_and_open_valuation(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="Mint1",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
    )
    pm.record_buy(
        mint="Mint2",
        token_amount=2_000_000,
        cost_sol=0.2,
        entry_market_cap=50.0,
    )

    pm.update_price("Mint1", 60.0)  # 2x -> 0.2 SOL value -> +0.1 SOL PnL
    pm.update_price("Mint2", 25.0)  # 0.5x -> 0.1 SOL value -> -0.1 SOL PnL

    assert pytest.approx(pm.calculate_unrealized_pnl("Mint1"), rel=1e-3) == 0.1
    assert pytest.approx(pm.calculate_unrealized_pnl("Mint2"), rel=1e-3) == -0.1
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-3) == 0.3


def test_position_manager_calculate_total_open_value_edge_cases(
    base_config: TradingBotConfig,
):
    pm = PositionManager(base_config)
    # Zero positions -> 0.0
    assert pm.calculate_total_open_value() == 0.0

    # 1. Zero market cap (rugged/crashed token) should evaluate to 0.0 value, not full cost
    pm._positions["MintRugged"] = {
        "cost_sol": 0.05,
        "entry_market_cap": 28.0,
        "current_market_cap": 0.0,
    }
    assert pm.calculate_total_open_value() == 0.0

    # 2. Missing current_market_cap defaults to entry_market_cap (1.0x -> cost_sol)
    pm.clear()
    pm._positions["MintNew"] = {
        "cost_sol": 0.02,
        "entry_market_cap": 28.0,
    }
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-3) == 0.02

    # 3. Missing cost_sol falls back to entry_sol or buy_amount_sol
    pm.clear()
    pm._positions["MintEntrySol"] = {
        "entry_sol": 0.03,
        "entry_market_cap": 20.0,
        "current_market_cap": 40.0,
    }
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-3) == 0.06

    pm.clear()
    pm._positions["MintFallbackDefault"] = {
        "entry_market_cap": 20.0,
        "current_market_cap": 30.0,
    }
    # base_config.buy_amount_sol is 0.1, 1.5x -> 0.15
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-3) == 0.15


def test_position_manager_serialization_restoration(base_config: TradingBotConfig):
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="Mint1",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=30.0,
        name="SolCat",
    )
    pm.update_price("Mint1", 45.0)

    serialized = pm.to_dict()
    assert "Mint1" in serialized
    assert serialized["Mint1"]["current_market_cap"] == 45.0
    assert serialized["Mint1"]["peak_market_cap"] == 45.0

    pm2 = PositionManager(base_config)
    pm2.restore_from_dict(serialized)
    assert len(pm2) == 1
    assert pm2.has_position("Mint1")
    assert pm2["Mint1"]["name"] == "SolCat"
    assert pm2["Mint1"]["peak_market_cap"] == 45.0


def test_position_manager_evaluate_exit_stagnant_timeout(base_config: TradingBotConfig):
    """BUG-16: PositionManager must trigger stagnant timeout exit when market cap is flat."""
    pm = PositionManager(base_config)
    t0 = 1000.0
    pm.record_buy(
        mint="MintFlat",
        token_amount=1_000_000,
        cost_sol=0.1,
        entry_market_cap=27.96,
        name="FlatToken",
    )
    pm._positions["MintFlat"]["entry_time"] = t0
    pm._positions["MintFlat"]["last_price_change_at"] = t0
    pm._positions["MintFlat"]["last_price"] = 27.96

    # Under timeout (60s < 120s) -> None or HOLD
    dec_hold = pm.evaluate_exit("MintFlat", current_market_cap=27.96, now=t0 + 60.0)
    assert dec_hold is not None
    assert dec_hold.action == ExitAction.HOLD

    # Exceeding timeout (121s >= 120s) -> FULL_EXIT with stagnant_timeout
    dec_exit = pm.evaluate_exit("MintFlat", current_market_cap=27.96, now=t0 + 121.0)
    assert dec_exit is not None
    assert dec_exit.action == ExitAction.FULL_EXIT
    assert dec_exit.exit_type == "stagnant_timeout"
