from __future__ import annotations

import pytest

from pumpfun_trading.bot.risk import track_position_peak
from pumpfun_trading.bot.strategy import (
    ExitAction,
    PositionExitState,
    TradingBotConfig,
    TradingStrategy,
    evaluate_exit_strategy,
    resolve_strategy_config,
    should_exit_position,
    update_position_peak,
)


def test_position_exit_state_model():
    state = PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )

    assert state.performance == 1.0
    assert state.peak_performance == 1.0
    assert state.drawdown_from_peak == 0.0
    assert not state.trailing_stop_active
    assert not state.tier_1_executed
    assert not state.tier_2_executed
    assert not state.moonbag_active

    # Update to higher price
    state.update_price(60.0)
    assert state.current_market_cap == 60.0
    assert state.peak_market_cap == 60.0
    assert state.performance == 2.0
    assert state.peak_performance == 2.0
    assert state.drawdown_from_peak == 0.0

    # Retracement
    state.update_price(51.0)
    assert state.current_market_cap == 51.0
    assert state.peak_market_cap == 60.0
    assert state.performance == 1.7
    assert state.peak_performance == 2.0
    assert pytest.approx(state.drawdown_from_peak, 0.001) == 0.15

    # Partial exit recording
    state.record_partial_exit(tier=1, sold_tokens=500_000)
    assert state.tier_1_executed
    assert state.remaining_token_amount == 500_000

    state.record_partial_exit(tier=2, sold_tokens=250_000)
    assert state.tier_2_executed
    assert state.moonbag_active
    assert state.remaining_token_amount == 250_000

    # Serialization roundtrip
    serialized = state.to_dict()
    assert serialized["remaining_token_amount"] == 250_000
    assert serialized["tier_1_executed"]
    assert serialized["tier_2_executed"]

    restored = PositionExitState.from_dict(serialized)
    assert restored.entry_market_cap == 30.0
    assert restored.remaining_token_amount == 250_000
    assert restored.moonbag_active


def test_position_exit_state_zero_and_fallback():
    zero_state = PositionExitState(
        entry_market_cap=0.0,
        current_market_cap=0.0,
        peak_market_cap=0.0,
        initial_token_amount=0,
        remaining_token_amount=0,
    )
    assert zero_state.performance == 1.0
    assert zero_state.peak_performance == 1.0
    assert zero_state.drawdown_from_peak == 0.0

    # Fallback from bare dict
    raw = {"entry_market_cap": 25.0, "token_amount": 500}
    from_dict_state = PositionExitState.from_dict(raw)
    assert from_dict_state.entry_market_cap == 25.0
    assert from_dict_state.initial_token_amount == 500
    assert from_dict_state.remaining_token_amount == 500


def test_update_position_peak():
    # Test on dict position
    pos_dict = {"entry_market_cap": 10.0, "current_market_cap": 10.0}
    peak = update_position_peak(pos_dict, 15.0)
    assert peak == 15.0
    assert pos_dict["peak_market_cap"] == 15.0
    assert pos_dict["current_market_cap"] == 15.0

    # Price declines: peak remains 15.0
    peak_declined = update_position_peak(pos_dict, 12.0)
    assert peak_declined == 15.0
    assert pos_dict["current_market_cap"] == 12.0

    # Test on PositionExitState
    state = PositionExitState(10.0, 10.0, 10.0, 100, 100)
    peak_state = update_position_peak(state, 20.0)
    assert peak_state == 20.0
    assert state.peak_market_cap == 20.0


def test_evaluate_exit_strategy_stop_loss():
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=100.0,
        current_market_cap=80.0,
        peak_market_cap=100.0,
        initial_token_amount=1_000,
        remaining_token_amount=1_000,
    )

    decision = evaluate_exit_strategy(config, state, current_market_cap=80.0)
    assert decision.action == ExitAction.FULL_EXIT
    assert decision.exit_type == "stop_loss"
    assert decision.sell_tokens == 1_000
    assert "stop_loss_hit" in decision.reason


def test_evaluate_exit_strategy_tiered_take_profit():
    config = resolve_strategy_config("balanced")  # tier_1=2.0x, tier_2=3.5x
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=10.0,
        peak_market_cap=10.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
    )

    # 1. At 1.8x -> hold (under 2.0x tier 1)
    decision = evaluate_exit_strategy(config, state, current_market_cap=18.0)
    assert decision.action == ExitAction.HOLD

    # 2. At 2.0x -> Tier 1 partial exit (sell 50% = 500,000 tokens)
    decision_t1 = evaluate_exit_strategy(config, state, current_market_cap=20.0)
    assert decision_t1.action == ExitAction.PARTIAL_EXIT
    assert decision_t1.exit_type == "tier_1"
    assert decision_t1.target_tier == 1
    assert decision_t1.sell_tokens == 500_000

    # Record Tier 1 fill
    state.record_partial_exit(tier=1, sold_tokens=decision_t1.sell_tokens)
    assert state.tier_1_executed
    assert state.remaining_token_amount == 500_000

    # 3. At 3.0x -> Hold waiting for Tier 2 (3.5x)
    decision_hold = evaluate_exit_strategy(config, state, current_market_cap=30.0)
    assert decision_hold.action == ExitAction.HOLD

    # 4. At 3.5x -> Tier 2 partial exit (sell 25% of initial = 250,000 tokens)
    decision_t2 = evaluate_exit_strategy(config, state, current_market_cap=35.0)
    assert decision_t2.action == ExitAction.PARTIAL_EXIT
    assert decision_t2.exit_type == "tier_2"
    assert decision_t2.target_tier == 2
    assert decision_t2.sell_tokens == 250_000

    # Record Tier 2 fill
    state.record_partial_exit(tier=2, sold_tokens=decision_t2.sell_tokens)
    assert state.tier_2_executed
    assert state.moonbag_active
    assert state.remaining_token_amount == 250_000

    # 5. Moonbag floor trigger: price drops to 2.4x <= 2.5x floor
    decision_moonbag = evaluate_exit_strategy(config, state, current_market_cap=24.0)
    assert decision_moonbag.action == ExitAction.FULL_EXIT
    assert decision_moonbag.exit_type == "moonbag_floor"
    assert decision_moonbag.sell_tokens == 250_000


def test_evaluate_exit_strategy_trailing_stop():
    # Test trailing stop when tiered take profit is disabled or before tier hits
    config = TradingBotConfig(
        enable_tiered_take_profit=False,
        enable_trailing_stop=True,
        trailing_stop_activation_pct=0.50,  # Activates at +50% (1.5x)
        trailing_stop_drop_pct=0.15,  # Exits if drops 15% from peak
        take_profit=3.0,
        stop_loss=0.85,
    )
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=10.0,
        peak_market_cap=10.0,
        initial_token_amount=10_000,
        remaining_token_amount=10_000,
    )

    # Price at 1.4x (+40%): Trailing stop not active yet
    d1 = evaluate_exit_strategy(config, state, current_market_cap=14.0)
    assert d1.action == ExitAction.HOLD
    assert not state.trailing_stop_active

    # Price reaches 1.6x (+60%): Trailing stop activates
    d2 = evaluate_exit_strategy(config, state, current_market_cap=16.0)
    assert d2.action == ExitAction.HOLD
    assert state.trailing_stop_active
    assert state.peak_market_cap == 16.0

    # Price climbs further to 2.0x: Peak updates to 20.0
    d3 = evaluate_exit_strategy(config, state, current_market_cap=20.0)
    assert d3.action == ExitAction.HOLD
    assert state.peak_market_cap == 20.0

    # Price drops to 18.0 (10% drop from 20.0): Retracement within tolerance (10% < 15%)
    d4 = evaluate_exit_strategy(config, state, current_market_cap=18.0)
    assert d4.action == ExitAction.HOLD

    # Price drops to 16.8 (16% drop from 20.0): Trailing stop triggers
    d5 = evaluate_exit_strategy(config, state, current_market_cap=16.8)
    assert d5.action == ExitAction.FULL_EXIT
    assert d5.exit_type == "trailing_stop"
    assert "trailing_stop_hit" in d5.reason
    assert d5.sell_tokens == 10_000


def test_evaluate_exit_strategy_low_balance_and_small_remainder():
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=20.0,
        peak_market_cap=20.0,
        initial_token_amount=10,
        remaining_token_amount=10,
    )

    # Small balance below min sell balance
    d_low = evaluate_exit_strategy(
        config, state, current_market_cap=20.0, token_balance=0
    )
    assert d_low.action == ExitAction.HOLD

    # Tier 1 with small balance where remainder <= min_sell_balance triggers FULL_EXIT
    d_small = evaluate_exit_strategy(
        config, state, current_market_cap=20.0, token_balance=2
    )
    assert d_small.action == ExitAction.FULL_EXIT
    assert d_small.target_tier == 1


def test_should_exit_position_compatibility():
    config = resolve_strategy_config("balanced")

    # Simple performance check without position state
    assert not should_exit_position(config, performance=1.1, token_balance=100)
    assert should_exit_position(config, performance=0.8, token_balance=100)
    assert should_exit_position(config, performance=2.0, token_balance=100)

    # With position state dict
    pos = {
        "entry_market_cap": 10.0,
        "current_market_cap": 20.0,
        "initial_token_amount": 1000,
        "remaining_token_amount": 1000,
    }
    assert should_exit_position(
        config,
        performance=2.0,
        token_balance=1000,
        position=pos,
        current_market_cap=20.0,
    )


def test_trading_strategy_exit_and_peak_methods():
    config = resolve_strategy_config("conservative")
    strat = TradingStrategy(config)

    pos = {
        "entry_market_cap": 10.0,
        "current_market_cap": 10.0,
        "initial_token_amount": 500,
        "remaining_token_amount": 500,
    }

    # Update peak
    peak = strat.update_peak(pos, 15.0)
    assert peak == 15.0

    # Evaluate exit
    decision = strat.evaluate_exit(pos, current_market_cap=18.0, token_balance=500)
    assert decision.action == ExitAction.PARTIAL_EXIT
    assert decision.exit_type == "tier_1"

    # Strategy summary
    summary = strat.summary()
    assert summary["enable_trailing_stop"] is True
    assert summary["enable_tiered_take_profit"] is True
    assert summary["tier_1_take_profit"] == 1.8


def test_bot_risk_track_position_peak():
    class DummyBot:
        def __init__(self):
            self.active_positions = {
                "mint_123": {
                    "entry_market_cap": 10.0,
                    "current_market_cap": 10.0,
                }
            }

    bot = DummyBot()
    peak = track_position_peak(bot, mint="mint_123", current_market_cap=25.0)
    assert peak == 25.0
    assert bot.active_positions["mint_123"]["peak_market_cap"] == 25.0
    assert bot.active_positions["mint_123"]["current_market_cap"] == 25.0

    # Non-existent mint returns market cap safely
    peak_missing = track_position_peak(
        bot, mint="missing_mint", current_market_cap=12.0
    )
    assert peak_missing == 12.0


def test_strategy_presets_and_custom_overrides():
    for preset_name in ["conservative", "balanced", "aggressive"]:
        preset_cfg = resolve_strategy_config(preset_name)
        assert preset_cfg.enable_trailing_stop is True
        assert preset_cfg.enable_tiered_take_profit is True
        assert preset_cfg.tier_1_take_profit > 1.0
        assert preset_cfg.tier_2_take_profit > preset_cfg.tier_1_take_profit

    # Custom override
    custom_cfg = resolve_strategy_config(
        "balanced",
        overrides={
            "enable_trailing_stop": False,
            "tier_1_take_profit": 2.2,
        },
    )
    assert custom_cfg.enable_trailing_stop is False
    assert custom_cfg.tier_1_take_profit == 2.2


def test_exits_and_decision_additional_branches(tmp_path):
    # Test Tier 2 full exit when remaining units <= min_sell_balance
    config = resolve_strategy_config("balanced")
    state = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=35.0,
        peak_market_cap=35.0,
        initial_token_amount=100,
        remaining_token_amount=25,
        tier_1_executed=True,
    )
    # Tier 2 triggers full exit because remainder is 0 <= min_sell_balance (1)
    d_t2_full = evaluate_exit_strategy(config, state, current_market_cap=35.0)
    assert d_t2_full.action == ExitAction.FULL_EXIT
    assert d_t2_full.exit_type == "tier_2"
    assert d_t2_full.target_tier == 2

    # Moonbag active but price is above floor -> HOLD
    state.record_partial_exit(tier=2, sold_tokens=25)
    assert state.moonbag_active
    d_moonbag_hold = evaluate_exit_strategy(
        config, state, current_market_cap=30.0, token_balance=50
    )
    assert d_moonbag_hold.action == ExitAction.HOLD

    # Standard take profit when tiered take profit is disabled
    cfg_no_tier = TradingBotConfig(
        enable_tiered_take_profit=False,
        enable_trailing_stop=False,
        take_profit=1.5,
        stop_loss=0.85,
    )
    state_no_tier = PositionExitState(
        entry_market_cap=10.0,
        current_market_cap=16.0,
        peak_market_cap=16.0,
        initial_token_amount=100,
        remaining_token_amount=100,
    )
    d_std_tp = evaluate_exit_strategy(cfg_no_tier, state_no_tier)
    assert d_std_tp.action == ExitAction.FULL_EXIT
    assert d_std_tp.exit_type == "take_profit"

    # Test TradingStrategy.is_eligible_for_buy and validate_risk
    strat = TradingStrategy(config)
    assert strat.is_eligible_for_buy(
        market_cap_sol=20.0, mint_seen_recently=False, buy_attempts=0
    )
    assert not strat.is_eligible_for_buy(
        market_cap_sol=1.0, mint_seen_recently=False, buy_attempts=0
    )
    assert strat.validate_risk(current_positions={}, proposed_entry_sol=0.01)

    # Test TradingBotConfig.from_file
    config_file = tmp_path / "bot_cfg.json"
    config_file.write_text(
        '{"preset": "conservative", "buy_amount_sol": 0.008}', encoding="utf-8"
    )
    loaded_cfg = TradingBotConfig.from_file(config_file)
    assert loaded_cfg.buy_amount_sol == 0.008
    assert loaded_cfg.strategy_preset == "conservative"


@pytest.mark.asyncio
async def test_bot_live_partial_sell_and_reconciliation(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from pumpfun_trading.bot.run import TradingBot

    SAMPLE_KEY = "5Mii42MBXa3reT732kLq8yW6FfE3d4D6aQoM2M3w5e9f8v7u6t5r4e3w2q1z9y8x"
    MINT = "So11111111111111111111111111111111111111112"

    config = TradingBotConfig(
        buy_amount_sol=0.01,
        enable_tiered_take_profit=True,
        tier_1_take_profit=2.0,
        tier_1_sell_fraction=0.50,
        tier_2_take_profit=3.5,
        tier_2_sell_fraction=0.25,
        enable_trailing_stop=True,
        min_sell_balance=10,
    )
    bot = TradingBot(
        private_key_b58=SAMPLE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        dry_run=False,
        paper_trade=False,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )

    # Mock execution client
    bot.execution.get_bonding_curve_pda = MagicMock(return_value=("CurvePDA", "bump"))
    bot.execution.get_bonding_curve_state = AsyncMock(
        return_value={
            "virtual_token_reserves": 1_000_000_000_000_000,
            "virtual_sol_reserves": 30_000_000_000,
            "market_cap_sol": 30.0,
        }
    )
    bot.execution.calculate_sell_sol_output = MagicMock(return_value=20_000_000)
    bot.execution.get_token_balance = AsyncMock(return_value=1_000_000)
    bot.execution.sell = AsyncMock(return_value="tx_sell_partial_sig")
    bot.execution.confirm_transaction = AsyncMock(return_value=True)

    # Populate active position
    bot.active_positions[MINT] = {
        "name": "LiveMoon",
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "peak_market_cap": 30.0,
        "initial_token_amount": 1_000_000,
        "remaining_token_amount": 1_000_000,
        "token_amount": 1_000_000,
    }

    # Execute Tier 1 partial sell
    sold_ok = await bot._sell_token(
        MINT,
        sell_fraction=0.50,
        reason="take_profit_tier_1",
        target_tier=1,
    )
    assert sold_ok is True
    assert MINT in bot.active_positions
    assert bot.active_positions[MINT]["remaining_token_amount"] == 500_000
    assert bot.active_positions[MINT]["tier_1_executed"] is True

    # Reconcile on-chain positions
    bot.execution.get_token_balance = AsyncMock(return_value=500_000)
    reconciled = await bot.reconcile_onchain_positions()
    assert reconciled[MINT]["status"] == "active"
    assert bot.active_positions[MINT]["remaining_token_amount"] == 500_000
    assert bot.active_positions[MINT]["tier_1_executed"] is True

    # Execute Tier 2 partial sell with Jito bundle
    bot.use_jito = True
    bot.execution.send_jito_bundle_with_fallback = AsyncMock(
        return_value="jito_bundle_sig"
    )
    sold_t2 = await bot._sell_token(
        MINT,
        sell_fraction=0.25,
        reason="take_profit_tier_2",
        target_tier=2,
    )
    assert sold_t2 is True
    assert bot.active_positions[MINT]["remaining_token_amount"] == 250_000
    assert bot.active_positions[MINT]["tier_2_executed"] is True
    assert bot.active_positions[MINT]["moonbag_active"] is True

    # Snapshot and recovery check
    bot._write_status_snapshot()
    bot.active_positions.clear()
    bot.safe_startup()
    assert MINT in bot.active_positions
    assert bot.active_positions[MINT]["remaining_token_amount"] == 250_000
    assert bot.active_positions[MINT]["tier_2_executed"] is True
    assert bot.active_positions[MINT]["moonbag_active"] is True

    # Full exit remainder
    sold_full = await bot._sell_token(MINT, reason="trailing_stop_hit")
    assert sold_full is True
    assert MINT not in bot.active_positions

    await bot.close()


def test_stagnant_curve_timeout_exit():
    """BUG-16: Stagnant bonding curves at 27.96 SOL with no price change must exit after timeout."""
    cfg = TradingBotConfig(
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=600.0,
        stagnant_price_delta_threshold_pct=0.005,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )

    # 1. Under timeout (elapsed 60s < 120s) -> HOLD
    d_early = evaluate_exit_strategy(cfg, state, current_market_cap=27.96, now=t0 + 60.0)
    assert d_early.action == ExitAction.HOLD

    # 2. Reached timeout (elapsed 120.1s >= 120.0s) -> FULL_EXIT
    d_timeout = evaluate_exit_strategy(cfg, state, current_market_cap=27.96, now=t0 + 120.1)
    assert d_timeout.action == ExitAction.FULL_EXIT
    assert d_timeout.exit_type == "stagnant_timeout"
    assert "stagnant_curve_timeout" in d_timeout.reason
    assert d_timeout.sell_tokens == 1_000_000

    # 3. should_exit_position helper returns True
    assert should_exit_position(
        cfg,
        performance=1.0,
        token_balance=1_000_000,
        position=state,
        current_market_cap=27.96,
        now=t0 + 120.1,
    ) is True


def test_stagnant_curve_price_movement_resets_timer():
    """BUG-16: Meaningful price changes reset last_price_change_at and prevent premature stagnation exits."""
    cfg = TradingBotConfig(
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        stagnant_price_delta_threshold_pct=0.005,  # 0.5%
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )

    # At t = 1090s (90s elapsed), price moves from 27.96 to 30.0 SOL (+7.3% > 0.5%)
    t_move = t0 + 90.0
    d_move = evaluate_exit_strategy(cfg, state, current_market_cap=30.0, now=t_move)
    assert d_move.action == ExitAction.HOLD
    assert state.last_price_change_at == t_move
    assert state.last_price == 30.0

    # At t = 1150s (150s from start, but only 60s from price move) -> HOLD
    d_mid = evaluate_exit_strategy(cfg, state, current_market_cap=30.0, now=t0 + 150.0)
    assert d_mid.action == ExitAction.HOLD

    # At t = 1211s (121s after price move) -> Stagnant Exit triggers
    d_stagnant = evaluate_exit_strategy(cfg, state, current_market_cap=30.0, now=t_move + 121.0)
    assert d_stagnant.action == ExitAction.FULL_EXIT
    assert d_stagnant.exit_type == "stagnant_timeout"


def test_max_hold_duration_timeout_exit():
    """BUG-16: Positions exceeding max_hold_time_seconds must exit regardless of minor price movement."""
    cfg = TradingBotConfig(
        enable_stagnant_exit=True,
        stagnant_timeout_seconds=120.0,
        enable_max_hold_timeout=True,
        max_hold_time_seconds=300.0,
        stagnant_price_delta_threshold_pct=0.005,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=30.0,
    )

    # Price moves frequently every 80 seconds, resetting stagnant timer:
    state.update_price(31.0, now=t0 + 80.0)
    state.update_price(32.0, now=t0 + 160.0)
    state.update_price(33.0, now=t0 + 240.0)

    # At t = 1280s (280s < 300s) -> HOLD (stagnant elapsed is 40s < 120s, max hold is 280s < 300s)
    d_hold = evaluate_exit_strategy(cfg, state, current_market_cap=33.0, now=t0 + 280.0)
    assert d_hold.action == ExitAction.HOLD

    # At t = 1301s (301s >= 300s max hold limit) -> FULL_EXIT (max_hold_timeout)
    d_max = evaluate_exit_strategy(cfg, state, current_market_cap=33.0, now=t0 + 301.0)
    assert d_max.action == ExitAction.FULL_EXIT
    assert d_max.exit_type == "max_hold_timeout"
    assert "max_hold_time_exceeded" in d_max.reason


def test_timeout_flags_disabled():
    """Disabled stagnant and max hold flags must not trigger timeout exits."""
    cfg = TradingBotConfig(
        enable_stagnant_exit=False,
        stagnant_timeout_seconds=60.0,
        enable_max_hold_timeout=False,
        max_hold_time_seconds=120.0,
    )
    t0 = 1000.0
    state = PositionExitState(
        entry_market_cap=27.96,
        current_market_cap=27.96,
        peak_market_cap=27.96,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        entry_time=t0,
        last_price_change_at=t0,
        last_price=27.96,
    )
    d = evaluate_exit_strategy(cfg, state, current_market_cap=27.96, now=t0 + 10_000.0)
    assert d.action == ExitAction.HOLD


def test_preset_stagnant_and_max_hold_configs():
    """Verify preset definitions configure stagnant and max hold limits properly."""
    cfg_cons = resolve_strategy_config("conservative")
    assert cfg_cons.enable_stagnant_exit is True
    assert cfg_cons.stagnant_timeout_seconds == 180.0
    assert cfg_cons.max_hold_time_seconds == 900.0

    cfg_bal = resolve_strategy_config("balanced")
    assert cfg_bal.enable_stagnant_exit is True
    assert cfg_bal.stagnant_timeout_seconds == 120.0
    assert cfg_bal.max_hold_time_seconds == 600.0

    cfg_agg = resolve_strategy_config("aggressive")
    assert cfg_agg.enable_stagnant_exit is True
    assert cfg_agg.stagnant_timeout_seconds == 60.0
    assert cfg_agg.max_hold_time_seconds == 300.0
