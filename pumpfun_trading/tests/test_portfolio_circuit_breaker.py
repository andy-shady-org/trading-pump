import datetime
import pytest

from pumpfun_trading.bot.risk import (
    DailyEquityTracker,
    check_daily_drawdown,
    evaluate_portfolio_circuit_breaker,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.presets import resolve_strategy_config


def test_daily_equity_tracker_initialization_and_rollover():
    tracker = DailyEquityTracker()
    assert tracker.starting_equity_sol == 0.0
    assert tracker.peak_daily_equity_sol == 0.0
    assert tracker.last_reset_date_utc == ""
    assert not tracker.circuit_breaker_engaged

    # Initial setup on day 1
    day1 = datetime.datetime(2026, 10, 12, 10, 0, 0, tzinfo=datetime.timezone.utc)
    res = tracker.initialize_or_rollover(10.0, 2.5, now_utc=day1)
    assert res is True
    assert tracker.starting_equity_sol == 12.5
    assert tracker.peak_daily_equity_sol == 12.5
    assert tracker.last_reset_date_utc == "2026-10-12"

    # Same day call should not reset
    res = tracker.initialize_or_rollover(9.0, 2.0, now_utc=day1)
    assert res is False
    assert tracker.starting_equity_sol == 12.5

    # Day 2 rollover at 00:00 UTC
    day2 = datetime.datetime(2026, 10, 13, 0, 1, 0, tzinfo=datetime.timezone.utc)
    tracker.record_realized_trade(1.5)
    assert tracker.realized_daily_pnl_sol == 1.5

    res = tracker.initialize_or_rollover(11.0, 1.0, now_utc=day2)
    assert res is True
    assert tracker.starting_equity_sol == 12.0
    assert tracker.peak_daily_equity_sol == 12.0
    assert tracker.realized_daily_pnl_sol == 0.0
    assert tracker.last_reset_date_utc == "2026-10-13"


def test_equity_updates_and_drawdown_calculation():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # Valuation rises
    current_eq, dd = tracker.update_valuation(12.0, 0.0, now_utc=day)
    assert current_eq == 12.0
    assert tracker.peak_daily_equity_sol == 12.0
    assert dd == 0.0

    # Valuation drops to 10.2 SOL from peak of 12.0 SOL
    # Drop = 1.8 SOL -> Drawdown = 1.8 / 12.0 (peak) = 15%
    current_eq, dd = tracker.update_valuation(10.2, 0.0, now_utc=day)
    assert current_eq == 10.2
    assert tracker.peak_daily_equity_sol == 12.0
    assert pytest.approx(dd, 0.001) == 0.15


def test_drawdown_calculation_with_low_baseline_high_peak():
    """
    Regression test for BUG-12: Small starting baseline (0.20 SOL) with large peak (37.3841 SOL).
    A minor pullback from peak (e.g. 0.6904 SOL to 36.6937 SOL) must be ~1.85% drawdown,
    NOT >100% or falsely tripping the circuit breaker limit (20.00%).
    """
    tracker = DailyEquityTracker()
    assert tracker.calculate_drawdown(0.0, 0.0) == 0.0

    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(0.20, 0.0, now_utc=day)
    assert tracker.starting_equity_sol == 0.20
    assert tracker.peak_daily_equity_sol == 0.20

    # Equity grows to 37.3841 SOL
    current_eq, dd = tracker.update_valuation(37.3841, 0.0, now_utc=day)
    assert current_eq == 37.3841
    assert tracker.peak_daily_equity_sol == 37.3841
    assert dd == 0.0

    # Equity pulls back to 36.6937 SOL (drop = 0.6904 SOL)
    current_eq, dd = tracker.update_valuation(36.6937, 0.0, now_utc=day)
    assert current_eq == 36.6937
    assert tracker.peak_daily_equity_sol == 37.3841
    # 0.6904 / 37.3841 = 0.0184676... (~1.85%)
    expected_dd = (37.3841 - 36.6937) / 37.3841
    assert pytest.approx(dd, 1e-6) == expected_dd
    assert dd < 0.02  # Less than 2%

    # Evaluate circuit breaker with 20% max allowed limit
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.20,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=36.6937,
        open_positions_valuation_sol=0.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged


def test_circuit_breaker_trigger_and_auto_unlock():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # 1. Normal trading within limits (5% drop from peak 10.0 -> 9.5 SOL)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=9.5,
        open_positions_valuation_sol=0.0,
        now_timestamp=1000.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged

    # 2. Severe loss breaching 15% limit (peak 10.0 -> 8.0 SOL = 20% drawdown)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0,
        now_utc=day,
    )
    assert locked
    assert "portfolio drawdown 20.00% exceeded" in reason
    assert tracker.circuit_breaker_engaged
    assert tracker.locked_at_timestamp == 1100.0
    assert tracker.total_lock_count == 1

    # 3. Subsequent check while lock duration is active (e.g., after 1 hour = 3600s)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0 + 3600.0,
        now_utc=day,
    )
    assert locked
    assert "portfolio drawdown 20.00% exceeded" in reason

    # 4. Auto-unlock after 24 hours (24 * 3600 = 86400s)
    locked, reason = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.0,
        open_positions_valuation_sol=0.0,
        now_timestamp=1100.0 + 86400.0,
        now_utc=day,
    )
    assert not locked
    assert reason == ""
    assert not tracker.circuit_breaker_engaged
    assert tracker.starting_equity_sol == 8.0
    assert tracker.peak_daily_equity_sol == 8.0


def test_circuit_breaker_manual_reset():
    tracker = DailyEquityTracker()
    day = datetime.datetime(2026, 10, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(10.0, 0.0, now_utc=day)

    # Trip breaker
    tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.10,
        emergency_hard_lock_hours=24.0,
        current_wallet_balance_sol=8.5,
        now_timestamp=1000.0,
        now_utc=day,
    )
    assert tracker.circuit_breaker_engaged

    # Manual reset with new baseline
    tracker.reset_circuit_breaker(force=True, new_baseline_sol=8.5)
    assert not tracker.circuit_breaker_engaged
    assert tracker.locked_at_timestamp is None
    assert tracker.lock_reason == ""
    assert tracker.starting_equity_sol == 8.5
    assert tracker.peak_daily_equity_sol == 8.5


def test_daily_equity_tracker_serialization():
    tracker = DailyEquityTracker(
        starting_equity_sol=15.0,
        peak_daily_equity_sol=18.5,
        realized_daily_pnl_sol=3.5,
        last_reset_date_utc="2026-10-12",
        circuit_breaker_engaged=True,
        locked_at_timestamp=1700000000.0,
        lock_reason="test lock",
        total_lock_count=2,
    )
    data = tracker.to_dict()
    assert data["starting_equity_sol"] == 15.0
    assert data["peak_daily_equity_sol"] == 18.5
    assert data["circuit_breaker_engaged"] is True

    restored = DailyEquityTracker.from_dict(data)
    assert restored.starting_equity_sol == 15.0
    assert restored.peak_daily_equity_sol == 18.5
    assert restored.realized_daily_pnl_sol == 3.5
    assert restored.last_reset_date_utc == "2026-10-12"
    assert restored.circuit_breaker_engaged is True
    assert restored.locked_at_timestamp == 1700000000.0
    assert restored.lock_reason == "test lock"
    assert restored.total_lock_count == 2


def test_evaluate_portfolio_circuit_breaker_with_bot_mock():
    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 10.0
            self.active_positions = {
                "mintA": {
                    "cost_sol": 2.0,
                    "entry_sol": 2.0,
                    "entry_market_cap": 2.0,
                    "current_market_cap": 2.0,
                },
            }
            self.config = TradingBotConfig(
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # Initial evaluation sets baseline to 12.0 SOL (10.0 wallet + 2.0 position)
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert reason == ""
    assert bot.daily_equity_tracker.starting_equity_sol == 12.0
    assert check_daily_drawdown(bot) is True

    # Drop position valuation to 0.0 SOL and wallet to 9.5 SOL -> total equity 9.5 SOL (drop of 2.5 SOL on 12.0 = 20.8%)
    bot.wallet_balance_sol = 9.5
    bot.active_positions["mintA"]["current_market_cap"] = 0.0

    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert is_breached
    assert "portfolio drawdown" in reason
    assert "circuit breaker:" in bot._last_event
    assert check_daily_drawdown(bot) is False


def test_circuit_breaker_realistic_pumpfun_lifecycle():
    """
    Regression test for BUG-15:
    Realistic trade lifecycle on Pump.fun (~27.96 SOL initial market cap).
    Opening a position (0.01 SOL cost) and subsequently closing it with a small profit
    must not trigger a false-positive 99%+ portfolio drawdown circuit breaker lock.
    """

    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 0.10
            self.active_positions = {}
            self.config = TradingBotConfig(
                buy_amount_sol=0.01,
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # 1. Starting state: wallet = 0.10 SOL, no positions -> baseline equity = 0.10 SOL
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.starting_equity_sol == 0.10
    assert bot.daily_equity_tracker.peak_daily_equity_sol == 0.10

    # 2. Buy token: wallet drops to 0.09 SOL, position opened with 0.01 SOL cost at 27.95899 SOL MC
    mint = "PumpFunToken111111111111111111111111111111"
    bot.wallet_balance_sol = 0.09
    bot.active_positions[mint] = {
        "cost_sol": 0.01,
        "entry_sol": 0.01,
        "entry_market_cap": 27.95899,
        "current_market_cap": 27.95899,
        "token_amount": 100_000_000,
    }

    # Evaluate circuit breaker: open value is 0.01 SOL, total equity is 0.10 SOL
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(
        0.10, rel=1e-5
    )

    # 3. Market cap increases slightly to 28.50 SOL (+1.93%)
    bot.active_positions[mint]["current_market_cap"] = 28.50
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    expected_peak = 0.09 + (0.01 * (28.50 / 27.95899))
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(
        expected_peak, rel=1e-5
    )

    # 4. Position closes with 0.0102 SOL proceeds (+2% profit returned to wallet)
    bot.active_positions.pop(mint)
    bot.wallet_balance_sol = 0.1002

    # Evaluate circuit breaker after trade close: total equity = 0.1002 SOL (drawdown = 0.0%)
    is_breached, reason = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert reason == ""
    assert bot.daily_equity_tracker.circuit_breaker_engaged is False


def test_circuit_breaker_partial_exit_lifecycle():
    """
    Regression test for BUG-21:
    Verifies that when a position executes a partial exit (e.g. 50% sold at 2.0x),
    the circuit breaker evaluates remaining holding value accurately (scaled by 50%),
    preventing over-inflation of peak equity and avoiding false drawdown spikes when the
    remainder is subsequently closed.
    """
    from pumpfun_trading.bot.position_manager import PositionManager

    class MockBot:
        def __init__(self):
            self.wallet_balance_sol = 0.90
            self.config = TradingBotConfig(
                buy_amount_sol=0.10,
                max_daily_drawdown_pct=0.15,
                emergency_hard_lock_hours=24.0,
            )
            self.position_manager = PositionManager(self.config)
            self.active_positions = self.position_manager._positions
            self.daily_equity_tracker = DailyEquityTracker()
            self._last_event = ""

    bot = MockBot()
    # 1. Starting baseline: wallet = 0.90 SOL + buy 0.10 SOL -> baseline = 1.00 SOL
    mint = "PartialPumpToken11111111111111111111111111"
    bot.position_manager.record_buy(
        mint=mint,
        token_amount=1_000_000,
        cost_sol=0.10,
        entry_market_cap=30.0,
    )
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.starting_equity_sol == pytest.approx(1.00)
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.00)

    # 2. Market cap rises to 60.0 SOL (2.0x) -> open value = 0.20 SOL -> peak equity = 0.90 + 0.20 = 1.10 SOL
    bot.position_manager.update_price(mint, 60.0)
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.10)

    # 3. Tier 1 partial exit: sell 50% (500k tokens), returning 0.10 SOL to wallet -> wallet = 1.00 SOL
    closed, rem = bot.position_manager.record_sell(
        mint, sold_tokens=500_000, proceeds_sol=0.10, target_tier=1, is_partial=True
    )
    assert not closed
    assert rem == 500_000
    bot.wallet_balance_sol = 1.00

    # With BUG-21 fixed: remaining open value = 0.05 * (60 / 30) = 0.10 SOL
    # Total equity = 1.00 (wallet) + 0.10 (open) = 1.10 SOL (exact match to peak!)
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.peak_daily_equity_sol == pytest.approx(1.10)
    assert bot.daily_equity_tracker.calculate_drawdown(
        bot.wallet_balance_sol, bot.position_manager.calculate_total_open_value()
    ) == pytest.approx(0.0)

    # 4. Final close of remaining 50% tokens at 60.0 SOL (yielding 0.10 SOL -> wallet = 1.10 SOL)
    bot.position_manager.record_sell(
        mint, sold_tokens=500_000, proceeds_sol=0.10, is_partial=False
    )
    bot.wallet_balance_sol = 1.10
    is_breached, _ = evaluate_portfolio_circuit_breaker(bot)
    assert not is_breached
    assert bot.daily_equity_tracker.circuit_breaker_engaged is False


def test_strategy_presets_circuit_breaker_config():
    cons = resolve_strategy_config("conservative")
    assert cons.max_daily_drawdown_pct == 0.15
    assert cons.emergency_hard_lock_hours == 24.0
    assert cons.auto_liquidate_on_circuit_breaker is True

    bal = resolve_strategy_config("balanced")
    assert bal.max_daily_drawdown_pct == 0.20
    assert bal.emergency_hard_lock_hours == 24.0
    assert bal.auto_liquidate_on_circuit_breaker is True

    agg = resolve_strategy_config("aggressive")
    assert agg.max_daily_drawdown_pct == 0.25
    assert agg.emergency_hard_lock_hours == 12.0
    assert agg.auto_liquidate_on_circuit_breaker is True


async def test_trading_bot_circuit_breaker_liquidates_and_locks(tmp_path):
    from unittest.mock import MagicMock
    from pumpfun_trading.bot.run import TradingBot
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate

    status_file = tmp_path / "status.json"
    audit_file = tmp_path / "audit.jsonl"

    config = TradingBotConfig(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        auto_liquidate_on_circuit_breaker=True,
        dry_run=True,
    )
    bot = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot.alert_enabled = True
    bot._send_alert = MagicMock()

    # Seed initial position and baseline (baseline = 10.0 + 2.0 = 12.0 SOL)
    mint = "TestMint1111111111111111111111111111111111"
    bot.wallet_balance_sol = 10.0
    bot.active_positions[mint] = {
        "name": "TestToken",
        "entry_market_cap": 2.0,
        "current_market_cap": 2.0,
        "peak_market_cap": 2.0,
        "token_amount": 1_000_000,
        "initial_token_amount": 1_000_000,
        "cost_sol": 2.0,
        "entry_sol": 2.0,
    }
    bot.daily_equity_tracker.initialize_or_rollover(10.0, 2.0)

    # 1. Update with minor drop (mc = 1.8 SOL -> total equity 11.8 / 12.0 = ~1.6% dd)
    update = BondingCurveStateUpdate(
        mint=mint,
        bonding_curve_pubkey="Curve111111111111111111111111111111111111111",
        slot=100,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.001,
        market_cap_sol=1.8,
        timestamp=1000.0,
    )
    await bot._handle_bonding_curve_state_update(update)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged
    assert mint in bot.active_positions

    # 2. Update with catastrophic drop (mc = 0.05 SOL, wallet drops to 9.5 SOL -> total equity 9.55 / 12.0 = 20.4% dd > 15%)
    bot.wallet_balance_sol = 9.5
    update_crash = BondingCurveStateUpdate(
        mint=mint,
        bonding_curve_pubkey="Curve111111111111111111111111111111111111111",
        slot=101,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.0001,
        market_cap_sol=0.05,
        timestamp=1001.0,
    )
    await bot._handle_bonding_curve_state_update(update_crash)

    # Verify circuit breaker engaged, position emergency liquidated, alert sent
    assert bot.daily_equity_tracker.circuit_breaker_engaged
    assert mint not in bot.active_positions
    bot._send_alert.assert_called()

    # 3. New candidate token rejected immediately while circuit breaker locked
    candidate_mint = "CandidateMint22222222222222222222222222222"
    update_candidate = BondingCurveStateUpdate(
        mint=candidate_mint,
        bonding_curve_pubkey="Curve222222222222222222222222222222222222222",
        slot=102,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.005,
        market_cap_sol=10.0,
        timestamp=1002.0,
    )
    await bot._handle_bonding_curve_state_update(update_candidate)
    assert candidate_mint not in bot.active_positions
    assert bot._last_event == "circuit_breaker_active"

    # Also via new token event
    await bot._handle_new_token_event({"mint": candidate_mint, "marketCapSol": 10.0})
    assert candidate_mint not in bot.active_positions
    assert bot._last_event == "circuit_breaker_active"

    # 4. Manual operator reset
    bot.reset_circuit_breaker(force=True)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged


async def test_trading_bot_circuit_breaker_snapshot_persistence_and_restore(tmp_path):
    from pumpfun_trading.bot.run import TradingBot

    status_file = tmp_path / "status.json"
    audit_file = tmp_path / "audit.jsonl"

    config = TradingBotConfig(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        dry_run=True,
    )
    bot = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot.daily_equity_tracker.circuit_breaker_engaged = True
    bot.daily_equity_tracker.lock_reason = "drawdown test limit breached"
    bot.daily_equity_tracker.starting_equity_sol = 20.0
    bot.daily_equity_tracker.peak_daily_equity_sol = 22.0
    bot.daily_equity_tracker.last_reset_date_utc = (
        DailyEquityTracker.get_current_utc_date()
    )
    bot.wallet_balance_sol = 20.0
    bot._write_status_snapshot()

    assert status_file.exists()

    # Create new bot instance and verify safe_startup restores lock state
    bot2 = TradingBot(
        "1" * 64,
        "https://mock.rpc",
        config=config,
        bot_status_path=str(status_file),
        audit_log_path=str(audit_file),
    )
    bot2.safe_startup()
    assert bot2.daily_equity_tracker.circuit_breaker_engaged is True
    assert bot2.daily_equity_tracker.starting_equity_sol == 20.0
    assert bot2.daily_equity_tracker.peak_daily_equity_sol == 22.0


async def test_trading_bot_trade_event_triggers_circuit_breaker():
    from unittest.mock import MagicMock
    from pumpfun_trading.bot.run import TradingBot
    from pumpfun_trading.streams.geyser import TradeEventUpdate

    config = TradingBotConfig(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        dry_run=True,
    )
    bot = TradingBot("1" * 64, "https://mock.rpc", config=config)
    bot.alert_enabled = True
    bot._send_alert = MagicMock()

    mint = "TradeEventMint1111111111111111111111111111"
    bot.wallet_balance_sol = 8.0
    bot.active_positions[mint] = {
        "name": "TokenTrade",
        "entry_market_cap": 2.0,
        "current_market_cap": 2.0,
        "peak_market_cap": 2.0,
        "token_amount": 1_000_000,
        "cost_sol": 2.0,
        "entry_sol": 2.0,
    }
    bot.daily_equity_tracker.initialize_or_rollover(8.0, 2.0)  # baseline = 10.0 SOL

    # Severe dump via TradeEventUpdate: virtual sol reserves drop
    update = TradeEventUpdate(
        mint=mint,
        sol_amount_lamports=1_000_000_000,
        token_amount=1000,
        is_buy=False,
        user="Seller111",
        timestamp=1000,
        virtual_sol_reserves=50_000,  # 0.00005 SOL -> 0.05 SOL market cap
        virtual_token_reserves=1_000_000_000_000,
        real_sol_reserves=0,
        real_token_reserves=0,
        slot=12345,
        signature="sig1",
        received_at=1000.0,
    )
    await bot._handle_trade_event_update(update)
    assert bot.daily_equity_tracker.circuit_breaker_engaged


async def test_circuit_breaker_edge_cases_and_liquidation_branches():
    from unittest.mock import AsyncMock, MagicMock
    from pumpfun_trading.bot.run import TradingBot
    from pumpfun_trading.streams.geyser import CompleteEventUpdate

    config = TradingBotConfig(
        max_daily_drawdown_pct=0.15,
        emergency_hard_lock_hours=24.0,
        auto_liquidate_on_circuit_breaker=True,
        dry_run=True,
    )
    bot = TradingBot("1" * 64, "https://mock.rpc", config=config)
    bot.alert_enabled = False

    # 1. Reset circuit breaker without alert_enabled
    bot.daily_equity_tracker.circuit_breaker_engaged = True
    bot.reset_circuit_breaker(force=True)
    assert not bot.daily_equity_tracker.circuit_breaker_engaged

    # 2. _liquidate_all_positions when sell fails vs succeeds
    mint1 = "Mint1111111111111111111111111111111111111"
    mint2 = "Mint2222222222222222222222222222222222222"
    bot.active_positions[mint1] = {"name": "Token1", "entry_market_cap": 1.0}
    bot.active_positions[mint2] = {"name": "Token2", "entry_market_cap": 1.0}

    bot._sell_token = AsyncMock(side_effect=[True, False])
    liquidated = await bot._liquidate_all_positions(reason="test_liq")
    assert liquidated == [mint1]

    # 3. CompleteEventUpdate for mint not in active_positions vs in active_positions
    complete_update_missing = CompleteEventUpdate(
        mint="NotInPos1111111111111111111111111111111111",
        user="User11111111111111111111111111111111111111",
        bonding_curve="Curve1111111111111111111111111111111111111",
        timestamp=1000,
        slot=100,
    )
    await bot._handle_complete_event_update(complete_update_missing)

    bot.active_positions[mint1] = {"name": "Token1", "entry_market_cap": 1.0}
    complete_update_active = CompleteEventUpdate(
        mint=mint1,
        user="User11111111111111111111111111111111111111",
        bonding_curve="Curve1111111111111111111111111111111111111",
        timestamp=1001,
        slot=101,
    )
    bot._sell_token = AsyncMock(return_value=True)
    await bot._handle_complete_event_update(complete_update_active)
    # BUG-44: no curve sell after completion; the exit waits for the AMM pool.
    bot._sell_token.assert_not_called()
    assert mint1 in bot._migrating_mints

    # 4. _handle_new_token_event missing mint and stopped requested
    await bot._handle_new_token_event({})
    bot._stop_requested = True
    await bot._handle_new_token_event({"mint": mint1})
    bot._stop_requested = False

    # 5. _handle_bonding_curve_state_update candidate buy success branch
    from pumpfun_trading.streams.geyser import BondingCurveStateUpdate
    from pumpfun_trading.strategies.filters import TokenScreeningVerdict

    mint_candidate = "BuyCandidate11111111111111111111111111111"
    update_buy = BondingCurveStateUpdate(
        mint=mint_candidate,
        bonding_curve_pubkey="CurveBuy1111111111111111111111111111111111",
        slot=200,
        virtual_token_reserves=1000,
        virtual_sol_reserves=1000,
        real_token_reserves=500,
        real_sol_reserves=500,
        token_total_supply=1_000_000_000,
        complete=False,
        price_sol=0.005,
        market_cap_sol=12.0,
        timestamp=1000.0,
    )
    bot._enrich_and_screen_token = AsyncMock(
        return_value=TokenScreeningVerdict(
            mint=mint_candidate, passed=True, risk_score=10.0, reasons=[]
        )
    )
    bot._should_buy = MagicMock(return_value=True)
    bot._buy_token = AsyncMock(return_value=True)
    bot.wallet_balance_sol = 10.0
    await bot._handle_bonding_curve_state_update(update_buy)
    bot._buy_token.assert_called_once()
