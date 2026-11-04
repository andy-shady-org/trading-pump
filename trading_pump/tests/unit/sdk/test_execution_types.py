"""Unit tests for ``sdk/execution_types.py``: Pump.fun constants and error types.

The shared Solana constants are trading-solana's since 0.5.0 and tested there.
"""

from __future__ import annotations

import pytest
from solders.pubkey import Pubkey

from trading_pump.sdk import execution_types as types


@pytest.mark.parametrize(
    "name",
    [
        "PUMP_PROGRAM_ID",
        "GLOBAL_STATE",
        "FEE_RECIPIENT",
        "MAYHEM_FEE_RECIPIENT",
        "BUYBACK_FEE_RECIPIENT",
        "PUMP_FEE_PROGRAM_ID",
        "EVENT_AUTHORITY",
    ],
)
def test_program_addresses_are_valid_pubkeys(name: str) -> None:
    value = getattr(types, name)
    assert str(Pubkey.from_string(value)) == value


def test_discriminators_are_distinct_eight_byte_prefixes() -> None:
    discriminators = [
        types.BUY_DISCRIMINATOR,
        types.SELL_DISCRIMINATOR,
        types.BUY_V2_DISCRIMINATOR,
        types.SELL_V2_DISCRIMINATOR,
    ]
    assert all(len(d) == 8 for d in discriminators)
    assert len(set(discriminators)) == len(discriminators)


def test_fee_config_key_is_a_pubkey_seed_and_the_default_fee() -> None:
    assert len(types.FEE_CONFIG_KEY) == 32
    assert types.PUMP_DEFAULT_FEE_BPS == 125


def test_error_hierarchy_lets_callers_catch_by_family() -> None:
    assert issubclass(types.NonStandardCurveError, types.CurveStateUnavailableError)
    assert issubclass(types.MayhemModeCurveError, types.NonStandardCurveError)
    assert issubclass(types.NotPumpFunCurveError, types.CurveStateUnavailableError)
    assert not issubclass(types.NotPumpFunCurveError, types.NonStandardCurveError)
    with pytest.raises(types.CurveStateUnavailableError):
        raise types.MayhemModeCurveError("mayhem")
