"""Regression tests for bot runtime, persistence and risk fixes (Batch 4b)."""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pumpfun_trading.bot.lifecycle import TradingBotState
from pumpfun_trading.bot.risk import (
    DailyEquityTracker,
    check_loss_per_trade,
    check_risk_limits,
)
from pumpfun_trading.bot.run import TradingBot
from pumpfun_trading.bot.strategy import TradingBotConfig
from pumpfun_trading.sdk.raydium import RaydiumPoolKeys

SAMPLE_PRIVATE_KEY = "1111111111111111111111111111111111111111111111111111111111111111"
MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
MINT_2 = "So11111111111111111111111111111111111111112"


def make_bot(tmp_path, **config_kwargs) -> TradingBot:
    config = TradingBotConfig(buy_amount_sol=0.01, dry_run=True, **config_kwargs)
    return TradingBot(
        private_key_b58=SAMPLE_PRIVATE_KEY,
        rpc_url="https://api.mainnet-beta.solana.com",
        config=config,
        bot_status_path=str(tmp_path / "status.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def make_pool(mint: str) -> RaydiumPoolKeys:
    fields = {name: f"{name}111" for name in RaydiumPoolKeys.__slots__}
    fields["coin_mint"] = mint
    return RaydiumPoolKeys(**fields)


async def test_snapshot_round_trip_keeps_cost_basis_and_pool(tmp_path):
    """BUG-45: cost_sol, position_id and pool keys survive a restart."""
    bot = make_bot(tmp_path)
    for mint in (MINT, MINT_2):
        bot.position_manager.record_buy(
            mint=mint,
            token_amount=350_000_000_000,
            cost_sol=0.01,
            entry_market_cap=30.0,
            buy_price=2.8e-8,
            metadata={"position_id": f"trade-{mint[:4]}"},
        )
    bot.active_positions = bot.position_manager.get_all_positions()
    bot._raydium_exit_pools[MINT_2] = make_pool(MINT_2)
    bot._migrating_mints.add(MINT_2)
    bot._write_status_snapshot()
    await bot.close()

    restored = make_bot(tmp_path)
    pos = restored.active_positions[MINT]
    assert pos["cost_sol"] == pytest.approx(0.01)
    assert pos["position_id"] == f"trade-{MINT[:4]}"
    assert "pool_keys" not in pos
    pool_pos = restored.active_positions[MINT_2]
    assert pool_pos["pool_keys"]["coin_mint"] == MINT_2
    assert MINT_2 in restored._migrating_mints
    assert isinstance(restored._exit_pool_keys(MINT_2, pool_pos), RaydiumPoolKeys)

    # Realized PnL uses the SOL cost, not the per-token unit price: at an
    # unchanged price only the modelled protocol fees are lost (FEAT-49).
    assert await restored._sell_token(MINT, reason="test") is True
    fee_loss = 0.01 * (restored._paper_round_trip_fee_factor() - 1.0)
    assert restored._trade_ledger[-1]["gross_pnl_sol"] == pytest.approx(fee_loss)
    assert restored.daily_equity_tracker.realized_daily_gross_pnl_sol == (
        pytest.approx(fee_loss)
    )
    await restored.close()


async def test_unit_buy_price_never_used_as_cost(tmp_path):
    """BUG-45: a position without cost_sol falls back to buy_amount_sol."""
    bot = make_bot(tmp_path)
    bot.active_positions[MINT] = {
        "name": "Legacy",
        "token_amount": 100_000_000,
        "initial_token_amount": 100_000_000,
        "entry_market_cap": 30.0,
        "current_market_cap": 30.0,
        "buy_price": 2.8e-8,
    }
    assert await bot._sell_token(MINT, reason="test") is True
    fee_loss = 0.01 * (bot._paper_round_trip_fee_factor() - 1.0)
    assert bot.daily_equity_tracker.realized_daily_gross_pnl_sol == pytest.approx(
        fee_loss
    )
    await bot.close()


def test_daily_rollover_releases_latched_breaker():
    """BUG-47: a lock taken late on day 1 clears at the next UTC date."""
    tracker = DailyEquityTracker()
    day1 = datetime.datetime(2026, 10, 15, 23, 0, tzinfo=datetime.timezone.utc)
    tracker.initialize_or_rollover(1.0, 0.0, day1)
    tracker.realized_daily_pnl_sol = -0.5
    tracker.circuit_breaker_engaged = True
    tracker.locked_at_timestamp = day1.timestamp()
    tracker.lock_reason = "locked"

    locked, _ = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.2,
        emergency_hard_lock_hours=24,
        current_wallet_balance_sol=0.5,
        now_timestamp=day1.timestamp() + 600,
        now_utc=day1 + datetime.timedelta(minutes=10),
    )
    assert locked is True

    day2 = day1 + datetime.timedelta(hours=2)
    locked, _ = tracker.evaluate_circuit_breaker(
        max_daily_drawdown_pct=0.2,
        emergency_hard_lock_hours=24,
        current_wallet_balance_sol=0.5,
        now_timestamp=day2.timestamp(),
        now_utc=day2,
    )
    assert locked is False
    assert tracker.circuit_breaker_engaged is False
    assert tracker.locked_at_timestamp is None
    assert tracker.realized_daily_pnl_sol == 0.0
    assert tracker.starting_equity_sol == pytest.approx(0.5)


def _risk_bot(**config):
    return SimpleNamespace(
        config=SimpleNamespace(**config), active_positions={}, _last_event=""
    )


def test_loss_per_trade_compares_sol_and_handles_zero_buy_amount():
    """BUG-70: the cap fires on SOL lost and never divides by buy_amount_sol."""
    bot = _risk_bot(max_loss_per_trade_sol=0.005, buy_amount_sol=0.0)
    bot.active_positions[MINT] = {"cost_sol": 0.01, "entry_market_cap": 30.0}
    assert check_loss_per_trade(bot, mint=MINT, current_market_cap=27.0) is True
    assert check_loss_per_trade(bot, mint=MINT, current_market_cap=12.0) is False
    assert "trade loss" in bot._last_event


def test_exposure_scaled_by_remaining_fraction():
    """BUG-71: partially sold positions only count their remaining cost."""
    bot = _risk_bot(
        buy_amount_sol=0.05,
        max_total_exposure_sol=0.25,
        max_position_size_sol=0.1,
        max_token_concentration_pct=0.5,
    )
    positions = {
        MINT: {
            "cost_sol": 0.2,
            "initial_token_amount": 1_000,
            "remaining_token_amount": 500,
        }
    }
    assert check_risk_limits(
        bot, mint=MINT_2, proposed_entry_sol=0.05, current_positions=positions
    )


async def test_no_buy_sent_after_shutdown(tmp_path):
    """BUG-91: a buy in flight at shutdown never sends or revives the bot."""
    bot = make_bot(tmp_path)
    bot._should_buy = lambda *a, **k: True
    bot._check_account_equity_guard = AsyncMock(return_value=True)
    bot._validate_balance = AsyncMock(return_value=True)
    bot._resolve_token_name = AsyncMock(return_value=None)
    bot.executor.execute_buy = AsyncMock()
    bot.request_shutdown()
    assert await bot._buy_token(MINT, 30.0) is False
    bot.executor.execute_buy.assert_not_awaited()

    bot.state = TradingBotState.SHUTDOWN
    bot._transition_to(TradingBotState.MONITORING, reason="buy_failed")
    assert bot.state == TradingBotState.SHUTDOWN
    await bot.close()


def test_max_positions_per_mint_is_enforced(tmp_path):
    """BUG-92: unsupported pyramiding values are clamped to one lot per mint."""
    bot = make_bot(tmp_path, max_positions_per_mint=3)
    assert bot.max_positions_per_mint == 1
    bot.active_positions[MINT] = {"name": "Held"}
    assert bot._should_buy(MINT, 30.0) is False


async def test_start_closes_http_clients(tmp_path):
    """BUG-74: start() releases the execution and API sessions on exit."""
    bot = make_bot(tmp_path)
    bot.execution.close = AsyncMock()
    bot.api.close = AsyncMock()

    async def empty_listen():
        bot.request_shutdown()
        if False:  # pragma: no cover
            yield None

    bot.geyser_client.listen = empty_listen
    await bot.start()
    bot.execution.close.assert_awaited()
    bot.api.close.assert_awaited()
