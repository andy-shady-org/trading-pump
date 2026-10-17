"""Unit tests for ``bot/sweep.py``: profit sweep planning and state (FEAT-42)."""

from __future__ import annotations

from solders.pubkey import Pubkey

import pytest

from pumpfun_trading.bot.sweep import (
    SWEEP_FEE_BUFFER_SOL,
    SweepState,
    effective_sweep_floor,
    plan_sweep,
    sweep_cash_flow,
    sweep_payloads,
    validate_sweep_config,
)
from pumpfun_trading.tests.support.factories import make_config

COLD_WALLET = str(Pubkey.new_unique())


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(0.0, 0.1 + 0.03 + SWEEP_FEE_BUFFER_SOL), (0.5, 0.5)],
)
def test_effective_sweep_floor_never_below_trading_need(
    configured: float, expected: float
) -> None:
    config = make_config(
        reserve_balance_sol=0.1,
        max_total_exposure_sol=0.03,
        profit_sweep_hot_floor_sol=configured,
    )

    assert effective_sweep_floor(config) == pytest.approx(expected)


def test_plan_sweep_moves_whole_lamports_above_floor() -> None:
    plan = plan_sweep(balance_sol=0.4, floor_sol=0.25, min_sweep_sol=0.05)

    assert plan.lamports == 150_000_000
    assert plan.amount_sol == pytest.approx(0.15)
    assert plan.skip_reason == ""


@pytest.mark.parametrize(
    ("balance", "reason"),
    [
        (0.25, "balance at or below the floor"),
        (0.2, "balance at or below the floor"),
        (0.29, "excess below profit_sweep_min_sol"),
    ],
)
def test_plan_sweep_skips_small_or_negative_excess(balance: float, reason: str) -> None:
    plan = plan_sweep(balance_sol=balance, floor_sol=0.25, min_sweep_sol=0.05)

    assert plan.lamports == 0
    assert plan.skip_reason == reason


def test_validate_sweep_config_disabled_is_always_valid() -> None:
    assert validate_sweep_config(make_config(), None) == []


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"profit_sweep_destination": ""}, "profit_sweep_destination is not set"),
        (
            {"profit_sweep_destination": "not-a-key"},
            "profit_sweep_destination is not a valid Solana address",
        ),
        (
            {"profit_sweep_destination": "SELF"},
            "profit_sweep_destination is the trading wallet itself",
        ),
        ({"profit_sweep_min_sol": 0.0}, "profit_sweep_min_sol must be positive"),
        (
            {"profit_sweep_interval_seconds": 0.0},
            "profit_sweep_interval_seconds must be positive",
        ),
    ],
)
def test_validate_sweep_config_enabled_reports_problem(
    overrides: dict[str, object], problem: str
) -> None:
    wallet = str(Pubkey.new_unique())
    values: dict[str, object] = {
        "profit_sweep_enabled": True,
        "profit_sweep_destination": COLD_WALLET,
        **overrides,
    }
    if values["profit_sweep_destination"] == "SELF":
        values["profit_sweep_destination"] = wallet

    assert validate_sweep_config(make_config(**values), wallet) == [problem]


def test_validate_sweep_config_enabled_and_complete_is_valid() -> None:
    config = make_config(
        profit_sweep_enabled=True, profit_sweep_destination=COLD_WALLET
    )

    assert validate_sweep_config(config, str(Pubkey.new_unique())) == []


def test_sweep_state_records_success_and_describes() -> None:
    state = SweepState()
    assert state.describe() == "none yet"

    state.record_success(0.15, "sig-1", 100.0)
    state.record_success(0.05, "sig-2", 200.0)

    assert (state.sweeps, state.last_signature, state.last_sweep_at) == (
        2,
        "sig-2",
        200.0,
    )
    assert state.total_swept_sol == pytest.approx(0.2)
    assert state.describe() == "0.2000 SOL in 2"
    state.last_error = "balance unavailable: RPC down for the whole morning"
    assert state.describe() == "ERROR (balance unavailable: RPC down for the wh)"


def test_sweep_state_round_trip_and_malformed() -> None:
    state = SweepState(
        total_swept_sol=1.5, sweeps=3, last_sweep_at=9.0, last_signature="s"
    )

    assert SweepState.from_dict(state.to_dict()) == state
    assert SweepState.from_dict(None) == SweepState()
    broken = SweepState.from_dict({"sweeps": "many", "last_check_at": "soon"})
    assert (broken.sweeps, broken.total_swept_sol, broken.last_check_at) == (
        0,
        0.0,
        None,
    )


def test_sweep_payloads_and_cash_flow_read_audit_records() -> None:
    records = [
        {"type": "sweep", "payload": {"cash_flow_sol": -0.150005}},
        {"type": "trade", "payload": {"cash_flow_sol": 0.01}},
        {"record_type": "sweep", "payload": {"cash_flow_sol": "bad"}},
        {"type": "sweep", "payload": "not a dict"},
        "garbage",
    ]

    payloads = sweep_payloads(records)

    assert [sweep_cash_flow(p) for p in payloads] == [-0.150005, 0.0]
    assert sweep_payloads(None) == []
