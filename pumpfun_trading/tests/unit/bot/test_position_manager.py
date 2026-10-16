"""Unit tests for ``bot/position_manager.py`` position book and displacement."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pumpfun_trading.bot.position_manager import (
    CapitalDisplacementEngine,
    PositionManager,
    _extract_position_fraction,
)
from pumpfun_trading.strategies.base import TradingBotConfig
from pumpfun_trading.strategies.exits import PositionExitState

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
