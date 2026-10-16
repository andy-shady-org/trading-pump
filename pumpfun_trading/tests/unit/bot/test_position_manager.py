"""Unit tests for ``bot/position_manager.py`` position book and displacement."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pumpfun_trading.bot.position_manager import (
    CapitalDisplacementEngine,
    Position,
    PositionManager,
    _extract_position_fraction,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import ExitAction, PositionExitState

MINT = "MintAAA111"
CANDIDATE = "MintCandidate999"


class _FakeEvEvaluator:
    """Deterministic EV evaluator returning canned scores."""

    def __init__(self, scores: list[Any], candidate_ev: float) -> None:
        self.scores = scores
        self.candidate_ev = candidate_ev
        self.candidate_calls: list[tuple[str, Any, float]] = []

    def rank_positions_by_ev(
        self, positions: dict[str, dict[str, Any]], current_time: float
    ) -> list[Any]:
        return list(self.scores)

    def evaluate_candidate(
        self, mint: str, momentum_signal: Any = None, conviction_percentile: float = 0.0
    ) -> float:
        self.candidate_calls.append((mint, momentum_signal, conviction_percentile))
        return self.candidate_ev


def _score(mint: str, ev: float, displaceable: bool = True) -> SimpleNamespace:
    return SimpleNamespace(mint=mint, ev_score=ev, is_displaceable=displaceable)


def _manager(**overrides: Any) -> PositionManager:
    return PositionManager(TradingBotConfig(**overrides))


def _saturated_engine(
    scores: list[Any], candidate_ev: float, **overrides: Any
) -> tuple[CapitalDisplacementEngine, _FakeEvEvaluator]:
    config = TradingBotConfig(max_active_positions=1, **overrides)
    manager = PositionManager(config)
    manager.record_buy(MINT, 1_000_000, 0.01, 30.0)
    evaluator = _FakeEvEvaluator(scores, candidate_ev)
    return CapitalDisplacementEngine(config, manager, evaluator), evaluator


# --- _extract_position_fraction -------------------------------------------------


@pytest.mark.parametrize(
    ("pos", "expected"),
    [
        (
            SimpleNamespace(initial_token_amount=100, remaining_token_amount=25),
            0.25,
        ),
        (SimpleNamespace(initial_token_amount=100, token_amount=40), 0.4),
        (SimpleNamespace(token_amount=50, remaining_token_amount=None), 1.0),
        (SimpleNamespace(initial_token_amount=0), 1.0),
        (SimpleNamespace(initial_token_amount=100, remaining_token_amount=500), 1.0),
        (SimpleNamespace(initial_token_amount=100, remaining_token_amount=-5), 0.0),
    ],
)
def test_extract_position_fraction_object_positions_returns_clamped_fraction(
    pos: Any, expected: float
) -> None:
    assert _extract_position_fraction(pos) == pytest.approx(expected)


def test_extract_position_fraction_non_numeric_initial_returns_full() -> None:
    assert _extract_position_fraction({"initial_token_amount": "lots"}) == 1.0


def test_extract_position_fraction_non_numeric_remaining_falls_back_to_full() -> None:
    pos = {"initial_token_amount": 100, "remaining_token_amount": "half"}

    assert _extract_position_fraction(pos) == 1.0


def test_extract_position_fraction_dict_token_amount_used_as_remaining() -> None:
    pos = {"initial_token_amount": 200, "token_amount": 50}

    assert _extract_position_fraction(pos) == pytest.approx(0.25)


# --- PositionManager book -------------------------------------------------------


def test_position_manager_positions_property_exposes_live_book() -> None:
    manager = _manager()
    manager.record_buy(MINT, 10, 0.01, 30.0)

    assert manager.positions is manager.get_all_positions()
    assert list(manager.positions) == [MINT]


def test_record_buy_metadata_price_used_when_no_explicit_price() -> None:
    manager = _manager()

    pos = manager.record_buy(
        MINT, 1_000_000, 0.01, 30.0, metadata={"entry_price": 4.2e-8, "z_score": 1.5}
    )

    assert pos["buy_price"] == pytest.approx(4.2e-8)
    assert pos["entry_price"] == pytest.approx(4.2e-8)
    assert pos["z_score"] == 1.5


def test_record_buy_explicit_price_overrides_metadata() -> None:
    manager = _manager()

    pos = manager.record_buy(
        MINT, 1_000_000, 0.01, 30.0, buy_price=1e-6, metadata={"buy_price": 9.0}
    )

    assert pos["entry_price"] == pytest.approx(1e-6)
    # metadata is merged after the computed fields
    assert pos["buy_price"] == 9.0


@pytest.mark.parametrize(
    ("token_amount", "cost_sol", "entry_mc", "expected_price"),
    [
        (2_000_000, 0.02, 30.0, 0.01),
        (100, 0.5, 30.0, 0.005),
        (0, 0.0, 30.0, 30.0 / 1_000_000_000.0),
        (0, 0.0, 0.0, 0.0),
        (0, 0.25, 0.0, 0.25),
    ],
)
def test_record_buy_derived_price_table_matches_fallback_chain(
    token_amount: int, cost_sol: float, entry_mc: float, expected_price: float
) -> None:
    manager = _manager()

    pos = manager.record_buy(MINT, token_amount, cost_sol, entry_mc)

    assert pos["buy_price"] == pytest.approx(expected_price)


def test_record_buy_blank_name_and_zero_market_cap_use_defaults() -> None:
    manager = _manager()

    pos = manager.record_buy(MINT, 10, 0.01, 0.0, name="   ", reason="")

    assert pos["name"] == MINT
    assert pos["entry_market_cap"] == 30.0
    assert pos["entry_reason"] == "entry"


def test_record_sell_unknown_mint_reports_closed() -> None:
    assert _manager().record_sell("missing", 10) == (True, 0)


def test_record_sell_partial_keeps_position_with_remaining_tokens() -> None:
    manager = _manager(dry_run=True)
    manager.record_buy(MINT, 1_000, 0.01, 30.0)

    closed, remaining = manager.record_sell(MINT, 400, target_tier=1, is_partial=True)

    assert (closed, remaining) == (False, 600)
    assert manager[MINT]["remaining_token_amount"] == 600
    assert manager[MINT]["token_amount"] == 600


def test_record_sell_partial_below_min_sell_balance_closes_live_position() -> None:
    manager = _manager(dry_run=False, min_sell_balance=100)
    manager.record_buy(MINT, 1_000, 0.01, 30.0)

    assert manager.record_sell(MINT, 950, is_partial=True) == (True, 0)
    assert MINT not in manager


# --- update_price ---------------------------------------------------------------


def test_update_price_unknown_mint_echoes_market_cap() -> None:
    assert _manager().update_price("missing", 42.0) == (0.0, 42.0, 42.0)


def test_update_price_zero_entry_adopts_current_as_entry() -> None:
    manager = _manager()
    manager[MINT] = {"entry_market_cap": 0.0, "last_price": 0.0}

    entry, current, peak = manager.update_price(MINT, 50.0, now=10.0)

    assert (entry, current, peak) == (50.0, 50.0, 50.0)
    assert manager[MINT]["entry_market_cap"] == 50.0


def test_update_price_non_positive_last_price_resets_reference() -> None:
    manager = _manager()
    manager[MINT] = {
        "entry_market_cap": 30.0,
        "last_price": -1.0,
        "last_price_change_at": 1.0,
    }

    manager.update_price(MINT, 45.0, now=99.0)

    assert manager[MINT]["last_price"] == 45.0
    # the stagnation clock is not reset on a reference repair
    assert manager[MINT]["last_price_change_at"] == 1.0


def test_update_price_zero_market_cap_keeps_reference_and_peak() -> None:
    manager = _manager()
    manager.record_buy(MINT, 10, 0.01, 30.0)
    manager.update_price(MINT, 60.0, now=5.0)

    entry, current, peak = manager.update_price(MINT, -10.0, now=6.0)

    assert (entry, current, peak) == (30.0, 0.0, 60.0)
    assert manager[MINT]["last_price"] == 60.0
    assert manager[MINT]["last_price_change_at"] == 5.0


def test_update_price_small_move_below_threshold_does_not_reset_clock() -> None:
    manager = _manager(stagnant_price_delta_threshold_pct=0.05)
    manager.record_buy(MINT, 10, 0.01, 30.0)
    changed_at = manager[MINT]["last_price_change_at"]

    manager.update_price(MINT, 30.3, now=changed_at + 100.0)

    assert manager[MINT]["last_price"] == 30.0
    assert manager[MINT]["last_price_change_at"] == changed_at


# --- exit evaluation ------------------------------------------------------------


def test_get_exit_state_unknown_mint_returns_none() -> None:
    assert _manager().get_exit_state("missing") is None


def test_get_exit_state_known_mint_returns_state() -> None:
    manager = _manager()
    manager.record_buy(MINT, 10, 0.01, 30.0)

    state = manager.get_exit_state(MINT)

    assert isinstance(state, PositionExitState)


def test_evaluate_exit_unknown_mint_returns_none() -> None:
    assert _manager().evaluate_exit("missing", 30.0) is None


def test_evaluate_exit_without_market_cap_keeps_stored_price() -> None:
    manager = _manager()
    manager.record_buy(MINT, 10, 0.01, 30.0)
    manager[MINT]["current_market_cap"] = 31.0

    manager.evaluate_exit(MINT, None, token_balance=10)

    assert manager[MINT]["current_market_cap"] == 31.0


def test_clear_pending_exit_ignores_missing_mint_or_tier() -> None:
    manager = _manager()
    manager.record_buy(MINT, 10, 0.01, 30.0)
    before = dict(manager[MINT])

    manager.clear_pending_exit("missing", 1)
    manager.clear_pending_exit(MINT, None)

    assert manager[MINT] == before


# --- valuation ------------------------------------------------------------------


def test_calculate_unrealized_pnl_scales_by_remaining_fraction() -> None:
    manager = _manager()
    manager.record_buy(MINT, 1_000, 0.1, 30.0)
    manager[MINT]["remaining_token_amount"] = 500

    pnl = manager.calculate_unrealized_pnl(MINT, current_market_cap=60.0)

    assert pnl == pytest.approx(0.05)


def test_calculate_unrealized_pnl_unknown_or_zero_entry_returns_zero() -> None:
    manager = _manager()
    manager["Zero"] = {"entry_market_cap": 0.0, "cost_sol": 1.0}

    assert manager.calculate_unrealized_pnl("missing") == 0.0
    assert manager.calculate_unrealized_pnl("Zero", 100.0) == 0.0


def test_total_cost_sol_uses_entry_sol_then_config_default() -> None:
    manager = _manager(buy_amount_sol=0.02)
    manager["A"] = {"entry_sol": 0.1}
    manager["B"] = {}

    assert manager.total_cost_sol() == pytest.approx(0.12)


# --- CapitalDisplacementEngine --------------------------------------------------


def test_displacement_engine_default_evaluator_is_position_ev() -> None:
    from pumpfun_trading.strategies.decision import PositionEvEvaluator

    config = TradingBotConfig()
    engine = CapitalDisplacementEngine(config, PositionManager(config))

    assert isinstance(engine.ev_evaluator, PositionEvEvaluator)


def test_displacement_engine_pending_target_round_trip() -> None:
    engine, _ = _saturated_engine([], 0.0)

    engine.request_displacement_exit(MINT, CANDIDATE)

    assert engine.is_displacement_pending(MINT)
    assert engine.get_pending_displacement_target(MINT) == CANDIDATE
    engine.clear_displacement(MINT)
    assert engine.get_pending_displacement_target(MINT) is None


def test_evaluate_displacement_rotation_disabled_declines() -> None:
    engine, _ = _saturated_engine(
        [_score(MINT, 0.0)], 1.0, enable_capital_rotation=False
    )

    decision = engine.evaluate_displacement(CANDIDATE, current_time=1_000.0)

    assert not decision.displace
    assert decision.reason == "capital_rotation_disabled"


def test_evaluate_displacement_candidate_already_held_declines() -> None:
    engine, _ = _saturated_engine([_score(MINT, 0.0)], 1.0)

    decision = engine.evaluate_displacement(MINT, current_time=1_000.0)

    assert decision.reason == "candidate_already_held"


def test_evaluate_displacement_free_capacity_declines() -> None:
    config = TradingBotConfig(max_active_positions=5, max_total_exposure_sol=10.0)
    engine = CapitalDisplacementEngine(
        config, PositionManager(config), _FakeEvEvaluator([], 1.0)
    )

    decision = engine.evaluate_displacement(CANDIDATE, current_time=1_000.0)

    assert decision.reason == "portfolio_has_capacity"


def test_evaluate_displacement_only_pending_positions_declines() -> None:
    engine, _ = _saturated_engine([_score(MINT, 0.0)], 1.0)
    engine.request_displacement_exit(MINT, "Other")

    decision = engine.evaluate_displacement(CANDIDATE, current_time=1_000.0)

    assert decision.reason == "no_displaceable_positions"


def test_evaluate_displacement_low_conviction_declines_with_ev_delta() -> None:
    engine, evaluator = _saturated_engine([_score(MINT, 0.1)], 0.6)

    decision = engine.evaluate_displacement(
        CANDIDATE, "signal", current_time=1_000.0, conviction_percentile=0.5
    )

    assert not decision.displace
    assert decision.reason == "conviction_below_min_percentile_0.95"
    assert decision.ev_delta == pytest.approx(0.5)
    assert evaluator.candidate_calls == [(CANDIDATE, "signal", 0.5)]


def test_evaluate_displacement_delta_below_friction_declines() -> None:
    # friction = 2 * 100bps + 3% hurdle = 0.05
    engine, _ = _saturated_engine([_score(MINT, 0.10)], 0.14)

    decision = engine.evaluate_displacement(CANDIDATE, current_time=1_000.0)

    assert not decision.displace
    assert decision.reason == "insufficient_ev_hurdle_delta"
    assert decision.displaced_mint == MINT
    assert decision.estimated_friction_sol == pytest.approx(0.05 * 0.01)


def test_evaluate_displacement_large_ev_delta_displaces_weakest() -> None:
    engine, _ = _saturated_engine(
        [_score("Young", -1.0, displaceable=False), _score(MINT, 0.1)], 0.5
    )

    decision = engine.evaluate_displacement(
        CANDIDATE, current_time=1_000.0, buy_amount_sol=0.1
    )

    assert decision.displace
    assert decision.displaced_mint == MINT
    assert decision.target_mint == CANDIDATE
    assert decision.ev_delta == pytest.approx(0.4)
    assert decision.estimated_friction_sol == pytest.approx(0.005)
    assert decision.reason == "positive_ev_displacement"


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


def test_position_dataclass_fraction_and_effective_cost():
    pos = Position(
        mint="Mint1",
        name="TestCoin",
        entry_market_cap=30.0,
        current_market_cap=60.0,
        peak_market_cap=60.0,
        initial_token_amount=1_000_000,
        remaining_token_amount=1_000_000,
        cost_sol=0.10,
        entry_sol=0.10,
    )
    assert pos.remaining_fraction == 1.0
    assert pos.effective_cost_sol == 0.10

    # After 50% partial exit
    pos.remaining_token_amount = 500_000
    assert pos.remaining_fraction == 0.50
    assert pytest.approx(pos.effective_cost_sol, rel=1e-5) == 0.05

    # After 75% partial exit (25% remaining)
    pos.remaining_token_amount = 250_000
    assert pos.remaining_fraction == 0.25
    assert pytest.approx(pos.effective_cost_sol, rel=1e-5) == 0.025

    # Zero initial tokens edge case
    pos_zero = Position(
        mint="MintZero",
        name="ZeroInit",
        entry_market_cap=30.0,
        current_market_cap=30.0,
        peak_market_cap=30.0,
        initial_token_amount=0,
        remaining_token_amount=0,
        cost_sol=0.05,
    )
    assert pos_zero.remaining_fraction == 1.0
    assert pos_zero.effective_cost_sol == 0.05


def test_position_manager_partial_exit_valuation_and_pnl(
    base_config: TradingBotConfig,
):
    """
    Regression test for BUG-21:
    Verifies that after Tier 1 (50% sell) and Tier 2 (25% sell) partial exits,
    calculate_total_open_value and calculate_unrealized_pnl accurately scale
    by remaining token fraction rather than remaining at 100% of initial cost.
    """
    pm = PositionManager(base_config)
    pm.record_buy(
        mint="MintPartial",
        token_amount=1_000_000,
        cost_sol=0.10,
        entry_market_cap=30.0,
        name="PartialToken",
    )

    # 1. At 2.0x market cap (60.0 SOL) before any sell:
    # Open value = 0.10 * (60 / 30) = 0.20 SOL
    # Unrealized PnL = 0.20 - 0.10 = +0.10 SOL
    pm.update_price("MintPartial", 60.0)
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-5) == 0.20
    assert pytest.approx(pm.calculate_unrealized_pnl("MintPartial"), rel=1e-5) == 0.10

    # 2. Execute Tier 1 partial sell (50% = 500,000 tokens)
    closed, rem_tokens = pm.record_sell(
        "MintPartial",
        sold_tokens=500_000,
        proceeds_sol=0.10,
        target_tier=1,
        is_partial=True,
    )
    assert not closed
    assert rem_tokens == 500_000

    # Remaining position is 50% of initial tokens (effective cost basis = 0.05 SOL)
    # Open value at 60.0 SOL = 0.05 * (60 / 30) = 0.10 SOL
    # Unrealized PnL = 0.10 - 0.05 = +0.05 SOL
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-5) == 0.10
    assert pytest.approx(pm.calculate_unrealized_pnl("MintPartial"), rel=1e-5) == 0.05

    # 3. Market cap surges to 3.5x (105.0 SOL)
    pm.update_price("MintPartial", 105.0)
    # Open value at 105.0 SOL = 0.05 * (105 / 30) = 0.175 SOL
    # Unrealized PnL = 0.175 - 0.05 = +0.125 SOL
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-5) == 0.175
    assert pytest.approx(pm.calculate_unrealized_pnl("MintPartial"), rel=1e-5) == 0.125

    # 4. Execute Tier 2 partial sell (250,000 tokens, leaving 250,000 tokens = 25% moonbag)
    closed, rem_tokens = pm.record_sell(
        "MintPartial",
        sold_tokens=250_000,
        proceeds_sol=0.0875,
        target_tier=2,
        is_partial=True,
    )
    assert not closed
    assert rem_tokens == 250_000

    # Remaining moonbag position is 25% of initial tokens (effective cost basis = 0.025 SOL)
    # Open value at 105.0 SOL = 0.025 * (105 / 30) = 0.0875 SOL
    # Unrealized PnL = 0.0875 - 0.025 = +0.0625 SOL
    assert pytest.approx(pm.calculate_total_open_value(), rel=1e-5) == 0.0875
    assert pytest.approx(pm.calculate_unrealized_pnl("MintPartial"), rel=1e-5) == 0.0625
