"""Global pytest fixtures and environment isolation."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Isolate tests from ambient persistence and audit environment variables."""
    isolated_status_path = str(tmp_path / "bot_status.json")
    isolated_audit_path = str(tmp_path / "audit_trail.jsonl")

    monkeypatch.setenv("PUMPFUN_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG_PATH", isolated_audit_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", isolated_audit_path)


OFFLINE_CREATOR = "7nYabs9dUhvxYwdTnrWVBL9MYviKSfrEbdWCUbcnwkpF"


@pytest.fixture
def offline_trade_rpc(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stubs the token-program and curve lookups that tx builders now require.

    Builders refuse to guess the creator or token program (BUG-68/69), so tests
    that only exercise transaction assembly provide them explicitly.
    """
    from solders.pubkey import Pubkey

    from pumpfun_trading.sdk.execution import (
        TOKEN_PROGRAM_ID_STR,
        PumpFunExecutionClient,
    )

    curve = {
        "virtual_sol_reserves": 30_000_000_000,
        "virtual_token_reserves": 1_073_000_000_000_000,
        "creator": OFFLINE_CREATOR,
        "is_mayhem_mode": False,
    }

    async def token_program(self, mint):
        return Pubkey.from_string(TOKEN_PROGRAM_ID_STR)

    async def curve_state(self, mint):
        return dict(curve)

    monkeypatch.setattr(
        PumpFunExecutionClient, "get_token_program_for_mint", token_program
    )
    monkeypatch.setattr(PumpFunExecutionClient, "_fetch_trade_curve_state", curve_state)
    return curve
