"""Unit tests for ``identifiers.py``: mints stay readable, keys stay masked."""

from __future__ import annotations

import pytest
from trading_core.ops.redact import redact_url

import trading_pump  # noqa: F401  (registers the predicate)
from trading_pump.identifiers import is_solana_pubkey
from trading_pump.tests.support.constants import SAMPLE_MINT, SAMPLE_PUMP_MINT


@pytest.mark.parametrize("value", [SAMPLE_MINT, SAMPLE_PUMP_MINT])
def test_mints_are_public_identifiers(value: str) -> None:
    assert is_solana_pubkey(value)


@pytest.mark.parametrize(
    "value",
    [
        "short",
        "a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9",  # hex has 0: not base58
        "x" * 45,
    ],
)
def test_other_segments_are_not(value: str) -> None:
    assert not is_solana_pubkey(value)


@pytest.mark.regression("BUG-102")
def test_importing_the_package_keeps_mints_in_urls_and_masks_keys() -> None:
    assert (
        redact_url(f"https://frontend-api-v3.pump.fun/coins/{SAMPLE_MINT}")
        == f"https://frontend-api-v3.pump.fun/coins/{SAMPLE_MINT}"
    )
    key = "a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9"
    assert redact_url(f"https://rpc.example.com/{key}") == "https://rpc.example.com/***"
