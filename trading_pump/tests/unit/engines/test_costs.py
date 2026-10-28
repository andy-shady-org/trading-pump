"""Unit tests for ``engines/costs.py`` replay cost model (Sprint 24C)."""

from __future__ import annotations

import pytest

from trading_pump.engines.costs import DEFAULT_JITO_TIP_LAMPORTS, ReplayCostModel
from trading_pump.sdk.costs import TOKEN_ACCOUNT_RENT_LAMPORTS
from trading_pump.sdk.execution import PUMP_DEFAULT_FEE_BPS


def test_buy_costs_pay_fee_tip_and_rent() -> None:
    costs = ReplayCostModel(priority_fee_lamports=10_000).buy_costs()

    assert costs.network_fee_lamports == 5_000 + 10_000
    assert costs.tip_lamports == DEFAULT_JITO_TIP_LAMPORTS
    assert costs.rent_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS


@pytest.mark.parametrize(
    ("full_exit", "close", "rent"),
    [
        (True, True, -TOKEN_ACCOUNT_RENT_LAMPORTS),
        (True, False, 0),
        (False, True, 0),
    ],
)
def test_sell_costs_refund_rent_only_on_closing_full_exit(
    full_exit: bool, close: bool, rent: int
) -> None:
    model = ReplayCostModel(close_token_account_on_full_exit=close)

    assert model.sell_costs(full_exit=full_exit).rent_lamports == rent


@pytest.mark.parametrize(
    ("env", "tip"),
    [
        ({}, DEFAULT_JITO_TIP_LAMPORTS),
        ({"PUMPFUN_JITO_TIP_LAMPORTS": "250000"}, 250_000),
        ({"PUMPFUN_USE_JITO": "false", "PUMPFUN_JITO_TIP_LAMPORTS": "250000"}, 0),
        ({"PUMPFUN_JITO_TIP_LAMPORTS": "lots"}, DEFAULT_JITO_TIP_LAMPORTS),
    ],
)
def test_from_env_uses_live_tip_settings(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], tip: int
) -> None:
    monkeypatch.delenv("PUMPFUN_USE_JITO", raising=False)
    monkeypatch.delenv("PUMPFUN_JITO_TIP_LAMPORTS", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    model = ReplayCostModel.from_env()

    assert model.tip_lamports == tip
    assert model.protocol_fee_bps == PUMP_DEFAULT_FEE_BPS


def test_from_env_explicit_values_win() -> None:
    model = ReplayCostModel.from_env(
        tip_lamports=-5, priority_fee_lamports=7, close_token_account_on_full_exit=False
    )

    assert model.tip_lamports == 0
    assert model.priority_fee_lamports == 7
    assert model.close_token_account_on_full_exit is False


@pytest.mark.parametrize(
    ("env", "entry", "exit_"),
    [
        ({}, None, None),
        (
            {
                "PUMPFUN_JITO_ENTRY_TIP_LAMPORTS": "0",
                "PUMPFUN_JITO_EXIT_TIP_LAMPORTS": "50000",
            },
            0,
            50_000,
        ),
        ({"PUMPFUN_JITO_EXIT_TIP_LAMPORTS": "lots"}, None, None),
        # Jito off: no side tip either, matching the live client.
        (
            {"PUMPFUN_USE_JITO": "false", "PUMPFUN_JITO_EXIT_TIP_LAMPORTS": "50000"},
            None,
            None,
        ),
    ],
)
def test_from_env_reads_the_split_entry_and_exit_tips(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    entry: int | None,
    exit_: int | None,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    model = ReplayCostModel.from_env()

    assert (model.entry_tip_lamports, model.exit_tip_lamports) == (entry, exit_)


def test_split_tips_apply_per_side_and_in_the_round_trip() -> None:
    model = ReplayCostModel(
        tip_lamports=100_000, entry_tip_lamports=0, exit_tip_lamports=25_000
    )

    assert model.buy_costs().tip_lamports == 0
    assert model.sell_costs(full_exit=True).tip_lamports == 25_000
    assert model.round_trip_fixed_costs_sol() == pytest.approx(
        (2 * 5_000 + 25_000) / 1_000_000_000
    )


@pytest.mark.parametrize(
    ("close", "tip", "expected_lamports"),
    [
        (True, 100_000, 2 * (5_000 + 100_000)),  # rent refunded by the closing sell
        (True, 0, 2 * 5_000),
        (False, 25_000, 2 * (5_000 + 25_000) + TOKEN_ACCOUNT_RENT_LAMPORTS),
    ],
)
def test_round_trip_fixed_costs_cover_both_legs_and_unrefunded_rent(
    close: bool, tip: int, expected_lamports: int
) -> None:
    model = ReplayCostModel(tip_lamports=tip, close_token_account_on_full_exit=close)

    assert model.round_trip_fixed_costs_sol() == pytest.approx(
        expected_lamports / 1_000_000_000
    )
