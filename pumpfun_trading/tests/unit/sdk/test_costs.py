"""Unit tests for ``sdk/costs.py`` transaction cost parsing (FEAT-49, BUG-96)."""

from __future__ import annotations

from typing import Any

import pytest

from pumpfun_trading.sdk.costs import (
    BASE_FEE_LAMPORTS_PER_SIGNATURE,
    COST_SOURCE_MODELLED,
    COST_SOURCE_TRANSACTION_META,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    TransactionCosts,
    model_transaction_costs,
    parse_transaction_costs,
)

WALLET = "Wallet1111111111111111111111111111111111111"
TOKEN_ATA = "TokenAta11111111111111111111111111111111111"
TIP = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
CURVE = "Curve111111111111111111111111111111111111111"


def _tx(
    pre: list[int], post: list[int], *, fee: int, err: Any = None, signers: int = 1
) -> dict[str, Any]:
    return {
        "meta": {"fee": fee, "err": err, "preBalances": pre, "postBalances": post},
        "transaction": {
            "message": {
                "accountKeys": [WALLET, TOKEN_ATA, CURVE, TIP],
                "header": {"numRequiredSignatures": signers},
            }
        },
    }


def test_parse_buy_splits_swap_fee_tip_and_rent() -> None:
    fee, tip, rent, swap = 25_000, 100_000, TOKEN_ACCOUNT_RENT_LAMPORTS, 10_000_000
    start = 1_000_000_000
    tx = _tx(
        pre=[start, 0, 50_000_000, 0],
        post=[start - swap - fee - tip - rent, rent, 50_000_000 + swap, tip],
        fee=fee,
    )

    costs = parse_transaction_costs(
        tx,
        wallet=WALLET,
        is_buy=True,
        token_accounts=[TOKEN_ATA],
        tip_accounts=[TIP],
        signature="sig",
    )

    assert costs.source == COST_SOURCE_TRANSACTION_META
    assert costs.swap_lamports == swap
    assert costs.network_fee_lamports == fee
    assert costs.priority_fee_lamports == fee - BASE_FEE_LAMPORTS_PER_SIGNATURE
    assert costs.tip_lamports == tip
    assert costs.rent_lamports == rent
    assert costs.total_cost_lamports == fee + tip + rent
    assert costs.wallet_delta_lamports == -(swap + fee + tip + rent)


def test_parse_closing_sell_refunds_rent() -> None:
    """BUG-96: closing the token account returns its rent to the wallet."""
    fee, tip, proceeds = 5_000, 50_000, 12_000_000
    rent = TOKEN_ACCOUNT_RENT_LAMPORTS
    start = 500_000_000
    tx = _tx(
        pre=[start, rent, 80_000_000, 0],
        post=[start + proceeds - fee - tip + rent, 0, 80_000_000 - proceeds, tip],
        fee=fee,
    )

    costs = parse_transaction_costs(
        tx, wallet=WALLET, is_buy=False, token_accounts=[TOKEN_ATA], tip_accounts=[TIP]
    )

    assert costs.swap_lamports == proceeds
    assert costs.rent_lamports == -rent
    assert costs.priority_fee_lamports == 0
    assert costs.total_cost_sol == pytest.approx((fee + tip - rent) / 1e9)
    assert costs.to_dict()["rent_sol"] == pytest.approx(-rent / 1e9)


@pytest.mark.parametrize(
    "tx, match",
    [
        ({"transaction": {}}, "no meta"),
        (_tx([1, 1, 1, 1], [1, 1, 1, 1], fee=5000, err={"Custom": 1}), "failed"),
        (
            {"meta": {"preBalances": [1], "postBalances": [1, 2]}, "transaction": {}},
            "do not match",
        ),
    ],
)
def test_parse_rejects_unusable_transactions(tx: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_transaction_costs(tx, wallet=WALLET, is_buy=True)


def test_parse_rejects_transaction_without_wallet() -> None:
    tx = _tx([1, 1, 1, 1], [1, 1, 1, 1], fee=5000)
    with pytest.raises(ValueError, match="not in transaction"):
        parse_transaction_costs(tx, wallet="Other", is_buy=True)


def test_parse_reads_json_parsed_keys_and_loaded_addresses() -> None:
    tx = {
        "meta": {
            "fee": 5000,
            "err": None,
            "preBalances": [100_000, 0],
            "postBalances": [90_000, 5_000],
            "loadedAddresses": {"writable": [TIP], "readonly": []},
        },
        "transaction": {"message": {"accountKeys": [{"pubkey": WALLET}]}},
    }

    costs = parse_transaction_costs(tx, wallet=WALLET, is_buy=True, tip_accounts=[TIP])

    assert costs.tip_lamports == 5_000
    assert costs.swap_lamports == 0


def test_model_costs_and_empty_swap() -> None:
    costs = model_transaction_costs(
        priority_fee_lamports=7_000, tip_lamports=-1, rent_lamports=-10, signatures=0
    )

    assert costs.source == COST_SOURCE_MODELLED
    assert costs.network_fee_lamports == BASE_FEE_LAMPORTS_PER_SIGNATURE + 7_000
    assert costs.tip_lamports == 0
    assert costs.rent_lamports == -10
    assert costs.swap_sol is None
    assert TransactionCosts().total_cost_lamports == 0
