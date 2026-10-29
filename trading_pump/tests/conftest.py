"""Global pytest fixtures and environment isolation."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})
_TESTS_ROOT = Path(__file__).parent


def _layer_marker(path: Path) -> str:
    """Return the taxonomy marker for a test file (docs/dev/TESTING.md).

    ``integration/`` and ``property/`` map to their own markers; everything
    else is ``unit``.
    """
    try:
        parts = path.relative_to(_TESTS_ROOT).parts
    except ValueError:
        return "unit"
    if parts and parts[0] in ("integration", "property"):
        return parts[0]
    return "unit"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply ``unit`` / ``integration`` / ``property`` by location, not per file."""
    for item in items:
        item.add_marker(_layer_marker(Path(item.path)))


# HTTP clients send requests for any host to a configured proxy, which is a
# local address, so the DNS guard below never sees the real host (BUG-143).
_PROXY_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_SESSION_GETADDRINFO: dict[str, Any] = {}


def _guard_getaddrinfo(real_getaddrinfo: Any) -> Any:
    def guarded_getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if name not in _LOCAL_HOSTS:
            raise socket.gaierror(f"external network disabled in tests: {name}")
        return real_getaddrinfo(host, *args, **kwargs)

    return guarded_getaddrinfo


def pytest_configure(config: pytest.Config) -> None:
    """Block DNS for the whole session, not only inside a test (BUG-143).

    A background thread that outlives its test (an alert worker) runs after
    the per-test guard is undone; this one is still in place.
    """
    _SESSION_GETADDRINFO["real"] = socket.getaddrinfo
    socket.getaddrinfo = _guard_getaddrinfo(socket.getaddrinfo)


def pytest_unconfigure(config: pytest.Config) -> None:
    real = _SESSION_GETADDRINFO.pop("real", None)
    if real is not None:
        socket.getaddrinfo = real


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast on any DNS lookup of a non-local host.

    Tests that quietly reached mainnet passed locally and failed in CI when the
    public RPC answered HTTP 429. Mock the client instead of opening a socket.
    Proxy variables are removed too, or the request goes through the proxy.
    """
    for name in _PROXY_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", _guard_getaddrinfo(socket.getaddrinfo))


@pytest.fixture(autouse=True)
def isolate_test_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path, request: pytest.FixtureRequest
) -> None:
    """Isolate tests from ambient settings, files and live RPC.

    An operator shell (direnv ``.envrc``) exports keys, endpoints and the
    engine's paths; tests must see the defaults, not the runtime's settings,
    and every test runs in its own ``tmp_path`` so nothing lands in the repo
    (BUG-143).
    """
    for name in [
        key for key in os.environ if key.startswith(("PUMPFUN_", "TRADING_CORE_"))
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    from trading_pump.strategies.enrichment import TokenEnricher

    monkeypatch.setattr(TokenEnricher, "holder_retry_delay_seconds", 0.0)

    # Fee/tip capture after a fill calls getTransaction (FEAT-49). Tests with a
    # partly mocked client must not reach mainnet, so it fails fast unless the
    # module opts in with ``USES_REAL_TRANSACTION_COSTS = True``.
    if not getattr(request.module, "USES_REAL_TRANSACTION_COSTS", False):
        from trading_pump.sdk.execution import PumpFunExecutionClient

        async def no_cost_rpc(self, signature, mint, **_kwargs):
            raise RuntimeError("transaction cost RPC disabled in tests")

        monkeypatch.setattr(
            PumpFunExecutionClient, "get_transaction_costs", no_cost_rpc
        )


@pytest.fixture(autouse=True)
def instant_retry_backoff(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Retry failed API / RPC calls without the real backoff wait.

    With the network blocked, every unmocked Pump.fun API or RPC lookup fails
    and retries: ~3.5 s of API backoff and ~0.7 s of RPC-pool backoff per call,
    which was most of the suite's wall-clock time. Retries still happen and are
    still counted; only the wait is skipped. Modules that test the backoff
    itself opt out with ``USES_REAL_RETRY_BACKOFF = True``.
    """
    if getattr(request.module, "USES_REAL_RETRY_BACKOFF", False):
        return

    from trading_pump.api import client as api_client
    from trading_pump.infra import rpc_pool

    # Both backoffs are awaited inline in ``request``; other sleeps in these
    # modules (the pool's health-loop interval) keep their real value.
    _zero_sleeps_in(monkeypatch, api_client, api_client.PumpFunApiClient.request)
    _zero_sleeps_in(monkeypatch, rpc_pool, rpc_pool.RpcConnectionPool.request)


def _zero_sleeps_in(
    monkeypatch: pytest.MonkeyPatch, module: types.ModuleType, function: Any
) -> None:
    """Give ``module`` an ``asyncio`` whose ``sleep`` is instant inside ``function``."""
    real_sleep = asyncio.sleep
    code = function.__code__

    def sleep(delay: float, result: Any = None) -> Any:
        if sys._getframe(1).f_code is code:
            delay = 0
        return real_sleep(delay, result)

    stand_in = types.SimpleNamespace(**vars(asyncio))
    stand_in.sleep = sleep
    monkeypatch.setattr(module, "asyncio", stand_in)


OFFLINE_CREATOR = "7nYabs9dUhvxYwdTnrWVBL9MYviKSfrEbdWCUbcnwkpF"


@pytest.fixture
def offline_trade_rpc(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stubs the token-program and curve lookups that tx builders now require.

    Builders refuse to guess the creator or token program (BUG-68/69), so tests
    that only exercise transaction assembly provide them explicitly.
    """
    from solders.pubkey import Pubkey

    from trading_pump.sdk.execution import (
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
