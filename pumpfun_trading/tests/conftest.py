"""Global pytest fixtures and environment isolation."""

from __future__ import annotations

import socket

import pytest

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast on any DNS lookup of a non-local host.

    Tests that quietly reached mainnet passed locally and failed in CI when the
    public RPC answered HTTP 429. Mock the client instead of opening a socket.
    """
    real_getaddrinfo = socket.getaddrinfo

    def guarded_getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if name not in _LOCAL_HOSTS:
            raise socket.gaierror(f"external network disabled in tests: {name}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def isolate_test_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path, request: pytest.FixtureRequest
) -> None:
    """Isolate tests from ambient persistence, audit env vars and live RPC."""
    isolated_status_path = str(tmp_path / "bot_status.json")
    isolated_audit_path = str(tmp_path / "audit_trail.jsonl")

    monkeypatch.setenv("PUMPFUN_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG_PATH", isolated_audit_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", isolated_audit_path)

    from pumpfun_trading.execution.executor import OrderExecutor

    monkeypatch.setattr(OrderExecutor, "balance_retry_delay_seconds", 0.0)

    # Fee/tip capture after a fill calls getTransaction (FEAT-49). Tests with a
    # partly mocked client must not reach mainnet, so it fails fast unless the
    # module opts in with ``USES_REAL_TRANSACTION_COSTS = True``.
    if not getattr(request.module, "USES_REAL_TRANSACTION_COSTS", False):
        from pumpfun_trading.sdk.execution import PumpFunExecutionClient

        async def no_cost_rpc(self, signature, mint, **_kwargs):
            raise RuntimeError("transaction cost RPC disabled in tests")

        monkeypatch.setattr(
            PumpFunExecutionClient, "get_transaction_costs", no_cost_rpc
        )


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
