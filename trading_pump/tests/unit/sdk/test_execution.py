"""Unit tests for ``sdk/execution.py``: the composed client and its re-exports.

Behaviour of each part lives in the mirrored mixin tests
(``test_pumpfun_execution`` and ``test_pumpswap_execution``); the client core
and the transport are trading-solana's since 0.5.0 and tested there.
"""

from __future__ import annotations

import pytest
from solders.keypair import Keypair
from trading_solana import constants as solana_constants
from trading_solana.client import SolanaClientBase
from trading_solana.transport import TransactionTransportMixin

from trading_pump.sdk import execution, execution_types
from trading_pump.sdk.execution import PumpFunExecutionClient
from trading_pump.sdk.execution_types import PUMP_DEFAULT_FEE_BPS
from trading_pump.sdk.pumpfun_execution import PumpFunCurveMixin
from trading_pump.sdk.pumpswap_execution import PumpSwapExecutionMixin


def test_client_composes_every_mixin() -> None:
    mro = PumpFunExecutionClient.__mro__
    for part in (
        PumpFunCurveMixin,
        PumpSwapExecutionMixin,
        TransactionTransportMixin,
        SolanaClientBase,
    ):
        assert part in mro
    assert mro.index(PumpFunCurveMixin) < mro.index(PumpSwapExecutionMixin)
    assert mro.index(PumpSwapExecutionMixin) < mro.index(TransactionTransportMixin)


def test_the_pump_fee_is_the_clients_own_not_trading_solanas() -> None:
    client = PumpFunExecutionClient(private_key_b58=str(Keypair()))
    assert client.pump_fee_bps == PUMP_DEFAULT_FEE_BPS == 125
    assert "pump_fee_bps" in vars(PumpFunExecutionClient)
    assert not hasattr(SolanaClientBase, "pump_fee_bps")


def test_client_exposes_methods_from_every_part() -> None:
    client = PumpFunExecutionClient(private_key_b58=str(Keypair()))

    assert client.wallet == client.keypair.pubkey()
    for name in (
        "get_token_balance",
        "send_transaction",
        "confirm_transaction",
        "get_transaction_costs",
        "build_buy_tx",
        "build_sell_tx",
        "get_bonding_curve_states",
        "get_pumpswap_pool_states",
        "pumpswap_sell",
    ):
        assert callable(getattr(client, name)), name


@pytest.mark.parametrize(
    "name",
    [
        name
        for name in vars(execution_types)
        if not name.startswith("_") and (name.isupper() or name.endswith("Error"))
    ],
)
def test_shared_constants_and_errors_are_re_exported(name: str) -> None:
    assert getattr(execution, name) is getattr(execution_types, name)
    assert name in execution.__all__


@pytest.mark.parametrize(
    "name",
    [
        name
        for name in vars(solana_constants)
        if not name.startswith("_") and (name.isupper() or name.endswith("Error"))
    ],
)
def test_trading_solanas_constants_and_errors_are_re_exported(name: str) -> None:
    # The client raises trading-solana's errors: one class, caught as before.
    assert getattr(execution, name) is getattr(solana_constants, name)
    assert name in execution.__all__


@pytest.mark.parametrize(
    "name",
    [
        "TransactionCosts",
        "JitoClient",
        "JitoTipConfig",
        "JITO_TIP_ACCOUNTS",
        "RpcConnectionPool",
        "calculate_buy_tokens_out",
    ],
)
def test_historical_imports_still_resolve(name: str) -> None:
    assert getattr(execution, name) is not None
    assert name in execution.__all__


def test_all_names_resolve() -> None:
    for name in execution.__all__:
        assert hasattr(execution, name), name
